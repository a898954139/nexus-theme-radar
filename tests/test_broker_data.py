from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts.broker_data import (
    build_broker_maps,
    build_broker_stats,
    build_coverage,
    parse_fubon_page,
)
from scripts import update_broker_data
from scripts.update_broker_data import decode_fubon_content, write_outputs


FUBON_HTML = """
<html><body>
<table class="t01">
  <tr><td>台積電(2330)主力進出比較圖</td></tr>
  <tr><td>台積電(2330) 券商分點-進出明細 單位：張　最後更新日：2026/08/07</td></tr>
  <tr><td>買超券商</td><td>買進</td><td>賣出</td><td>買超</td><td>佔成交比重</td>
      <td>賣超券商</td><td>買進</td><td>賣出</td><td>賣超</td><td>佔成交比重</td></tr>
  <tr><td><a href="zco0/zco0.djhtm?a=2330&amp;b=8440">摩根大通</a></td>
      <td>3,110</td><td>970</td><td>2,140</td><td>9.36%</td>
      <td><a href="zco0/zco0.djhtm?a=2330&amp;b=1470">台灣摩根士丹利</a></td>
      <td>641</td><td>2,846</td><td>2,205</td><td>9.64%</td></tr>
  <tr><td>合計買超張數</td><td>7,724</td><td>合計賣超張數</td><td>8,512</td></tr>
</table>
</body></html>
"""


def test_parse_fubon_page_reads_both_sides_and_normalizes_signs() -> None:
    result = parse_fubon_page(FUBON_HTML, stock_code="2330", stock_name="台積電")

    assert result["status"] == "ok"
    assert result["trade_date"] == "2026-08-07"
    assert result["records"] == [
        {
            "stock_code": "2330",
            "stock_name": "台積電",
            "broker_id": "8440",
            "broker_name": "摩根大通",
            "buy": 3110,
            "sell": 970,
            "net": 2140,
            "source_ratio": 9.36,
        },
        {
            "stock_code": "2330",
            "stock_name": "台積電",
            "broker_id": "1470",
            "broker_name": "台灣摩根士丹利",
            "buy": 641,
            "sell": 2846,
            "net": -2205,
            "source_ratio": 9.64,
        },
    ]


def test_parse_fubon_page_returns_no_data_without_silent_success() -> None:
    result = parse_fubon_page("<html><body><table class='t01'></table></body></html>", "2330")

    assert result["status"] == "no_data"
    assert result["records"] == []


def test_parse_fubon_page_fails_closed_when_table_shape_changes() -> None:
    html = """
    <html><body><table class="t01">
      <tr><td>標題</td></tr>
      <tr><td>券商欄位已改版</td><td>買進</td></tr>
    </table></body></html>
    """

    result = parse_fubon_page(html, "2330")

    assert result["status"] == "error"
    assert result["error"] == "Fubon broker table header not found"


def test_broker_stats_and_maps_match_frontend_contract() -> None:
    records = [
        {"stock_code": "2330", "stock_name": "台積電", "broker_id": "8440",
         "broker_name": "摩根大通", "buy": 3110, "sell": 970, "net": 2140,
         "source_ratio": 9.36},
        {"stock_code": "2317", "stock_name": "鴻海", "broker_id": "8440",
         "broker_name": "摩根大通", "buy": 700, "sell": 100, "net": 600,
         "source_ratio": 4.0},
        {"stock_code": "2330", "stock_name": "台積電", "broker_id": "1470",
         "broker_name": "台灣摩根士丹利", "buy": 641, "sell": 2846, "net": -2205,
         "source_ratio": 9.64},
    ]

    stats = build_broker_stats(records, top_n=5)
    maps = build_broker_maps(records)

    assert stats[0]["name"] == "摩根大通"
    assert stats[0]["buy"] == 3810
    assert stats[0]["sell"] == 1070
    assert stats[0]["dt"] is None
    assert stats[0]["ov"] is None
    assert stats[0]["top"] == [["2330", "台積電"], ["2317", "鴻海"]]

    assert maps["2330"][0]["id"] == "1470"
    assert maps["2330"][0]["net"] == -2205
    assert maps["2330"][0]["ratio"] == 9.64
    assert maps["2330"][0]["stocks"] == []
    assert maps["2330"][1]["id"] == "8440"
    assert maps["2330"][1]["ratio"] == 9.36
    assert maps["2330"][1]["stocks"] == [["2317", "鴻海", 600]]


