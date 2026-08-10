from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from scripts.day_trading_activity import (
    DAY_TRADING_CACHE_FILENAME,
    TPEX_DAILY_URL,
    TPEX_INTRADAY_URL,
    TWSE_MI_INDEX_URL,
    TWSE_TWTB4U_URL,
    DayTradingDataError,
    build_market_rows,
    parse_tpex_day_trading,
    parse_tpex_total_volume,
    parse_twse_day_trading,
    parse_twse_total_volume,
    refresh_day_trading_cache,
    select_settled_target,
    validate_day_trading_cache,
)


FIXTURES = Path(__file__).parent / "fixtures" / "day_trading_activity"


def _fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _market_payload(exchange: str):
    if exchange == "TWSE":
        return _fixture("twse_twtb4u.json"), _fixture("twse_mi_index.json")
    return _fixture("tpex_intraday.json"), _fixture("tpex_daily_quotes.json")


def test_official_urls_use_current_twse_and_tpex_routes() -> None:
    assert TWSE_TWTB4U_URL.endswith("/rwd/zh/dayTrading/TWTB4U")
    assert TWSE_MI_INDEX_URL.endswith("/rwd/zh/afterTrading/MI_INDEX")
    assert TPEX_INTRADAY_URL.endswith("/www/zh-tw/intraday/stat")
    assert TPEX_DAILY_URL.endswith("/www/zh-tw/afterTrading/dailyQuotes")


def test_twse_parsers_find_named_tables_and_strip_commas() -> None:
    numerators = parse_twse_day_trading(_fixture("twse_twtb4u.json"))
    denominators = parse_twse_total_volume(_fixture("twse_mi_index.json"))

    assert numerators == {"2330": 300}
    assert denominators == {"2330": 1000}
    assert build_market_rows("TWSE", "2026-08-05", numerators, denominators)["TWSE:2330"][
        "day_trading_volume_ratio"
    ] == pytest.approx(0.3)


def test_tpex_parsers_find_named_columns_and_keep_exchange_qualified_keys() -> None:
    numerators = parse_tpex_day_trading(_fixture("tpex_intraday.json"))
    denominators = parse_tpex_total_volume(_fixture("tpex_daily_quotes.json"))
    rows = build_market_rows("TPEX", "2026-08-05", numerators, denominators)

    assert numerators == {"6488": 250}
    assert denominators == {"6488": 1000}
    assert set(rows) == {"TPEX:6488"}
    assert rows["TPEX:6488"]["day_trading_volume_ratio"] == pytest.approx(0.25)


def test_daily_parser_normalizes_field_whitespace_and_merges_matching_tables() -> None:
    payload = _fixture("tpex_daily_quotes.json")
    payload["tables"][0]["fields"][8] = " 成交股數\n"
    management_fields = list(payload["tables"][0]["fields"])
    management_row = [""] * len(management_fields)
    management_row[management_fields.index("代號")] = "8069"
    management_row[management_fields.index("名稱")] = "元太"
    management_row[management_fields.index(" 成交股數\n")] = "2,000"
    payload["tables"].append(
        {
            "title": "管理股票",
            "fields": management_fields,
            "data": [management_row],
        }
    )

    assert parse_tpex_total_volume(payload) == {"6488": 1000, "8069": 2000}


@pytest.mark.parametrize(
    ("numerator", "denominator", "reason"),
    [
        (10, 0, "total_volume_not_positive"),
        (-1, 10, "negative_volume"),
        (11, 10, "day_trading_volume_exceeds_total"),
    ],
)
def test_invalid_ratios_are_missing_not_zero(numerator: int, denominator: int, reason: str) -> None:
    row = build_market_rows("TWSE", "2026-08-05", {"2330": numerator}, {"2330": denominator})[
        "TWSE:2330"
    ]

    assert row["day_trading_volume_ratio"] is None
    assert row["missing_reason"] == reason


