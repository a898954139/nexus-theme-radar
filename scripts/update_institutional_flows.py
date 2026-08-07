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
except ModuleNotFoundError:  # pragma: no cover - running as scripts/<file>.py
    from institutional_flows import (
        FLOWS_FILE,
        SCHEMA_VERSION,
        fetch_tpex_flows,
        fetch_twse_flows,
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
    parser.add_argument("--date", help="Trading day as YYYY-MM-DD (default: today, Taipei).")
    parser.add_argument("--history-days", type=int, default=DEFAULT_HISTORY_DAYS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if args.date:
        day = date.fromisoformat(args.date)
    else:
        # The exchanges publish on Taipei time; using UTC would ask for
        # "tomorrow" during the Taipei evening and get an empty response.
        day = (datetime.now(timezone.utc) + timedelta(hours=8)).date()

    import requests

    session = requests.Session()
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

    universe = load_universe(args.aliases)
    store_path = args.data_dir / FLOWS_FILE
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
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
