"""Money-flow leaderboards, cross-marked against our own symbol universe.

These are published by an upstream project rather than an exchange, and they
carry two hazards that are invisible until the page renders wrong.

The first is structural: the two metrics do not share a payload shape. The
net-buy files wrap their rows in an object with metadata; the holding-change
files are a bare list. Code written against one silently reads nothing from the
other.

The second is semantic. Leveraged and thematic ETFs dominate these boards --
their unit counts move for reasons that have nothing to do with conviction in a
company -- and some report a three-institution holding ratio above 100%, which
is arithmetically impossible for a share count and reflects a different
denominator. Left in, they fill the top of every board.
"""

from __future__ import annotations

import pytest

from scripts.institutional_rankings import (
    RANKING_WINDOWS,
    is_probable_etf,
    parse_ranking,
    ranking_key,
)

UNIVERSE = {"TWSE:2330", "TPEX:8299"}


def _netbuy_payload(rows: list[dict]) -> dict:
    """The wrapped shape, as published for metric=netbuy."""
    return {
        "updated": "2026-08-05T11:10:00Z",
        "metric": "net_buy_sell",
        "window": 5,
        "unit": "張",
        "side": "up",
        "date_range": {"start": "2026-07-30", "end": "2026-08-05"},
        "data": rows,
    }


def _netbuy_row(rank=1, code="2330", name="台積電", market="TWSE", total=242326):
    return {"rank": rank, "code": code, "name": name, "market": market,
            "foreign": 200000, "trust": 42326, "dealer": 0, "total": total}


def _change_row(code="2330", name="台積電", market="TWSE", ratio=44.05, change=42.03):
    return {"code": code, "name": name, "market": market,
            "three_inst_ratio": ratio, "change": change}


# ── the two payload shapes ────────────────────────────────────────────────


def test_the_wrapped_netbuy_shape_is_parsed() -> None:
    result = parse_ranking(_netbuy_payload([_netbuy_row()]), universe=UNIVERSE)

    assert result["metric"] == "net_buy_sell"
    assert result["unit"] == "張"
    assert len(result["entries"]) == 1


def test_the_bare_list_change_shape_is_parsed() -> None:
    """metric=change publishes a bare list with no metadata wrapper. Code that
    only handles the wrapped shape reads zero rows and shows an empty board
    rather than failing loudly.
    """
    result = parse_ranking([_change_row()], universe=UNIVERSE)

    assert len(result["entries"]) == 1
    assert result["entries"][0]["code"] == "2330"


def test_an_empty_or_malformed_payload_yields_no_entries() -> None:
    assert parse_ranking([], universe=UNIVERSE)["entries"] == []
    assert parse_ranking({}, universe=UNIVERSE)["entries"] == []
    assert parse_ranking(None, universe=UNIVERSE)["entries"] == []


# ── cross-marking our universe ────────────────────────────────────────────


def test_symbols_in_our_universe_are_marked() -> None:
    """The whole point of the board for us: which of the stocks the radar
    surfaced are the institutions actually buying."""
    rows = [_netbuy_row(code="2330"), _netbuy_row(rank=2, code="1234", name="別的")]

    entries = parse_ranking(_netbuy_payload(rows), universe=UNIVERSE)["entries"]

    assert entries[0]["in_universe"] is True
    assert entries[1]["in_universe"] is False


def test_marking_respects_the_exchange_not_just_the_code() -> None:
    """A TPEX code that happens to match a TWSE one in our universe is not the
    same instrument."""
    rows = [_netbuy_row(code="2330", market="TPEX")]

    entries = parse_ranking(_netbuy_payload(rows), universe=UNIVERSE)["entries"]

    assert entries[0]["in_universe"] is False


def test_tpex_symbols_in_our_universe_are_marked() -> None:
    rows = [_netbuy_row(code="8299", name="群聯", market="TPEX")]

    entries = parse_ranking(_netbuy_payload(rows), universe=UNIVERSE)["entries"]

    assert entries[0]["in_universe"] is True
    assert entries[0]["instrument_id"] == "TPEX:8299"


