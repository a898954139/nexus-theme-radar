"""Fill in quarterly fundamentals for the whole configured symbol universe.

The hourly radar pipeline (``fundamentals_pipeline``) refreshes only symbols
that surfaced in a published theme, under a per-run fetch budget. That keeps
the hourly job fast, but it means a symbol added to ``symbol_aliases.tw.json``
stays without fundamentals until some theme happens to mention it.

This is the other half: walk the configured universe, fetch whatever the
quarterly throttle says is due, and stop. Run it after growing the symbol
list; re-running it inside the same quarter costs nothing because every
symbol is already current.

Usage:
    python scripts/backfill_all_fundamentals.py
    python scripts/backfill_all_fundamentals.py --dry-run
    python scripts/backfill_all_fundamentals.py --only 2330,8299
    python scripts/backfill_all_fundamentals.py --force --max-workers 2
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.fundamentals_pipeline import (
        FUNDAMENTALS_CACHE_FILE,
        load_fundamentals_cache,
        write_fundamentals_cache,
    )
    from scripts.symbol_mapping import DEFAULT_SYMBOL_REGISTRY_PATH, load_symbol_aliases
    from scripts.theme_symbol_fundamentals import latest_expected_quarter
except ModuleNotFoundError:  # `python scripts/backfill_all_fundamentals.py`
    # puts scripts/ on sys.path[0], hiding the package path -- the same dual
    # import every other entrypoint in this repo carries.
    from fundamentals_pipeline import (  # type: ignore[no-redef]
        FUNDAMENTALS_CACHE_FILE,
        load_fundamentals_cache,
        write_fundamentals_cache,
    )
    from symbol_mapping import (  # type: ignore[no-redef]
        DEFAULT_SYMBOL_REGISTRY_PATH,
        load_symbol_aliases,
    )
    from theme_symbol_fundamentals import latest_expected_quarter  # type: ignore[no-redef]

LOGGER = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data"
DEFAULT_SYMBOL_INDEX_PATH = DEFAULT_SYMBOL_REGISTRY_PATH
MIN_SYMBOL_UNIVERSE_SIZE = 2280

# Goodinfo rate-limits hard. Measured 2026-08-07: three concurrent workers
# turned 20 symbols into 19 HTTP 500s in 8 seconds, and every one of those
# symbols then succeeded when retried serially. Concurrency does not speed
# this up here -- it converts the run into a wall of failures. Serial is the
# only setting that actually completes, so it is the default.
DEFAULT_MAX_WORKERS = 1

# Goodinfo answers a throttled client with 500 rather than 429, so a failure
# is not evidence the symbol is bad. Retry with a widening gap before giving up.
DEFAULT_RETRIES = 3
RETRY_BACKOFF_SECONDS = (10.0, 30.0)


@dataclass
class BackfillReport:
    """What one backfill run actually did, for the caller to print or assert."""

    universe: int = 0
    selected: list[str] = field(default_factory=list)
    succeeded: int = 0
    failed: int = 0
    failures: dict[str, str] = field(default_factory=dict)

    @property
    def skipped(self) -> int:
        """Symbols already holding the current quarter -- the throttle working."""
        return self.universe - len(self.selected)


def load_symbol_universe(path: str | Path = DEFAULT_SYMBOL_INDEX_PATH) -> list[str]:
    """Canonical ``EXCHANGE:code`` ids for the complete configured universe.

    The official company registry is the product's stock universe and includes
    the 2,280+ symbols guarded by the daily workflow, without ETFs or other
    non-company flow instruments. Keep accepting the compact alias file and
    mapping-style flows index for explicit compatibility.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    symbols = payload.get("symbols") if isinstance(payload, Mapping) else None
    if isinstance(symbols, list):
        universe = []
        for row in symbols:
            if not isinstance(row, Mapping):
                continue
            code = str(row.get("symbol") or "")
            exchange = str(row.get("exchange") or "")
            if code and exchange in {"TWSE", "TPEX", "ESB"}:
                universe.append(f"{exchange}:{code}")
        if universe:
            return sorted(set(universe))

    if isinstance(symbols, Mapping):
        universe = []
        for code, metadata in symbols.items():
            if not isinstance(metadata, Mapping):
                continue
            exchange = str(metadata.get("exchange") or "")
            if exchange in {"TWSE", "TPEX", "ESB"}:
                universe.append(f"{exchange}:{code}")
        if universe:
            return sorted(set(universe))

    aliases = load_symbol_aliases(path)
    return sorted(
        f"{metadata['exchange']}:{ticker}"
        for ticker, metadata in aliases["symbols"].items()
    )


