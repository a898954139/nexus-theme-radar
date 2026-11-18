from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.monthly_revenue import (
    EVENTS_FILENAME,
    HISTORY_FILENAME,
    load_config,
    parse_period,
    parse_revenue_row,
    run_monthly_revenue,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "monthly_revenue_datasets.tw.json"
TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfe_t187ap05_O"
# 2026-11-05 10:00 Taipei
IN_WINDOW = datetime(2026, 11, 5, 2, 0, tzinfo=timezone.utc)


def _row(symbol: str = "2330", period: str = "11510", revenue: str = "330,000,000", **overrides: str) -> dict:
    row = {
        "出表日期": "1151105",
        "資料年月": period,
        "公司代號": symbol,
        "公司名稱": "台積電",
        "產業別": "半導體業",
        "營業收入-當月營收": revenue,
        "營業收入-上月營收": "300,000,000",
        "營業收入-去年當月營收": "250,000,000",
        "營業收入-上月比較增減(%)": "10.00",
        "營業收入-去年同月增減(%)": "32.00",
    }
    row.update(overrides)
    return {key: value for key, value in row.items() if value is not None}


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THEME_RADAR_MONTHLY_REVENUE", "1")


class FakeFetcher:
    def __init__(self, rows_by_url: dict[str, list[dict] | Exception]) -> None:
        self.rows_by_url = rows_by_url
        self.calls: list[str] = []

    def __call__(self, _session, url: str) -> list[dict]:
        self.calls.append(url)
        result = self.rows_by_url.get(url, [])
        if isinstance(result, Exception):
            raise result
        return result


def _events(output_dir: Path) -> list[dict]:
    return json.loads((output_dir / EVENTS_FILENAME).read_text(encoding="utf-8"))["items"]


def test_config_loads_both_markets() -> None:
    config = load_config(CONFIG_PATH)
    assert {dataset["exchange"] for dataset in config["datasets"]} == {"TWSE", "TPEX"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("11510", "2026-10"), ("115/10", "2026-10"), ("2026-10", "2026-10"), ("202610", "2026-10"), ("", None), ("11513", None)],
)
def test_parse_period(raw: str, expected: str | None) -> None:
    assert parse_period(raw) == expected


def test_event_carries_required_fields(tmp_path: Path) -> None:
    fetcher = FakeFetcher({TWSE_URL: [_row()]})
    statuses = run_monthly_revenue(None, tmp_path, IN_WINDOW, config_path=CONFIG_PATH, fetch_rows=fetcher)

    [event] = _events(tmp_path)
    assert event["instrument_id"] == "TWSE:2330"
    assert event["symbol"] == "2330"
    assert event["period"] == "2026-10"
    assert event["revenue_twd_thousands"] == 330_000_000
    assert event["mom_pct"] == 10.0
    assert event["yoy_pct"] == 32.0
    assert "is_record_high" in event
    twse = next(status for status in statuses if status["dataset_id"] == "t187ap05_L")
    assert twse["status"] == "ok" and twse["items"] == 1 and twse["fetch_state"] == "fetched"


def test_same_period_does_not_emit_twice(tmp_path: Path) -> None:
    fetcher = FakeFetcher({TWSE_URL: [_row(), _row()]})
    run_monthly_revenue(None, tmp_path, IN_WINDOW, config_path=CONFIG_PATH, fetch_rows=fetcher)
    next_day = datetime(2026, 11, 6, 2, 0, tzinfo=timezone.utc)
    statuses = run_monthly_revenue(None, tmp_path, next_day, config_path=CONFIG_PATH, fetch_rows=fetcher)

    assert len(_events(tmp_path)) == 1
    twse = next(status for status in statuses if status["dataset_id"] == "t187ap05_L")
    assert twse["items"] == 0 and twse["rows"] == 2


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"營業收入-當月營收": ""}, "missing_revenue"),
        ({"公司代號": None}, "missing_symbol"),
        ({"資料年月": "bad"}, "missing_period"),
        (
            {"營業收入-去年同月增減(%)": "", "營業收入-去年當月營收": ""},
            "missing_yoy_pct",
        ),
    ],
)
def test_missing_field_is_excluded_not_zero_filled(override: dict, reason: str) -> None:
    config = load_config(CONFIG_PATH)
    record, excluded = parse_revenue_row(_row(**override), config["field_aliases"])
    assert record is None
    assert excluded == reason


def test_missing_pct_is_derived_from_official_bases() -> None:
    config = load_config(CONFIG_PATH)
    record, _ = parse_revenue_row(_row(**{"營業收入-上月比較增減(%)": ""}), config["field_aliases"])
    assert record is not None
    assert record["mom_pct"] == 10.0
    assert record["derived_fields"] == ["mom_pct"]


