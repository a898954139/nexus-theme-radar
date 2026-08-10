from __future__ import annotations

import copy

import pytest

from scripts.stock_watchlist import (
    average_rank_percentiles,
    build_stock_watchlist,
    validate_stock_watchlist_payload,
)


def _symbol(instrument_id: str, name: str | None = None, **overrides):
    exchange, code = instrument_id.split(":", 1)
    row = {
        "instrument_id": instrument_id,
        "market_id": "TW_EQUITY",
        "asset_class": "equity",
        "symbol": code,
        "exchange": exchange,
        "name_zh": name or code,
    }
    row.update(overrides)
    return row


def _theme(theme_id: str, heat: float, momentum: float, direct=(), related=(), change=0):
    return {
        "theme_id": theme_id,
        "name_zh": theme_id,
        "heat_score": heat,
        "momentum_score": momentum,
        "heat_change_24h": change,
        "direct_symbols": list(direct),
        "related_symbols": list(related),
    }


def _fundamentals(
    *,
    latest_revenue=120,
    prior_revenue=100,
    latest_eps=12,
    prior_eps=10,
    previous_revenue=110,
    previous_eps=11,
    gross=0.5,
    operating=0.3,
    net=0.2,
    cash_flow=20,
    debt=0.3,
):
    return {
        "fiscal_quarter": "2026Q2",
        "quarters": [
            {
                "period": "2026Q2",
                "revenue": latest_revenue,
                "eps": latest_eps,
                "gross_margin": gross,
                "operating_margin": operating,
                "net_margin": net,
            },
            {"period": "2026Q1", "revenue": previous_revenue, "eps": previous_eps},
            {"period": "2025Q2", "revenue": prior_revenue, "eps": prior_eps},
        ],
        "health": {
            "operating_cash_flow_2026Q2": cash_flow,
            "debt_ratio": debt,
        },
    }


def _flow(*totals: int):
    return {
        "series": [
            [f"2026-08-{7 - index:02d}", 0, 0, 0, total]
            for index, total in enumerate(totals)
        ]
    }


def _daytrade(ratio: float | None):
    if ratio is None:
        return {"as_of": "2026-08-05", "missing_reason": "official day-trade missing"}
    return {
        "as_of": "2026-08-05",
        "day_trading_volume": int(ratio * 1000),
        "total_volume": 1000,
        "day_trading_volume_ratio": ratio,
    }


def _base_inputs():
    momentum = {
        "generated_at": "2026-08-08T00:00:00Z",
        "observed_hour": "2026-08-08T00:00:00Z",
        "themes": [
            _theme(
                "ai_server",
                80,
                60,
                direct=[_symbol("TWSE:2330", "台積電"), _symbol("TPEX:6488", "環球晶")],
                related=[_symbol("TWSE:2454", "聯發科")],
                change=5,
            ),
            _theme(
                "robotics",
                40,
                90,
                direct=[_symbol("TWSE:2330", "台積電")],
                related=[_symbol("TWSE:9999", "濾掉", market_id="US_EQUITY")],
            ),
        ],
    }
    fundamentals = {
        "TWSE:2330": _fundamentals(cash_flow=30, debt=0.2),
        "TPEX:6488": _fundamentals(
            latest_revenue=100,
            prior_revenue=100,
            latest_eps=10,
            prior_eps=10,
            cash_flow=-1,
            debt=0.6,
        ),
        "TWSE:2454": _fundamentals(latest_revenue=90, prior_revenue=100, latest_eps=8, prior_eps=10),
    }
    flows = {
        "TWSE:2330": _flow(10, 20, 30, 40, 50),
        "TPEX:6488": _flow(-10, -20, -30),
        "TWSE:2454": _flow(0, 0, 0, 0, 0),
    }
    daytrade = {
        "TWSE:2330": _daytrade(0.30),
        "TPEX:6488": _daytrade(0.29),
        "TWSE:2454": _daytrade(None),
    }
    return momentum, fundamentals, flows, daytrade


