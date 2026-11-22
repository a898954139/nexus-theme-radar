from __future__ import annotations

import copy
import json

from scripts.moat_screen import (
    LONG_RULES,
    THRESHOLDS,
    evaluate,
    load_fundamentals_universe,
    moat_metrics,
    screen_summary,
    screen_universe,
)
from scripts.stock_watchlist import build_stock_watchlist, validate_stock_watchlist_payload

from test_stock_watchlist import _base_inputs


def _statement(
    *,
    net_income=(30, 25, 25, 20),
    equity=1000,
    gross=(0.40, 0.40, 0.40, 0.40),
    operating=(10, 10, 10, 10),
    debt=0.30,
    periods=("2026Q2", "2026Q1", "2025Q4", "2025Q3"),
):
    return {
        "quarters": [{"period": p, "gross_margin": g} for p, g in zip(periods, gross)],
        "health": {"debt_ratio": debt},
        "statements": {
            "income": {p: {"net_income": n} for p, n in zip(periods, net_income)},
            "balance": {periods[0]: {"total_equity": equity}},
            "cash_flow": {p: {"operating": o} for p, o in zip(periods, operating)},
        },
    }


def test_metrics_are_ttm_and_four_quarter_averages():
    metrics = moat_metrics(_statement())
    assert metrics["roe_ttm"] == 0.1
    assert metrics["gross_margin_4q"] == 0.4
    assert metrics["debt_ratio"] == 0.3
    assert metrics["operating_cash_flow_ttm"] == 40


def test_thresholds_are_the_agreed_moat_v1_values():
    assert THRESHOLDS == {
        "roe_ttm_min": 0.08,
        "gross_margin_4q_min": 0.15,
        "debt_ratio_max": 0.60,
        "operating_cash_flow_ttm_min_exclusive": 0.0,
    }


def test_negative_cash_flow_fails_only_the_long_horizon():
    row = evaluate(_statement(operating=(-10, -10, 5, 5)))
    assert row["short_pass"] is True
    assert row["long_pass"] is False
    assert row["failed"] == ["operating_cash_flow_ttm"]


def test_each_short_rule_fails_both_horizons():
    for statement, rule in (
        (_statement(net_income=(1, 1, 1, 1)), "roe_ttm"),
        (_statement(gross=(0.10, 0.10, 0.10, 0.10)), "gross_margin_4q"),
        (_statement(debt=0.61), "debt_ratio"),
    ):
        row = evaluate(statement)
        assert row["failed"] == [rule]
        assert row["short_pass"] is False and row["long_pass"] is False


def test_boundaries_are_inclusive_where_agreed():
    row = evaluate(_statement(net_income=(20, 20, 20, 20), gross=(0.15,) * 4, debt=0.60, operating=(0, 0, 0, 1)))
    assert row["short_pass"] is True and row["long_pass"] is True


def test_missing_or_gapped_data_fails_closed_and_is_named():
    gapped = _statement(periods=("2026Q2", "2026Q1", "2025Q3", "2025Q2"))
    row = evaluate(gapped)
    assert "roe_ttm_missing" in row["failed"]
    assert "operating_cash_flow_ttm_missing" in row["failed"]
    assert row["short_pass"] is False

    no_equity = _statement(equity=-5)
    assert "roe_ttm_missing" in evaluate(no_equity)["failed"]

    empty = evaluate({})
    assert empty["failed"] == [f"{rule}_missing" for rule in LONG_RULES]
    assert empty["short_pass"] is False


def test_universe_loader_reads_only_statement_files(tmp_path):
    (tmp_path / "TWSE-2330.json").write_text(json.dumps(_statement()), encoding="utf-8")
    (tmp_path / "TPEX-6488.json").write_text(json.dumps(_statement(debt=0.9)), encoding="utf-8")
    (tmp_path / "symbol_registry.tw.json").write_text("{}", encoding="utf-8")
    (tmp_path / "TWSE-BROKEN.json").write_text("{not json", encoding="utf-8")
    universe = load_fundamentals_universe(tmp_path)
    assert sorted(universe) == ["TPEX:6488", "TWSE:2330"]
    screened = screen_universe(universe)
    summary = screen_summary(screened, generated_at="2026-11-22T00:00:00Z", candidate_ids={"TWSE:2330", "TWSE:1111"})
    assert summary["universe"] == {"evaluated": 2, "short_pass": 1, "long_pass": 1, "no_fundamentals": 0}
    assert summary["candidates"] == {"evaluated": 1, "short_pass": 1, "long_pass": 1, "no_fundamentals": 1}
    assert summary["failure_counts"] == {"debt_ratio": 1}


def _moat(short: dict[str, bool], long: dict[str, bool]):
    return {key: {"short_pass": short[key], "long_pass": long[key]} for key in short}