def select_symbols_to_fetch(
    universe: Iterable[str],
    *,
    cache: Mapping[str, Mapping[str, Any]],
    as_of: datetime,
    force: bool = False,
) -> list[str]:
    """Instrument ids whose cached fundamentals are missing or stale.

    Mirrors ``theme_symbol_fundamentals.symbols_due_for_refresh`` but reads the
    configured universe instead of a published payload. A cached entry with no
    ``fiscal_quarter`` counts as stale rather than raising: comparing None to
    the expected quarter is a TypeError that would end the whole run over one
    damaged entry.
    """
    ordered = list(universe)
    if force:
        return ordered

    expected = latest_expected_quarter(as_of)
    due = []
    for instrument_id in ordered:
        context = cache.get(instrument_id)
        if context is None:
            due.append(instrument_id)
            continue
        quarter = context.get("fiscal_quarter")
        if not isinstance(quarter, str) or quarter < expected:
            due.append(instrument_id)
    return due


def _bare_ticker(instrument_id: str) -> str:
    """Goodinfo is queried by 4-digit ticker; ``TWSE:`` prefixes 404 there."""
    return instrument_id.split(":", 1)[-1]


def backfill_fundamentals(
    universe: Iterable[str],
    *,
    cache: Mapping[str, Mapping[str, Any]],
    as_of: datetime,
    fetch: Callable[[str], Mapping[str, Any]],
    force: bool = False,
    dry_run: bool = False,
    max_workers: int = DEFAULT_MAX_WORKERS,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: tuple[float, ...] = RETRY_BACKOFF_SECONDS,
    checkpoint_every: int = 25,
    on_progress: Callable[[Mapping[str, Mapping[str, Any]]], None] | None = None,
    skip_exchanges: frozenset[str] = frozenset(),
) -> tuple[dict[str, Mapping[str, Any]], BackfillReport]:
    """Fetch every due symbol and return the merged cache plus a report.

    ``fetch`` takes a bare ticker and returns one ``fundamental_context``. It
    may raise; a raising symbol is retried, then recorded as a failure that
    costs only itself. The returned cache always contains every prior entry,
    so a partial run never republishes a truncated file.
    """
    ordered = list(universe)
    selected = select_symbols_to_fetch(ordered, cache=cache, as_of=as_of, force=force)
    report = BackfillReport(universe=len(ordered), selected=selected)

    merged: dict[str, Mapping[str, Any]] = dict(cache)
    if dry_run or not selected:
        return merged, report

    def run(instrument_id: str) -> tuple[str, Mapping[str, Any] | None, str | None]:
        exchange = instrument_id.split(":", 1)[0]
        if exchange in skip_exchanges:
            return instrument_id, None, f"unsupported exchange: {exchange}"
        ticker = _bare_ticker(instrument_id)
        last_error = "no attempt made"
        for attempt in range(max(1, retries)):
            try:
                return instrument_id, fetch(ticker), None
            except Exception as error:  # noqa: BLE001 - a scraped source fails
                # per symbol; one 500 must not cost the other symbols their
                # results, and is usually throttling rather than a bad symbol.
                last_error = str(error)
                if attempt + 1 < max(1, retries) and backoff_seconds:
                    pause = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                    if pause > 0:
                        LOGGER.info(
                            "fundamentals_backfill_retry symbol=%s attempt=%d pause=%.0fs",
                            instrument_id, attempt + 1, pause,
                        )
                        time.sleep(pause)
        return instrument_id, None, last_error

    workers = max(1, min(max_workers, len(selected)))
    processed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # map() yields in submission order, so the merged cache is identical
        # regardless of which worker finished first.
        for instrument_id, context, error in pool.map(run, selected):
            processed += 1
            if error is not None:
                report.failed += 1
                report.failures[instrument_id] = error
                LOGGER.warning(
                    "fundamentals_backfill_failed symbol=%s error=%s", instrument_id, error
                )
            else:
                merged[instrument_id] = context
                report.succeeded += 1
            if on_progress and checkpoint_every > 0 and processed % checkpoint_every == 0:
                on_progress(merged)

    if on_progress and processed and processed % max(1, checkpoint_every) != 0:
        on_progress(merged)

    return merged, report


