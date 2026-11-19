#!/usr/bin/env python3
"""Daily sector history for the path backtest (issue #12).

Two official series, kept in one growing file (``data/market/sector-daily.json``):

* ``indices``: TWSE MI_INDEX sector index % change per trading day -- single
  industries *and* composites (電子工業 stands in for 科技股全體), plus the TAIEX
  itself under ``加權``. Fetched once per day; a day TWSE answers with no table is
  remembered in ``closed`` so holidays are not refetched every run.
* ``foreign_net``: foreign net buy/sell per official industry, in 張, summed
  from the per-symbol shards in ``data/flows`` (TWSE T86 / TPEx). The shards
  only keep ~60 trading days, so the daily sums are copied in here and outlive
  them; that is what lets the backtest window grow past 60 days.

    python scripts/sector_history.py --data-dir data --since 2026-08-01
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

try:  # pragma: no cover
    from scripts.market_temperature import TAIPEI, TWSE_MI_INDEX, _num, _signed, requests_getter
    from scripts.sector_flows import SHARES_PER_UNIT, load_registry
except ModuleNotFoundError:  # pragma: no cover
    from market_temperature import TAIPEI, TWSE_MI_INDEX, _num, _signed, requests_getter
    from sector_flows import SHARES_PER_UNIT, load_registry

LOGGER = logging.getLogger("sector_history")

HISTORY_FILE = "sector-daily.json"
TAIEX_KEY = "加權"
SCHEMA_VERSION = 1

Getter = Callable[[str, Mapping[str, Any]], Any]


def parse_index_changes(payload: Mapping[str, Any]) -> dict[str, float]:
    """MI_INDEX table 0 -> {short name: % change}, composites included.

    The sign is not in the percent column: TWSE paints it into 漲跌(+/-) as a
    red/green HTML fragment, which ``_signed`` reads.
    """
    if not isinstance(payload, Mapping) or payload.get("stat") != "OK":
        return {}
    for table in payload.get("tables") or []:
        fields = list(table.get("fields") or [])
        if "漲跌百分比(%)" not in fields:
            continue
        i_pct = fields.index("漲跌百分比(%)")
        i_sign = fields.index("漲跌(+/-)") if "漲跌(+/-)" in fields else None
        out: dict[str, float] = {}
        for raw in table.get("data") or []:
            name = str(raw[0]).strip()
            if name == "發行量加權股價指數":
                short = TAIEX_KEY
            elif name.endswith("類指數"):
                short = name[: -len("類指數")]
            else:
                continue
            pct = _num(raw[i_pct])
            if pct is None:
                continue
            if i_sign is not None and pct >= 0:
                pct = _signed(raw[i_sign], pct)
            out.setdefault(short, round(float(pct), 4))
        if out:
            return out  # table 0 = price indices; later tables are total-return
    return {}


def load_history(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    return {
        "schema_version": SCHEMA_VERSION,
        "source": payload.get("source") or {
            "indices": "TWSE MI_INDEX type=IND (table 0, % change)",
            "foreign_net": "data/flows per-symbol foreign_net, summed by registry industry (張)",
        },
        "indices": dict(payload.get("indices") or {}),
        "closed": sorted(set(payload.get("closed") or [])),
        "foreign_net": dict(payload.get("foreign_net") or {}),
    }


def pending_index_days(history: Mapping[str, Any], since: date, today: date, *, after_close: bool) -> list[date]:
    """Weekdays from ``since`` that have neither an index row nor a closed mark."""
    known = set(history.get("indices") or {}) | set(history.get("closed") or [])
    last = today if after_close else today - timedelta(days=1)
    out = []
    day = since
    while day <= last:
        if day.weekday() < 5 and day.isoformat() not in known:
            out.append(day)
        day += timedelta(days=1)
    return out


def update_indices(history: dict[str, Any], get: Getter, days: Iterable[date], *,
                   pause_seconds: float = 3.0, today: date | None = None) -> int:
    """Fetch MI_INDEX for each day; returns how many trading days were added."""
    added = 0
    closed = set(history["closed"])
    for index, day in enumerate(days):
        if index and pause_seconds:
            time.sleep(pause_seconds)
        try:
            payload = get(TWSE_MI_INDEX, {"response": "json", "date": day.strftime("%Y%m%d"), "type": "IND"})
        except Exception as exc:  # noqa: BLE001 - one bad day must not lose the rest
            LOGGER.warning("sector_history_fetch_failed day=%s error=%s", day, type(exc).__name__)
            continue
        changes = parse_index_changes(payload)
        if changes:
            history["indices"][day.isoformat()] = changes
            added += 1
        elif today is None or day < today:
            # TWSE answers holidays with stat != OK. Today stays unmarked: the
            # table may simply not be published yet.
            closed.add(day.isoformat())
    history["indices"] = {key: history["indices"][key] for key in sorted(history["indices"])}
    history["closed"] = sorted(closed)
    return added


# A day is summed only when most of the market reported it. Shards of delisted
# or newly listed symbols carry odd dates, and a day where one exchange failed
# (TWSE without TPEx) would read as a sector-wide swing.
MIN_DAY_COVERAGE = 0.9


def sum_foreign_by_industry(flows_dir: Path, registry: Mapping[str, str]) -> dict[str, dict[str, float]]:
    """{date: {industry: foreign net 張}} over the shards in ``flows_dir``, full days only."""
    out: dict[str, dict[str, float]] = {}
    counts: dict[str, int] = {}
    for shard_path in sorted(flows_dir.glob("*.json")):
        try:
            shard = json.loads(shard_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        industry = registry.get(str(shard.get("symbol") or ""))
        fields = shard.get("fields") or []
        if not industry or "foreign_net" not in fields or "date" not in fields:
            continue
        i_date, i_net = fields.index("date"), fields.index("foreign_net")
        for row in shard.get("series") or []:
            try:
                day, net = str(row[i_date]), row[i_net]
            except (IndexError, TypeError):
                continue
            if not isinstance(net, (int, float)):
                continue
            bucket = out.setdefault(day, {})
            bucket[industry] = bucket.get(industry, 0.0) + net / SHARES_PER_UNIT
            counts[day] = counts.get(day, 0) + 1
    if not counts:
        return {}
    floor = max(counts.values()) * MIN_DAY_COVERAGE
    return {day: {k: round(v, 1) for k, v in sorted(rows.items())}
            for day, rows in sorted(out.items()) if counts[day] >= floor}


def merge_foreign(history: dict[str, Any], sums: Mapping[str, Mapping[str, float]]) -> int:
    """Newer shard sums win for the days they cover; older days are kept."""
    changed = 0
    for day, rows in sums.items():
        if history["foreign_net"].get(day) != dict(rows):
            history["foreign_net"][day] = dict(rows)
            changed += 1
    history["foreign_net"] = {key: history["foreign_net"][key] for key in sorted(history["foreign_net"])}
    return changed


def write_history(path: Path, history: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--registry", type=Path, default=Path("config/symbol_registry.tw.json"))
    parser.add_argument("--since", default="2026-08-01", help="First day to backfill (YYYY-MM-DD)")
    parser.add_argument("--max-days", type=int, default=120, help="Cap on MI_INDEX requests per run")
    parser.add_argument("--pause-seconds", type=float, default=3.0)
    parser.add_argument("--skip-fetch", action="store_true", help="Only refresh foreign_net from data/flows")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    path = args.data_dir / "market" / HISTORY_FILE
    history = load_history(path)
    now = datetime.now(TAIPEI)
    added = 0
    if not args.skip_fetch:
        import requests

        days = pending_index_days(history, date.fromisoformat(args.since), now.date(),
                                  after_close=now.hour >= 15)[: args.max_days]
        LOGGER.info("sector_history_pending days=%d", len(days))
        with requests.Session() as session:
            added = update_indices(history, requests_getter(session), days,
                                   pause_seconds=args.pause_seconds, today=now.date())
    flows = merge_foreign(history, sum_foreign_by_industry(args.data_dir / "flows", load_registry(args.registry)))
    write_history(path, history)
    LOGGER.info("sector_history_written index_days=%d added=%d foreign_days=%d foreign_changed=%d",
                len(history["indices"]), added, len(history["foreign_net"]), flows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
