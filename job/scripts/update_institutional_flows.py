#!/usr/bin/env python3
"""Fetch one trading day of institutional net buy/sell and merge it into the store.

Two requests cover the whole market -- TWSE and TPEX each publish every symbol
for a given day in one response -- so this runs once after the close rather than
per symbol.

Only the symbols in our own universe are kept. The exchanges publish ~2,250
symbols a day; storing all of them would grow the file past what a static page
can reasonably fetch, and the page only ever looks up symbols the radar
surfaced.

A non-trading day yields no rows from either exchange, which is indistinguishable
from a date-format slip. That is why the two formats are pinned by tests rather
than assembled inline here.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

try:  # pragma: no cover - exercised by the real CI entrypoint
    from scripts.institutional_flows import (
        FLOWS_FILE,
        SCHEMA_VERSION,
        fetch_tpex_flows,
        fetch_twse_flows,
    )
    from scripts.flows_store import (
        FLOWS_DIR,
        load_existing_index,
        split_by_symbol,
        write_index,
        write_symbol_files,
    )
except ModuleNotFoundError:  # pragma: no cover - running as scripts/<file>.py
    from institutional_flows import (
        FLOWS_FILE,
        SCHEMA_VERSION,
        fetch_tpex_flows,
        fetch_twse_flows,
    )
    from flows_store import (
        FLOWS_DIR,
        load_existing_index,
        split_by_symbol,
        write_index,
        write_symbol_files,
    )

LOGGER = logging.getLogger("update_institutional_flows")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALIASES = ROOT / "config" / "symbol_aliases.tw.json"

# Roughly a quarter of trading days. Enough for the detail page's trend view
# without letting the file grow without bound.
DEFAULT_HISTORY_DAYS = 60


def load_universe(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    symbols = payload.get("symbols", {})
    return {
        f"{meta.get('exchange', 'TWSE')}:{ticker}"
        for ticker, meta in symbols.items()
        if isinstance(meta, Mapping)
    }


def load_store(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        LOGGER.warning("flows_store_unreadable path=%s error=%s", path, error)
        return {}
    symbols = payload.get("symbols")
    return dict(symbols) if isinstance(symbols, dict) else {}


def merge_flows(
    store: Mapping[str, list[dict[str, Any]]],
    flows: list[dict[str, Any]],
    *,
    universe: set[str],
    history_days: int = DEFAULT_HISTORY_DAYS,
) -> dict[str, list[dict[str, Any]]]:
    """Fold one day's flows into the store, newest first, without duplicates."""
    merged = {key: list(value) for key, value in store.items()}

    for flow in flows:
        instrument_id = flow["instrument_id"]
        if instrument_id not in universe:
            continue
        series = [entry for entry in merged.get(instrument_id, [])
                  if entry.get("date") != flow["date"]]
        entry = {key: value for key, value in flow.items()
                 if key not in {"instrument_id", "symbol", "name", "exchange", "unit"}}
        series.append(entry)
        series.sort(key=lambda item: item.get("date", ""), reverse=True)
        merged[instrument_id] = series[:history_days]

    return merged