def _default_fetch(pause_seconds: float) -> Callable[[str], Mapping[str, Any]]:
    """Real Goodinfo fetcher, imported lazily so tests never need requests."""
    import requests

    try:
        from scripts.goodinfo_fundamentals import fetch_symbol_fundamentals
    except ModuleNotFoundError:
        from goodinfo_fundamentals import fetch_symbol_fundamentals  # type: ignore[no-redef]

    session = requests.Session()

    def fetch(ticker: str) -> Mapping[str, Any]:
        return fetch_symbol_fundamentals(
            session,
            ticker,
            fetched_at=datetime.now(timezone.utc),
            pause_seconds=pause_seconds,
        )

    return fetch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--symbols-index",
        type=Path,
        default=DEFAULT_SYMBOL_INDEX_PATH,
        help="JSON symbol index for the complete backfill universe",
    )
    parser.add_argument(
        "--aliases",
        type=Path,
        default=None,
        help="Compatibility alias for a targeted compact universe",
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--only",
        help="Comma-separated tickers to restrict the run to, e.g. 2330,8299",
    )
    parser.add_argument(
        "--force", action="store_true", help="Refetch even symbols already current"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would be fetched, fetch nothing"
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help="Concurrent symbol fetches. Default 1: Goodinfo 500s under concurrency",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help="Attempts per symbol before giving up (throttling shows up as 500)",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=3.0,
        help="Delay between the three statement requests within one symbol",
    )
    parser.add_argument(
        "--min-universe-size",
        type=int,
        default=MIN_SYMBOL_UNIVERSE_SIZE,
        help="Fail before fetching if the configured universe is smaller than this",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=25,
        help="Persist successful results after this many attempted symbols",
    )
    parser.add_argument(
        "--skip-exchanges",
        default="ESB",
        help="Comma-separated exchanges to record as unavailable without scraping",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    universe = load_symbol_universe(args.aliases or args.symbols_index)
    if len(universe) < args.min_universe_size and not args.aliases:
        LOGGER.error("symbol universe too small: %d < %d", len(universe), args.min_universe_size)
        return 1
    if args.only:
        wanted = {token.strip() for token in args.only.split(",") if token.strip()}
        universe = [i for i in universe if _bare_ticker(i) in wanted]
        unknown = wanted - {_bare_ticker(i) for i in universe}
        if unknown:
            LOGGER.warning("unknown_tickers_ignored %s", sorted(unknown))
        if not universe:
            LOGGER.error("no matching symbols in --only")
            return 1

    cache_path = Path(args.data_dir) / FUNDAMENTALS_CACHE_FILE
    cache = load_fundamentals_cache(cache_path)

    merged, report = backfill_fundamentals(
        universe,
        cache=cache,
        as_of=datetime.now(timezone.utc),
        fetch=_default_fetch(args.pause_seconds),
        force=args.force,
        dry_run=args.dry_run,
        max_workers=args.max_workers,
        retries=args.retries,
        checkpoint_every=args.checkpoint_every,
        on_progress=(
            None
            if args.dry_run
            else lambda current: write_fundamentals_cache(
                cache_path, current, publish=False
            )
        ),
        skip_exchanges=frozenset(token.strip() for token in args.skip_exchanges.split(",") if token.strip()),
    )

    LOGGER.info(
        "backfill universe=%d due=%d skipped=%d ok=%d failed=%d",
        report.universe, len(report.selected), report.skipped,
        report.succeeded, report.failed,
    )
    for instrument_id, error in sorted(report.failures.items()):
        LOGGER.warning("  failed %s: %s", instrument_id, error)

    if args.dry_run:
        for instrument_id in report.selected:
            LOGGER.info("  would fetch %s", instrument_id)
        return 0

    if report.succeeded:
        write_fundamentals_cache(cache_path, merged)
        LOGGER.info("wrote %s (%d symbols)", cache_path, len(merged))

    # A run where every single fetch failed is a broken run, not a quiet no-op.
    return 1 if report.selected and not report.succeeded else 0


if __name__ == "__main__":
    sys.exit(main())
