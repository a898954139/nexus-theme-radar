"""Per-stock institutional net buy/sell from the official exchange APIs.

TWSE and TPEX both publish the whole market for one trading day in a single
response, so this is a two-request-per-day job rather than a per-symbol scrape.

Both feeds carry the same trap: the dealer figure appears three times -- the
total, the proprietary component and the hedging component -- under labels that
differ only by a parenthetical. Matching on a keyword lands on a component, and
the resulting numbers stay individually plausible while being wrong. These
tests pin the columns by index and, more importantly, pin the reconciliation
that would catch it if they ever move.
"""

from __future__ import annotations

from datetime import date

import pytest

from scripts.institutional_flows import (
    ROC_DATE_FORMAT_EXAMPLE,
    parse_tpex_payload,
    parse_twse_csv,
    roc_date,
    to_instrument_id,
)

# Trimmed from the real 2026-08-05 responses. Column positions are preserved
# exactly; only the number of data rows is reduced.
TWSE_HEADER = (
    "證券代號,證券名稱,外陸資買進股數(不含外資自營商),外陸資賣出股數(不含外資自營商),"
    "外陸資買賣超股數(不含外資自營商),外資自營商買進股數,外資自營商賣出股數,"
    "外資自營商買賣超股數,投信買進股數,投信賣出股數,投信買賣超股數,自營商買賣超股數,"
    "自營商買進股數(自行買賣),自營商賣出股數(自行買賣),自營商買賣超股數(自行買賣),"
    "自營商買進股數(避險),自營商賣出股數(避險),自營商買賣超股數(避險),三大法人買賣超股數,"
)


def _twse_csv(rows: list[str]) -> str:
    return "115年08月05日 三大法人買賣超日報\n" + TWSE_HEADER + "\n" + "\n".join(rows) + "\n"


# 2330: foreign +1,000, trust +200, dealer total +50 (self +30, hedge +20)
#       => 三大法人 1,250. The self-only column (30) is deliberately different
#       from the dealer total so a mis-indexed parse cannot pass by accident.
TWSE_2330 = (
    '="2330","台積電 ","5,000","4,000","1,000","0","0","0","300","100","200","50",'
    '"130","100","30","120","100","20","1,250",'
)


def _tpex_payload(rows: list[list[str]]) -> dict:
    return {
        "tables": [
            {
                "fields": ["代號", "名稱"] + ["買進股數", "賣出股數", "買賣超股數"] * 7
                + ["三大法人買賣超股數合計"],
                "data": rows,
            }
        ]
    }


def _tpex_row(code="8299", name="群聯", foreign_excl=800, foreign_dealer=0,
              trust=100, dealer_total=25, total=925) -> list[str]:
    foreign_all = foreign_excl + foreign_dealer
    return [
        code, name,
        "0", "0", str(foreign_excl),          # [2..4]   foreign excl. dealer
        "0", "0", str(foreign_dealer),        # [5..7]   foreign dealer
        "0", "0", str(foreign_all),           # [8..10]  foreign total
        "0", "0", str(trust),                 # [11..13] trust
        "0", "0", "0",                        # [14..16] dealer self
        "0", "0", "0",                        # [17..19] dealer hedge
        "0", "0", str(dealer_total),          # [20..22] dealer total
        str(total),                           # [23]
    ]


# ── date handling ─────────────────────────────────────────────────────────


def test_twse_and_tpex_want_different_date_formats() -> None:
    """TWSE takes 20260805; TPEX takes the ROC year, 115/08/05. Sending either
    one the other's format returns an empty result rather than an error, so a
    format slip looks like a quiet holiday instead of a bug."""
    assert roc_date(date(2026, 8, 5)) == "115/08/05"
    assert date(2026, 8, 5).strftime("%Y%m%d") == "20260805"


def test_roc_year_is_the_western_year_minus_1911() -> None:
    assert roc_date(date(2000, 1, 1)) == "89/01/01"
    assert roc_date(date(2026, 12, 31)) == "115/12/31"


# ── TWSE parsing ──────────────────────────────────────────────────────────