def test_coverage_counts_attempts_failures_and_observed_symbols() -> None:
    coverage = build_coverage(
        requested_symbols=["2330", "2317", "9999"],
        results={
            "2330": {"status": "ok", "records": [{"stock_code": "2330"}]},
            "2317": {"status": "no_data", "records": []},
            "9999": {"status": "error", "records": [], "error": "timeout"},
        },
        source_updated="2026-08-07T19:59:57+08:00",
    )

    assert coverage["requested_symbols"] == 3
    assert coverage["attempted_symbols"] == 3
    assert coverage["failed_symbols"] == 1
    assert coverage["successful_symbols"] == 2
    assert coverage["symbols_with_data"] == 1
    assert coverage["attempt_coverage"] == 1.0
    assert coverage["data_coverage"] == pytest.approx(1 / 3)
    assert coverage["data_coverage_denominator"] == "requested_symbols"
    assert coverage["no_data_symbol_codes"] == ["2317"]
    assert coverage["failed_symbol_codes"] == ["9999"]
    assert coverage["not_attempted_symbol_codes"] == []


def test_decode_fubon_content_supports_cp950_broker_names() -> None:
    html = "<html><body>台灣摩根士丹利</body></html>"

    assert decode_fubon_content(html.encode("cp950")) == html


def test_write_outputs_keeps_handoff_arrays_and_index_metadata(tmp_path) -> None:
    records = [{
        "stock_code": "2330",
        "stock_name": "台積電",
        "broker_id": "8440",
        "broker_name": "摩根大通",
        "buy": 3110,
        "sell": 970,
        "net": 2140,
    }]

    write_outputs(
        tmp_path,
        universe={"2330": "台積電"},
        results={"2330": {"status": "ok", "records": records}},
        generated_at="2026-08-07T13:00:00Z",
        source_updated="2026-08-07",
    )

    stats = json.loads((tmp_path / "broker-stats.json").read_text())
    stock_map = json.loads((tmp_path / "broker-map" / "2330.json").read_text())
    index = json.loads((tmp_path / "broker-map" / "index.json").read_text())

    assert isinstance(stats, list)
    assert isinstance(stock_map, list)
    assert index["symbols"]["2330"]["summary"]["net"] == 2140


def test_update_refuses_to_publish_when_a_symbol_fetch_fails(tmp_path, monkeypatch) -> None:
    symbols_path = tmp_path / "index.json"
    symbols_path.write_text(json.dumps({
        "symbols": {
            "2330": {"name": "台積電"},
            "2317": {"name": "鴻海"},
        }
    }))

    class FakeSession:
        def get(self, url, **_kwargs):
            if url.endswith("2317.djhtm"):
                raise TimeoutError("test timeout")
            return SimpleNamespace(
                content=FUBON_HTML.encode("cp950"),
                raise_for_status=lambda: None,
            )

    import requests
    monkeypatch.setattr(requests, "Session", FakeSession)
    monkeypatch.setattr(update_broker_data.time, "sleep", lambda _seconds: None)

    result = update_broker_data.main([
        "--data-dir", str(tmp_path / "data"),
        "--symbols-index", str(symbols_path),
        "--delay", "0",
        "--min-universe-size", "0",
    ])

    assert result == 1
    coverage = json.loads((tmp_path / "data" / "broker-coverage.json").read_text())
    assert coverage["failed_symbol_codes"] == ["2317"]
    assert not (tmp_path / "data" / "broker-stats.json").exists()


def test_update_refuses_to_fetch_a_partial_symbol_universe(tmp_path, monkeypatch) -> None:
    symbols_path = tmp_path / "index.json"
    symbols_path.write_text(json.dumps({"symbols": {"2330": {"name": "台積電"}}}))

    class UnexpectedSession:
        def get(self, *_args, **_kwargs):
            raise AssertionError("fetch must not start for an undersized universe")

    import requests
    monkeypatch.setattr(requests, "Session", UnexpectedSession)

    result = update_broker_data.main([
        "--data-dir", str(tmp_path / "data"),
        "--symbols-index", str(symbols_path),
        "--min-universe-size", "2280",
    ])

    assert result == 1
    coverage = json.loads((tmp_path / "data" / "broker-coverage.json").read_text())
    assert coverage["validation_error"] == "symbol universe too small: 1 < 2280"
    assert coverage["attempted_symbols"] == 0
    assert not (tmp_path / "data" / "broker-stats.json").exists()
