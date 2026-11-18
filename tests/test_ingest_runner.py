from __future__ import annotations

import importlib.util
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from scripts.ingest_runner import (
    LAST_FETCH_SQL,
    IngestConfigError,
    UnknownGroupError,
    connection_factory_from_environment,
    due_sources,
    fetch_group,
    load_ingest_config,
    run_ingest_group,
)
from scripts.radar_store import (
    INGEST_PIPELINE_RUN_INSERT_SQL,
    PIPELINE_RUN_INSERT_SQL,
    SOURCE_RUN_INSERT_SQL,
    write_radar_run,
)
from tests.test_radar_store import FakeConnection, FakeCursor


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 18, 8, 5, 3, tzinfo=timezone.utc)
SECRET = "s" * 48


def _load_module(relative: str, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INGEST_API = _load_module("api/cron/ingest.py", "api_cron_ingest")
HEALTH_API = _load_module("api/source-health.py", "api_source_health")


# --- fakes -------------------------------------------------------------------


class IngestCursor(FakeCursor):
    def __init__(self, last_rows: list[tuple[str, datetime]]) -> None:
        super().__init__()
        self.last_rows = last_rows

    def fetchall(self) -> list[tuple[str, datetime]]:
        return list(self.last_rows)


class IngestConnection(FakeConnection):
    def __init__(self, last_rows: list[tuple[str, datetime]] | None = None) -> None:
        super().__init__()
        self.cursor_object = IngestCursor(last_rows or [])


def _record(source: dict[str, Any], n: int, fetched_at: datetime) -> dict[str, Any]:
    return {
        "id": f"{source['source_id']}-{n}",
        "title_zh": f"{source['source_id']} headline {n}",
        "summary": "",
        "source_id": source["source_id"],
        "source_class": source.get("source_class"),
        "market_id": "TW_EQUITY",
        "published_at": (fetched_at - timedelta(minutes=3)).isoformat(),
        "url": f"https://example.invalid/{source['source_id']}/{n}",
        "extraction_method": "rss",
        "fetched_at": fetched_at.isoformat(),
    }


def _fake_fetcher(failing: set[str] = frozenset()):
    calls: list[str] = []

    def fetcher(session, source, fetched_at, **_):
        calls.append(source["source_id"])
        status = {"source_id": source["source_id"], "status": "ok", "items": 2,
                  "error": None, "elapsed_ms": 12}
        if source["source_id"] in failing:
            return [], {**status, "status": "error", "items": 0, "error": "HTTP 503"}
        return [_record(source, 1, fetched_at), _record(source, 2, fetched_at)], status

    fetcher.calls = calls  # type: ignore[attr-defined]
    return fetcher


def _null_session(_source):
    return None


# --- config ------------------------------------------------------------------


def test_repo_config_resolves_every_group_to_rss_sources() -> None:
    config = load_ingest_config()
    assert set(config["groups"]) == {"tw-news-a", "tw-news-b", "global-wire"}
    seen: list[str] = []
    for sources in config["groups"].values():
        for source in sources:
            assert source["fetch_method"] == "rss" and source["feed_url"]
            assert source["min_interval_minutes"] >= 1
            seen.append(source["source_id"])
    assert len(seen) == len(set(seen)), "a source must belong to one group only"
    registry_ids = {s["source_id"] for s in config["registry_sources"]}
    assert "financialjuice" in registry_ids
    # Every active RSS source of the hourly run is covered by some group.
    registry = json.loads((ROOT / "config/source_registry.tw.json").read_text("utf-8"))
    active_rss = {
        s["source_id"] for s in registry["sources"]
        if s.get("status") == "active" and s.get("fetch_method") == "rss"
    }
    assert active_rss <= set(seen)
    assert config["time_budget_seconds"] <= 45


def _write_config(tmp_path: Path, groups: list[dict[str, Any]], **extra: Any) -> Path:
    path = tmp_path / "groups.json"
    path.write_text(json.dumps({"groups": groups, **extra}), encoding="utf-8")
    return path


def test_config_rejects_source_in_two_groups(tmp_path: Path) -> None:
    path = _write_config(tmp_path, [
        {"group_id": "a", "source_ids": ["cnyes"]},
        {"group_id": "b", "source_ids": ["cnyes"]},
    ])
    with pytest.raises(IngestConfigError, match="both"):
        load_ingest_config(path)


def test_config_rejects_non_rss_and_unknown_sources(tmp_path: Path) -> None:
    with pytest.raises(IngestConfigError, match="unsupported"):
        load_ingest_config(_write_config(tmp_path, [{"group_id": "a", "source_ids": ["mops"]}]))
    with pytest.raises(IngestConfigError, match="not an active"):
        load_ingest_config(_write_config(tmp_path, [{"group_id": "a", "source_ids": ["twse"]}]))


def test_config_rejects_budget_over_hobby_headroom(tmp_path: Path) -> None:
    path = _write_config(tmp_path, [{"group_id": "a", "source_ids": ["cnyes"]}],
                         time_budget_seconds=58)
    with pytest.raises(IngestConfigError, match="time_budget_seconds"):
        load_ingest_config(path)


# --- min interval --------------------------------------------------------------


def test_due_sources_respects_min_interval_with_scheduler_grace() -> None:
    sources = [
        {"source_id": "a", "min_interval_minutes": 5},
        {"source_id": "b", "min_interval_minutes": 5},
        {"source_id": "c", "min_interval_minutes": 30},
        {"source_id": "d", "min_interval_minutes": 5},
    ]
    last = {
        "a": NOW - timedelta(minutes=4, seconds=55),  # previous 5-min tick: due (grace)
        "b": NOW - timedelta(minutes=2),             # overlapping call: rate-limited
        "c": NOW - timedelta(minutes=10),            # slow source: rate-limited
    }
    due, skipped = due_sources(sources, last, NOW)
    assert [s["source_id"] for s in due] == ["a", "d"]
    assert [s["source_id"] for s in skipped] == ["b", "c"]
    assert all(s["reason"] == "min_interval" for s in skipped)


# --- fetch budget ----------------------------------------------------------------


def test_fetch_group_turns_slow_source_into_budget_error() -> None:
    release = threading.Event()

    def fetcher(session, source, fetched_at, **_):
        if source["source_id"] == "slow":
            release.wait(5)
        return [], {"source_id": source["source_id"], "status": "ok", "items": 0,
                    "error": None, "elapsed_ms": 1}

    try:
        _, statuses = fetch_group(
            [{"source_id": "fast"}, {"source_id": "slow"}],
            NOW,
            budget_seconds=1,
            fetcher=fetcher,
            session_factory=_null_session,
        )
    finally:
        release.set()
    by_id = {s["source_id"]: s for s in statuses}
    assert by_id["fast"]["status"] == "ok"
    assert by_id["slow"]["status"] == "error"
    assert "time budget" in by_id["slow"]["error"]


def test_fetch_group_contains_fetcher_exceptions() -> None:
    def fetcher(session, source, fetched_at, **_):
        raise RuntimeError("boom postgres://u:pw@h/db")

    _, statuses = fetch_group([{"source_id": "x"}], NOW, budget_seconds=5,
                              fetcher=fetcher, session_factory=_null_session)
    assert statuses[0]["status"] == "error"
    assert "pw@" not in statuses[0]["error"]


# --- end to end with a fake DB -----------------------------------------------------


def test_run_ingest_group_writes_one_ingest_run() -> None:
    config = load_ingest_config()
    connection = IngestConnection([("moneydj", NOW - timedelta(minutes=1))])
    fetcher = _fake_fetcher(failing={"yahoo_finance_tw"})
    summary = run_ingest_group(
        "tw-news-a", connection_factory=lambda: connection, config=config,
        now=NOW, fetcher=fetcher, session_factory=_null_session,
    )
    assert summary["result"] == "written"
    assert sorted(fetcher.calls) == ["cnyes", "yahoo_finance_tw"]
    assert [s["source_id"] for s in summary["skipped"]] == ["moneydj"]
    assert summary["db_article_count"] == 2
    assert summary["failed_source_count"] == 1
    assert summary["run_id"].startswith("ingest-tw-news-a-20261118T080503Z-")
    sqls = [sql for sql, _ in connection.cursor_object.calls]
    assert sqls[0] == LAST_FETCH_SQL
    assert INGEST_PIPELINE_RUN_INSERT_SQL in sqls
    assert PIPELINE_RUN_INSERT_SQL not in sqls
    run_row = next(p for sql, p in connection.cursor_object.calls if sql == INGEST_PIPELINE_RUN_INSERT_SQL)
    assert run_row["run_kind"] == "ingest" and run_row["ingest_group"] == "tw-news-a"
    assert run_row["json_event_count"] == 0 and run_row["elapsed_ms"] >= 0
    source_runs = next(p for sql, p in connection.cursor_object.calls if sql == SOURCE_RUN_INSERT_SQL)
    assert {r["source_id"]: r["status"] for r in source_runs} == {
        "cnyes": "ok", "yahoo_finance_tw": "error"}
    assert connection.closed is True
    assert connection.transactions == 1


def test_run_ingest_group_nothing_due_writes_nothing() -> None:
    config = load_ingest_config()
    connection = IngestConnection([("financialjuice", NOW - timedelta(seconds=30))])
    fetcher = _fake_fetcher()
    summary = run_ingest_group(
        "global-wire", connection_factory=lambda: connection, config=config,
        now=NOW, fetcher=fetcher, session_factory=_null_session,
    )
    assert summary["result"] == "nothing_due"
    assert fetcher.calls == []
    assert connection.transactions == 0
    assert connection.closed is True


def test_run_ingest_group_unknown_group() -> None:
    with pytest.raises(UnknownGroupError):
        run_ingest_group("nope", connection_factory=IngestConnection, config=load_ingest_config())


def test_hourly_writer_sql_unchanged_without_ingest_group() -> None:
    connection = FakeConnection()
    write_radar_run(connection, run_id="r", started_at=NOW, window_hours=72,
                    registry_sources=[], statuses=[], articles=[], events=[])
    sqls = [sql for sql, _ in connection.cursor_object.calls]
    assert PIPELINE_RUN_INSERT_SQL in sqls
    assert "run_kind" not in PIPELINE_RUN_INSERT_SQL


def test_connection_factory_requires_credential() -> None:
    assert connection_factory_from_environment({}) is None
    assert callable(connection_factory_from_environment({"RADAR_INGEST_DATABASE_URL": "host=x"}))


# --- HTTP endpoint -------------------------------------------------------------------


def _env(**extra: str) -> dict[str, str]:
    return {"RADAR_INGEST_CRON_SECRET": SECRET, "RADAR_INGEST_DATABASE_URL": "host=x", **extra}


def _never_runs(*_args, **_kwargs):
    raise AssertionError("runner must not be called")


@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Bearer wrong"},
    {"Authorization": SECRET},
    {"Authorization": f"Basic {SECRET}"},
])
def test_ingest_endpoint_401_without_correct_secret(headers: dict[str, str]) -> None:
    status, body = INGEST_API.handle_ingest(
        "GET", "/api/cron/ingest?group=tw-news-a", headers, env=_env(), runner=_never_runs)
    assert status == 401
    assert SECRET not in json.dumps(body)


