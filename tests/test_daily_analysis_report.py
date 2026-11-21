"""Issue #8: daily pre-market analysis list (cloud) and report write-back (local)."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.local_analysis_report import (
    REPORT_KEYS,
    ReportError,
    cmd_push,
    validate_report,
)
from scripts.prepare_analysis_queue import (
    BarFetcher,
    Candidate,
    QueueInputError,
    candidate_pools,
    edition_for,
    fundamental_payload,
    month_url,
    parse_month_payload,
    prepare_batch,
    select_candidates,
    technical_metrics,
)


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "db/supabase" / "migrations" / "20261118090200_create_analysis_report.sql"
REPORT_DATE = date(2026, 11, 19)
DATA_AS_OF = date(2026, 11, 18)


# --- exchange parsing --------------------------------------------------------


TWSE_PAYLOAD = {
    "stat": "OK",
    "fields": ["日期", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌價差", "成交筆數"],
    "data": [
        ["115/11/17", "25,000,000", "26,000,000,000", "1,040.00", "1,050.00", "1,035.00", "1,045.00", "+5.00", "40,000"],
        ["115/11/18", "0", "0", "--", "--", "--", "--", " 0.00", "0"],
    ],
}
TPEX_PAYLOAD = {
    "stat": "ok",
    "tables": [{
        "fields": ["日 期", "成交張數", "成交仟元", "開盤", "最高", "最低", "收盤", "漲跌", "筆數"],
        "data": [["115/11/18", "1,234", "45,000", "36.50", "37.00", "36.20", "36.80", "0.30", "900"]],
    }],
}


def test_twse_rows_parse_and_halted_session_is_omitted() -> None:
    bars = parse_month_payload(TWSE_PAYLOAD, "TWSE")
    assert bars == [{"date": "2026-11-17", "open": 1040.0, "high": 1050.0, "low": 1035.0,
                     "close": 1045.0, "volume": 25_000_000.0}]


def test_tpex_lots_are_converted_to_shares() -> None:
    [bar] = parse_month_payload(TPEX_PAYLOAD, "TPEX")
    assert bar["date"] == "2026-11-18"
    assert bar["volume"] == 1_234_000.0
    assert bar["close"] == 36.8


def test_out_of_order_ohlc_and_bad_status_raise() -> None:
    broken = copy.deepcopy(TWSE_PAYLOAD)
    broken["data"][0][4] = "1,000.00"  # high below open
    with pytest.raises(QueueInputError):
        parse_month_payload(broken, "TWSE")
    with pytest.raises(QueueInputError):
        parse_month_payload({"stat": "很抱歉，沒有符合條件的資料!"}, "TWSE")


def test_month_urls_use_official_endpoints() -> None:
    assert month_url("2330", "TWSE", date(2026, 11, 1)).startswith(
        "https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=20261101&stockNo=2330"
    )
    assert "tpex.org.tw" in month_url("3577", "TPEX", date(2026, 11, 1))


def test_fetcher_respects_budget_and_records_deferred() -> None:
    sleeps: list[float] = []
    fetcher = BarFetcher(lambda url: TWSE_PAYLOAD, budget=1, sleep=sleeps.append)
    assert fetcher.month("2330", "TWSE", date(2026, 11, 1))
    assert fetcher.month("2330", "TWSE", date(2026, 10, 1)) is None
    assert fetcher.deferred == ["2330:2026-10"]
    assert sleeps == []


# --- selection ---------------------------------------------------------------


def _cand(symbol: str, short_rank: int | None, long_rank: int | None) -> Candidate:
    return Candidate(symbol, "TWSE", f"TWSE:{symbol}", symbol, short_rank, 50.0, long_rank, 50.0, ())


def test_selection_fills_short_then_long_and_replaces_ineligible() -> None:
    short = [_cand(f"1{i:03d}", i, None) for i in range(1, 15)]
    long = [_cand("1001", 1, 1)] + [_cand(f"2{i:03d}", None, i) for i in range(2, 8)]
    bad = {"1002", "2002"}
    calls: list[str] = []

    def eligible(c: Candidate) -> str | None:
        calls.append(c.symbol)
        return "no_observed_quotes" if c.symbol in bad else None

    result = select_candidates(short, long, eligible)
    symbols = [c.symbol for c, _ in result.picked]
    assert len(symbols) == 10
    assert symbols[:7] == ["1001", "1003", "1004", "1005", "1006", "1007", "1008"]
    assert symbols[7:] == ["2003", "2004", "2005"]  # 1001 already taken, 2002 excluded
    assert [e["symbol"] for e in result.excluded] == ["1002", "2002"]
    assert len(calls) == len(set(calls))


def test_selection_backfills_when_a_pool_runs_dry() -> None:
    short = [_cand(f"1{i:03d}", i, None) for i in range(1, 12)]
    result = select_candidates(short, [], lambda c: None)
    assert [h for _, h in result.picked] == ["short"] * 10


def test_candidate_pools_follow_watchlist_ranks() -> None:
    watchlist = json.loads((ROOT / "job/data" / "public-stock-watchlist-v1.json").read_text(encoding="utf-8"))
    short, long = candidate_pools(watchlist)
    assert short and long
    assert [c.short_rank for c in short[:5]] == sorted(c.short_rank for c in short[:5])
    assert all(c.exchange in {"TWSE", "TPEX"} for c in short + long)


def test_weekend_has_no_edition() -> None:
    saturday = datetime(2026, 11, 21, 6, 5, tzinfo=timezone(timedelta(hours=8)))
    assert edition_for(saturday) is None
    assert edition_for(saturday - timedelta(days=2)) == date(2026, 11, 19)


# --- deterministic snapshot --------------------------------------------------


def _candles(count: int, end: date = DATA_AS_OF, start_price: float = 100.0) -> list[dict[str, float | str]]:
    days: list[date] = []
    cursor = end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    days.reverse()
    out = []
    for index, day in enumerate(days):
        close = start_price + index * 0.1
        out.append({"date": day.isoformat(), "open": close - 0.5, "high": close + 1,
                    "low": close - 1, "close": close, "volume": 1000.0 + index})
    return out


def test_metrics_are_plain_arithmetic() -> None:
    metrics = technical_metrics(_candles(260))
    assert metrics["last_close"] == pytest.approx(125.9)
    assert metrics["ma5"] == pytest.approx(125.7)
    assert metrics["atr14"] == pytest.approx(2.0)
    assert metrics["high20"] == pytest.approx(126.9)
    assert "swing" not in json.dumps(metrics)


def test_fundamentals_keep_missing_and_never_zero_pe() -> None:
    raw = {"quarters": [{"period": "2026Q3", "eps": 1.0}], "valuation": {"ttm_eps": 4.0}, "missing": []}
    payload, missing = fundamental_payload(raw, 100.0)
    assert payload["valuation"]["pe"] == 25.0
    assert missing == []
    payload, missing = fundamental_payload({**raw, "valuation": {"ttm_eps": -1.0}}, 100.0)
    assert "pe" not in payload["valuation"]
    assert any("valuation.pe" in m for m in missing)
    with pytest.raises(QueueInputError):
        fundamental_payload({"quarters": []}, 100.0)


# --- report validation ---------------------------------------------------------


QUEUE_ROW = {"symbol": "2330", "report_date": REPORT_DATE}


def _report(**overrides: object) -> dict[str, object]:
    report: dict[str, object] = {
        "symbol": "2330",
        "report_date": REPORT_DATE.isoformat(),
        "data_as_of": DATA_AS_OF.isoformat(),
        "framework_version": "nexus-market-analysis/v1",
        "generated_at": "2026-11-19T07:41:00+08:00",
        "bias": "bullish",
        "actionability": "wait_for_confirmation",
        "conclusion": "日線多頭結構未破，等回測 1,020 需求區確認再考慮。",
        "market_structure": "W1 上升趨勢；D1 回檔至前高轉支撐，尚未出現 CHoCH。",
        "key_levels": [
            {"label": "前高轉支撐", "price": 1020, "kind": "support"},
            {"label": "近期高點", "price": 1080, "kind": "resistance"},
        ],
        "primary_scenario": {"summary": "回測支撐守穩後續攻前高", "trigger": "1,020 收紅 K 且量增",
                             "entry_zone": [1015, 1025], "targets": [1080]},
        "alternative_scenario": {"summary": "跌破 1,000 轉為區間整理", "trigger": "日收低於 1,000"},
        "confirmation": "D1 收盤站回 1,030 以上",
        "invalidation": {"price": 995, "condition": "日收盤跌破 995"},
        "no_trade_warning": None,
        "news_context": "外資連三日賣超，但新聞方向不取代價格確認。",
    }
    report.update(overrides)
    return report


def _validate(report: dict[str, object]) -> dict[str, object]:
    return validate_report(report, queue_row=QUEUE_ROW, data_as_of=DATA_AS_OF, last_close=1045.0)


def test_valid_report_maps_to_row() -> None:
    row = _validate(_report())
    assert row["bias"] == "bullish"
    assert row["invalidation_price"] == 995.0
    assert row["data_as_of"] == DATA_AS_OF and row["report_date"] == REPORT_DATE
    assert set(json.loads(row["report"])) == REPORT_KEYS


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"thinking": "..."}, "reasoning/debug"),
        ({"primary_scenario": {**_report()["primary_scenario"], "debug_detector": []}}, "reasoning/debug"),
        ({"report_date": DATA_AS_OF.isoformat()}, "report_date"),
        ({"data_as_of": "2026-11-17"}, "data_as_of"),
        ({"invalidation": {"price": 400, "condition": "x"}}, "outside"),
        ({"bias": "up"}, "bias"),
        ({"actionability": "no_trade", "no_trade_warning": None}, "no_trade"),
        ({"actionability": "actionable", "primary_scenario": {**_report()["primary_scenario"], "entry_zone": None}}, "entry_zone"),
        ({"conclusion": "長" * 401}, "exceeds"),
        ({"symbol": "2317"}, "symbol"),
    ],
)
def test_invalid_reports_are_refused(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ReportError, match=message):
        _validate(_report(**overrides))


def test_extra_top_level_key_is_refused() -> None:
    with pytest.raises(ReportError, match="extra"):
        _validate({**_report(), "score": 3})


# --- migration contract ---------------------------------------------------------


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def _grants_to(sql: str, role: str) -> list[str]:
    statements = [" ".join(s.split()) for s in sql.split(";")]
    return [s[s.index("grant "):] for s in statements if "grant " in s and s.endswith(f"to {role}")]


def test_analyst_role_is_least_privilege() -> None:
    sql = _sql()
    grants = _grants_to(sql, "radar_analyst")
    assert grants == [
        "grant usage on schema radar to radar_analyst",
        "grant select on radar.analysis_batch, radar.analysis_queue, radar.technical_snapshot, "
        "radar.fundamental_snapshot to radar_analyst",
        "grant select, insert, update on radar.analysis_report to radar_analyst",
    ]
    assert "create role radar_analyst nologin" in sql
    assert "delete" not in " ".join(_grants_to(sql, "radar_analyst") + _grants_to(sql, "radar_writer"))


def test_writer_cannot_write_reports_and_tables_are_rerunnable() -> None:
    sql = _sql()
    writer = " ".join(_grants_to(sql, "radar_writer"))
    assert "grant select on radar.analysis_report to radar_writer" in writer
    assert "insert, update on radar.daily_bar" in writer and "radar.analysis_report to radar_writer" in writer
    assert writer.count("analysis_report") == 1
    for table in ("daily_bar", "analysis_batch", "analysis_queue", "technical_snapshot",
                  "fundamental_snapshot", "analysis_report"):
        assert f"create table if not exists radar.{table} (" in sql
    assert "primary key (symbol, report_date, framework_version)" in sql
    assert "check (data_as_of < report_date)" in sql
    assert "postgres://" not in sql and "to anon" not in sql and "to authenticated" not in sql


# --- entrypoints, workflow, front end --------------------------------------------


@pytest.mark.parametrize("script", ["prepare_analysis_queue.py", "local_analysis_report.py"])
def test_entrypoints_import_like_ci(script: str) -> None:
    # Invoked by path, as CI and the local task do: `scripts.` is not importable.
    result = subprocess.run([sys.executable, f"scripts/{script}", "--help"], cwd=ROOT / "job",
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_prepare_without_credential_skips_cleanly() -> None:
    env = {k: v for k, v in os.environ.items() if k != "THEME_RADAR_DATABASE_URL"}
    result = subprocess.run([sys.executable, "scripts/prepare_analysis_queue.py"], cwd=ROOT / "job", env=env,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {"analysis_queue": "skipped"}


def test_workflow_slots_precede_seven_am_taipei() -> None:
    workflow = (ROOT / ".github" / "workflows" / "prepare-analysis-queue.yml").read_text(encoding="utf-8")
    assert '"5,35,50 22 * * 0-4"' in workflow  # 06:05/06:35/06:50 Taipei, Mon-Fri
    assert "secrets.THEME_RADAR_DATABASE_URL" in workflow
    assert "RADAR_ANALYST" not in workflow and "service_role" not in workflow
    assert "contents: read" in workflow


def test_front_end_never_shows_an_old_edition_as_today() -> None:
    service = (ROOT / "front/src" / "services" / "analysisReport.ts").read_text(encoding="utf-8")
    card = (ROOT / "front/src" / "components" / "stock" / "DailyReportCard.tsx").read_text(encoding="utf-8")
    detail = (ROOT / "front/src" / "components" / "stock" / "StockDetail.tsx").read_text(encoding="utf-8")
    api = (ROOT / "backend/api" / "analysis-report.js").read_text(encoding="utf-8")
    assert "if (payload.report_date !== today) return { kind: 'not_produced', today };" in service
    assert "payload.report.report_date === today" in service
    assert "今日報告未產出" in card
    assert "資料 →" in card and "台股開盤分析" in card
    assert "<DailyReportCard code={code} />" in detail
    assert "process.env.RADAR_API_DATABASE_URL" in api
    assert "s-maxage=60, stale-while-revalidate=300" in api
    assert "if (body.report_date !== today) return { ...base, status: 'not_produced' };" in api
    for text in (service, card):
        assert "DATABASE_URL" not in text and "service_role" not in text


# --- live Postgres (opt-in) -------------------------------------------------------
# Throwaway DB with both radar migrations applied, and login roles granted
# radar_writer / radar_analyst / radar_reader. Skipped in CI.

WRITER_URL = os.environ.get("RADAR_TEST_WRITER_URL", "").strip()
ANALYST_URL = os.environ.get("RADAR_TEST_ANALYST_URL", "").strip()
READER_URL = os.environ.get("RADAR_TEST_READER_URL", "").strip()
live = pytest.mark.skipif(not (WRITER_URL and ANALYST_URL), reason="RADAR_TEST_WRITER_URL/ANALYST_URL not set")


def _watchlist(symbols: list[str]) -> dict[str, object]:
    items = [{"instrument": {"instrument_id": f"TWSE:{s}", "symbol": s, "exchange": "TWSE", "name_zh": s},
              "themes": [], "short": {"rank": i + 1, "score": 90 - i}, "long": {"rank": i + 1, "score": 80 - i}}
             for i, s in enumerate(symbols)]
    return {"candidate_as_of": "2026-11-18T22:00:00Z", "short": {"items": items}, "long": {"items": items}}


def _fake_exchange(edition: date, short_history: set[str]):
    history = {}

    def http_get(url: str) -> dict[str, object]:
        symbol = url.split("stockNo=")[1]
        if symbol not in history:
            history[symbol] = _candles(300 if symbol in short_history else 650, end=edition - timedelta(days=1))
        month = url.split("date=")[1][:6]
        rows = []
        for c in history[symbol]:
            if c["date"].replace("-", "")[:6] == month:
                y, m, d = c["date"].split("-")
                rows.append([f"{int(y) - 1911}/{m}/{d}", str(int(c["volume"])), "0", str(c["open"]),
                             str(c["high"]), str(c["low"]), str(c["close"]), "0", "1"])
        return {"stat": "OK", "data": rows}

    return http_get


@live
def test_live_cloud_prepares_and_local_writes_report(tmp_path: Path) -> None:
    psycopg = pytest.importorskip("psycopg")
    # A random future weekday edition so reruns of this test never collide.
    edition = date(2030, 1, 7) + timedelta(weeks=uuid.uuid4().int % 2000)
    symbols = [f"9{uuid.uuid4().int % 1000:03d}"]
    while len(symbols) < 12:
        candidate = f"9{uuid.uuid4().int % 1000:03d}"
        if candidate not in symbols:
            symbols.append(candidate)
    short_history = {symbols[1]}
    fundamentals = {"quarters": [{"period": "2026Q3", "eps": 1.0}], "valuation": {"ttm_eps": 4.0}}
    now = datetime.combine(edition, datetime.min.time(), timezone.utc)

    with psycopg.connect(WRITER_URL, autocommit=True) as writer:
        args = dict(watchlist=_watchlist(symbols), report_date=edition, now=now,
                    fundamentals_loader=lambda s, e: fundamentals)
        fetch = _fake_exchange(edition, short_history)
        summary = prepare_batch(writer, fetcher=BarFetcher(fetch, budget=10_000, sleep=lambda s: None), **args)
        assert summary["analysis_queue"] == "prepared", summary
        assert len(summary["selected"]) == 10
        assert symbols[1] not in summary["selected"]
        assert summary["excluded"][0]["reason"].startswith("insufficient_history")
        again = prepare_batch(writer, fetcher=BarFetcher(fetch, budget=0, sleep=lambda s: None), **args)
        assert again["analysis_queue"] == "already_prepared"
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            writer.execute(
                "insert into radar.analysis_report (symbol) values ('x')"
            )

    first = summary["selected"][0]
    data_as_of = edition - timedelta(days=3 if edition.weekday() == 0 else 1)
    reports = tmp_path / "reports"
    reports.mkdir()
    with psycopg.connect(ANALYST_URL, autocommit=True) as analyst:
        last_close = float(analyst.execute(
            "select last_close from radar.technical_snapshot where symbol = %s and data_as_of = %s",
            (first, data_as_of)).fetchone()[0])
        report = _report(symbol=first, report_date=edition.isoformat(), data_as_of=data_as_of.isoformat(),
                         key_levels=[{"label": "支撐", "price": round(last_close * 0.97, 2), "kind": "support"}],
                         primary_scenario={"summary": "s", "trigger": "t", "entry_zone": None, "targets": []},
                         invalidation={"price": round(last_close * 0.95, 2), "condition": "跌破"})
        (reports / f"{first}.json").write_text(json.dumps(report, ensure_ascii=False))
        assert cmd_push(analyst, edition, tmp_path) == 0
        assert cmd_push(analyst, edition, tmp_path) == 0  # rerun is an upsert
        assert analyst.execute(
            "select count(*) from radar.analysis_report where report_date = %s", (edition,)).fetchone()[0] == 1

        # Least privilege: everything outside list/snapshots/report is refused.
        for statement in (
            "select 1 from radar.daily_bar limit 1",
            "select 1 from radar.article limit 1",
            "select 1 from radar.event limit 1",
            "select 1 from radar.pipeline_run limit 1",
            "select 1 from theme_radar.hourly_theme_heat limit 1",
            f"delete from radar.analysis_report where symbol = '{first}'",
            f"update radar.analysis_queue set rank = rank where report_date = '{edition}'",
            "insert into radar.analysis_batch (report_date) values ('2000-01-01')",
            "create table radar.x (id int)",
        ):
            with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.UndefinedTable)) as caught:
                analyst.execute(statement)
            if isinstance(caught.value, psycopg.errors.UndefinedTable):
                assert "theme_radar" in statement  # schema absent in a bare test DB


@pytest.mark.skipif(not READER_URL, reason="RADAR_TEST_READER_URL not set")
def test_live_reader_reads_reports_but_cannot_write() -> None:
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(READER_URL, autocommit=True) as reader:
        reader.execute("select count(*) from radar.analysis_report").fetchone()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.execute("update radar.analysis_report set conclusion = conclusion")
