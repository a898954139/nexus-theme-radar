"""Whole-universe quarterly fundamentals backfill.

The hourly radar pipeline only refreshes symbols that surfaced in a theme, and
caps itself at a per-run fetch budget. That is the right behaviour for an
hourly job, and the wrong behaviour for "we just grew the symbol list, go fill
in everything that is missing".

These tests pin the backfill's contract: it walks the *configured symbol
universe* rather than the published payload, it honours the same quarterly
throttle so a re-run costs nothing, and one symbol failing never costs the
other symbols their results.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from scripts.backfill_all_fundamentals import (
    backfill_fundamentals,
    load_symbol_universe,
    select_symbols_to_fetch,
)

ANCHOR = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
# 2026-08-20 is past the 14 August filing deadline, so Q2 is the newest
# statement expected to exist.
EXPECTED_QUARTER = "2026Q2"

# Production backs off 10s then 30s between retries. Any test exercising a
# failing fetch must override it, or the suite pays that wall-clock for real.
NO_BACKOFF = (0.0, 0.0)


def _context(quarter: str = EXPECTED_QUARTER) -> dict:
    return {
        "quarters": [{"period": quarter, "revenue": 100.0, "eps": 1.0}],
        "fiscal_quarter": quarter,
        "basis": "parent_only",
    }


# ── universe loading ──────────────────────────────────────────────────


def test_universe_comes_from_symbol_aliases_not_the_published_payload(tmp_path):
    """The whole point of the backfill: cover configured symbols, including
    ones no theme has ever mentioned."""
    aliases = tmp_path / "aliases.json"
    aliases.write_text(
        json.dumps(
            {
                "market_id": "TW_EQUITY",
                "market_scope": ["TW_EQUITY"],
                "symbols": {
                    "2330": {"name_zh": "台積電", "exchange": "TWSE", "aliases": ["台積電"]},
                    "8299": {"name_zh": "群聯", "exchange": "TPEX", "aliases": ["群聯"]},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    universe = load_symbol_universe(aliases)

    # Canonical instrument ids, so the cache keys match what the radar writes.
    assert universe == ["TPEX:8299", "TWSE:2330"]


# ── quarterly throttle ────────────────────────────────────────────────


def test_symbols_already_holding_the_current_quarter_are_skipped():
    """A re-run right after a successful run must fetch nothing at all."""
    universe = ["TWSE:2330", "TPEX:8299"]
    cache = {"TWSE:2330": _context(), "TPEX:8299": _context()}

    assert select_symbols_to_fetch(universe, cache=cache, as_of=ANCHOR) == []


def test_symbols_missing_from_cache_are_selected():
    universe = ["TWSE:2330", "TPEX:8299"]
    cache = {"TWSE:2330": _context()}

    assert select_symbols_to_fetch(universe, cache=cache, as_of=ANCHOR) == ["TPEX:8299"]


def test_symbols_holding_a_stale_quarter_are_selected():
    universe = ["TWSE:2330"]
    cache = {"TWSE:2330": _context("2026Q1")}

    assert select_symbols_to_fetch(universe, cache=cache, as_of=ANCHOR) == ["TWSE:2330"]


def test_cached_entry_without_a_fiscal_quarter_is_refetched_not_crashed():
    """A context missing ``fiscal_quarter`` must read as "stale", never raise.

    Comparing None against the expected quarter string is a TypeError, which
    would take down the whole backfill over one damaged cache entry.
    """
    universe = ["TWSE:2330"]
    cache = {"TWSE:2330": {"quarters": []}}

    assert select_symbols_to_fetch(universe, cache=cache, as_of=ANCHOR) == ["TWSE:2330"]


def test_force_ignores_the_throttle_and_selects_everything():
    universe = ["TWSE:2330", "TPEX:8299"]
    cache = {"TWSE:2330": _context(), "TPEX:8299": _context()}

    selected = select_symbols_to_fetch(universe, cache=cache, as_of=ANCHOR, force=True)

    assert selected == ["TWSE:2330", "TPEX:8299"]


# ── fetching ──────────────────────────────────────────────────────────


def test_backfill_fetches_by_bare_ticker_and_keys_the_cache_canonically():
    """Goodinfo is queried by 4-digit ticker; the cache is keyed by
    ``EXCHANGE:ticker`` so the radar can find it."""
    seen = []

    def fetch(ticker: str) -> dict:
        seen.append(ticker)
        return _context()

    cache, report = backfill_fundamentals(
        ["TWSE:2330", "TPEX:8299"], cache={}, as_of=ANCHOR, fetch=fetch,
    )

    assert sorted(seen) == ["2330", "8299"]
    assert sorted(cache) == ["TPEX:8299", "TWSE:2330"]
    assert report.succeeded == 2
    assert report.failed == 0


def test_one_failing_symbol_does_not_lose_the_others():
    """A scraped source fails per-symbol. Losing 29 good results because the
    30th 404'd would make the backfill worthless at scale."""

    def fetch(ticker: str) -> dict:
        if ticker == "8299":
            raise RuntimeError("goodinfo unavailable")
        return _context()

    cache, report = backfill_fundamentals(
        ["TWSE:2330", "TPEX:8299"], cache={}, as_of=ANCHOR, fetch=fetch,
        backoff_seconds=NO_BACKOFF,
    )

    assert list(cache) == ["TWSE:2330"]
    assert report.succeeded == 1
    assert report.failed == 1
    assert report.failures == {"TPEX:8299": "goodinfo unavailable"}


