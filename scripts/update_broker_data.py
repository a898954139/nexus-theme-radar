#!/usr/bin/env python3
"""Fetch the daily public broker pages and publish the broker UI snapshots.

The source is one Fubon page per symbol. Every requested symbol gets an
outcome, including a successful ``no_data`` response, so a missing branch list
cannot be mistaken for a fetch failure. A run only publishes the derived
snapshots after every requested page was attempted successfully.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:  # pragma: no cover - exercised by the real CI entrypoint
    from scripts.broker_data import (
        BROKER_DATA_SCHEMA_VERSION,
        FUBON_BROKER_URL,
        broker_map_filename,
        build_broker_maps,
        build_broker_stats,
        build_coverage,
        parse_fubon_page,
    )
except ModuleNotFoundError:  # pragma: no cover - running as scripts/<file>.py
    from broker_data import (
        BROKER_DATA_SCHEMA_VERSION,
        FUBON_BROKER_URL,
        broker_map_filename,
        build_broker_maps,
        build_broker_stats,
        build_coverage,
        parse_fubon_page,
    )


LOGGER = logging.getLogger("update_broker_data")
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SYMBOL_INDEX = ROOT / "data" / "flows" / "index.json"


def decode_fubon_content(content: bytes) -> str:
    """Decode Fubon's Traditional Chinese response without hiding corruption."""
    return content.decode("cp950")