def test_missing_denominator_is_explicit_and_never_cross_joins_exchange() -> None:
    twse = build_market_rows("TWSE", "2026-08-05", {"6488": 5}, {})
    tpex = build_market_rows("TPEX", "2026-08-05", {"6488": 5}, {"6488": 10})

    assert twse["TWSE:6488"]["day_trading_volume_ratio"] is None
    assert twse["TWSE:6488"]["missing_reason"] == "total_volume_missing"
    assert tpex["TPEX:6488"]["day_trading_volume_ratio"] == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (parse_twse_day_trading, {}),
        (parse_twse_total_volume, {"stat": "OK", "tables": []}),
        (parse_tpex_day_trading, {"stat": "ok", "tables": [{"fields": ["wrong"], "data": []}]}),
        (parse_tpex_total_volume, "<html>error</html>"),
    ],
)
def test_schema_drift_empty_and_html_responses_fail_closed(parser, payload) -> None:
    with pytest.raises(DayTradingDataError):
        parser(payload)


@pytest.mark.parametrize(
    ("parser", "code_column"),
    [
        (parse_twse_day_trading, "證券代號"),
        (parse_twse_total_volume, "證券代號"),
        (parse_tpex_day_trading, "證券代號"),
        (parse_tpex_total_volume, "代號"),
    ],
)
def test_parsers_reject_partial_tables_that_only_contain_join_columns(parser, code_column) -> None:
    payload = {
        "stat": "OK",
        "tables": [{"fields": [code_column, "成交股數"], "data": [["2330", "100"]]}],
    }
    if parser in {parse_twse_day_trading, parse_tpex_day_trading}:
        payload["tables"][0]["fields"][1] = "當日沖銷交易成交股數"

    with pytest.raises(DayTradingDataError, match="required columns"):
        parser(payload)


def test_target_is_second_complete_trading_day_before_latest() -> None:
    target = select_settled_target(
        date(2026, 8, 10),
        ["2026-08-07", "2026-08-06", "2026-08-05", "2026-08-04"],
    )
    assert target == "2026-08-05"


def test_same_target_cache_hit_does_not_refetch(tmp_path: Path) -> None:
    calls: list[str] = []

    def fetch_market(exchange: str, _target: str):
        calls.append(exchange)
        return _market_payload(exchange)

    cache_path = tmp_path / DAY_TRADING_CACHE_FILENAME
    first = refresh_day_trading_cache(
        cache_path,
        target_date="2026-08-05",
        generated_at="2026-08-10T00:00:00Z",
        fetch_market=fetch_market,
    )
    second = refresh_day_trading_cache(
        cache_path,
        target_date="2026-08-05",
        generated_at="2026-08-10T01:00:00Z",
        fetch_market=fetch_market,
    )

    assert calls == ["TWSE", "TPEX"]
    assert second == first


def test_one_market_failure_keeps_other_market_and_marks_old_cache_stale(tmp_path: Path) -> None:
    cache_path = tmp_path / DAY_TRADING_CACHE_FILENAME
    prior = refresh_day_trading_cache(
        cache_path,
        target_date="2026-08-05",
        generated_at="2026-08-10T00:00:00Z",
        fetch_market=lambda exchange, _target: _market_payload(exchange),
    )

    def fail_twse(exchange: str, _target: str):
        if exchange == "TWSE":
            raise TimeoutError("bounded timeout")
        intraday, daily = _market_payload(exchange)
        intraday["date"] = daily["date"] = "20260806"
        return intraday, daily

    refreshed = refresh_day_trading_cache(
        cache_path,
        target_date="2026-08-06",
        generated_at="2026-08-10T01:00:00Z",
        fetch_market=fail_twse,
    )

    assert prior["symbols"]["TWSE:2330"]["status"] == "fresh"
    assert refreshed["sources"]["TWSE"]["status"] == "stale"
    assert refreshed["symbols"]["TWSE:2330"]["status"] == "stale"
    assert refreshed["symbols"]["TPEX:6488"]["as_of"] == "2026-08-06"
    assert refreshed["symbols"]["TPEX:6488"]["status"] == "fresh"


