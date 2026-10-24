"""AC tests for the offline PVA + Nexus technical research builder."""
from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import shutil

import pytest

from scripts import analyze_stock_audit_technical as mod


ROOT = Path(__file__).parents[1]


def _external_sources_pinned() -> bool:
    return all(
        path.exists() and mod._sha256(path) == mod.PINNED_SOURCE_SHA256[key]
        for key, path in (("pva", mod.DEFAULT_PVA_PATH), ("nexus-structure", mod.DEFAULT_DETECTOR_PATH))
    )


EXTERNAL_RUNTIME_AVAILABLE = shutil.which("node") is not None and _external_sources_pinned()


def business_days(count: int, end: date = mod.REPORT_DATE) -> list[date]:
    result: list[date] = []
    cursor = end
    while len(result) < count:
        if cursor.weekday() < 5:
            result.append(cursor)
        cursor -= timedelta(days=1)
    return sorted(result)


def bars(count: int = 650, *, end: date = mod.REPORT_DATE) -> list[dict[str, float | str]]:
    result = []
    for index, day in enumerate(business_days(count, end)):
        base = 100 + index * 0.12 + ((index % 11) - 5) * 1.8
        close = base + (1.4 if index % 7 in (0, 1, 2) else -1.1 if index % 13 in (0, 1) else 0.2)
        result.append({
            "date": day.isoformat(),
            "open": base,
            "high": max(base, close) + 2.5,
            "low": min(base, close) - 2.5,
            "close": close,
            "volume": 1_000_000 + index,
        })
    return result


def constant_seed_bars(count: int = 600) -> list[dict[str, float | str]]:
    result = []
    for index, day in enumerate(business_days(count)):
        if index < 200:
            op, high, low, close = 100.0, 101.0, 99.0, 100.0
        else:
            op, high, low, close = 110.0, 111.0, 109.0, 110.0
        result.append({"date": day.isoformat(), "open": op, "high": high, "low": low, "close": close, "volume": 1000.0})
    return result


@pytest.mark.skipif(
    not EXTERNAL_RUNTIME_AVAILABLE,
    reason="cross-repo PVA/Node sources unavailable or hash-drifted (local integration only)",
)
def test_pva_uses_actual_runtime_and_excludes_preseed_zero_values():
    candles = constant_seed_bars()
    pva, _series = mod._pva_analysis(candles, "TEST", mod.DEFAULT_PVA_PATH)
    assert pva["status"] == "ready"
    assert pva["settings"]["anchor_mode"] == "EMA"
    assert pva["settings"]["anchor_ema_length"] == 200
    assert pva["readiness"]["preseed_zero_excluded"] is True
    assert pva["post_seed_bar_count"] == 400
    assert all(pva["nullable_timeline"][index][key] is None for index in range(199) for key in ("P", "V", "A"))

    # Independent oracle for EMA200 seed, ATR14 RMA update, and P position at
    # the first post-seed bar.  Runtime finite zeros cannot satisfy this check.
    ema_at_200 = (199 * 100 + 110) / 200  # seed at index 199 is still 100; retained for clarity
    ema_at_200 = 100 + (2 / 201) * 10
    atr_at_200 = (13 * 2 + 11) / 14
    expected_p = (110 - ema_at_200) / atr_at_200
    assert pva["nullable_timeline"][200]["P"] == pytest.approx(expected_p)
    assert pva["nullable_timeline"][200]["V"] is None
    assert pva["nullable_timeline"][201]["V"] is not None


def test_missing_extended_source_fails_closed_without_235_bar_fallback():
    source = {"symbol": "TEST", "candles": bars(235)}
    analysis = mod.analyze_stock(source)
    assert analysis["analysis_status"] == "unavailable"
    assert analysis["pva"]["status"] == "unready"
    assert analysis["plan"]["status"] == "no_trade"
    assert analysis["plan"]["entry"] is None
    assert "235-bar candles are not a PVA fallback" in analysis["plan"]["reason"]


def test_completed_weekly_aggregation_drops_current_incomplete_week():
    candles = bars(650)
    weekly, metadata = mod.aggregate_completed_weekly(candles, mod.REPORT_DATE)
    assert weekly[-1]["date"] == "2026-10-16"
    assert weekly[-1]["source_dates"][-1] == "2026-10-16"
    assert metadata["dropped_current_week"]["week_start"] == "2026-10-19"
    assert metadata["dropped_current_week"]["dropped_dates"] == ["2026-10-19", "2026-10-20", "2026-10-21"]