def test_existing_cache_entries_survive_a_partial_run():
    """The backfill merges into the cache; it never republishes a truncated
    one. A symbol that failed today keeps yesterday's numbers."""

    def fetch(ticker: str) -> dict:
        raise RuntimeError("boom")

    prior = {"TWSE:2454": _context("2026Q1")}
    cache, report = backfill_fundamentals(
        ["TWSE:2330"], cache=prior, as_of=ANCHOR, fetch=fetch,
        backoff_seconds=NO_BACKOFF,
    )

    assert cache["TWSE:2454"] == prior["TWSE:2454"]
    assert report.failed == 1


def test_dry_run_reports_the_work_without_fetching():
    def fetch(ticker: str) -> dict:  # pragma: no cover - must never run
        raise AssertionError("dry run must not fetch")

    cache, report = backfill_fundamentals(
        ["TWSE:2330"], cache={}, as_of=ANCHOR, fetch=fetch, dry_run=True,
    )

    assert cache == {}
    assert report.selected == ["TWSE:2330"]
    assert report.succeeded == 0


def test_results_are_deterministic_regardless_of_completion_order():
    """Parallel workers finish out of order; the written cache must not."""

    def fetch(ticker: str) -> dict:
        return _context()

    cache, _ = backfill_fundamentals(
        ["TPEX:8299", "TWSE:2330", "TWSE:2454"], cache={}, as_of=ANCHOR,
        fetch=fetch, max_workers=3,
    )

    assert list(cache) == ["TPEX:8299", "TWSE:2330", "TWSE:2454"]


def test_a_transient_failure_is_retried_before_being_given_up_on():
    """Goodinfo answers a throttled client with 500, not 429, so a single
    failure is not evidence the symbol is bad. Measured 2026-08-07: 19 of 20
    symbols 500'd under concurrency and every one succeeded on a serial retry.
    """
    attempts: dict[str, int] = {}

    def fetch(ticker: str) -> dict:
        attempts[ticker] = attempts.get(ticker, 0) + 1
        if attempts[ticker] < 3:
            raise RuntimeError("500 Server Error")
        return _context()

    cache, report = backfill_fundamentals(
        ["TWSE:2330"], cache={}, as_of=ANCHOR, fetch=fetch,
        retries=3, backoff_seconds=NO_BACKOFF,
    )

    assert attempts["2330"] == 3
    assert report.succeeded == 1
    assert report.failed == 0
    assert "TWSE:2330" in cache


def test_retries_are_bounded_and_the_last_error_is_reported():
    attempts: dict[str, int] = {}

    def fetch(ticker: str) -> dict:
        attempts[ticker] = attempts.get(ticker, 0) + 1
        raise RuntimeError(f"500 Server Error (attempt {attempts[ticker]})")

    _, report = backfill_fundamentals(
        ["TWSE:2330"], cache={}, as_of=ANCHOR, fetch=fetch,
        retries=3, backoff_seconds=NO_BACKOFF,
    )

    assert attempts["2330"] == 3
    assert report.failed == 1
    assert report.failures["TWSE:2330"] == "500 Server Error (attempt 3)"


def test_serial_is_the_default_because_concurrency_gets_us_throttled():
    """Pins the measured finding rather than leaving it to a comment."""
    from scripts.backfill_all_fundamentals import DEFAULT_MAX_WORKERS

    assert DEFAULT_MAX_WORKERS == 1


def test_concurrency_is_bounded():
    """Goodinfo blocks aggressive clients. The cap is the containment rule
    that lets this run against hundreds of symbols at all."""
    import threading

    live = 0
    peak = 0
    guard = threading.Lock()
    release = threading.Event()

    def fetch(ticker: str) -> dict:
        nonlocal live, peak
        with guard:
            live += 1
            peak = max(peak, live)
        release.wait(timeout=2.0)
        with guard:
            live -= 1
        return _context()

    universe = [f"TWSE:{2000 + i}" for i in range(12)]

    worker = threading.Thread(
        target=backfill_fundamentals,
        args=(universe,),
        kwargs={
            "cache": {}, "as_of": ANCHOR, "fetch": fetch, "max_workers": 3,
            # No real backoff: this test asserts on concurrency, and the
            # production 10s/30s pauses would make it take a minute.
            "backoff_seconds": NO_BACKOFF,
        },
    )
    worker.start()
    # Give the pool time to saturate before letting anyone finish.
    threading.Event().wait(0.3)
    release.set()
    worker.join(timeout=10)

    assert peak <= 3, f"expected at most 3 concurrent fetches, saw {peak}"
