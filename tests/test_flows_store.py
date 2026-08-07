"""Whole-market daily flows, stored one file per symbol.

The rankings only cover the ~293 symbols that reached a leaderboard. Looking up
an arbitrary stock needs the whole market, which is ~2,220 symbols a day.

That forces the layout. Measured 2026-08-07: sixty days of the whole market in
one file is 7.1MB, which every visitor would download to read one symbol.
Per-symbol files are 2.9KB each -- the page fetches exactly the one it needs.
Rows are arrays rather than objects because repeating five key names across
133,000 rows costs 2.1x the bytes for no added meaning.
"""

from __future__ import annotations

import json

import pytest

from scripts.flows_store import (
    SERIES_FIELDS,
    build_index,
    flow_filename,
    merge_symbol_series,
    split_by_symbol,
)


def _flow(instrument_id="TWSE:2330", name="台積電", day="2026-08-07",
          foreign=1000, trust=200, dealer=50, total=1250):
    return {
        "instrument_id": instrument_id, "symbol": instrument_id.split(":")[1],
        "name": name, "exchange": instrument_id.split(":")[0], "date": day,
        "foreign_net": foreign, "trust_net": trust, "dealer_net": dealer,
        "total_net": total, "unit": "shares",
    }


# ── file naming ───────────────────────────────────────────────────────────


def test_filename_carries_the_exchange_so_codes_cannot_collide() -> None:
    """A TWSE code and a TPEX code can be identical; one filename for both
    would silently serve the wrong company's numbers."""
    assert flow_filename("TWSE:2330") == "TWSE-2330.json"
    assert flow_filename("TPEX:8299") == "TPEX-8299.json"


def test_filename_rejects_a_path_traversal_attempt() -> None:
    """The code reaches this from a URL query parameter on the page side."""
    with pytest.raises(ValueError):
        flow_filename("TWSE:../../etc/passwd")
    with pytest.raises(ValueError):
        flow_filename("../secrets")


def test_filename_accepts_the_letter_suffixes_taiwan_etfs_use() -> None:
    assert flow_filename("TWSE:00631L") == "TWSE-00631L.json"
    assert flow_filename("TWSE:00403A") == "TWSE-00403A.json"


# ── splitting a day into per-symbol series ────────────────────────────────


def test_a_day_splits_into_one_entry_per_symbol() -> None:
    result = split_by_symbol([_flow(), _flow("TPEX:8299", "群聯")])

    assert sorted(result) == ["TPEX:8299", "TWSE:2330"]


def test_rows_are_compact_arrays_in_a_declared_field_order() -> None:
    """Objects cost 2.1x the bytes across 133,000 rows. The order is published
    as SERIES_FIELDS so the page reads by index rather than guessing.
    """
    result = split_by_symbol([_flow()])
    row = result["TWSE:2330"]["series"][0]

    assert row == ["2026-08-07", 1000, 200, 50, 1250]
    assert SERIES_FIELDS == ("date", "foreign_net", "trust_net", "dealer_net", "total_net")


def test_the_symbol_name_is_kept_once_not_per_row() -> None:
    result = split_by_symbol([_flow()])

    assert result["TWSE:2330"]["name"] == "台積電"
    assert result["TWSE:2330"]["exchange"] == "TWSE"


# ── merging days ──────────────────────────────────────────────────────────


def test_merging_keeps_the_series_newest_first() -> None:
    existing = {"series": [["2026-08-05", 1, 1, 1, 3]]}
    merged = merge_symbol_series(existing, [["2026-08-07", 2, 2, 2, 6]])

    assert [row[0] for row in merged] == ["2026-08-07", "2026-08-05"]


def test_rerunning_a_day_replaces_rather_than_duplicating_it() -> None:
    existing = {"series": [["2026-08-07", 1, 1, 1, 3]]}
    merged = merge_symbol_series(existing, [["2026-08-07", 9, 9, 9, 27]])

    assert merged == [["2026-08-07", 9, 9, 9, 27]]


def test_history_is_bounded() -> None:
    existing = {"series": [[f"2026-06-{d:02d}", 1, 1, 1, 3] for d in range(20, 10, -1)]}
    merged = merge_symbol_series(existing, [["2026-08-07", 2, 2, 2, 6]], history_days=3)

    assert len(merged) == 3
    assert merged[0][0] == "2026-08-07"


def test_a_symbol_with_no_prior_history_starts_a_series() -> None:
    assert merge_symbol_series(None, [["2026-08-07", 1, 1, 1, 3]]) == [
        ["2026-08-07", 1, 1, 1, 3]
    ]


def test_a_malformed_existing_series_is_replaced_not_propagated() -> None:
    """A truncated write must not make every later run fail."""
    assert merge_symbol_series({"series": "not a list"}, [["2026-08-07", 1, 1, 1, 3]]) == [
        ["2026-08-07", 1, 1, 1, 3]
    ]


# ── the index ─────────────────────────────────────────────────────────────


def test_the_index_lets_the_page_resolve_a_bare_code() -> None:
    """The user types 2330; the page needs to know it lives at TWSE-2330.json
    without probing both exchanges and 404ing on one."""
    index = build_index({
        "TWSE:2330": {"name": "台積電", "exchange": "TWSE"},
        "TPEX:8299": {"name": "群聯", "exchange": "TPEX"},
    })

    assert index["symbols"]["2330"] == {"file": "TWSE-2330.json", "name": "台積電", "exchange": "TWSE"}
    assert index["symbols"]["8299"]["exchange"] == "TPEX"


def test_the_index_is_json_serialisable_and_sorted() -> None:
    index = build_index({
        "TWSE:2454": {"name": "聯發科", "exchange": "TWSE"},
        "TWSE:2330": {"name": "台積電", "exchange": "TWSE"},
    })

    assert list(index["symbols"]) == ["2330", "2454"]
    json.dumps(index, ensure_ascii=False)


def test_a_duplicate_bare_code_across_exchanges_keeps_both() -> None:
    """Codes are not globally unique. Silently dropping one would make that
    stock permanently unsearchable."""
    index = build_index({
        "TWSE:1234": {"name": "甲公司", "exchange": "TWSE"},
        "TPEX:1234": {"name": "乙公司", "exchange": "TPEX"},
    })

    entry = index["symbols"]["1234"]
    alternates = entry.get("alternates") or []

    assert len({entry["exchange"], *(alt["exchange"] for alt in alternates)}) == 2