def load_symbol_universe(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    symbols = payload.get("symbols", {})
    if not isinstance(symbols, Mapping):
        raise ValueError(f"symbol index has no symbols mapping: {path}")
    universe: dict[str, str] = {}
    for code, record in symbols.items():
        if not isinstance(record, Mapping):
            continue
        universe[str(code)] = str(record.get("name", ""))
    if not universe:
        raise ValueError(f"symbol index is empty: {path}")
    return dict(sorted(universe.items()))


def fetch_symbol(
    session: Any,
    code: str,
    name: str,
    *,
    timeout: float,
    retries: int = 3,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = session.get(
                FUBON_BROKER_URL.format(code=code),
                timeout=timeout,
                headers={"User-Agent": "nexus-theme-radar/1.0"},
            )
            response.raise_for_status()
            # Fubon declares Big5, and CP950 covers its common extensions.
            # Keep decoding strict so a source encoding change fails visibly.
            html = decode_fubon_content(response.content)
            return parse_fubon_page(html, stock_code=code, stock_name=name)
        except Exception as error:  # noqa: BLE001 - one symbol must be isolated
            last_error = error
            if attempt < retries:
                time.sleep(min(2**attempt, 8))
    return {
        "status": "error",
        "stock_code": code,
        "records": [],
        "error": str(last_error),
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def write_outputs(
    data_dir: Path,
    *,
    universe: Mapping[str, str],
    results: Mapping[str, Mapping[str, Any]],
    generated_at: str,
    source_updated: str | None,
) -> dict[str, Any]:
    records = [
        record
        for result in results.values()
        for record in result.get("records", [])
    ]
    stats = build_broker_stats(records)
    maps = build_broker_maps(records)
    coverage = build_coverage(
        universe.keys(), results, source_updated=source_updated,
    )
    coverage.update({
        "generated_at": generated_at,
        "source": FUBON_BROKER_URL,
        "source_scope": "Fubon top buy/sell branch rows per symbol",
    })

    _write_json(data_dir / "broker-coverage.json", coverage)
    # Keep the handoff contract exact: brokerStats is a top-level array.
    # Run metadata and source coverage live in broker-coverage.json.
    _write_json(data_dir / "broker-stats.json", stats)

    map_dir = data_dir / "broker-map"
    map_index: dict[str, Any] = {
        "schema_version": BROKER_DATA_SCHEMA_VERSION,
        "generated_at": generated_at,
        "source": FUBON_BROKER_URL,
        "unit": "lots",
        "symbols": {},
    }
    for code, branches in maps.items():
        filename = broker_map_filename(code)
        stock_records = [record for record in records if str(record.get("stock_code")) == code]
        summary_buy = sum(int(record.get("buy", 0) or 0) for record in stock_records)
        summary_sell = sum(int(record.get("sell", 0) or 0) for record in stock_records)
        # Each shard is the exact brokerData[stockCode] array. Metadata and
        # the shard lookup stay in broker-map/index.json.
        _write_json(map_dir / filename, branches)
        map_index["symbols"][code] = {
            "file": filename,
            "name": universe.get(code, ""),
            "broker_count": len(branches),
            "summary": {
                "buy": summary_buy,
                "sell": summary_sell,
                "net": summary_buy - summary_sell,
            },
        }
    _write_json(map_dir / "index.json", map_index)
    return coverage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--symbols-index", type=Path, default=DEFAULT_SYMBOL_INDEX)
    parser.add_argument("--limit", type=int, help="Fetch only the first N symbols for a smoke run.")
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--min-attempt-coverage", type=float, default=1.0,
        help="Fail without publishing if attempted/requested falls below this ratio.",
    )
    parser.add_argument(
        "--min-universe-size", type=int, default=2280,
        help="Fail before fetching if the symbol universe is smaller than this.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    if not 0 <= args.min_attempt_coverage <= 1:
        parser.error("--min-attempt-coverage must be between 0 and 1")
    if args.min_universe_size < 0:
        parser.error("--min-universe-size must not be negative")

    universe = load_symbol_universe(args.symbols_index)
    if len(universe) < args.min_universe_size:
        generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        validation_error = (
            f"symbol universe too small: {len(universe)} < {args.min_universe_size}"
        )
        coverage = build_coverage(universe.keys(), {}, source_updated=None)
        coverage.update({
            "generated_at": generated_at,
            "source": FUBON_BROKER_URL,
            "source_scope": "Fubon top buy/sell branch rows per symbol",
            "validation_error": validation_error,
        })
        LOGGER.error(validation_error)
        _write_json(args.data_dir / "broker-coverage.json", coverage)
        return 1

    requested = dict(list(universe.items())[:args.limit]) if args.limit else universe
    LOGGER.info("fetching broker pages symbols=%d delay=%.2fs", len(requested), args.delay)

    import requests

    session = requests.Session()
    results: dict[str, dict[str, Any]] = {}
    for index, (code, name) in enumerate(requested.items(), start=1):
        result = fetch_symbol(session, code, name, timeout=args.timeout)
        results[code] = result
        LOGGER.info(
            "broker_fetch progress=%d/%d code=%s status=%s rows=%d",
            index, len(requested), code, result["status"], len(result.get("records", [])),
        )
        if index < len(requested):
            time.sleep(max(args.delay, 0))

    source_dates = [
        str(result.get("trade_date"))
        for result in results.values()
        if result.get("trade_date")
    ]
    source_updated = max(source_dates) if source_dates else None
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    coverage = build_coverage(requested.keys(), results, source_updated=source_updated)
    coverage.update({
        "generated_at": generated_at,
        "source": FUBON_BROKER_URL,
        "source_scope": "Fubon top buy/sell branch rows per symbol",
    })

    if coverage["attempt_coverage"] < args.min_attempt_coverage or coverage["failed_symbols"]:
        LOGGER.error(
            "broker coverage incomplete attempted=%.2f failed=%d; refusing to publish",
            coverage["attempt_coverage"], coverage["failed_symbols"],
        )
        _write_json(args.data_dir / "broker-coverage.json", coverage)
        return 1

    if args.dry_run:
        LOGGER.info(
            "dry run complete attempted=%d with_data=%d; nothing written",
            coverage["attempted_symbols"], coverage["symbols_with_data"],
        )
        return 0

    write_outputs(
        args.data_dir,
        universe=requested,
        results=results,
        generated_at=generated_at,
        source_updated=source_updated,
    )
    LOGGER.info(
        "wrote broker snapshots attempted=%d with_data=%d brokers=%d",
        coverage["attempted_symbols"], coverage["symbols_with_data"],
        len(build_broker_stats([
            record for result in results.values() for record in result.get("records", [])
        ])),
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