def _build(**overrides):
    momentum, fundamentals, flows, daytrade = _base_inputs()
    return build_stock_watchlist(
        momentum_payload=overrides.get("momentum", momentum),
        fundamentals_by_instrument=overrides.get("fundamentals", fundamentals),
        institutional_flows=overrides.get("flows", flows),
        day_trading_activity=overrides.get("daytrade", daytrade),
        generated_at="2026-08-08T01:00:00Z",
        candidate_as_of="2026-08-08T00:00:00Z",
        top_n=overrides.get("top_n", 50),
    )


def test_average_rank_percentile_handles_ties_singletons_equal_and_missing():
    assert average_rank_percentiles({"a": 10, "b": 20, "c": 30}) == {
        "a": 0,
        "b": 50,
        "c": 100,
    }
    assert average_rank_percentiles({"a": 10, "b": 10, "c": 30}) == {
        "a": 25,
        "b": 25,
        "c": 100,
    }
    assert average_rank_percentiles({"a": 7}) == {"a": 50}
    assert average_rank_percentiles({"a": 7, "b": 7}) == {"a": 50, "b": 50}
    assert average_rank_percentiles({"a": None, "b": 7}) == {"b": 50}


def test_missing_theme_metrics_remain_null_without_dropping_eligible_candidate():
    symbol = _symbol("TWSE:1111", "缺題材分數")
    momentum = {
        "generated_at": "2026-08-08T00:00:00Z",
        "observed_hour": "2026-08-08T00:00:00Z",
        "themes": [_theme("missing-theme", None, None, direct=[symbol])],
    }

    payload = _build(
        momentum=momentum,
        fundamentals={},
        flows={},
        daytrade={"TWSE:1111": _daytrade(0.2)},
        top_n=1,
    )
    row = payload["short"]["items"][0]

    assert payload["searchable"][0]["instrument"]["instrument_id"] == "TWSE:1111"
    assert row["themes"][0]["heat_score"] is None
    assert row["themes"][0]["momentum_score"] is None
    assert row["short"]["components"]["theme_attention"]["raw"] is None
    assert row["short"]["components"]["theme_attention"]["normalized"] is None
    assert row["short"]["components"]["daytrade_activity"]["effective_weight"] == 1


def test_composite_rounds_once_after_using_unrounded_normalized_values():
    symbol = _symbol("TWSE:1111")
    momentum = {
        "generated_at": "2026-08-08T00:00:00Z",
        "observed_hour": "2026-08-08T00:00:00Z",
        "themes": [_theme("rounding", 50.495, 50.495, direct=[symbol])],
    }

    payload = _build(momentum=momentum, fundamentals={}, flows={}, daytrade={}, top_n=1)
    row = payload["short"]["items"][0]

    assert row["short"]["components"]["theme_attention"]["normalized"] == pytest.approx(50.495)
    assert row["short"]["score"] == 50


def test_projector_filters_dedupes_selects_same_top_set_and_keeps_search_pool():
    payload = _build(top_n=2)

    short_ids = [item["instrument"]["instrument_id"] for item in payload["short"]["items"]]
    long_ids = [item["instrument"]["instrument_id"] for item in payload["long"]["items"]]
    searchable_ids = [item["instrument"]["instrument_id"] for item in payload["searchable"]]

    assert set(short_ids) == set(long_ids)
    assert payload["short"]["count"] == payload["long"]["count"] == 2
    assert "TWSE:9999" not in searchable_ids
    assert "TWSE:2454" in searchable_ids
    assert any(not row["selected_top50"] for row in payload["searchable"])

    tsmc = next(item for item in payload["short"]["items"] if item["instrument"]["instrument_id"] == "TWSE:2330")
    assert [theme["theme_id"] for theme in tsmc["themes"]] == ["ai_server", "robotics"]
    assert tsmc["short"]["components"]["theme_attention"]["raw"] == 78
    assert tsmc["coverage"]["short_ratio"] > 0.5