def test_twse_row_maps_to_the_total_dealer_column_not_a_component() -> None:
    """Column 11 is the dealer total; 14 (self) and 17 (hedge) are its parts.

    Keyword-matching "自營商買賣超股數" hits column 14 first. Measured against
    the real 2026-08-05 market: using 14 corrupts 750 of 1,332 symbols while
    leaving every figure individually plausible.
    """
    flows = parse_twse_csv(_twse_csv([TWSE_2330]), as_of=date(2026, 8, 5))

    assert len(flows) == 1
    entry = flows[0]
    assert entry["foreign_net"] == 1000
    assert entry["trust_net"] == 200
    assert entry["dealer_net"] == 50, "picked up the self-trade component, not the total"


def test_twse_rows_failing_reconciliation_are_dropped() -> None:
    """foreign + trust + dealer must equal the published total. A row that
    disagrees means the columns moved, and a wrong number is worse than a
    missing one on a page about money flow.
    """
    broken = (
        '="1234","壞資料 ","0","0","1,000","0","0","0","0","0","200","50",'
        '"0","0","30","0","0","20","9,999",'
    )
    flows = parse_twse_csv(_twse_csv([TWSE_2330, broken]), as_of=date(2026, 8, 5))

    assert [entry["symbol"] for entry in flows] == ["2330"]


def test_twse_parses_the_exchange_and_instrument_id() -> None:
    flows = parse_twse_csv(_twse_csv([TWSE_2330]), as_of=date(2026, 8, 5))

    assert flows[0]["exchange"] == "TWSE"
    assert flows[0]["instrument_id"] == "TWSE:2330"
    assert flows[0]["date"] == "2026-08-05"


def test_twse_strips_the_excel_quoting_from_the_code() -> None:
    """TWSE wraps codes as ="2330" so Excel keeps the leading zeros."""
    flows = parse_twse_csv(_twse_csv([TWSE_2330]), as_of=date(2026, 8, 5))

    assert flows[0]["symbol"] == "2330"


def test_twse_ignores_the_title_and_header_rows() -> None:
    flows = parse_twse_csv(_twse_csv([TWSE_2330]), as_of=date(2026, 8, 5))

    assert all(entry["symbol"].strip() for entry in flows)
    assert "證券代號" not in {entry["symbol"] for entry in flows}


def test_an_empty_twse_response_yields_no_rows_rather_than_raising() -> None:
    """A non-trading day returns a body with no data rows."""
    assert parse_twse_csv("115年08月09日 三大法人買賣超日報\n", as_of=date(2026, 8, 9)) == []


# ── TPEX parsing ──────────────────────────────────────────────────────────


def test_tpex_row_maps_to_the_dealer_total_column() -> None:
    flows = parse_tpex_payload(_tpex_payload([_tpex_row()]), as_of=date(2026, 8, 5))

    assert len(flows) == 1
    entry = flows[0]
    assert entry["foreign_net"] == 800
    assert entry["trust_net"] == 100
    assert entry["dealer_net"] == 25
    assert entry["exchange"] == "TPEX"
    assert entry["instrument_id"] == "TPEX:8299"


def test_tpex_reconciles_against_the_foreign_total_not_the_excluding_column() -> None:
    """TPEX's published total is built from the foreign *total* (column 10).

    On 2026-08-05 the foreign-dealer column was zero for all 919 symbols, so
    both readings agreed by coincidence. Reconciling against column 4 would
    start dropping rows the first day that is not true.
    """
    row = _tpex_row(foreign_excl=800, foreign_dealer=50, trust=100,
                    dealer_total=25, total=975)

    flows = parse_tpex_payload(_tpex_payload([row]), as_of=date(2026, 8, 5))

    assert len(flows) == 1, "reconciliation rejected a row the exchange considers valid"
    # The reported per-stock foreign figure stays the excluding-dealer one, to
    # match what TWSE publishes for the same concept.
    assert flows[0]["foreign_net"] == 800


def test_tpex_rows_failing_reconciliation_are_dropped() -> None:
    row = _tpex_row(foreign_excl=800, foreign_dealer=0, trust=100,
                    dealer_total=25, total=9999)

    assert parse_tpex_payload(_tpex_payload([row]), as_of=date(2026, 8, 5)) == []


def test_an_empty_tpex_payload_yields_no_rows() -> None:
    assert parse_tpex_payload({"tables": []}, as_of=date(2026, 8, 5)) == []
    assert parse_tpex_payload({}, as_of=date(2026, 8, 5)) == []