@pytest.mark.skipif(
    not EXTERNAL_RUNTIME_AVAILABLE,
    reason="cross-repo PVA/Node sources unavailable or hash-drifted (local integration only)",
)
def test_actual_nexus_detector_and_replay_are_used_with_stable_outputs():
    source = {"symbol": "TEST", "technical_candles": bars(600)}
    first = mod.analyze_stock(source)
    second = mod.analyze_stock(source)
    assert first["analysis_status"] == "complete"
    assert next(receipt for receipt in first["method_receipts"] if receipt["id"] == "nexus-structure")
    assert first["timeframes"]["D1"]["bar_count"] == 600
    assert first["timeframes"]["W1"]["candles"][-1]["date"] == "2026-10-16"
    assert first["timeframes"]["D1"]["engine"]["replay_candidate_counts"]["fvg"] >= 0
    assert first["timeframes"]["D1"]["pivots"]
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(second, ensure_ascii=False, sort_keys=True)
    assert all("/Users/" not in json.dumps(receipt) for receipt in first["method_receipts"])


@pytest.mark.skipif(
    not EXTERNAL_RUNTIME_AVAILABLE,
    reason="cross-repo PVA/Node sources unavailable or hash-drifted (local integration only)",
)
def test_pva_prefix_values_are_causal_and_prefix_stable():
    candles = bars(650)
    full, _ = mod._pva_analysis(candles, "TEST", mod.DEFAULT_PVA_PATH)
    prefix, _ = mod._pva_analysis(candles[:620], "TEST", mod.DEFAULT_PVA_PATH)
    for index in range(620):
        assert full["nullable_timeline"][index] == prefix["nullable_timeline"][index]


def test_zone_review_rejects_later_body_close_and_unreviewed_ob():
    source = bars(6)
    raw = {"id": "ob-1-1", "kind": "ob", "dir": 1, "low": 40, "high": 50, "mid": 45, "startIndex": 1, "bornIndex": 1, "state": 0, "taps": 0}
    untouched = mod._zone_validation(raw, source, "D1")
    assert untouched["state"] == "candidate"
    assert untouched["reviewed_valid"] is False
    touched_source = [dict(item) for item in source]
    touched_source[3].update(open=44.0, high=52.0, low=44.0, close=51.0)
    reviewed = mod._zone_validation(raw, touched_source, "D1")
    assert reviewed["state"] == "active"
    assert reviewed["reviewed_valid"] is True
    assert reviewed["reaction"]["source_candle_id"].startswith("D1:candle-")
    broken_source = [dict(item) for item in touched_source]
    broken_source[5].update(open=38.0, high=41.0, low=30.0, close=38.0)
    invalidated = mod._zone_validation(raw, broken_source, "D1")
    assert invalidated["state"] == "invalidated"
    assert invalidated["validation_reason"] == "strict_later_body_close_invalidates_ob"


def test_zone_ledger_keeps_historical_rows_but_blocks_old_or_noncurrent_chart_zones():
    old_candles = [
        {"date": "2026-03-01", "open": 90, "high": 101, "low": 89, "close": 95, "volume": 1},
        {"date": "2026-10-21", "open": 100, "high": 102, "low": 98, "close": 100, "volume": 1},
    ]
    raw = {"id": "ob-old", "kind": "ob", "dir": 1, "low": 89, "high": 95, "mid": 92, "startIndex": 0, "bornIndex": 0, "state": 0, "taps": 0}
    expired = mod._zone_validation(raw, old_candles, "D1", current_engine_ids={"ob-old"}, as_of=mod.REPORT_DATE)
    assert expired["state"] == "expired"
    assert expired["chart_only_active"] is False
    not_current = mod._zone_validation(raw, old_candles, "D1", current_engine_ids=set(), as_of=mod.REPORT_DATE)
    assert not_current["state"] == "expired"
    assert not_current["current_engine_candidate"] is False
    invalidating_candles = [
        {"date": "2026-03-01", "open": 45, "high": 51, "low": 44, "close": 48, "volume": 1},
        {"date": "2026-10-21", "open": 38, "high": 41, "low": 30, "close": 38, "volume": 1},
    ]
    invalidated_old = mod._zone_validation(raw, invalidating_candles, "D1", current_engine_ids={"ob-old"}, as_of=mod.REPORT_DATE)
    assert invalidated_old["expired"] is True
    assert invalidated_old["state"] == "invalidated"
    assert invalidated_old["validation_reason"] == "strict_later_body_close_invalidates_ob"
    exhausted = mod._zone_validation(
        {**raw, "id": "ob-exhausted", "exhausted": True, "taps": 5},
        old_candles,
        "D1",
        current_engine_ids={"ob-exhausted"},
        as_of=mod.REPORT_DATE,
    )
    assert exhausted["state"] == "exhausted"
    assert exhausted["chart_only_active"] is False