def test_no_prior_cache_records_missing_market_without_fabricated_rows(tmp_path: Path) -> None:
    payload = refresh_day_trading_cache(
        tmp_path / DAY_TRADING_CACHE_FILENAME,
        target_date="2026-08-05",
        generated_at="2026-08-10T00:00:00Z",
        fetch_market=lambda exchange, _target: (
            (_ for _ in ()).throw(TimeoutError("timeout"))
            if exchange == "TWSE"
            else _market_payload(exchange)
        ),
    )

    assert payload["sources"]["TWSE"]["status"] == "missing"
    assert not any(key.startswith("TWSE:") for key in payload["symbols"])
    assert payload["sources"]["TWSE"]["error"] == "TimeoutError: timeout"


def test_disjoint_official_symbol_sets_do_not_mark_market_fresh(tmp_path: Path) -> None:
    numerator, denominator = _market_payload("TWSE")
    denominator["tables"][0]["data"][0][0] = "2317"

    payload = refresh_day_trading_cache(
        tmp_path / DAY_TRADING_CACHE_FILENAME,
        target_date="2026-08-05",
        generated_at="2026-08-10T00:00:00Z",
        fetch_market=lambda exchange, _target: (
            (numerator, denominator) if exchange == "TWSE" else _market_payload(exchange)
        ),
    )

    assert payload["sources"]["TWSE"]["status"] == "missing"
    assert not any(key.startswith("TWSE:") for key in payload["symbols"])


def test_cache_schema_and_source_attribution_are_exact() -> None:
    payload = refresh_day_trading_cache(
        Path("/dev/null"),
        target_date="2026-08-05",
        generated_at="2026-08-10T00:00:00Z",
        fetch_market=lambda exchange, _target: _market_payload(exchange),
        write=False,
    )
    validate_day_trading_cache(payload)
    assert set(payload) == {"schema_version", "generated_at", "target_date", "sources", "symbols"}
    assert payload["sources"]["TWSE"] == {
        "as_of": "2026-08-05",
        "finality": "settled_t_plus_2",
        "numerator_url": TWSE_TWTB4U_URL,
        "denominator_url": TWSE_MI_INDEX_URL,
        "status": "fresh",
        "error": None,
    }
    assert payload["sources"]["TPEX"]["numerator_url"] == TPEX_INTRADAY_URL
    assert payload["sources"]["TPEX"]["denominator_url"] == TPEX_DAILY_URL

    broken = copy.deepcopy(payload)
    broken["symbols"]["TWSE:2330"]["extra"] = True
    with pytest.raises(ValueError, match="unexpected symbol keys"):
        validate_day_trading_cache(broken)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: payload["symbols"]["TWSE:2330"].update({"day_trading_volume": -1}),
            "invalid day-trading volume",
        ),
        (
            lambda payload: payload["symbols"]["TWSE:2330"].update({"as_of": "2026-08-04"}),
            "source date mismatch",
        ),
        (
            lambda payload: payload["symbols"]["TWSE:2330"].update({"day_trading_volume_ratio": 0.9}),
            "ratio does not match",
        ),
        (
            lambda payload: payload["symbols"]["TWSE:2330"].update(
                {"day_trading_volume_ratio": None, "status": "missing", "missing_reason": "fabricated"}
            ),
            "fresh source has no valid join",
        ),
    ],
)
def test_cache_validator_rejects_corrupted_numeric_and_date_invariants(mutate, message) -> None:
    payload = refresh_day_trading_cache(
        Path("/dev/null"),
        target_date="2026-08-05",
        generated_at="2026-08-10T00:00:00Z",
        fetch_market=lambda exchange, _target: _market_payload(exchange),
        write=False,
    )
    mutate(payload)

    with pytest.raises(ValueError, match=message):
        validate_day_trading_cache(payload)