# ── shared shape ──────────────────────────────────────────────────────────


def test_instrument_ids_match_the_fundamentals_cache_keys() -> None:
    """The detail page joins flows to fundamentals on this key."""
    assert to_instrument_id("TWSE", "2330") == "TWSE:2330"
    assert to_instrument_id("TPEX", "8299") == "TPEX:8299"


def test_units_are_shares_and_recorded_as_such() -> None:
    """Both feeds publish 股數. The rankings publish 張 (1,000 shares); mixing
    them silently understates one by three orders of magnitude."""
    flows = parse_twse_csv(_twse_csv([TWSE_2330]), as_of=date(2026, 8, 5))

    assert flows[0]["unit"] == "shares"


def test_a_zero_net_is_kept_not_treated_as_missing() -> None:
    """A symbol the institutions did not trade is a real observation."""
    row = (
        '="9999","無交易 ","0","0","0","0","0","0","0","0","0","0",'
        '"0","0","0","0","0","0","0",'
    )
    flows = parse_twse_csv(_twse_csv([row]), as_of=date(2026, 8, 5))

    assert len(flows) == 1
    assert flows[0]["foreign_net"] == 0
    assert flows[0]["total_net"] == 0


# ── merging into the store ────────────────────────────────────────────────

from scripts.update_institutional_flows import merge_flows  # noqa: E402

UNIVERSE = {"TWSE:2330", "TPEX:8299"}


def _flow(instrument_id="TWSE:2330", day="2026-08-05", total=1250):
    return {
        "instrument_id": instrument_id, "symbol": instrument_id.split(":")[1],
        "name": "台積電", "exchange": instrument_id.split(":")[0],
        "date": day, "foreign_net": 1000, "trust_net": 200,
        "dealer_net": 50, "total_net": total, "unit": "shares",
    }


def test_only_symbols_in_our_universe_are_stored() -> None:
    """The exchanges publish ~2,250 symbols a day; the page only ever looks up
    the ones the radar surfaced."""
    merged = merge_flows({}, [_flow(), _flow("TWSE:9999")], universe=UNIVERSE)

    assert list(merged) == ["TWSE:2330"]


def test_rerunning_the_same_day_replaces_rather_than_duplicates() -> None:
    """The job may be re-run after a failure; two rows for one date would
    double that day on the chart."""
    store = merge_flows({}, [_flow(total=1250)], universe=UNIVERSE)
    merged = merge_flows(store, [_flow(total=9999)], universe=UNIVERSE)

    assert len(merged["TWSE:2330"]) == 1
    assert merged["TWSE:2330"][0]["total_net"] == 9999


def test_series_is_newest_first_regardless_of_arrival_order() -> None:
    store = merge_flows({}, [_flow(day="2026-08-05")], universe=UNIVERSE)
    merged = merge_flows(store, [_flow(day="2026-08-04")], universe=UNIVERSE)

    assert [entry["date"] for entry in merged["TWSE:2330"]] == ["2026-08-05", "2026-08-04"]


def test_history_is_bounded_and_drops_the_oldest() -> None:
    """Unbounded growth would eventually make the file too large for a static
    page to fetch on load."""
    store: dict = {}
    for day in range(1, 6):
        store = merge_flows(
            store, [_flow(day=f"2026-08-{day:02d}")], universe=UNIVERSE, history_days=3,
        )

    dates = [entry["date"] for entry in store["TWSE:2330"]]
    assert dates == ["2026-08-05", "2026-08-04", "2026-08-03"]


def test_stored_entries_drop_the_fields_repeated_on_every_row() -> None:
    """instrument_id/name/exchange are constant per symbol; repeating them on
    every one of 60 daily entries is pure payload weight."""
    merged = merge_flows({}, [_flow()], universe=UNIVERSE)
    entry = merged["TWSE:2330"][0]

    assert set(entry) == {"date", "foreign_net", "trust_net", "dealer_net", "total_net"}


def test_an_untouched_symbol_keeps_its_history() -> None:
    store = merge_flows({}, [_flow("TPEX:8299")], universe=UNIVERSE)
    merged = merge_flows(store, [_flow("TWSE:2330")], universe=UNIVERSE)

    assert "TPEX:8299" in merged
    assert len(merged["TPEX:8299"]) == 1