def test_related_factor_attention_formula_bonus_cap_and_top_set_ignore_short_score():
    symbols = [_symbol(f"TWSE:{1000 + index}") for index in range(4)]
    momentum = {
        "themes": [
            _theme("primary", 80, 60, direct=[symbols[0]], related=[symbols[1]]),
            _theme("second", 40, 90, direct=[symbols[0], symbols[2]]),
            _theme("third", 10, 10, direct=[symbols[0], symbols[3]]),
        ]
    }
    flows = {
        symbol["instrument_id"]: _flow(-100, -100, -100)
        for symbol in symbols
    }
    flows[symbols[1]["instrument_id"]] = _flow(100, 100, 100)
    payload = build_stock_watchlist(
        momentum_payload=momentum,
        fundamentals_by_instrument={},
        institutional_flows=flows,
        day_trading_activity={},
        generated_at="2026-08-08T01:00:00Z",
        candidate_as_of="2026-08-08T00:00:00Z",
        top_n=1,
    )

    searchable = {row["instrument"]["instrument_id"]: row for row in payload["searchable"]}
    assert searchable[symbols[0]["instrument_id"]]["selected_top50"] is True
    assert searchable[symbols[1]["instrument_id"]]["selected_top50"] is False

    full_payload = build_stock_watchlist(
        momentum_payload=momentum,
        fundamentals_by_instrument={},
        institutional_flows=flows,
        day_trading_activity={},
        generated_at="2026-08-08T01:00:00Z",
        candidate_as_of="2026-08-08T00:00:00Z",
        top_n=4,
    )
    items = {row["instrument"]["instrument_id"]: row for row in full_payload["short"]["items"]}
    assert items[symbols[0]["instrument_id"]]["short"]["components"]["theme_attention"]["raw"] == 83
    assert items[symbols[1]["instrument_id"]]["short"]["components"]["theme_attention"]["raw"] == pytest.approx(62.05)


def test_missing_components_are_reweighted_and_never_published_as_zeroes():
    _, fundamentals, flows, daytrade = _base_inputs()
    fundamentals["TWSE:2454"] = {}
    flows["TWSE:2454"] = {"series": [["2026-08-07", 0, 0, 0, 1]]}
    payload = _build(fundamentals=fundamentals, flows=flows, daytrade=daytrade)

    mediatek = next(
        item for item in payload["short"]["items"]
        if item["instrument"]["instrument_id"] == "TWSE:2454"
    )
    components = mediatek["short"]["components"]

    assert components["institutional_short_activity"]["available"] is False
    assert components["institutional_short_activity"]["raw"] is None
    assert components["institutional_short_activity"]["normalized"] is None
    assert sum(component["effective_weight"] for component in components.values()) == pytest.approx(1)
    assert "institutional_short_activity" in mediatek["coverage"]["missing"]


def test_scores_use_contract_weights_and_overnight_null_does_not_adjust_or_flag():
    payload = _build()
    item = next(row for row in payload["short"]["items"] if row["instrument"]["instrument_id"] == "TWSE:2330")

    short = item["short"]
    long = item["long"]

    assert short["components"]["theme_attention"]["base_weight"] == 0.55
    assert short["components"]["institutional_short_activity"]["base_weight"] == 0.20
    assert short["components"]["daytrade_activity"]["base_weight"] == 0.15
    assert short["components"]["fundamental_defense"]["base_weight"] == 0.10
    assert long["components"]["fundamental_quality"]["base_weight"] == 0.60
    assert long["components"]["institutional_support"]["base_weight"] == 0.20
    assert long["components"]["theme_persistence"]["base_weight"] == 0.15
    assert long["components"]["trading_stability"]["base_weight"] == 0.05
    assert short["risk_adjustment"]["overnight_risk_adjustment"]["value"] is None
    assert short["risk_adjustment"]["overnight_risk_adjustment"]["applied"] == 0
    assert short["risk_adjustment"]["overnight_risk_adjustment"]["missing_reason"]
    assert short["components"]["daytrade_activity"]["normalized"] == 60
    assert long["components"]["trading_stability"]["normalized"] == 40
    assert isinstance(short["score"], int)
    assert isinstance(long["score"], int)
    assert "overnight_risk" not in [flag["key"] for flag in item["flags"]]


