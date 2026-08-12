#!/usr/bin/env python3
"""Aggregate per-symbol institutional net flows into sector buy/sell rankings.

Sector membership comes from `config/symbol_registry.tw.json`'s official
`industry_name_zh`, where every symbol belongs to exactly one industry. The
supply-chain taxonomy in `config/industry_supply_chains.tw.json` cannot be used
here: it is theme-oriented and deliberately multi-membership (2330 sits in 78
groups), so summing over it would count one symbol's flow into dozens of
sectors and report the whole market as buying everything.

ETFs carry no industry code and are skipped -- a sector ranking that lists 0050
alongside 半導體 is double-counting its own constituents.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

LOGGER = logging.getLogger(__name__)

# Net-flow fields as published per symbol, mapped to the panels the page shows.
PANELS: tuple[tuple[str, str, str], ...] = (
    ("foreign_net", "foreign", "外資買賣超"),
    ("trust_net", "trust", "投信買賣超"),
    ("dealer_net", "dealer", "主力買賣超"),
)

TOP_N = 5
# Upstream publishes share counts. Convert to 張 (1,000 shares), the unit Taiwan
# quotes institutional flow in -- not 億元, which would need a price per symbol
# we do not carry here and would silently mislabel volume as money.
SHARES_PER_UNIT = 1_000
VALUE_UNIT = "張"


def load_registry(path: Path) -> dict[str, str]:
    """symbol -> official industry name, for symbols that have one."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for entry in payload.get("symbols", []):
        symbol = entry.get("symbol")
        industry = entry.get("industry_name_zh")
        if symbol and industry:
            out[str(symbol)] = str(industry)
    return out


def _latest_row(shard: Mapping[str, Any]) -> tuple[str, dict[str, float]] | None:
    """Newest dated row of a shard, as (date, {field: value})."""
    fields = shard.get("fields") or []
    series = shard.get("series") or []
    if not fields or not series:
        return None
    # Shards are written newest-first, but pick by date so a reordering upstream
    # cannot silently publish a stale day as current.
    try:
        newest = max(series, key=lambda row: row[0])
    except (IndexError, TypeError):
        return None
    row = dict(zip(fields, newest))
    date = row.pop("date", None)
    if not isinstance(date, str):
        return None
    return date, {k: v for k, v in row.items() if isinstance(v, (int, float))}


def aggregate_sectors(
    shards: Iterable[Mapping[str, Any]],
    registry: Mapping[str, str],
) -> tuple[str | None, dict[str, dict[str, float]]]:
    """Sum each net-flow field per sector for the most recent trading day.

    Returns the date aggregated and {sector: {field: total}}. Shards whose
    newest row predates the market-wide latest date are dropped rather than
    blended in, so one lagging symbol cannot mix two sessions together.
    """
    rows: list[tuple[str, str, dict[str, float]]] = []
    for shard in shards:
        symbol = str(shard.get("symbol") or "")
        sector = registry.get(symbol)
        if not sector:
            continue
        latest = _latest_row(shard)
        if latest is None:
            continue
        date, values = latest
        rows.append((date, sector, values))

    if not rows:
        return None, {}

    as_of = max(date for date, _, _ in rows)
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for date, sector, values in rows:
        if date != as_of:
            continue
        for field, value in values.items():
            totals[sector][field] += value
    return as_of, {k: dict(v) for k, v in totals.items()}


def build_flow_panels(totals: Mapping[str, Mapping[str, float]]) -> list[dict[str, Any]]:
    """Top-N buy and sell sectors per investor type, in page order."""
    panels: list[dict[str, Any]] = []
    for field, key, title in PANELS:
        ranked = sorted(
            ((sector, values.get(field, 0.0)) for sector, values in totals.items()),
            key=lambda pair: pair[1],
            reverse=True,
        )
        buy = [
            {"rank": i + 1, "name": name, "value": round(value / SHARES_PER_UNIT)}
            for i, (name, value) in enumerate(ranked[:TOP_N])
            if value > 0
        ]
        sell = [
            {"rank": i + 1, "name": name, "value": round(value / SHARES_PER_UNIT)}
            for i, (name, value) in enumerate(reversed(ranked[-TOP_N:]))
            if value < 0
        ]
        panels.append({"id": key, "title": title, "unit": VALUE_UNIT,
                       "buy": buy, "sell": sell})
    return panels


def iter_shards(flows_dir: Path) -> Iterable[dict[str, Any]]:
    for path in sorted(flows_dir.glob("*.json")):
        if path.name == "index.json":
            continue
        try:
            yield json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("skipping unreadable shard %s: %s", path.name, exc)


def main() -> int:  # pragma: no cover - manual smoke entrypoint
    logging.basicConfig(level=logging.INFO)
    root = Path(__file__).resolve().parent.parent
    registry = load_registry(root / "config" / "symbol_registry.tw.json")
    as_of, totals = aggregate_sectors(iter_shards(root / "data" / "flows"), registry)
    print(json.dumps({"as_of": as_of, "panels": build_flow_panels(totals)},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
