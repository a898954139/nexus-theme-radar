"""Date/calendar contract tests for the reusable Stock Audit renderer."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from scripts.analyze_stock_audit_technical import aggregate_completed_weekly
from scripts.stock_audit_technical_contract import weekly_bars

ROOT = Path(__file__).parents[1]


def renderer():
    spec = importlib.util.spec_from_file_location("stock_audit_renderer_dates", ROOT / "scripts/render_stock_audit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source():
    return json.loads((ROOT / "reports/stock-audit-2026-10-21.json").read_text())


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def calendar_candles():
    """Build a small in-test 10/22 extension from the tracked 10/21 fixture."""
    candles = deepcopy(source()["stocks"][0]["technical_candles"])
    last = deepcopy(candles[-1])
    last["date"] = "2026-10-22"
    candles.append(last)
    return candles


def calendar_completion():
    return {
        "timeframe": "W1",
        "as_of": "2026-10-22",
        "last_session_date": "2026-10-22",
        "announced_at": "2026-10-22T20:10:00+08:00",
        "forecast_cutoff": "2026-10-23T06:00:00+08:00",
        "next_session_date": "2026-10-27",
        "remaining_weekdays": ["2026-10-23", "2026-10-26"],
        "closed_dates": [
            {
                "date": "2026-10-23",
                "status": "full_day_closed",
                "announced_at": "2026-10-22T20:10:00+08:00",
                "source": "https://www.twse.com.tw/rwd/zh/news/newsDetail?response=json&id=8a8216d6a0fa351b01a1638507a10203",
            },
            {
                "date": "2026-10-26",
                "status": "scheduled_holiday",
                "announced_at": None,
                "source": "https://www.twse.com.tw/holidaySchedule/holidaySchedule?response=json&queryYear=115",
            },
        ],
        "calendar_source": [
            "https://www.twse.com.tw/rwd/zh/news/newsDetail?response=json&id=8a8216d6a0fa351b01a1638507a10203",
            "https://www.twse.com.tw/holidaySchedule/holidaySchedule?response=json&queryYear=115",
        ],
        "calendar_evidence_file": "calendar.json",
        "source": "TWSE",
        "status": "complete",
    }


def report_2022():
    data = deepcopy(source())

    def shift(value):
        if isinstance(value, dict):
            return {key: shift(item) for key, item in value.items()}
        if isinstance(value, list):
            return [shift(item) for item in value]
        if isinstance(value, str):
            return value.replace("2026-10-21", "2026-10-22").replace("2026-10-22T06:00:00+08:00", "2026-10-23T06:00:00+08:00")
        return value

    data = shift(data)
    data["report_date"] = "2026-10-22"
    data["forecast_cutoff"] = "2026-10-23T06:00:00+08:00"
    data["retrieved_at"] = "2026-10-24T10:55:00+08:00"
    for reference in data["market"]["references"]:
        reference["as_of"] = "2026-10-23T05:00:00+08:00" if reference["label"] == "台指期夜盤" else "2026-10-23T04:00:00+08:00"
    data["market"].update({
        "next_session_date": "2026-10-27",
        "calendar_notice": "10/23 颱風休市、10/26 補假；下一預定交易日 10/27。",
        "calendar_source": ["https://www.twse.com.tw/holidaySchedule/holidaySchedule?response=json&queryYear=115"],
        "night_contract": "TX202611",
        "spot_as_of": "2026-10-22T13:30:00+08:00",
        "economic_events": [{
            "name": "FOMC meeting",
            "dates": ["2026-10-27", "2026-10-28"],
            "source": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        }],
    })
    for stock in data["stocks"]:
        analysis = stock["technical_analysis"]
        analysis["candle_sha256"] = canonical_hash(stock["technical_candles"])
        analysis["canonical_review"]["candle_sha256"] = analysis["candle_sha256"]
        stock["research"]["morning_brief"]["candle_sha256"] = analysis["candle_sha256"]
    return data


def test_report_date_21_fallback_is_byte_identical():
    module = renderer()
    expected = (ROOT / "reports/stock-audit-2026-10-21.html").read_text()
    assert module.render(source()) == expected


def test_report_date_22_uses_dynamic_clocks_titles_financial_labels_and_calendar_notice():
    module = renderer()
    html = module.render(report_2022())
    assert "Stock Audit｜2026-10-22 台股投資決策卡" in html
    assert "10/22 台股收盤" in html
    assert "資料截止 2026-10-23 06:00（台北）" in html
    assert "美股為 10/22 收盤＝10/23 04:00" in html
    assert "台指期為 10/22 15:00–10/23 05:00 夜盤" in html
    assert "10/23 颱風休市、10/26 補假；下一預定交易日 10/27" in html
    assert "下一交易日：10/27；不將 10/23 視為正常開盤" in html
    assert "FOMC meeting（2026-10-27、2026-10-28）" in html
    assert "holidaySchedule" in html
    assert "完整來源與研究快照" in html
    assert "stock-audit-2026-10-22.json" in html
    assert "9 月營收" in html and "2026 H1 EPS" in html and "H1 毛利率" in html


def test_us_close_conversion_is_dst_aware_and_night_session_is_next_calendar_day():
    module = renderer()
    winter = module.expected_us_close("2026-01-30")
    summer = module.expected_us_close("2026-03-09")
    assert winter.isoformat() == "2026-01-31T05:00:00+08:00"
    assert summer.isoformat() == "2026-03-10T04:00:00+08:00"
    assert module.expected_night_close("2026-10-22").isoformat() == "2026-10-23T05:00:00+08:00"
    assert module.expected_forecast_cutoff("2026-10-22").isoformat() == "2026-10-23T06:00:00+08:00"


def test_wrong_report_date_or_cutoff_is_rejected():
    module = renderer()
    wrong = report_2022()
    wrong["report_date"] = "2026-02-31"
    with pytest.raises(ValueError):
        module.render(wrong)
    wrong = report_2022()
    wrong["forecast_cutoff"] = "2026-10-24T06:00:00+08:00"
    with pytest.raises(ValueError, match="forecast_cutoff"):
        module.render(wrong)


def test_future_financial_period_is_rejected_but_dynamic_past_period_is_allowed():
    module = renderer()
    future = report_2022()
    for stock in future["stocks"]:
        stock["financial"]["eps_period"] = "2027H1"
        stock["financial"]["gross_margin_period"] = "2027H1"
    with pytest.raises(ValueError, match="At least 3 complete"):
        module.render(future)
    dynamic = report_2022()
    for stock in dynamic["stocks"]:
        stock["financial"]["eps_period"] = "2026Q3"
        stock["financial"]["gross_margin_period"] = "2026Q3"
    assert "2026 Q3 EPS" in module.render(dynamic)


def test_week_completion_baseline_and_calendar_closed_week():
    baseline_candles = source()["stocks"][0]["technical_candles"]
    assert weekly_bars(baseline_candles, "2026-10-21")[-1]["date"] == "2026-10-16"

    candles = calendar_candles()
    completion = calendar_completion()
    assert weekly_bars(candles, "2026-10-22", completion)[-1]["date"] == "2026-10-22"
    weekly, metadata = aggregate_completed_weekly(candles, date.fromisoformat("2026-10-22"), completion)
    assert weekly[-1]["date"] == "2026-10-22"
    assert metadata["completion_verified"] is True
    assert metadata["week_completion"]["next_session_date"] == "2026-10-27"


def test_week_completion_rejects_future_announcement_and_missing_closed_weekday():
    candles = calendar_candles()
    completion = calendar_completion()
    completion["announced_at"] = "2026-10-24T00:00:00+08:00"
    with pytest.raises(ValueError, match="week_completion"):
        weekly_bars(candles, "2026-10-22", completion)
    forged = calendar_completion()
    forged.update({
        "as_of": "2026-10-19",
        "last_session_date": "2026-10-19",
        "forecast_cutoff": "2026-10-20T06:00:00+08:00",
        "next_session_date": "2026-10-20",
        "remaining_weekdays": [],
        "closed_dates": [],
        "announced_at": "2026-10-19T20:00:00+08:00",
    })
    with pytest.raises(ValueError, match="week_completion"):
        weekly_bars(candles, "2026-10-19", forged)
    completion = calendar_completion()
    completion["remaining_weekdays"] = ["2026-10-23"]
    with pytest.raises(ValueError, match="week_completion"):
        weekly_bars(candles, "2026-10-22", completion)


def test_calendar_notice_is_text_not_executable_markup():
    from bs4 import BeautifulSoup
    module=renderer();data=report_2022()
    data['market']['calendar_notice']='<img src=x onerror=alert(1)>'
    soup=BeautifulSoup(module.render(data),'html.parser')
    assert not soup.select('#market img')
    assert '<img src=x onerror=alert(1)>' in soup.select_one('#market').get_text()