def test_ingest_endpoint_fails_closed_without_strong_secret() -> None:
    for env in ({}, {"RADAR_INGEST_CRON_SECRET": "short"}):
        status, _ = INGEST_API.handle_ingest(
            "GET", "/api/cron/ingest?group=tw-news-a",
            {"Authorization": "Bearer short"}, env=env, runner=_never_runs)
        assert status == 503


def test_ingest_endpoint_validates_group_and_db() -> None:
    auth = {"Authorization": f"Bearer {SECRET}"}
    assert INGEST_API.handle_ingest("GET", "/api/cron/ingest?group=../x", auth,
                                    env=_env(), runner=_never_runs)[0] == 400
    assert INGEST_API.handle_ingest("GET", "/api/cron/ingest?group=a", auth,
                                    env={"RADAR_INGEST_CRON_SECRET": SECRET},
                                    runner=_never_runs)[0] == 503
    assert INGEST_API.handle_ingest("DELETE", "/api/cron/ingest?group=a", auth,
                                    env=_env(), runner=_never_runs)[0] == 405


def test_ingest_endpoint_runs_group_and_redacts_failures(caplog: pytest.LogCaptureFixture) -> None:
    auth = {"Authorization": f"Bearer {SECRET}"}
    seen: list[str] = []

    def ok_runner(group, *, connection_factory):
        seen.append(group)
        return {"group": group, "result": "written"}

    status, body = INGEST_API.handle_ingest(
        "GET", "/api/cron/ingest?group=tw-news-b", auth, env=_env(), runner=ok_runner)
    assert (status, body["result"], seen) == (200, "written", ["tw-news-b"])

    def unknown(group, *, connection_factory):
        raise UnknownGroupError(group)

    assert INGEST_API.handle_ingest("GET", "/api/cron/ingest?group=zzz", auth,
                                    env=_env(), runner=unknown)[0] == 404

    def broken(group, *, connection_factory):
        raise RuntimeError("connect postgresql://w:hunter2@db.invalid/postgres failed")

    with caplog.at_level(logging.ERROR):
        status, body = INGEST_API.handle_ingest(
            "GET", "/api/cron/ingest?group=tw-news-b", auth, env=_env(), runner=broken)
    assert status == 500
    assert "hunter2" not in caplog.text and "hunter2" not in json.dumps(body)