def _gated(moat, *, long_gate=True, reference=None):
    momentum, fundamentals, flows, daytrade = _base_inputs()
    return build_stock_watchlist(
        momentum_payload=momentum,
        fundamentals_by_instrument=fundamentals,
        institutional_flows=flows,
        day_trading_activity=daytrade,
        generated_at="2026-08-08T01:00:00Z",
        candidate_as_of="2026-08-08T00:00:00Z",
        reference_fundamentals=reference if reference is not None else fundamentals,
        moat=moat,
        long_moat_gate=long_gate,
    )


def test_watchlist_selects_only_short_passing_names_and_long_list_is_a_subset():
    moat = _moat(
        {"TWSE:2330": True, "TPEX:6488": True, "TWSE:2454": False},
        {"TWSE:2330": True, "TPEX:6488": False, "TWSE:2454": False},
    )
    payload = _gated(moat)
    validate_stock_watchlist_payload(payload)
    short_ids = [i["instrument"]["instrument_id"] for i in payload["short"]["items"]]
    long_ids = [i["instrument"]["instrument_id"] for i in payload["long"]["items"]]
    assert sorted(short_ids) == ["TPEX:6488", "TWSE:2330"]
    assert long_ids == ["TWSE:2330"]
    short_only = next(i for i in payload["short"]["items"] if i["instrument"]["instrument_id"] == "TPEX:6488")
    assert short_only["long"]["rank"] is None
    assert payload["methodology_version"] == "stock_watchlist_v2"
    searchable = {row["instrument"]["instrument_id"]: row for row in payload["searchable"]}
    assert searchable["TWSE:2454"]["selected_top50"] is False
    assert searchable["TPEX:6488"]["long_rank"] is None
    assert payload["coverage"]["eligible_count"] == 3


def test_long_gate_off_keeps_long_list_equal_to_short_list():
    moat = _moat(
        {"TWSE:2330": True, "TPEX:6488": True, "TWSE:2454": True},
        {"TWSE:2330": True, "TPEX:6488": False, "TWSE:2454": False},
    )
    payload = _gated(moat, long_gate=False)
    assert payload["short"]["count"] == payload["long"]["count"] == 3


def test_fundamental_score_uses_the_fixed_universe_not_the_candidate_list():
    """M018: a candidate's score must not move when other candidates change."""
    moat = _moat({k: True for k in ("TWSE:2330", "TPEX:6488", "TWSE:2454")}, {k: True for k in ("TWSE:2330", "TPEX:6488", "TWSE:2454")})
    _, fundamentals, _, _ = _base_inputs()
    universe = copy.deepcopy(fundamentals)
    weak = copy.deepcopy(fundamentals["TWSE:2454"])
    for index in range(20):
        universe[f"TWSE:{8000 + index}"] = weak

    def score(payload):
        return next(
            i["fundamentals"]["score"] for i in payload["short"]["items"] if i["instrument"]["instrument_id"] == "TWSE:2330"
        )

    first = score(_gated(moat, reference=universe))

    momentum, fundamentals, flows, daytrade = _base_inputs()
    momentum["themes"][0]["related_symbols"] = []  # 2454 leaves the candidate list this hour
    second_payload = build_stock_watchlist(
        momentum_payload=momentum,
        fundamentals_by_instrument=fundamentals,
        institutional_flows=flows,
        day_trading_activity=daytrade,
        generated_at="2026-08-08T02:00:00Z",
        candidate_as_of="2026-08-08T01:00:00Z",
        reference_fundamentals=universe,
        moat=moat,
    )
    assert score(second_payload) == first


def test_report_explains_every_candidate_next_to_the_watchlist_outcome():
    moat = {
        "TWSE:2330": evaluate(_statement()),
        "TPEX:6488": evaluate(_statement(operating=(-10, -10, 5, 5))),
        "TWSE:2454": evaluate(_statement(gross=(0.096,) * 4)),
    }
    payload = _gated(moat)
    summary = screen_summary(
        moat,
        generated_at=payload["generated_at"],
        candidate_ids={row["instrument"]["instrument_id"] for row in payload["searchable"]},
        searchable=payload["searchable"],
    )
    report = {row["instrument"]["instrument_id"]: row for row in summary["report"]}
    assert set(report) == {"TWSE:2330", "TPEX:6488", "TWSE:2454"}
    rejected = report["TWSE:2454"]
    assert rejected["failed"] == ["gross_margin_4q"]
    assert rejected["selected_top50"] is False and rejected["short_rank"] is None
    assert rejected["metrics"]["gross_margin_4q"] == 0.096
    short_only = report["TPEX:6488"]
    assert short_only["short_pass"] and not short_only["long_pass"]
    assert short_only["selected_top50"] and short_only["long_rank"] is None
    assert [row["rule"] for row in summary["rule_stats"]] == list(LONG_RULES)
    assert summary["rule_stats"][1]["universe_failed"] == 1