def _manual_d1_for_plan() -> tuple[list[dict[str, float | str]], dict, dict]:
    days = ["2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21"]
    candles = [
        {"date": days[0], "open": 120, "high": 150, "low": 118, "close": 125, "volume": 1},
        {"date": days[1], "open": 105, "high": 110, "low": 100, "close": 106, "volume": 1},
        {"date": days[2], "open": 98, "high": 104, "low": 90, "close": 99, "volume": 1},
        {"date": days[3], "open": 101, "high": 103, "low": 96, "close": 102, "volume": 1},
        {"date": days[4], "open": 101, "high": 102, "low": 97, "close": 100, "volume": 1},
        {"date": days[5], "open": 99, "high": 101, "low": 96, "close": 100, "volume": 1},
    ]
    pivots = [
        {"source_id": "D1:pivot-high-near", "kind": "swing_high", "price": 110, "confirmed_at_index": 2, "date": days[1], "classification": "strong"},
        {"source_id": "D1:pivot-high-target", "kind": "swing_high", "price": 150, "confirmed_at_index": 1, "date": days[0], "classification": "strong"},
        {"source_id": "D1:pivot-low-defense", "kind": "swing_low", "price": 90, "confirmed_at_index": 3, "date": days[2], "classification": "strong"},
    ]
    pva = {"status": "ready", "latest": {"P": 1.0, "V": 0.2, "A": 0.1, "ATR": 2.0}}
    return candles, {"pivots": pivots, "zones": []}, pva


def test_plan_uses_prior_confirmed_trigger_and_actual_target_source():
    candles, d1, pva = _manual_d1_for_plan()
    plan = mod._derive_plan(candles, pva, d1, as_of=mod.REPORT_DATE, w1_read={"bias": "中性", "phase": "range"})
    assert plan["status"] == "conditional"
    assert plan["trigger_source"] == "D1:pivot-high-near"
    assert plan["defense_source"] == "D1:pivot-low-defense"
    assert plan["targets"][0]["source_id"] == "D1:pivot-high-target"
    assert plan["targets"][0]["price"] == 149.5
    assert plan["targets"][0]["rr"] == pytest.approx((149.5 - plan["entry"]) / (plan["entry"] - plan["stop"]))
    assert plan["confirmation"]["latest_bar_not_trigger"] is True


def test_plan_rejects_near_barrier_when_first_source_rr_is_below_one():
    candles, d1, pva = _manual_d1_for_plan()
    d1["pivots"][1]["price"] = 130
    plan = mod._derive_plan(candles, pva, d1, as_of=mod.REPORT_DATE, w1_read={"bias": "中性"})
    assert plan["status"] == "no_trade"
    assert plan["entry"] is None and plan["targets"] == []
    assert "RR<1" in plan["reason"]


def test_plan_rejects_entry_inside_active_bearish_ob_even_with_far_target():
    candles, d1, pva = _manual_d1_for_plan()
    d1["zones"] = [{
        "id": "D1:bearish-ob-105-115",
        "type": "ob",
        "dir": -1,
        "low": 105,
        "high": 115,
        "chart_only_active": True,
        "origin": {"formation_date": "2026-10-15"},
    }]
    plan = mod._derive_plan(candles, pva, d1, as_of=mod.REPORT_DATE, w1_read={"bias": "中性"})
    assert plan["status"] == "no_trade"
    assert plan["entry"] is None and plan["targets"] == []
    assert "obstacle" in plan["reason"]
    assert plan["details"]["obstacle_source"] == "D1:bearish-ob-105-115"