# ── ETFs ──────────────────────────────────────────────────────────────────


def test_leveraged_and_numbered_etfs_are_recognised() -> None:
    """Taiwan ETF codes start 00; leveraged and inverse ones carry an L/R
    suffix. These dominate the boards on unit-count mechanics."""
    assert is_probable_etf("00685L") is True
    assert is_probable_etf("00960") is True
    assert is_probable_etf("00403A") is True
    assert is_probable_etf("2330") is False
    assert is_probable_etf("8299") is False


def test_etf_entries_are_flagged_rather_than_silently_dropped() -> None:
    """Flagging lets the page choose; dropping here would make the ranks lie
    about the source data."""
    rows = [_netbuy_row(code="00685L", name="群益臺灣加權正2"),
            _netbuy_row(rank=2, code="2330")]

    entries = parse_ranking(_netbuy_payload(rows), universe=UNIVERSE)["entries"]

    assert entries[0]["is_etf"] is True
    assert entries[1]["is_etf"] is False


def test_an_impossible_holding_ratio_is_flagged() -> None:
    """00960 publishes three_inst_ratio 170.8% -- impossible as a share of
    shares outstanding. Rendering it beside real percentages implies the two
    mean the same thing.
    """
    entries = parse_ranking([_change_row(code="00960", ratio=170.77)],
                            universe=UNIVERSE)["entries"]

    assert entries[0]["ratio_out_of_range"] is True


def test_a_normal_ratio_is_not_flagged() -> None:
    entries = parse_ranking([_change_row(code="2330", ratio=44.05)],
                            universe=UNIVERSE)["entries"]

    assert entries[0]["ratio_out_of_range"] is False


def test_a_missing_ratio_is_not_treated_as_out_of_range() -> None:
    """Absent is not the same as impossible."""
    row = {"code": "2330", "name": "台積電", "market": "TWSE", "change": 1.0}

    entries = parse_ranking([row], universe=UNIVERSE)["entries"]

    assert entries[0]["ratio_out_of_range"] is False


# ── file naming ───────────────────────────────────────────────────────────


def test_ranking_keys_cover_every_metric_window_and_side() -> None:
    """16 files: 2 metrics x 4 windows x 2 sides."""
    keys = [ranking_key(metric, window, side)
            for metric in ("netbuy", "change")
            for window in RANKING_WINDOWS
            for side in ("up", "down")]

    assert len(keys) == 16
    assert len(set(keys)) == 16
    assert "top_three_inst_netbuy_5_up" in keys
    assert "top_three_inst_change_20_down" in keys


def test_windows_match_what_upstream_publishes() -> None:
    assert list(RANKING_WINDOWS) == [5, 10, 20, 30]


# ── trimming ──────────────────────────────────────────────────────────────

from scripts.update_institutional_rankings import trim_entries  # noqa: E402


def _entry(code="1234", in_universe=False):
    return {"code": code, "in_universe": in_universe}


def test_trimming_keeps_the_head_of_the_board() -> None:
    entries = [_entry(str(i)) for i in range(100)]

    assert len(trim_entries(entries, top_n=50)) == 50


def test_a_symbol_we_track_is_kept_however_far_down_it_ranks() -> None:
    """A stock the radar surfaced sitting at rank 120 is the most useful row on
    the board for us; a plain head-of-list cut would drop it."""
    entries = [_entry(str(i)) for i in range(100)]
    entries[80] = _entry("2330", in_universe=True)

    kept = trim_entries(entries, top_n=50)

    assert any(entry["code"] == "2330" for entry in kept)
    assert len(kept) == 51


def test_a_tracked_symbol_inside_the_head_is_not_duplicated() -> None:
    entries = [_entry("2330", in_universe=True)] + [_entry(str(i)) for i in range(10)]

    kept = trim_entries(entries, top_n=5)

    assert [entry["code"] for entry in kept].count("2330") == 1


def test_trimming_a_short_board_changes_nothing() -> None:
    entries = [_entry(str(i)) for i in range(3)]

    assert trim_entries(entries, top_n=50) == entries