# --- source health endpoint ---------------------------------------------------------


class HealthConnection:
    def __init__(self, rows):
        self.rows = rows
        self.closed = False

    def cursor(self):
        rows = self.rows

        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql):
                assert "radar.source_run" in sql

            def fetchall(self):
                return rows

        return _Cursor()

    def close(self):
        self.closed = True


def test_source_health_shapes_rows_and_caches() -> None:
    row = ("cnyes", "鉅亨網", "error", NOW, 0, 15000,
           "timeout talking to postgres://u:pw@h/db", NOW - timedelta(minutes=10), 12, 11)
    connection = HealthConnection([row])
    status, body, cache = HEALTH_API.handle_source_health(
        "GET", env={"RADAR_API_DATABASE_URL": "host=x"},
        connect=lambda _url: connection, clock=lambda: NOW)
    assert status == 200 and "s-maxage=60" in cache
    item = body["sources"][0]
    assert item["last_status"] == "error" and item["ok_24h"] == 11
    assert item["last_started_at"] == "2026-11-18T08:05:03Z"
    assert "pw@" not in item["last_error"]
    assert connection.closed


def test_source_health_503_without_credential_and_502_on_db_error() -> None:
    assert HEALTH_API.handle_source_health("GET", env={})[0] == 503

    def broken(_url):
        raise RuntimeError("down")

    assert HEALTH_API.handle_source_health(
        "GET", env={"RADAR_API_DATABASE_URL": "x"}, connect=broken)[0] == 502


