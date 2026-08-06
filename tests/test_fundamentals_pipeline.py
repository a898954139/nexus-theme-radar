"""Wiring quarterly fundamentals into the hourly radar run.

Goodinfo is a scraped third party on an hourly pipeline whose real job is
theme momentum. These tests pin the containment rules: fetch only what is due,
and never let a fundamentals failure take the radar run down with it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from scripts.fundamentals_pipeline import enrich_with_fundamentals

ANCHOR = datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc)


def _payload():
    return {
        "themes": [
            {
                "theme_id": "memory_hbm",
                "direct_symbols": [
                    {"instrument_id": "TWSE:2344", "symbol": "2344", "exchange": "TWSE"},
                ],
                "related_symbols": [
                    {"instrument_id": "TPEX:8299", "symbol": "8299", "exchange": "TPEX"},
                ],
            },
        ],
    }


def _context(period: str = "2026Q1", eps: float = 2.25):
    return {
        "quarters": [{"period": period, "revenue": 382.5, "eps": eps}],
        "health": {"cash": 255.2, f"net_income_{period}": 101.1},
        "valuation": {"ttm_eps": 3.37},
        "basis": "parent_only",
        "fiscal_quarter": period,
    }


def _fetcher(results: dict, calls: list):
    def fetch(symbol: str):
        calls.append(symbol)
        outcome = results[symbol]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return fetch


def test_fundamentals_are_attached_to_the_published_payload():
    calls: list[str] = []
    enriched, cache = enrich_with_fundamentals(
        _payload(),
        cache={},
        as_of=ANCHOR,
        fetch=_fetcher({"2344": _context(), "8299": _context(eps=68.8)}, calls),
    )

    theme = enriched["themes"][0]
    assert theme["direct_symbols"][0]["fundamentals"]["quarters"][0]["eps"] == 2.25
    assert theme["related_symbols"][0]["fundamentals"]["quarters"][0]["eps"] == 68.8
    assert sorted(calls) == ["2344", "8299"]
    assert sorted(cache) == ["TPEX:8299", "TWSE:2344"]


def test_cached_symbols_are_not_refetched():
    """The pipeline runs hourly; statements change quarterly. Refetching every
    hour would be pure waste and needless load on a scraped source."""
    calls: list[str] = []
    cache = {"TWSE:2344": _context(), "TPEX:8299": _context()}

    enriched, _ = enrich_with_fundamentals(
        _payload(), cache=cache, as_of=ANCHOR, fetch=_fetcher({}, calls),
    )

    assert calls == []
    assert enriched["themes"][0]["direct_symbols"][0]["fundamentals"]["quarters"]


def test_a_stale_quarter_is_refetched():
    calls: list[str] = []
    cache = {"TWSE:2344": _context(period="2025Q2"), "TPEX:8299": _context()}

    _, updated = enrich_with_fundamentals(
        _payload(), cache=cache, as_of=ANCHOR,
        fetch=_fetcher({"2344": _context()}, calls),
    )

    assert calls == ["2344"]
    assert updated["TWSE:2344"]["fiscal_quarter"] == "2026Q1"


def test_a_fetch_failure_never_breaks_the_radar_run():
    """Theme momentum is this pipeline's actual job. A scraper failure must
    degrade to 'no fundamentals', not abort the hourly publish."""
    calls: list[str] = []
    enriched, cache = enrich_with_fundamentals(
        _payload(),
        cache={},
        as_of=ANCHOR,
        fetch=_fetcher(
            {"2344": RuntimeError("goodinfo down"), "8299": _context(eps=68.8)}, calls,
        ),
    )

    theme = enriched["themes"][0]
    # The failed symbol carries no fundamentals at all -- not an empty object,
    # which would read downstream as a real, empty measurement.
    assert "fundamentals" not in theme["direct_symbols"][0]
    # The healthy symbol is unaffected by its neighbour's failure.
    assert theme["related_symbols"][0]["fundamentals"]["quarters"][0]["eps"] == 68.8
    assert "TWSE:2344" not in cache


def test_every_symbol_failing_still_publishes_the_themes():
    enriched, cache = enrich_with_fundamentals(
        _payload(),
        cache={},
        as_of=ANCHOR,
        fetch=_fetcher(
            {"2344": RuntimeError("down"), "8299": RuntimeError("down")}, [],
        ),
    )

    assert enriched["themes"][0]["theme_id"] == "memory_hbm"
    assert cache == {}


def test_the_bare_ticker_is_what_reaches_goodinfo():
    """Goodinfo is queried by 4-digit ticker; the exchange prefix is Nexus
    canonical identity and would 404 there."""
    calls: list[str] = []
    enrich_with_fundamentals(
        _payload(), cache={}, as_of=ANCHOR,
        fetch=_fetcher({"2344": _context(), "8299": _context()}, calls),
    )

    assert all(":" not in symbol for symbol in calls)


def test_a_symbol_budget_bounds_the_run():
    """A pool that suddenly grows must not turn one hourly run into hundreds of
    scrapes."""
    calls: list[str] = []
    _, cache = enrich_with_fundamentals(
        _payload(), cache={}, as_of=ANCHOR,
        fetch=_fetcher({"2344": _context(), "8299": _context()}, calls),
        max_fetches=1,
    )

    assert len(calls) == 1
    assert len(cache) == 1


# ─── cache persistence ──────────────────────────────────────────────────────


def test_cache_round_trips_through_disk(tmp_path):
    from scripts.fundamentals_pipeline import load_fundamentals_cache, write_fundamentals_cache

    path = tmp_path / "fundamentals-cache.json"
    write_fundamentals_cache(path, {"TWSE:2344": _context()})

    assert load_fundamentals_cache(path)["TWSE:2344"]["quarters"][0]["eps"] == 2.25


def test_a_missing_or_corrupt_cache_reads_as_empty(tmp_path):
    """A damaged cache must cost one refetch, never an aborted radar run."""
    from scripts.fundamentals_pipeline import load_fundamentals_cache

    assert load_fundamentals_cache(tmp_path / "absent.json") == {}

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert load_fundamentals_cache(corrupt) == {}

    wrong_shape = tmp_path / "wrong.json"
    wrong_shape.write_text('["a list"]', encoding="utf-8")
    assert load_fundamentals_cache(wrong_shape) == {}


def test_attaching_cached_statements_needs_no_fetching():
    """Reading a committed cache and calling a scraped third party are
    different risks. Publishing what is already on disk must not require the
    fetch opt-in, or a cache that exists sits unused."""
    calls: list[str] = []
    cache = {"TWSE:2344": _context(), "TPEX:8299": _context()}

    enriched, _ = enrich_with_fundamentals(
        _payload(), cache=cache, as_of=ANCHOR,
        fetch=_fetcher({}, calls), max_fetches=0,
    )

    assert calls == []
    assert enriched["themes"][0]["direct_symbols"][0]["fundamentals"]["quarters"]