def write_store(path: Path, store: Mapping[str, list[dict[str, Any]]], *, generated_at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "unit": "shares",
        "source": "TWSE T86 / TPEX dailyTrade (official)",
        "symbols": {key: store[key] for key in sorted(store)},
    }
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES)
    parser.add_argument("--date", help="Trading day as YYYY-MM-DD (default: every missing weekday up to today, Taipei).")
    parser.add_argument("--history-days", type=int, default=DEFAULT_HISTORY_DAYS)
    parser.add_argument(
        "--skip-market", action="store_true",
        help="Only update the radar universe file; skip the ~2,220 per-symbol market files.",
    )
    parser.add_argument("--catch-up-days", type=int, default=31,
                        help="Without --date, fetch every missing weekday in this many calendar days.")
    parser.add_argument("--pause-seconds", type=float, default=3.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if args.date:
        days = [date.fromisoformat(args.date)]
    else:
        # The exchanges publish on Taipei time; using UTC would ask for
        # "tomorrow" during the Taipei evening and get an empty response.
        today = (datetime.now(timezone.utc) + timedelta(hours=8)).date()
        # GitHub routinely starts the 17:20 schedule hours late. Once the delay
        # crosses Taipei midnight, "today" is the next, still-empty day, and a
        # today-only fetch silently skips the day that did trade -- which is how
        # the flows stopped at 2026-10-30. Catch up every missing weekday instead.
        days = pending_days(stored_dates(load_store(args.data_dir / FLOWS_FILE)), today, args.catch_up_days)
        if not days:
            LOGGER.info("flows up to date through %s", today)
            return 0
        LOGGER.info("catching up %d day(s): %s", len(days), ", ".join(d.isoformat() for d in days))

    import requests

    session = requests.Session()
    universe = load_universe(args.aliases)
    store_path = args.data_dir / FLOWS_FILE
    for index, day in enumerate(days):
        if index:
            time.sleep(args.pause_seconds)  # stay polite to the exchanges
        update_day(session, day, args, universe, store_path)

    return 0


def stored_dates(store: Mapping[str, list[dict[str, Any]]]) -> set[str]:
    return {str(entry.get("date")) for series in store.values() for entry in series if entry.get("date")}


def pending_days(known: set[str], today: date, lookback: int) -> list[date]:
    """Weekdays in (today - lookback, today] with no stored rows, oldest first.

    Holidays come back empty and are simply skipped by the fetch, so no
    holiday calendar is needed here.
    """
    if not known:
        return [today]
    latest = max(known)
    days = []
    for offset in range(lookback - 1, -1, -1):
        day = today - timedelta(days=offset)
        if day.weekday() >= 5 or day.isoformat() in known or day.isoformat() < latest:
            continue
        days.append(day)
    return days


def update_day(session: Any, day: date, args: argparse.Namespace, universe: set[str], store_path: Path) -> int:
    flows: list[dict[str, Any]] = []
    for label, fetch in (("TWSE", fetch_twse_flows), ("TPEX", fetch_tpex_flows)):
        try:
            rows = fetch(session, day)
        except Exception as error:  # noqa: BLE001 - one exchange must not lose the other
            LOGGER.warning("institutional_fetch_failed exchange=%s error=%s", label, error)
            continue
        LOGGER.info("fetched exchange=%s date=%s rows=%d", label, day, len(rows))
        flows.extend(rows)

    if not flows:
        LOGGER.warning(
            "no rows for %s -- a non-trading day, or the date format was rejected", day,
        )
        return 0

    merged = merge_flows(
        load_store(store_path), flows, universe=universe, history_days=args.history_days,
    )
    kept = sum(1 for flow in flows if flow["instrument_id"] in universe)
    LOGGER.info(
        "merged date=%s market_rows=%d in_universe=%d symbols=%d",
        day, len(flows), kept, len(merged),
    )

    if args.dry_run:
        LOGGER.info("dry run: %s not written", store_path)
        return 0

    write_store(store_path, merged, generated_at=datetime.now(timezone.utc))
    LOGGER.info("wrote %s", store_path)

    # The universe file above backs the radar's own symbols. This writes the
    # whole market, one file per symbol, so the flows page can look up a code
    # nobody has surfaced yet. Sixty days of the whole market in one file is
    # 7.1MB; per symbol it is ~3KB, and the page fetches only what was asked
    # for.
    if not args.skip_market:
        flows_dir = args.data_dir / FLOWS_DIR
        by_symbol = split_by_symbol(flows)
        written = write_symbol_files(flows_dir, by_symbol, history_days=args.history_days)
        known = load_existing_index(flows_dir)
        known.update({
            instrument_id: {"name": entry["name"], "exchange": entry["exchange"]}
            for instrument_id, entry in by_symbol.items()
        })
        write_index(flows_dir, known)
        LOGGER.info(
            "wrote %s (%d symbol file(s), index covers %d)", flows_dir, written, len(known),
        )

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