# --- repo hygiene ---------------------------------------------------------------------


def test_no_secret_material_in_scheduler_sql() -> None:
    migration = (ROOT / "supabase/migrations/20261118090000_radar_ingest_scheduler.sql").read_text("utf-8").lower()
    manual = (ROOT / "supabase/manual/radar_ingest_schedule.sql").read_text("utf-8").lower()
    assert "cron.schedule" not in migration, "schedules are an operational switch, not a migration"
    assert "vault.decrypted_secrets" in migration
    assert "revoke all on function radar.invoke_ingest(text) from public" in migration
    assert "security definer" in migration and "set search_path" in migration
    for text in (migration, manual):
        assert "bearer " not in text.replace("'bearer ' ||", "")
        assert "postgres://" not in text and "postgresql://" not in text


def test_vercel_config_bounds_ingest_function() -> None:
    config = json.loads((ROOT / "vercel.json").read_text("utf-8"))
    ingest = config["functions"]["api/cron/ingest.py"]
    assert ingest["maxDuration"] <= 60
    assert "data" in ingest["excludeFiles"]
    ignored = (ROOT / ".vercelignore").read_text("utf-8").splitlines()
    assert "scripts/" not in ignored and "requirements.txt" not in ignored


# --- live Postgres (opt-in, same convention as test_radar_store) --------------------

WRITER_URL = os.environ.get("RADAR_TEST_WRITER_URL", "").strip()
READER_URL = os.environ.get("RADAR_TEST_READER_URL", "").strip()


@pytest.mark.skipif(not WRITER_URL, reason="RADAR_TEST_WRITER_URL not set")
def test_live_ingest_group_respects_min_interval_and_health_reads_it() -> None:
    pytest.importorskip("psycopg")
    factory = connection_factory_from_environment({"RADAR_INGEST_DATABASE_URL": WRITER_URL})
    base = load_ingest_config()
    tag = uuid.uuid4().hex[:8]
    group = f"live-{tag}"
    source = {
        "source_id": f"live_{tag}", "name": f"Live {tag}", "source_class": "financial_media",
        "fetch_method": "rss", "feed_url": "https://example.invalid/rss",
        "min_interval_minutes": 5, "market_id": "TW_EQUITY",
    }
    config = {**base, "groups": {group: [source]},
              "registry_sources": [{**source, "status": "active"}]}
    first = run_ingest_group(group, connection_factory=factory, config=config,
                             fetcher=_fake_fetcher(), session_factory=_null_session)
    assert first["result"] == "written" and first["db_article_count"] == 2
    second = run_ingest_group(group, connection_factory=factory, config=config,
                              fetcher=_fake_fetcher(), session_factory=_null_session)
    assert second["result"] == "nothing_due"

    import psycopg
    with psycopg.connect(WRITER_URL) as connection:
        row = connection.execute(
            "select run_kind, ingest_group, elapsed_ms is not null from radar.pipeline_run where run_id = %s",
            (first["run_id"],)).fetchone()
        assert row == ("ingest", group, True)

    if READER_URL:
        status, body, _ = HEALTH_API.handle_source_health(
            "GET", env={"RADAR_API_DATABASE_URL": READER_URL})
        assert status == 200
        mine = [s for s in body["sources"] if s["source_id"] == source["source_id"]]
        assert mine and mine[0]["last_status"] == "ok" and mine[0]["runs_24h"] == 1
