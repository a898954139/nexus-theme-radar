#!/usr/bin/env python3
"""Pull the money-flow leaderboards and mark the symbols we track.

Sixteen files: two metrics (net buy/sell, holding-ratio change) x four windows
(5/10/20/30 trading days) x two sides (up, down).

Unlike every other fetch in this pipeline, the source is a third-party project
rather than an exchange, so a failure here is expected to be routine: one board
failing leaves the other fifteen intact and keeps whatever was previously
stored for it.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:  # pragma: no cover - exercised by the real CI entrypoint
    from scripts.institutional_rankings import (
        INSTITUTIONAL_BASE_URL,
        RANKING_METRICS,
        RANKING_SIDES,
        RANKING_WINDOWS,
        RANKINGS_FILE,
        SCHEMA_VERSION,
        fetch_ranking,
        ranking_key,
    )
except ModuleNotFoundError:  # pragma: no cover - running as scripts/<file>.py
    from institutional_rankings import (
        INSTITUTIONAL_BASE_URL,
        RANKING_METRICS,
        RANKING_SIDES,
        RANKING_WINDOWS,
        RANKINGS_FILE,
        SCHEMA_VERSION,
        fetch_ranking,
        ranking_key,
    )

LOGGER = logging.getLogger("update_institutional_rankings")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALIASES = ROOT / "config" / "symbol_aliases.tw.json"

# The boards publish 200 rows each; 16 x 200 would be ~1.5MB for a page that
# shows a leaderboard. Entries matching our universe are always kept regardless
# of rank, since those are the ones the radar cross-references.
DEFAULT_TOP_N = 50


def load_universe(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    symbols = payload.get("symbols", {})
    return {
        f"{meta.get('exchange', 'TWSE')}:{ticker}"
        for ticker, meta in symbols.items()
        if isinstance(meta, Mapping)
    }


def trim_entries(entries: list[dict[str, Any]], *, top_n: int) -> list[dict[str, Any]]:
    """Keep the leading rows, plus every entry from our universe wherever it
    ranked. A symbol we track sitting at rank 120 is the single most useful row
    on the board for us, and a plain head-of-list cut would drop it.
    """
    kept = list(entries[:top_n])
    seen = {id(entry) for entry in kept}
    kept.extend(entry for entry in entries[top_n:]
                if entry.get("in_universe") and id(entry) not in seen)
    return kept


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES)
    parser.add_argument("--base-url", default=INSTITUTIONAL_BASE_URL)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    universe = load_universe(args.aliases)
    import requests

    session = requests.Session()

    boards: dict[str, Any] = {}
    failures: dict[str, str] = {}
    for metric in RANKING_METRICS:
        for window in RANKING_WINDOWS:
            for side in RANKING_SIDES:
                key = ranking_key(metric, window, side)
                try:
                    board = fetch_ranking(
                        session, metric, window, side,
                        universe=universe, base_url=args.base_url,
                    )
                except Exception as error:  # noqa: BLE001 - one board must not lose the rest
                    LOGGER.warning("ranking_fetch_failed key=%s error=%s", key, error)
                    failures[key] = str(error)
                    continue

                entries = board["entries"]
                marked = sum(1 for entry in entries if entry["in_universe"])
                board["entries"] = trim_entries(entries, top_n=args.top_n)
                board["source_rows"] = len(entries)
                boards[key] = board
                LOGGER.info(
                    "fetched key=%s rows=%d kept=%d in_universe=%d",
                    key, len(entries), len(board["entries"]), marked,
                )

    if not boards:
        LOGGER.error("every ranking failed; leaving the existing file untouched")
        return 1

    if args.dry_run:
        LOGGER.info("dry run: %d board(s) fetched, nothing written", len(boards))
        return 0

    path = args.data_dir / RANKINGS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": args.base_url,
        "rankings": {key: boards[key] for key in sorted(boards)},
    }
    if failures:
        body["failures"] = failures
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LOGGER.info("wrote %s (%d board(s), %d failed)", path, len(boards), len(failures))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