def test_institutional_direction_requires_three_observations_and_fundamentals_prefer_yoy():
    _, fundamentals, flows, daytrade = _base_inputs()
    fundamentals["TWSE:2330"] = _fundamentals(latest_revenue=111, prior_revenue=100)
    fundamentals["TPEX:6488"] = _fundamentals(prior_revenue=None, previous_revenue=100, latest_revenue=100.5)
    flows["TWSE:2454"] = _flow(5, -5)
    payload = _build(fundamentals=fundamentals, flows=flows, daytrade=daytrade)

    tsmc = next(row for row in payload["short"]["items"] if row["instrument"]["instrument_id"] == "TWSE:2330")
    globalwafers = next(row for row in payload["short"]["items"] if row["instrument"]["instrument_id"] == "TPEX:6488")
    mediatek = next(row for row in payload["short"]["items"] if row["instrument"]["instrument_id"] == "TWSE:2454")

    assert tsmc["fundamentals"]["comparison_basis"] == "YoY"
    assert tsmc["fundamentals"]["revenue_direction"] == "up"
    assert globalwafers["fundamentals"]["comparison_basis"] == "QoQ"
    assert globalwafers["fundamentals"]["revenue_direction"] == "flat"
    assert mediatek["institutional"]["direction"] == "insufficient"


def test_fundamentals_fall_back_to_qoq_when_exact_prior_year_quarter_is_absent():
    _, fundamentals, flows, daytrade = _base_inputs()
    fundamentals["TWSE:2330"] = {
        "fiscal_quarter": "2026Q2",
        "quarters": [
            {"period": "2026Q2", "revenue": 120, "eps": 12},
            {"period": "2026Q1", "revenue": 100, "eps": 10},
            {"period": "2025Q4", "revenue": 60, "eps": 6},
        ],
        "health": {},
    }

    payload = _build(fundamentals=fundamentals, flows=flows, daytrade=daytrade)
    row = next(item for item in payload["short"]["items"] if item["instrument"]["instrument_id"] == "TWSE:2330")

    assert row["fundamentals"]["comparison_basis"] == "QoQ"
    assert row["fundamentals"]["revenue_growth"] == 20
    assert row["fundamentals"]["eps_growth"] == 20


def test_fundamentals_do_not_substitute_older_cash_flow_for_latest_quarter():
    _, fundamentals, flows, daytrade = _base_inputs()
    fundamentals["TWSE:2330"]["health"] = {
        "operating_cash_flow_2026Q1": 999,
        "debt_ratio": 0.2,
    }

    payload = _build(fundamentals=fundamentals, flows=flows, daytrade=daytrade)
    row = next(item for item in payload["short"]["items"] if item["instrument"]["instrument_id"] == "TWSE:2330")

    assert row["fundamentals"]["operating_cash_flow"] is None


def test_real_institutional_flow_shape_uses_latest_five_rows_and_source_date():
    _, fundamentals, _, daytrade = _base_inputs()
    rows = [
        {"date": f"2026-08-0{7 - index}", "total_net": value}
        for index, value in enumerate([5, 4, 3, 2, 1, -999])
    ]
    payload = _build(
        fundamentals=fundamentals,
        flows={"TWSE:2330": rows},
        daytrade=daytrade,
    )
    tsmc = next(row for row in payload["short"]["items"] if row["instrument"]["instrument_id"] == "TWSE:2330")

    assert tsmc["institutional"] == {
        "direction": "positive",
        "as_of": "2026-08-07",
        "observation_count": 5,
        "five_day_net": 15,
    }


def test_eligible_pool_rejects_non_equity_unknown_exchange_and_malformed_registry_rows():
    valid = _symbol("TWSE:2330")
    momentum = {
        "themes": [
            _theme(
                "eligibility",
                50,
                50,
                direct=[
                    valid,
                    _symbol("TWSE:0050", asset_class="etf"),
                    _symbol("NYSE:TSM", exchange="NYSE"),
                    _symbol("TWSE:12 34", symbol="12 34"),
                    _symbol("TWSE:2454", exchange="TPEX"),
                ],
            )
        ]
    }
    payload = _build(momentum=momentum, fundamentals={}, flows={}, daytrade={})

    assert [row["instrument"]["instrument_id"] for row in payload["searchable"]] == ["TWSE:2330"]