def test_plan_rejects_nearest_ambiguous_trigger_without_skipping_to_farther_strong():
    candles, d1, pva = _manual_d1_for_plan()
    d1["pivots"][0]["classification"] = "ambiguous"
    plan = mod._derive_plan(candles, pva, d1, as_of=mod.REPORT_DATE, w1_read={"bias": "中性"})
    assert plan["status"] == "no_trade"
    assert plan["entry"] is None and plan["targets"] == []
    assert plan["details"]["trigger_source"] == "D1:pivot-high-near"
    assert "ambiguous" in plan["reason"]


def test_structure_read_keeps_detector_event_separate_from_unassessed_phase():
    candles, d1, pva = _manual_d1_for_plan()
    d1["breaks"] = [{
        "source_id": "D1:str-1-5-3",
        "internal": False,
        "dir": 1,
        "base": "BOS",
        "label": "Strong BOS",
    }]
    read = mod._structure_read(candles, d1, pva)
    assert read["bias"] == "偏多"
    assert read["bias_source"].startswith("Nexus detector")
    assert read["last_event"] == "Strong BOS"
    assert read["phase"] == "unassessed"


def test_weekly_bearish_gate_does_not_generate_countertrend_buy():
    candles, d1, pva = _manual_d1_for_plan()
    plan = mod._derive_plan(candles, pva, d1, as_of=mod.REPORT_DATE, w1_read={"bias": "偏空", "last_event": "CHoCH"})
    assert plan["status"] == "no_trade"
    assert plan["entry"] is None and plan["add"] is None and plan["stop"] is None and plan["targets"] == []
    assert "W1" in plan["reason"]


@pytest.mark.skipif(
    not EXTERNAL_RUNTIME_AVAILABLE,
    reason="cross-repo PVA/Node sources unavailable or hash-drifted (local integration only)",
)
def test_source_receipt_pin_has_hash_revision_and_no_private_path():
    source = {"symbol": "TEST", "technical_candles": bars(600)}
    analysis = mod.analyze_stock(source)
    receipts = analysis["method_receipts"]
    assert {receipt["id"] for receipt in receipts} == {"technical-candles", "pva", "nexus-structure"}
    for receipt in receipts:
        assert receipt["source_sha256"] and len(receipt["source_sha256"]) == 64
        assert receipt["revision"]
        assert "/" not in receipt["source_path"]
        assert "http" not in json.dumps(receipt)


def test_source_receipt_pin_rejects_hash_drift(tmp_path: Path):
    source = tmp_path / "drifted.py"
    source.write_text("drifted\n")
    with pytest.raises(mod.TechnicalInputError, match="hash drift"):
        mod._source_receipt(source, method_id="pva", params={}, expected_sha256="0" * 64)


def test_analyzer_marks_source_drift_unavailable_without_fake_pass(tmp_path: Path):
    drifted = tmp_path / "pva_reclaim_runtime.py"
    drifted.write_text("not the pinned runtime\n")
    analysis = mod.analyze_stock(
        {"symbol": "TEST", "technical_candles": bars(600)},
        {"pva": drifted, "detector": mod.DEFAULT_DETECTOR_PATH},
    )
    assert analysis["analysis_status"] == "unavailable"
    assert "hash drift" in analysis["plan"]["reason"]


def test_cli_writes_unavailable_evidence_but_returns_nonzero(tmp_path: Path):
    legacy_input = tmp_path / "legacy.json"
    source = json.loads((ROOT / "reports/stock-audit-2026-10-21.json").read_text())
    for stock in source.get("stocks", []):
        stock.pop("technical_candles", None)
        stock.pop("technical_data_notes", None)
        stock.pop("technical_excluded_rows", None)
    legacy_input.write_text(json.dumps(source, ensure_ascii=False))
    output = tmp_path / "unavailable.json"
    rc = mod.main([
        "--input", str(legacy_input),
        "--output", str(output),
    ])
    assert rc != 0
    payload = json.loads(output.read_text())
    assert payload["stocks"]
    assert all(stock["technical_analysis"]["analysis_status"] == "unavailable" for stock in payload["stocks"])


def test_plan_rejects_non_positive_atr_buffer_stop():
    candles, d1, pva = _manual_d1_for_plan()
    pva["latest"]["ATR"] = 1000.0
    plan = mod._derive_plan(candles, pva, d1, as_of=mod.REPORT_DATE, w1_read={"bias": "中性"})
    assert plan["status"] == "no_trade"
    assert plan["stop"] is None
    assert "停損" in plan["reason"]
