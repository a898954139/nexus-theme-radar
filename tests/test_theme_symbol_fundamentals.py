"""Attaching quarterly fundamentals to the published theme symbol entries.

The public momentum feed already carries per-theme ``direct_symbols`` /
``related_symbols``. These tests pin the additive contract: a ``fundamentals``
object hangs off each symbol that has one, and every pre-existing field on the
payload survives untouched, because downstream consumers read that file
directly.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from scripts.theme_symbol_fundamentals import (
    attach_symbol_fundamentals,
    symbols_due_for_refresh,
)

ANCHOR = datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc)


def _payload():
    return {
        "schema_version": "theme_radar_public_momentum.v0.9",
        "generated_at": "2026-08-06T09:00:00Z",
        "themes": [
            {
                "rank": 1,
                "theme_id": "memory_hbm",
                "name_zh": "記憶體與 HBM",
                "heat_score": 65,
                "taiwan_mapping_count": 2,
                "representative_news": {"id": "news-1"},
                "direct_symbols": [
                    {"instrument_id": "TWSE:2344", "symbol": "2344",
                     "exchange": "TWSE", "name_zh": "華邦電"},
                ],
                "related_symbols": [
                    {"instrument_id": "TPEX:8299", "symbol": "8299",
                     "exchange": "TPEX", "name_zh": "群聯"},
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
        "source": "Goodinfo.tw quarterly statements",
        "fetched_at": "2026-08-06T09:00:00Z",
        "fiscal_quarter": period,
    }


# ─── additive contract ──────────────────────────────────────────────────────


def test_fundamentals_attach_to_matching_symbols() -> None:
    payload = attach_symbol_fundamentals(
        _payload(), {"TWSE:2344": _context(), "TPEX:8299": _context(eps=68.8)},
    )

    theme = payload["themes"][0]
    assert theme["direct_symbols"][0]["fundamentals"]["quarters"][0]["eps"] == 2.25
    assert theme["related_symbols"][0]["fundamentals"]["quarters"][0]["eps"] == 68.8


def test_every_pre_existing_field_survives() -> None:
    """This file is published to consumers we do not control."""

    before = _payload()
    after = attach_symbol_fundamentals(deepcopy(before), {"TWSE:2344": _context()})

    assert set(after) == set(before)
    assert after["schema_version"] == before["schema_version"]

    theme_before, theme_after = before["themes"][0], after["themes"][0]
    assert set(theme_after) == set(theme_before)
    for key, value in theme_before.items():
        if key not in {"direct_symbols", "related_symbols"}:
            assert theme_after[key] == value

    symbol_before = theme_before["direct_symbols"][0]
    symbol_after = theme_after["direct_symbols"][0]
    assert set(symbol_after) == set(symbol_before) | {"fundamentals"}
    for key, value in symbol_before.items():
        assert symbol_after[key] == value


def test_symbol_without_fundamentals_is_left_alone() -> None:
    """Absent data must read as absent, never as an empty measurement."""

    payload = attach_symbol_fundamentals(_payload(), {})

    theme = payload["themes"][0]
    assert "fundamentals" not in theme["direct_symbols"][0]
    assert "fundamentals" not in theme["related_symbols"][0]


def test_input_payload_is_not_mutated() -> None:
    source = _payload()
    snapshot = deepcopy(source)

    attach_symbol_fundamentals(source, {"TWSE:2344": _context()})

    assert source == snapshot


def test_the_same_symbol_across_themes_gets_the_same_object() -> None:
    payload = _payload()
    payload["themes"].append(
        {
            "rank": 2, "theme_id": "ai_server", "name_zh": "AI 伺服器",
            "direct_symbols": [
                {"instrument_id": "TWSE:2344", "symbol": "2344", "exchange": "TWSE"},
            ],
            "related_symbols": [],
        }
    )

    enriched = attach_symbol_fundamentals(payload, {"TWSE:2344": _context()})

    first = enriched["themes"][0]["direct_symbols"][0]["fundamentals"]
    second = enriched["themes"][1]["direct_symbols"][0]["fundamentals"]
    assert first == second


# ─── quarterly refresh gating ───────────────────────────────────────────────


def test_symbols_missing_from_cache_are_due() -> None:
    due = symbols_due_for_refresh(_payload(), cache={}, as_of=ANCHOR)

    assert due == ["TPEX:8299", "TWSE:2344"]


def test_symbol_cached_for_the_current_quarter_is_skipped() -> None:
    """Statements change quarterly; refetching hourly would be pure waste and
    unnecessary load on a scraped third party."""

    cache = {"TWSE:2344": _context(), "TPEX:8299": _context()}

    assert symbols_due_for_refresh(_payload(), cache=cache, as_of=ANCHOR) == []


def test_stale_quarter_becomes_due_again() -> None:
    cache = {"TWSE:2344": _context(period="2025Q4"), "TPEX:8299": _context()}

    assert symbols_due_for_refresh(_payload(), cache=cache, as_of=ANCHOR) == ["TWSE:2344"]


def test_cached_entry_without_a_fiscal_quarter_is_due_not_a_crash() -> None:
    """A context missing ``fiscal_quarter`` must read as stale, never raise.

    ``None < "2026Q1"`` is a TypeError, so one damaged or partially written
    cache entry would take down the whole hourly radar publish rather than
    costing a single refetch.
    """

    cache = {"TWSE:2344": {"quarters": []}, "TPEX:8299": _context()}

    assert symbols_due_for_refresh(_payload(), cache=cache, as_of=ANCHOR) == ["TWSE:2344"]


@pytest.mark.parametrize(
    "as_of,expected",
    [
        # TWSE filing deadlines: Q1 5/15, Q2 8/14, Q3 11/14, Q4 (annual) 3/31.
        # Verified against live Goodinfo data on 2026-08-06: newest filed
        # quarter was 2026Q1, i.e. Q2 had not yet landed.
        (datetime(2026, 8, 6, tzinfo=timezone.utc), "2026Q1"),
        (datetime(2026, 8, 13, tzinfo=timezone.utc), "2026Q1"),
        (datetime(2026, 8, 20, tzinfo=timezone.utc), "2026Q2"),
        (datetime(2026, 5, 14, tzinfo=timezone.utc), "2025Q4"),
        (datetime(2026, 5, 20, tzinfo=timezone.utc), "2026Q1"),
        (datetime(2026, 3, 30, tzinfo=timezone.utc), "2025Q3"),
        # The annual report is due 3/31 and carries Q4.
        (datetime(2026, 3, 31, tzinfo=timezone.utc), "2025Q4"),
        (datetime(2026, 4, 5, tzinfo=timezone.utc), "2025Q4"),
        (datetime(2026, 11, 20, tzinfo=timezone.utc), "2026Q3"),
        (datetime(2026, 1, 5, tzinfo=timezone.utc), "2025Q3"),
    ],
)
def test_expected_quarter_follows_filing_deadlines(as_of: datetime, expected: str) -> None:
    """Taiwan filings land in arrears, so the newest *available* quarter trails
    the calendar quarter — but by a deadline, not a fixed offset. A flat
    two-quarter lag stays a whole quarter stale for months after each filing
    date, refusing to refresh statements that are already public."""

    from scripts.theme_symbol_fundamentals import latest_expected_quarter

    assert latest_expected_quarter(as_of) == expected


def test_statement_detail_is_kept_out_of_the_published_payload() -> None:
    """``statements`` exists for the per-stock detail page, which reads the
    cache file directly. Inlining it here would multiply it by every symbol
    occurrence across every theme, in a file the radar page fetches on load
    and never uses those lines from.
    """
    payload = {
        "themes": [
            {"theme_id": "ai", "direct_symbols": [{"instrument_id": "TWSE:2330"}]},
        ]
    }
    context = {
        "quarters": [{"period": "2026Q1", "eps": 22.08}],
        "health": {"cash": 30356.0},
        "statements": {"income": {"2026Q1": {"rd_expense": 654.0}}},
    }

    attached = attach_symbol_fundamentals(payload, {"TWSE:2330": context})
    published = attached["themes"][0]["direct_symbols"][0]["fundamentals"]

    assert "statements" not in published
    assert published["quarters"] == context["quarters"]
    assert published["health"] == context["health"]
    # The cache entry itself must keep the detail the page depends on.
    assert "statements" in context