def test_rank_ties_break_by_theme_attention_then_instrument_id():
    momentum = {
        "themes": [
            _theme(
                "tie",
                50,
                50,
                direct=[
                    _symbol("TWSE:1111", "A"),
                    _symbol("TWSE:2222", "B"),
                    _symbol("TWSE:3333", "C"),
                ],
            )
        ]
    }
    shared_fundamental = _fundamentals(latest_revenue=100, prior_revenue=100, latest_eps=10, prior_eps=10)
    payload = build_stock_watchlist(
        momentum_payload=momentum,
        fundamentals_by_instrument={key: shared_fundamental for key in ["TWSE:1111", "TWSE:2222", "TWSE:3333"]},
        institutional_flows={key: _flow(0, 0, 0) for key in ["TWSE:1111", "TWSE:2222", "TWSE:3333"]},
        day_trading_activity={key: _daytrade(0.1) for key in ["TWSE:1111", "TWSE:2222", "TWSE:3333"]},
        generated_at="2026-08-08T01:00:00Z",
        candidate_as_of="2026-08-08T00:00:00Z",
    )

    assert [row["instrument"]["instrument_id"] for row in payload["short"]["items"]] == [
        "TWSE:1111",
        "TWSE:2222",
        "TWSE:3333",
    ]
    assert [row["short"]["rank"] for row in payload["short"]["items"]] == [1, 2, 3]


@pytest.mark.parametrize(
    ("flag", "mutate"),
    [
        ("heat_rising", lambda m, f, fl, d: m["themes"][0].update({"heat_change_24h": 5})),
        ("multi_theme", lambda m, f, fl, d: None),
        ("institutional_positive", lambda m, f, fl, d: fl.update({"TWSE:2330": _flow(1, 1, 1)})),
        ("fundamentals_improving", lambda m, f, fl, d: None),
        ("high_daytrade", lambda m, f, fl, d: d.update({"TWSE:2330": _daytrade(0.30)})),
        ("overnight_risk", lambda m, f, fl, d: d["TWSE:2330"].update({"overnight_risk": 70})),
        ("cashflow_weak", lambda m, f, fl, d: f.update({"TWSE:2330": _fundamentals(cash_flow=0)})),
        ("high_leverage", lambda m, f, fl, d: f.update({"TWSE:2330": _fundamentals(debt=0.60)})),
        ("data_sparse", lambda m, f, fl, d: (f.update({"TWSE:2330": {}}), fl.update({"TWSE:2330": {"series": []}}), d.update({"TWSE:2330": _daytrade(None)}))),
    ],
)
def test_flags_are_source_backed_and_threshold_inclusive(flag, mutate):
    momentum, fundamentals, flows, daytrade = _base_inputs()
    mutate(momentum, fundamentals, flows, daytrade)

    payload = _build(momentum=momentum, fundamentals=fundamentals, flows=flows, daytrade=daytrade)
    tsmc = next(row for row in payload["searchable"] if row["instrument"]["instrument_id"] == "TWSE:2330")

    assert flag in [entry["key"] for entry in tsmc["flags"]]


def test_flag_thresholds_do_not_trigger_below_threshold_or_when_missing():
    momentum, fundamentals, flows, daytrade = _base_inputs()
    momentum["themes"][0]["heat_change_24h"] = 4.99
    fundamentals["TWSE:2330"] = _fundamentals(latest_revenue=None, latest_eps=None, cash_flow=None, debt=None)
    flows["TWSE:2330"] = _flow(-1, 1, 0)
    daytrade["TWSE:2330"] = _daytrade(0.299)
    daytrade["TWSE:2330"]["overnight_risk"] = 69.99
    payload = _build(momentum=momentum, fundamentals=fundamentals, flows=flows, daytrade=daytrade)
    row = next(item for item in payload["searchable"] if item["instrument"]["instrument_id"] == "TWSE:2330")

    flags = [entry["key"] for entry in row["flags"]]
    assert "heat_rising" not in flags
    assert "institutional_positive" not in flags
    assert "fundamentals_improving" not in flags
    assert "high_daytrade" not in flags
    assert "overnight_risk" not in flags
    assert "cashflow_weak" not in flags
    assert "high_leverage" not in flags


