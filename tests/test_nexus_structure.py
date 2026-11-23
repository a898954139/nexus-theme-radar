"""Nexus structure job (job/scripts/nexus_structure.py) and its table mapping.

The real detector is a private, sha256-pinned Node package that is not present
in CI, so these tests inject a fake detector with the same output shape
(current.structureBreaks / fvgZones / obZones, pivots.swingHighs / swingLows).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import nexus_structure as ns
from scripts.radar_tables import DATASETS, map_nexus_structure

ROOT = Path(__file__).resolve().parents[1]


def _candles(count: int = 400, end: date = date(2026, 11, 20)) -> list[dict]:
    days: list[date] = []
    day = end
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    days.reverse()
    out = []
    for i, d in enumerate(days):
        base = 100 + i * 0.1 + 6 * math.sin(i / 9)
        out.append({"date": d.isoformat(), "open": base, "high": base + 1.5, "low": base - 1.5,
                    "close": base + 0.5, "volume": 1000.0})
    return out


def _fractals(candles, width=2):
    highs, lows = [], []
    for i in range(width, len(candles) - width):
        window = candles[i - width:i + width + 1]
        if candles[i]["high"] == max(c["high"] for c in window):
            highs.append(i)
        if candles[i]["low"] == min(c["low"] for c in window):
            lows.append(i)
    return {"swingHighs": highs, "swingLows": lows}


def fake_detector(candles, *, timeframe, mintick):
    n = len(candles)
    close = candles[-1]["close"]
    breaks = [
        {"id": f"str--1-{n-30}-{n-35}-CHoCH", "dir": -1, "base": "CHoCH", "label": "CHoCH", "internal": False,
         "strong": False, "price": close - 5, "startIndex": n - 35, "endIndex": n - 30},
        {"id": f"str-1-{n-4}-{n-8}-BOS", "dir": 1, "base": "BOS", "label": "BOS", "internal": False,
         "strong": True, "price": close - 1, "startIndex": n - 8, "endIndex": n - 4},
        {"id": f"str--1-{n-2}-{n-3}-iCHoCH", "dir": -1, "base": "CHoCH", "label": "iCHoCH", "internal": True,
         "strong": False, "price": close, "startIndex": n - 3, "endIndex": n - 2},
    ]
    # One live bullish FVG well below (never wicked into afterwards), one far above,
    # and one already filled (must be dropped).
    zones = [
        {"id": "fvg-live", "kind": "fvg", "dir": 1, "low": -10.0, "high": -9.0, "mid": -9.5,
         "startIndex": n - 3, "bornIndex": n - 2},
        {"id": "fvg-filled", "kind": "fvg", "dir": 1, "low": 1000.0, "high": 1001.0, "mid": 1000.5,
         "startIndex": n - 12, "bornIndex": n - 11},
    ]
    # Shift the live zone to just under the low of every later bar so it stays unfilled.
    later_low = min(c["low"] for c in candles[n - 1:])
    zones[0].update(low=later_low - 3, high=later_low - 2, mid=later_low - 2.5)
    obs = [{"id": "ob-above", "kind": "ob", "dir": -1, "low": close * 1.2, "high": close * 1.25,
            "mid": close * 1.225, "startIndex": n - 20, "bornIndex": n - 19}]
    return {"current": {"structureBreaks": breaks, "fvgZones": zones, "obZones": obs,
                        "summary": {}}, "pivots": _fractals(candles)}


INSTRUMENT = {"instrument_id": "TWSE:2317", "symbol": "2317", "exchange": "TWSE", "name_zh": "鴻海"}


def test_analyze_instrument_reads_bias_levels_and_breaks():
    candles = _candles()
    item = ns.analyze_instrument(INSTRUMENT, candles, detector=fake_detector, pva_path=None, today=date(2026, 11, 23))
    assert item["as_of"] == "2026-11-20"
    assert item["timeframes"]["D1"]["bias"] == "偏多"          # latest external break is the up BOS
    assert item["timeframes"]["D1"]["last_event"] == "BOS"     # the internal iCHoCH is ignored
    assert item["timeframes"]["W1"]["bias"] == "偏多"
    assert item["bias"] == "偏多"
    assert item["pva"]["status"] == "unavailable"
    sides = {lvl["side"] for lvl in item["levels"]}
    assert {"support", "resistance"} <= sides
    kinds = {(lvl["kind"], lvl["side"]) for lvl in item["levels"]}
    assert ("fvg", "support") in kinds and ("ob", "resistance") in kinds
    assert all(lvl["low"] != 1000.0 for lvl in item["levels"])  # filled FVG dropped
    close = item["close"]
    for lvl in item["levels"]:
        if lvl["side"] == "support":
            assert lvl["high"] < close
        if lvl["side"] == "resistance":
            assert lvl["low"] > close
    assert [b["label"] for b in item["breaks"] if b["timeframe"] == "D1"] == ["BOS", "CHoCH"]
    assert "週線偏多" in item["summary"] and "日線偏多" in item["summary"]


def test_overall_bias_combines_timeframes():
    assert ns.overall_bias("偏多", "偏多") == "偏多"
    assert ns.overall_bias("偏多", "偏空") == "分歧"
    assert ns.overall_bias("偏空", "中性") == "偏空"
    assert ns.overall_bias("中性", "偏多") == "偏多"


def test_completed_weeks_drop_the_running_week():
    candles = _candles(200, end=date(2026, 11, 18))           # Wednesday
    weekly = ns.completed_weeks(candles, date(2026, 11, 18))
    assert weekly[-1]["week_start"] == "2026-11-09"
    friday = _candles(200, end=date(2026, 11, 20))
    assert ns.completed_weeks(friday, date(2026, 11, 20))[-1]["week_start"] == "2026-11-16"
    # Holiday Friday: Thursday is the last bar, and the next Monday closes the week.
    thursday = _candles(200, end=date(2026, 11, 19))
    assert ns.completed_weeks(thursday, date(2026, 11, 19))[-1]["week_start"] == "2026-11-09"
    assert ns.completed_weeks(thursday, date(2026, 11, 23))[-1]["week_start"] == "2026-11-16"


def test_completed_sessions_drops_todays_partial_bar():
    candles = _candles(5, end=date(2026, 11, 20))
    open_session = datetime(2026, 11, 20, 3, 0, tzinfo=timezone.utc)   # 11:00 Taipei
    after_close = datetime(2026, 11, 20, 7, 0, tzinfo=timezone.utc)    # 15:00 Taipei
    assert ns.completed_sessions(candles, open_session)[-1]["date"] == "2026-11-19"
    assert ns.completed_sessions(candles, after_close)[-1]["date"] == "2026-11-20"


def test_shape_candles_from_yahoo_payload():
    payload = {"chart": {"result": [{
        "meta": {"gmtoffset": 28800},
        "timestamp": [1763600400, 1763686800, 1763773200],   # 2025-11-20/21/22 09:00 Taipei
        "indicators": {"quote": [{"open": [10, None, 11], "high": [11, 12, 12], "low": [9, 10, 10.5],
                                  "close": [10.5, 11, 11.5], "volume": [1000, 2000, None]}]},
    }]}}
    rows = ns.shape_candles(payload)
    assert [r["date"] for r in rows] == ["2025-11-20", "2025-11-22"]   # the bar with a null open is dropped
    assert rows[1]["volume"] == 0.0


def test_build_skips_failed_stocks_and_maps_to_tables(tmp_path):
    watch = {"searchable": [{"instrument": INSTRUMENT},
                            {"instrument": {"instrument_id": "TPEX:6488", "symbol": "6488", "exchange": "TPEX", "name_zh": "環球晶"}}],
             "short": {"items": []}, "long": {"items": []}}
    (tmp_path / ns.WATCHLIST_FILENAME).write_text(json.dumps(watch), encoding="utf-8")

    def candles_for(inst):
        return _candles() if inst["symbol"] == "2317" else _candles(50)

    now = datetime(2026, 11, 23, 7, 10, tzinfo=timezone.utc)
    result = ns.build(tmp_path, detector=fake_detector, method={"detector_sha256": "x", "detector_revision": "b1534508"},
                      pva_path=None, candles_for=candles_for, now=now)
    assert result["universe_count"] == 2
    assert [i["instrument"]["instrument_id"] for i in result["items"]] == ["TWSE:2317"]
    assert result["unavailable"][0]["instrument_id"] == "TPEX:6488"

    versioned = map_nexus_structure(json.loads(json.dumps(result)))
    assert versioned.header_table == "nexus_structure" and versioned.version_column == "fetched_at"
    header = versioned.headers[0]
    assert header["instrument_id"] == "TWSE:2317" and header["d1_bias"] == "偏多" and header["w1_bias"] == "偏多"
    assert header["fetched_at"] == "2026-11-23T07:10:00Z"
    tables = {c.table: c for c in versioned.children}
    assert tables["nexus_structure_level"].rows and tables["nexus_structure_break"].rows
    assert all(row[1] == header["fetched_at"] for c in versioned.children for row in c.rows)

    (tmp_path / ns.OUTPUT_FILENAME).write_text(json.dumps(result), encoding="utf-8")
    assert DATASETS["nexus-structure"](tmp_path).dataset == "nexus-structure"


def test_mapper_rejects_unknown_bias():
    bad = {"generated_at": "2026-11-23T07:10:00Z", "method_version": "v1", "method": {},
           "items": [{"instrument": INSTRUMENT, "bias": "觀望", "as_of": "2026-11-20", "close": 1,
                      "timeframes": {"D1": {}}, "pva": {"status": "unavailable"}, "levels": [], "breaks": [],
                      "summary": "x"}]}
    with pytest.raises(ValueError):
        map_nexus_structure(bad)


def test_main_fails_closed_without_the_pinned_detector(tmp_path):
    missing = tmp_path / "nope.js"
    assert ns.main(["--data-dir", str(tmp_path), "--detector-path", str(missing)]) == 1
    assert not (tmp_path / ns.OUTPUT_FILENAME).exists()


def test_entrypoint_imports_like_the_scheduler():
    # jobs.conf invokes the file by path from job/: scripts/ is sys.path[0], no `scripts.` package.
    done = subprocess.run([sys.executable, "scripts/nexus_structure.py", "--help"], cwd=ROOT / "job",
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