def test_excluded_rows_are_counted_in_status(tmp_path: Path) -> None:
    fetcher = FakeFetcher({TWSE_URL: [_row(), _row(symbol="2317", **{"營業收入-當月營收": "-"})]})
    statuses = run_monthly_revenue(None, tmp_path, IN_WINDOW, config_path=CONFIG_PATH, fetch_rows=fetcher)

    twse = next(status for status in statuses if status["dataset_id"] == "t187ap05_L")
    assert twse["excluded_rows"] == 1
    assert twse["excluded_reasons"] == {"missing_revenue": 1}
    assert [event["symbol"] for event in _events(tmp_path)] == ["2330"]


def test_field_drift_reports_error(tmp_path: Path) -> None:
    fetcher = FakeFetcher({TWSE_URL: [{"unexpected": "1"}]})
    statuses = run_monthly_revenue(None, tmp_path, IN_WINDOW, config_path=CONFIG_PATH, fetch_rows=fetcher)

    twse = next(status for status in statuses if status["dataset_id"] == "t187ap05_L")
    assert twse["status"] == "error"
    assert "no parsable rows" in twse["error"]


def test_fetch_failure_is_isolated_and_retried(tmp_path: Path) -> None:
    fetcher = FakeFetcher({TWSE_URL: RuntimeError("boom"), TPEX_URL: [_row(symbol="6488")]})
    statuses = run_monthly_revenue(None, tmp_path, IN_WINDOW, config_path=CONFIG_PATH, fetch_rows=fetcher)

    by_id = {status["dataset_id"]: status for status in statuses}
    assert by_id["t187ap05_L"]["status"] == "error"
    assert by_id["mopsfe_t187ap05_O"]["status"] == "ok"
    assert _events(tmp_path)[0]["instrument_id"] == "TPEX:6488"

    later = datetime(2026, 11, 5, 6, 0, tzinfo=timezone.utc)
    run_monthly_revenue(None, tmp_path, later, config_path=CONFIG_PATH, fetch_rows=fetcher)
    assert fetcher.calls.count(TWSE_URL) == 2  # failed dataset retried same day
    assert fetcher.calls.count(TPEX_URL) == 1  # succeeded dataset throttled


def test_outside_window_skips_fetch(tmp_path: Path) -> None:
    fetcher = FakeFetcher({TWSE_URL: [_row()]})
    day_15 = datetime(2026, 11, 15, 2, 0, tzinfo=timezone.utc)
    statuses = run_monthly_revenue(None, tmp_path, day_15, config_path=CONFIG_PATH, fetch_rows=fetcher)

    assert fetcher.calls == []
    assert {status["fetch_state"] for status in statuses} == {"skipped_outside_window"}
    assert {status["status"] for status in statuses} == {"ok"}
    assert not (tmp_path / HISTORY_FILENAME).exists()


def test_window_uses_taipei_date(tmp_path: Path) -> None:
    fetcher = FakeFetcher({TWSE_URL: [_row()]})
    # 2026-10-31 17:00 UTC == 2026-11-01 01:00 Taipei
    anchor = datetime(2026, 10, 31, 17, 0, tzinfo=timezone.utc)
    run_monthly_revenue(None, tmp_path, anchor, config_path=CONFIG_PATH, fetch_rows=fetcher)
    assert TWSE_URL in fetcher.calls


def test_record_high_needs_history(tmp_path: Path) -> None:
    fetcher = FakeFetcher({TWSE_URL: [_row()]})
    run_monthly_revenue(None, tmp_path, IN_WINDOW, config_path=CONFIG_PATH, fetch_rows=fetcher)
    [event] = _events(tmp_path)
    assert event["is_record_high"] is None  # 2 seeded months < 12, unknown, not False

    history_path = tmp_path / HISTORY_FILENAME
    history = json.loads(history_path.read_text(encoding="utf-8"))
    history["series"]["TWSE:2330"].update({f"2025-{month:02d}": 200_000_000.0 for month in range(1, 13)})
    history_path.write_text(json.dumps(history), encoding="utf-8")

    fetcher.rows_by_url[TWSE_URL] = [_row(period="11511", revenue="400,000,000")]
    run_monthly_revenue(
        None,
        tmp_path,
        datetime(2026, 12, 3, 2, 0, tzinfo=timezone.utc),
        config_path=CONFIG_PATH,
        fetch_rows=fetcher,
    )
    newest = _events(tmp_path)[0]
    assert newest["period"] == "2026-11"
    assert newest["is_record_high"] is True
    assert "record_high" in newest["signals"]


def test_disabled_env_returns_no_statuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THEME_RADAR_MONTHLY_REVENUE", "0")
    fetcher = FakeFetcher({TWSE_URL: [_row()]})
    assert run_monthly_revenue(None, tmp_path, IN_WINDOW, config_path=CONFIG_PATH, fetch_rows=fetcher) == []
    assert fetcher.calls == []
