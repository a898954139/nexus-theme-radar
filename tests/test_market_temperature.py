"""Market temperature bar and news-vs-market divergence (issue #10)."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import market_temperature as mt  # noqa: E402

NOW = datetime(2026, 11, 18, 23, 10, tzinfo=timezone.utc)  # 07:10 Taipei, 11-19

FMTQIK = {
    "stat": "OK",
    "fields": ["日期", "成交股數", "成交金額", "成交筆數", "發行量加權股價指數", "漲跌點數"],
    "data": [
        ["115/11/17", "1", "1", "1", "40,092.11", "-947.97"],
        ["115/11/18", "1", "1", "1", "40,194.91", "102.80"],
    ],
}
BFI82U = {
    "stat": "OK",
    "fields": ["單位名稱", "買進金額", "賣出金額", "買賣差額"],
    "data": [
        ["自營商(自行買賣)", "1", "1", "0"],
        ["外資及陸資(不含外資自營商)", "449,712,321,928", "487,805,959,365", "-38,093,637,437"],
        ["外資自營商", "0", "0", "0"],
    ],
}
MI_INDEX = {
    "stat": "OK",
    "tables": [
        {
            "title": "價格指數(臺灣證券交易所)",
            "fields": ["指數", "收盤指數", "漲跌(+/-)", "漲跌點數", "漲跌百分比(%)", "特殊處理註記"],
            "data": [
                ["發行量加權股價指數", "40,194.91", "<p style='color:red'>+</p>", "102.80", "0.26", ""],
                ["半導體類指數", "1,365.38", "<p style='color:red'>+</p>", "8.64", "0.64", ""],
                ["電子工業類指數", "2,465.47", "<p style='color:red'>+</p>", "21.45", "0.88", ""],
                ["航運類指數", "200.00", "<p style='color:green'>-</p>", "3.00", "1.48", ""],
                ["電腦及週邊設備類指數", "300.00", "<p style='color:red'>+</p>", "3.00", "1.01", ""],
                ["未含電子指數", "24,939.44", "<p style='color:green'>-</p>", "482.95", "1.90", ""],
            ],
        },
        {"title": "報酬指數", "fields": ["報酬指數", "收盤指數", "漲跌(+/-)", "漲跌點數", "漲跌百分比(%)", "特殊處理註記"],
         "data": [["半導體類報酬指數", "1", "+", "1", "9.99", ""]]},
    ],
}
TAIFEX = [
    {"Date": "20261118", "Contract": "TX", "ContractMonth(Week)": "202611", "Last": "40025", "Change": "14",
     "%": "0.03%", "TradingSession": "一般"},
    {"Date": "20261118", "Contract": "TX", "ContractMonth(Week)": "202611", "Last": "39792", "Change": "-219",
     "%": "-0.55%", "TradingSession": "盤後"},
    {"Date": "20261118", "Contract": "TX", "ContractMonth(Week)": "202612", "Last": "39894", "Change": "-213",
     "%": "-0.53%", "TradingSession": "盤後"},
    {"Date": "20261118", "Contract": "TX", "ContractMonth(Week)": "202611/202612", "Last": "102", "Change": "0",
     "%": "0", "TradingSession": "盤後"},
    {"Date": "20261118", "Contract": "MTX", "ContractMonth(Week)": "202611", "Last": "1", "Change": "0",
     "%": "0", "TradingSession": "盤後"},
]


def fake_get(routes: dict[str, object]):
    def get(url, params):
        if url not in routes:
            raise ConnectionError(url)
        value = routes[url]
        return value(params) if callable(value) else value
    return get


def finnhub(params):
    return {"TSM": {"c": 301.2, "d": 6.1, "dp": 2.07, "t": 1763499600},
            "SOXX": {"c": 250.5, "d": 6.09, "dp": 2.49, "t": 1763499600}}[params["symbol"]]


ALL_ROUTES = {mt.TWSE_FMTQIK: FMTQIK, mt.TWSE_BFI82U: BFI82U, mt.TAIFEX_FUT: TAIFEX, mt.FINNHUB_QUOTE: finnhub}


def bearish_events(now: datetime) -> list[dict]:
    stamp = (now - timedelta(hours=2)).isoformat()
    return [
        {"direction": -1, "score": 0.7, "publishedAt": stamp},
        {"direction": -1, "score": 0.5, "publishedAt": stamp},
        {"direction": 0, "score": 0.9, "publishedAt": stamp},
    ]


def test_parsers_read_the_official_formats() -> None:
    assert mt.parse_fmtqik(FMTQIK) == {"date": "2026-11-18", "close": 40194.91, "change": 102.8, "pct": 0.26}
    assert mt.parse_bfi82u(BFI82U) == -380.9
    tx = mt.parse_tx_night(TAIFEX)
    assert (tx["month"], tx["last"], tx["pct"], tx["date"]) == ("202611", 39792.0, -0.55, "2026-11-18")


def test_sector_board_uses_twse_industries_with_signs_from_colour() -> None:
    board = mt.parse_sector_board(MI_INDEX)
    assert [row["name"] for row in board] == ["電腦及週邊", "半導體", "航運"]
    assert board[-1]["chg"] == -1.48  # green => negative
    assert all(row["name"] != "電子工業" for row in board)  # composite excluded


def test_issue_case_bearish_news_on_a_strong_chip_night_shows_the_divergence() -> None:
    """2026-11-18 style: SOX +2.49%, news leaning bearish -> 新聞偏空，市場偏多."""
    routes = dict(ALL_ROUTES)
    routes[mt.TAIFEX_FUT] = []  # no night session yet; US anchors decide
    market = mt.build_market(fake_get(routes), NOW, bearish_events(NOW), finnhub_key="k")
    assert market["news"]["lean"] == "偏空"
    assert market["market"]["lean"] == "偏多"
    assert market["divergence"]["message"] == "新聞偏空，市場偏多"


def test_every_indicator_has_an_as_of_and_missing_is_explicit() -> None:
    market = mt.build_market(fake_get(ALL_ROUTES), NOW, [], finnhub_key="")
    by_id = {row["id"]: row for row in market["indicators"]}
    assert [row["id"] for row in market["indicators"]] == ["taiex", "tx_night", "sox", "tsm_adr", "foreign_net"]
    for key in ("taiex", "tx_night", "foreign_net"):
        assert by_id[key]["missing"] is False and by_id[key]["as_of"]
    for key in ("sox", "tsm_adr"):
        assert by_id[key] == {"id": key, "label": by_id[key]["label"], "missing": True,
                              "reason": "未設定 FINNHUB_API_KEY"}
        assert "value" not in by_id[key]  # no invented number


def test_a_failing_source_only_blanks_its_own_card() -> None:
    routes = {mt.TWSE_FMTQIK: FMTQIK}
    market = mt.build_market(fake_get(routes), NOW, [], finnhub_key="k")
    by_id = {row["id"]: row for row in market["indicators"]}
    assert by_id["taiex"]["missing"] is False
    assert all(by_id[key]["missing"] for key in ("tx_night", "sox", "tsm_adr", "foreign_net"))


def test_us_and_taiwan_sessions_are_dated_independently() -> None:
    market = mt.build_market(fake_get(ALL_ROUTES), NOW, [], finnhub_key="k")
    by_id = {row["id"]: row for row in market["indicators"]}
    assert by_id["taiex"]["as_of"] == "2026-11-18"
    assert by_id["tsm_adr"]["as_of"] == "2025-11-18"  # whatever Finnhub's t says, not the TW date
    assert "SOXX" in by_id["sox"]["session"]


def test_no_divergence_hint_before_directions_exist() -> None:
    undirected = [{"score": 0.8, "publishedAt": NOW.isoformat()}]
    market = mt.build_market(fake_get(ALL_ROUTES), NOW, undirected, finnhub_key="k")
    assert market["news"] is None and market["divergence"] is None


def test_taiex_history_merge_is_idempotent() -> None:
    history = {"rows": [{"date": "2026-11-17", "close": 1.0, "change": 0.0, "pct": 0.0}]}
    rows = mt.parse_fmtqik_history(FMTQIK)
    merged = mt.merge_taiex_history(history, rows)
    assert [r["date"] for r in merged["rows"]] == ["2026-11-17", "2026-11-18"]
    assert mt.merge_taiex_history(merged, rows) is merged


def test_build_payload_never_carries_stale_quotes(monkeypatch, tmp_path) -> None:
    """A failed quote feed must leave the boards empty, not repeat the last run."""
    import update_pre_market as upm

    previous = {"events": [], "pulse": [{"id": "SOX", "delta": "+2.49%"}], "sectors": [{"name": "半導體", "chg": 4.0}]}
    (tmp_path / upm.LATEST_FILE).write_text(json.dumps(previous), encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise upm.requests.RequestException("blocked")

    monkeypatch.setattr(upm, "fetch_feed", lambda session: [])
    monkeypatch.setattr(upm, "fetch_quotes", boom)
    monkeypatch.setattr(upm, "fetch_twse_sector_board", boom)
    monkeypatch.setattr(upm, "fetch_taiex_history", lambda get, today: [])
    monkeypatch.setattr(upm, "build_market", lambda get, now, events, finnhub_key="": {
        "generated_at": now.isoformat(), "indicators": [], "news": None,
        "market": {"lean": None, "avg_pct": None, "basis": None}, "divergence": None})
    payload = upm.build_payload(tmp_path, NOW, skip_translate=True)
    assert payload["pulse"] == [] and payload["sectors"] == []
    assert "market" in payload


def test_market_snapshot_rows_skip_missing_indicators() -> None:
    from radar_store import map_market_snapshot

    market = mt.build_market(fake_get(ALL_ROUTES), NOW, [], finnhub_key="")
    rows = map_market_snapshot({"generated_at": NOW.isoformat(), "market": market})
    assert {row["instrument_id"] for row in rows} == {"taiex", "tx_night", "foreign_net"}
    assert all(row["session_date"] for row in rows)