def test_schema_validator_is_exact_and_checks_same_set_and_rank_continuity():
    payload = _build()
    validate_stock_watchlist_payload(payload)

    broken = copy.deepcopy(payload)
    broken["short"]["items"][0]["unexpected"] = True
    with pytest.raises(ValueError, match="unexpected keys"):
        validate_stock_watchlist_payload(broken)

    broken = copy.deepcopy(payload)
    broken["long"]["items"].pop()
    broken["long"]["count"] -= 1
    with pytest.raises(ValueError, match="same instrument set"):
        validate_stock_watchlist_payload(broken)

    broken = copy.deepcopy(payload)
    broken["short"]["items"][0]["short"]["rank"] = 3
    with pytest.raises(ValueError, match="rank continuity"):
        validate_stock_watchlist_payload(broken)

    broken = copy.deepcopy(payload)
    broken["short"]["items"][0]["short"]["components"]["theme_attention"]["normalized"] = 101
    with pytest.raises(ValueError, match="normalized score"):
        validate_stock_watchlist_payload(broken)

    broken = copy.deepcopy(payload)
    broken["short"]["items"][0]["fundamentals"]["unexpected"] = True
    with pytest.raises(ValueError, match="unexpected fundamentals keys"):
        validate_stock_watchlist_payload(broken)

    broken = copy.deepcopy(payload)
    broken["searchable"][0]["short_rank"] = 999
    with pytest.raises(ValueError, match="searchable rank"):
        validate_stock_watchlist_payload(broken)

    broken = copy.deepcopy(payload)
    broken["coverage"]["unexpected"] = True
    with pytest.raises(ValueError, match="top-level coverage"):
        validate_stock_watchlist_payload(broken)

    broken = copy.deepcopy(payload)
    broken["short"]["unexpected"] = True
    with pytest.raises(ValueError, match="watchlist section"):
        validate_stock_watchlist_payload(broken)

    broken = copy.deepcopy(payload)
    broken["sources"]["momentum"]["unexpected"] = True
    with pytest.raises(ValueError, match="momentum source"):
        validate_stock_watchlist_payload(broken)

    broken = copy.deepcopy(payload)
    broken["short"]["items"][0]["short"]["components"]["unexpected"] = copy.deepcopy(
        broken["short"]["items"][0]["short"]["components"]["theme_attention"]
    )
    with pytest.raises(ValueError, match="short component"):
        validate_stock_watchlist_payload(broken)

    broken = copy.deepcopy(payload)
    broken["methodology"]["short_weights"]["theme_attention"] = 0.54
    with pytest.raises(ValueError, match="short methodology"):
        validate_stock_watchlist_payload(broken)

    broken = copy.deepcopy(payload)
    broken["short"]["items"][0], broken["short"]["items"][1] = (
        broken["short"]["items"][1],
        broken["short"]["items"][0],
    )
    for rank, item in enumerate(broken["short"]["items"], start=1):
        item["short"]["rank"] = rank
        searchable = next(
            row for row in broken["searchable"]
            if row["instrument"]["instrument_id"] == item["instrument"]["instrument_id"]
        )
        searchable["short_rank"] = rank
    with pytest.raises(ValueError, match="score order"):
        validate_stock_watchlist_payload(broken)

    broken = copy.deepcopy(payload)
    selected_index = next(
        index for index, row in enumerate(broken["searchable"])
        if row["selected_top50"]
    )
    fake = copy.deepcopy(broken["searchable"][selected_index])
    fake["instrument"] = {
        "instrument_id": "TWSE:ZZZZ",
        "symbol": "ZZZZ",
        "exchange": "TWSE",
        "name_zh": "假資料",
    }
    fake["selected_top50"] = False
    fake["short_rank"] = None
    fake["long_rank"] = None
    broken["searchable"][selected_index] = fake
    with pytest.raises(ValueError, match="selected instruments missing from searchable"):
        validate_stock_watchlist_payload(broken)

    broken = copy.deepcopy(payload)
    broken["short"]["items"][0]["short"]["score"] += 1
    with pytest.raises(ValueError, match="invalid short composite score"):
        validate_stock_watchlist_payload(broken)
