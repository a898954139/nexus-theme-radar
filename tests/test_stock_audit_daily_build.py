"""Daily stock-audit build (jobs.conf: stock-audit): multi-symbol, tick-aware, fail-closed."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone

import pytest

from scripts import build_stock_audit as b

REPORT = date(2026, 11, 23)  # a Monday: the night session TAIFEX files under it began Friday


def roc(day: date) -> str:
    return f"{day.year - 1911}/{day.month:02d}/{day.day:02d}"


def trading_days(end: date, count: int) -> list[date]:
    days, cur = [], end
    while len(days) < count:
        if cur.weekday() < 5:
            days.append(cur)
        cur -= timedelta(days=1)
    return sorted(days)


DAYS = trading_days(REPORT, 260)


def price_for(i: int) -> float:
    return round(200 + 30 * math.sin(i / 9) + i * 0.2, 1)


class FakeResponse:
    def __init__(self, payload=None, text=""):
        self._payload, self.text, self.status_code = payload, text, 200

    def json(self):
        return self._payload


class FakeSource:
    def __init__(self, closed=False):
        self.receipts, self.urls, self.closed = [], [], closed

    def get(self, url):
        self.urls.append(url)
        if "exchangeReport" in url:
            stamp = url.split("date=")[1][:6]
            year, month = int(stamp[:4]), int(stamp[4:6])
            month_days = [d for d in DAYS if (d.year, d.month) == (year, month)]
            if self.closed:
                month_days = [d for d in month_days if d < REPORT]
            if "STOCK_DAY" in url:
                rows = []
                for d in month_days:
                    i = DAYS.index(d)
                    c = price_for(i)
                    rows.append([roc(d), "1,000,000", "x", f"{c - 1}", f"{c + 2}", f"{c - 3}", f"{c}"])
                return FakeResponse({"stat": "OK", "data": rows})
            return FakeResponse({"stat": "OK", "data": [[roc(d), "x", "x", f"{15 + (DAYS.index(d) % 7)}"] for d in month_days]})
        if "yahoo" in url:
            now = datetime(2026, 11, 22, 21, 0, tzinfo=timezone.utc)  # Sat 05:00 Taipei: Friday's US close
            stamps = [int((now - timedelta(days=k)).timestamp()) for k in (3, 2, 1, 0)]
            return FakeResponse({"chart": {"result": [{"meta": {"regularMarketTime": stamps[-1], "regularMarketPrice": 101},
                                                        "timestamp": stamps, "indicators": {"quote": [{"close": [98, 99, 100, 101]}]}}]}})
        if "taifex" in url:
            prev = DAYS[-2].strftime("%Y/%m/%d")
            return FakeResponse(text=f"<p>{prev} 15:00 ~ 05:00</p><table class='table_f'><tbody>"
                                     "<tr><td>TX</td><td>202612</td><td>1</td><td>2</td><td>3</td><td>23000</td><td>+50</td><td>0.22</td><td>9</td></tr>"
                                     "</tbody></table>")
        raise AssertionError(url)


FROZEN = type("Frozen", (datetime,), {"now": classmethod(lambda cls, tz=None: datetime(2026, 11, 23, 17, 40, tzinfo=tz))})


def test_tick_levels_follow_twse_price_bands() -> None:
    assert b.tick_size(9.99) == 0.01 and b.tick_size(49) == 0.05 and b.tick_size(99) == 0.1
    assert b.tick_size(250) == 0.5 and b.tick_size(999) == 1 and b.tick_size(1500) == 5
    assert b.ceil_tick(1501) == 1505 and b.floor_tick(1504) == 1500
    assert b.ceil_tick(250.2) == 250.5 and b.floor_tick(12.07) == 12.05


def test_collect_stock_builds_validator_consistent_levels(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(b, "ROOT", b.ROOT)  # fundamentals read from the committed cache
    stock = b.collect_stock(FakeSource(), REPORT, "2317", "鴻海", tmp_path)
    candles = stock["technical"]["candles"]
    assert candles[-1]["date"] == REPORT.isoformat()
    assert stock["price"] == candles[-1]["close"]
    assert stock["price_as_of"].startswith(REPORT.isoformat())
    assert abs(stock["technical"]["ma20"] - sum(c["close"] for c in candles[-20:]) / 20) < 1e-9
    assert abs(stock["valuation"]["premium_pct"] - (stock["fundamentals"]["pe"] / stock["valuation"]["baseline_pe"] - 1) * 100) < 1e-6
    for op in stock["operations"]:
        assert op["stop"] < op["entry"] < op["add"] < op["take_profit"]
        assert op["entry"] == b.ceil_tick(op["entry"]) and op["stop"] == b.floor_tick(op["stop"])
    # Completed months are cached; a second build only refetches the report month.
    again = FakeSource()
    b.collect_stock(again, REPORT, "2317", "鴻海", tmp_path)
    assert len(again.urls) == 2 and all("date=202611" in url for url in again.urls)


def test_monday_forecast_accepts_fridays_night_session_and_us_close() -> None:
    forecast = b.collect_forecast(FakeSource(), REPORT, DAYS[-2].isoformat())
    assert len(forecast["references"]) == 7
    assert any("台指期" in ref["label"] for ref in forecast["references"])


def test_main_writes_report_and_skips_incomplete_stocks(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(b, "Source", lambda delay=0.0: FakeSource())
    monkeypatch.setattr(b, "datetime", FROZEN)
    out = tmp_path / "audit.json"
    code = b.main(["--date", REPORT.isoformat(), "--symbols", "2317:鴻海,0000:不存在", "--output", str(out),
                   "--cache-dir", str(tmp_path / "cache"), "--delay", "0"])
    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert [s["symbol"] for s in payload["stocks"]] == ["2317"]
    assert payload["report_date"] == REPORT.isoformat() and payload["forecast"]


def test_weekday_holiday_exits_cleanly_without_writing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(b, "Source", lambda delay=0.0: FakeSource(closed=True))
    monkeypatch.setattr(b, "datetime", FROZEN)
    out = tmp_path / "audit.json"
    code = b.main(["--date", REPORT.isoformat(), "--symbols", "2317", "--output", str(out),
                   "--cache-dir", str(tmp_path / "cache"), "--delay", "0"])
    assert code == 0 and not out.exists()


def test_watchlist_candidates_are_twse_only_and_deduped(tmp_path) -> None:
    item = lambda s, ex: {"instrument": {"symbol": s, "exchange": ex, "name_zh": s}}
    path = tmp_path / "w.json"
    path.write_text(json.dumps({"short": {"items": [item("2317", "TWSE"), item("3081", "TPEX"), item("2330", "TWSE")]},
                                "long": {"items": [item("2317", "TWSE"), item("2454", "TWSE"), item("9999", "TWSE")]}}))
    picked = [s for s, _ in b.watchlist_candidates(path, 6)]
    assert "3081" not in picked and picked.count("2317") == 1
    assert "9999" not in picked  # no fundamentals cache -> not a candidate


def test_number_accepts_an_already_signed_down_value() -> None:
    """2026-11-23 17:40: TAIFEX sent '▼-5.25'; number() made it '--5.25' (M027)."""
    parse_number = b.number
    assert parse_number("▼-5.25") == -5.25
    assert parse_number("▼5.25") == -5.25
    assert parse_number("-▼0.30%") == -0.30
    assert parse_number("▲1,234.5") == 1234.5
    assert parse_number("-12") == -12.0
