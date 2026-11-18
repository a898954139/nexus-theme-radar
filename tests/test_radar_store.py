from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.radar_store import (
    ARTICLE_UPSERT_SQL,
    EVENT_UPSERT_SQL,
    PIPELINE_RUN_INSERT_SQL,
    SOURCE_RUN_INSERT_SQL,
    SOURCE_UPSERT_SQL,
    TRACKING_CANDIDATES_REQUIRED_KEYS,
    TRACKING_CANDIDATES_UPSERT_SQL,
    map_articles,
    map_events,
    map_sources,
    map_tracking_candidates_snapshot,
    normalize_url,
    redact_error,
    url_hash,
    write_radar_run,
)
from scripts.update_theme_radar import run_radar_dual_write


ROOT = Path(__file__).resolve().parents[1]
ANCHOR = datetime(2026, 11, 18, 7, 0, tzinfo=timezone.utc)
MIGRATION_GLOB = "*_create_radar_schema.sql"


def _article(url: str, *, source_id: str = "cnyes", title: str = "台積電法說") -> dict[str, object]:
    return {
        "id": f"{source_id}-{url_hash(url)[:12]}",
        "title_zh": title,
        "summary": "summary",
        "source": source_id,
        "source_id": source_id,
        "source_class": "financial_media",
        "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"],
        "published_at": "2026-11-18T06:30:00Z",
        "url": url,
        "extraction_method": "rss",
        "fetched_at": "2026-11-18T07:00:05Z",
    }


def _event(cluster_id: str, url: str, members: list[str]) -> dict[str, object]:
    return {
        **_article(url),
        "cluster_id": cluster_id,
        "cluster_event_ids": members,
        "cluster_size": len(members),
        "primary_theme_id": "statementdog_tag_1470",
        "theme_score": 0.333,
        "decision": "track_watch",
        "tw_relevance_status": "supply_chain",
        "confirmation_status": "unconfirmed",
        "official_evidence_count": 0,
    }


REGISTRY = [
    {"source_id": "cnyes", "name": "鉅亨網", "source_class": "financial_media",
     "fetch_method": "rss", "status": "active", "authority_rank": 10,
     "feed_url": "https://news.cnyes.com/rss"},
    {"source_id": "twse", "name": "TWSE", "status": "planned"},
]
STATUSES = [
    {"source_id": "cnyes", "status": "ok", "items": 3, "error": None, "elapsed_ms": 120},
    {"source_id": "moneydj", "status": "failed", "items": 0, "error": "timeout", "elapsed_ms": 20000},
]


class _Scope(AbstractContextManager[object]):
    def __init__(self, connection: "FakeConnection", kind: str) -> None:
        self.connection = connection
        self.kind = kind

    def __enter__(self) -> object:
        if self.kind == "transaction":
            self.connection.transactions += 1
        return self.connection.cursor_object if self.kind == "cursor" else self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is not None and self.kind == "transaction":
            self.connection.rollbacks += 1
        return False


class FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def executemany(self, sql: str, params: list[dict[str, object]]) -> None:
        self.calls.append((sql, list(params)))

    def execute(self, sql: str, params: object) -> None:
        self.calls.append((sql, params))


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_object = FakeCursor()
        self.transactions = 0
        self.rollbacks = 0
        self.closed = False

    def transaction(self) -> _Scope:
        return _Scope(self, "transaction")

    def cursor(self) -> _Scope:
        return _Scope(self, "cursor")

    def close(self) -> None:
        self.closed = True


# --- url_hash / dedup ------------------------------------------------------


def test_normalize_url_drops_fragment_trackers_and_case_of_host() -> None:
    assert normalize_url(
        "HTTPS://News.Cnyes.com:443/news/id/1?utm_source=rss&id=7&fbclid=x#top"
    ) == "https://news.cnyes.com/news/id/1?id=7"
    assert url_hash("https://a.tw/x?utm_medium=feed") == url_hash("https://a.tw/x")
    assert url_hash("https://a.tw/x?id=1") != url_hash("https://a.tw/x?id=2")
    with pytest.raises(ValueError):
        normalize_url("  ")


def test_map_articles_dedups_same_url_within_run_and_counts_duplicates() -> None:
    rows, duplicates = map_articles(
        [
            _article("https://a.tw/1"),
            _article("https://a.tw/1?utm_source=yahoo", source_id="yahoo_finance_tw"),
            _article("https://a.tw/2"),
        ],
        run_id="run-1",
        fetched_fallback=ANCHOR,
    )
    assert duplicates == 1
    assert [row["source_id"] for row in rows] == ["cnyes", "cnyes"]
    assert len({row["url_hash"] for row in rows}) == 2


def test_map_events_keys_by_cluster_id_and_keeps_full_payload() -> None:
    rows, duplicates = map_events(
        [
            _event("cluster-a", "https://a.tw/1", ["m1", "m2"]),
            _event("cluster-a", "https://a.tw/1", ["m1", "m2"]),
        ],
        run_id="run-1",
        seen_at=ANCHOR,
    )
    assert duplicates == 1
    assert rows[0]["event_id"] == "cluster-a"
    assert rows[0]["cluster_size"] == 2
    assert '"cluster_id": "cluster-a"' in rows[0]["payload"]


def test_map_sources_adds_unregistered_ids_so_foreign_keys_hold() -> None:
    rows = map_sources(REGISTRY, extra_source_ids=["moneydj", "cnyes"])
    by_id = {row["source_id"]: row for row in rows}
    assert by_id["cnyes"]["enabled"] is True
    assert by_id["twse"]["enabled"] is False
    assert by_id["moneydj"]["registry_status"] == "unregistered"


def test_write_radar_run_is_one_transaction_in_fk_order() -> None:
    connection = FakeConnection()
    summary = write_radar_run(
        connection,
        run_id="run-1",
        started_at=ANCHOR,
        window_hours=72,
        registry_sources=REGISTRY,
        statuses=STATUSES,
        articles=[_article("https://a.tw/1"), _article("https://a.tw/1#dup")],
        events=[_event("cluster-a", "https://a.tw/1", ["m1"])],
    )
    assert connection.transactions == 1
    assert [sql for sql, _ in connection.cursor_object.calls] == [
        SOURCE_UPSERT_SQL,
        PIPELINE_RUN_INSERT_SQL,
        SOURCE_RUN_INSERT_SQL,
        ARTICLE_UPSERT_SQL,
        EVENT_UPSERT_SQL,
    ]
    assert summary == {
        "json_article_count": 2,
        "db_article_count": 1,
        "duplicate_url_count": 1,
        "json_event_count": 1,
        "db_event_count": 1,
        "duplicate_event_count": 0,
        "failed_source_count": 1,
    }


def test_write_radar_run_validates_before_opening_a_transaction() -> None:
    connection = FakeConnection()
    bad = _article("https://a.tw/1")
    bad["published_at"] = "not-a-date"
    with pytest.raises(ValueError):
        write_radar_run(
            connection,
            run_id="run-1",
            started_at=ANCHOR,
            window_hours=72,
            registry_sources=REGISTRY,
            statuses=STATUSES,
            articles=[bad],
            events=[],
        )
    assert connection.transactions == 0
    assert connection.cursor_object.calls == []


def test_upsert_sql_dedups_on_url_hash_and_event_id() -> None:
    assert "ON CONFLICT (url_hash) DO UPDATE" in ARTICLE_UPSERT_SQL
    assert "seen_count = radar.article.seen_count + 1" in ARTICLE_UPSERT_SQL
    assert "first_run_id" not in ARTICLE_UPSERT_SQL.split("DO UPDATE SET")[1]
    assert "ON CONFLICT (event_id) DO UPDATE" in EVENT_UPSERT_SQL
    assert "first_seen_at" not in EVENT_UPSERT_SQL.split("DO UPDATE SET")[1]


# --- fail-closed wiring ----------------------------------------------------


def _dual_write(factory, **overrides):
    kwargs = dict(
        connection_factory=factory,
        producer_run_id="run-1",
        started_at=ANCHOR,
        window_hours=72,
        registry_sources=REGISTRY,
        statuses=STATUSES,
        articles=[_article("https://a.tw/1")],
        events=[_event("cluster-a", "https://a.tw/1", ["m1"])],
    )
    kwargs.update(overrides)
    return run_radar_dual_write(**kwargs)


def test_dual_write_skips_without_credential(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        result = _dual_write(None)
    assert result["radar_dual_write"] == "skipped"
    assert "reason=credential_unavailable" in caplog.text


def test_dual_write_failure_is_contained_and_redacts_dsn(caplog: pytest.LogCaptureFixture) -> None:
    def factory():
        raise RuntimeError(
            "could not connect postgresql://writer:s3cret@db.example.invalid:5432/postgres password=s3cret"
        )

    with caplog.at_level(logging.WARNING):
        result = _dual_write(factory)
    assert result["radar_dual_write"] == "failed"
    assert "s3cret" not in caplog.text
    assert "example.invalid" not in caplog.text
    assert "radar_dual_write_failed" in caplog.text


def test_dual_write_success_closes_connection() -> None:
    connection = FakeConnection()
    result = _dual_write(lambda: connection)
    assert result == {
        "radar_dual_write": "written",
        "radar_articles_upserted": 1,
        "radar_events_upserted": 1,
        "radar_tracking_candidates_snapshot": False,
    }
    assert connection.closed is True


def test_redact_error_keeps_class_name() -> None:
    assert redact_error(ValueError("x postgres://u:p@h/db y")) == "ValueError: x <redacted-dsn> y"


# --- migration contract ----------------------------------------------------


def _migration_text() -> str:
    matches = sorted((ROOT / "supabase" / "migrations").glob(MIGRATION_GLOB))
    assert len(matches) == 1
    return matches[0].read_text(encoding="utf-8").lower()


def test_migration_is_rerunnable_and_least_privilege() -> None:
    sql = _migration_text()
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    for statement in statements:
        body = "\n".join(
            line for line in statement.splitlines() if not line.strip().startswith("--")
        ).strip()
        if body.startswith("create table") or body.startswith("create index"):
            assert " if not exists " in body.replace("\n", " "), body[:80]
    for table in (
        "source", "pipeline_run", "source_run", "article", "event",
        "event_impact", "market_snapshot", "institutional_flow_daily",
    ):
        assert f"create table if not exists radar.{table} (" in sql
    assert "url_hash text primary key" in sql
    assert "primary key (event_id, target_id, rule_version)" in sql
    assert "revoke all on schema radar from public" in sql
    assert "grant select on all tables in schema radar to radar_reader" in sql
    writer_grant = sql.split("grant select, insert, update on", 1)[1].split(";", 1)[0]
    assert "radar_writer" in writer_grant
    assert "delete" not in sql.split("grant usage on schema radar to radar_writer", 1)[1]
    assert "to anon" not in sql and "to authenticated" not in sql
    assert "postgres://" not in sql and "postgresql://" not in sql


# --- tracking-candidates snapshot (#6) ---------------------------------------

TRACKING_CANDIDATES_JSON = ROOT / "data" / "tracking-candidates.json"
TRACKING_MIGRATION_GLOB = "*_create_radar_tracking_candidates_snapshot.sql"


def _tracking_payload() -> dict[str, object]:
    return json.loads(TRACKING_CANDIDATES_JSON.read_text(encoding="utf-8"))


def test_tracking_snapshot_stores_committed_json_verbatim() -> None:
    payload = _tracking_payload()
    row = map_tracking_candidates_snapshot(payload, run_id="run-1")
    assert json.loads(row["payload"]) == payload
    assert row["item_count"] == len(payload["items"]) == payload["total_items"]
    assert row["run_id"] == "run-1"
    assert row["generated_at"].tzinfo is not None


def test_tracking_snapshot_rejects_contract_breaks_and_allows_additions() -> None:
    payload = _tracking_payload()
    map_tracking_candidates_snapshot({**payload, "new_field": 1}, run_id="r")
    for key in ("items", "matcher_contract", "generated_at"):
        broken = {k: v for k, v in payload.items() if k != key}
        with pytest.raises(ValueError):
            map_tracking_candidates_snapshot(broken, run_id="r")
    with pytest.raises(ValueError):
        map_tracking_candidates_snapshot({**payload, "items": {}}, run_id="r")


def test_tracking_required_keys_match_the_js_contract() -> None:
    js = (ROOT / "api" / "_lib" / "trackingCandidatesContract.js").read_text(encoding="utf-8")
    block = js.split("TRACKING_CANDIDATES_REQUIRED_KEYS = Object.freeze([", 1)[1].split("]);", 1)[0]
    js_keys = tuple(part.strip().strip("',") for part in block.split("\n") if part.strip())
    assert js_keys == TRACKING_CANDIDATES_REQUIRED_KEYS
    assert set(TRACKING_CANDIDATES_REQUIRED_KEYS) <= set(_tracking_payload())


def test_write_radar_run_writes_snapshot_after_pipeline_run_in_same_transaction() -> None:
    connection = FakeConnection()
    write_radar_run(
        connection,
        run_id="run-1",
        started_at=ANCHOR,
        window_hours=72,
        registry_sources=REGISTRY,
        statuses=STATUSES,
        articles=[_article("https://a.tw/1")],
        events=[_event("cluster-a", "https://a.tw/1", ["m1"])],
        tracking_candidates=_tracking_payload(),
    )
    assert connection.transactions == 1
    sqls = [sql for sql, _ in connection.cursor_object.calls]
    assert sqls[-1] == TRACKING_CANDIDATES_UPSERT_SQL
    assert sqls.index(PIPELINE_RUN_INSERT_SQL) < sqls.index(TRACKING_CANDIDATES_UPSERT_SQL)


def test_write_radar_run_rejects_bad_snapshot_before_transaction() -> None:
    connection = FakeConnection()
    with pytest.raises(ValueError):
        write_radar_run(
            connection,
            run_id="run-1",
            started_at=ANCHOR,
            window_hours=72,
            registry_sources=REGISTRY,
            statuses=STATUSES,
            articles=[],
            events=[],
            tracking_candidates={"items": []},
        )
    assert connection.transactions == 0


def test_dual_write_passes_tracking_candidates_through() -> None:
    connection = FakeConnection()
    summary = run_radar_dual_write(
        connection_factory=lambda: connection,
        producer_run_id="run-1",
        started_at=ANCHOR,
        window_hours=72,
        registry_sources=REGISTRY,
        statuses=STATUSES,
        articles=[],
        events=[],
        tracking_candidates=_tracking_payload(),
    )
    assert summary["radar_tracking_candidates_snapshot"] is True
    assert TRACKING_CANDIDATES_UPSERT_SQL in [sql for sql, _ in connection.cursor_object.calls]


def test_tracking_migration_is_rerunnable_and_least_privilege() -> None:
    paths = sorted((ROOT / "supabase" / "migrations").glob(TRACKING_MIGRATION_GLOB))
    assert len(paths) == 1
    sql = paths[0].read_text(encoding="utf-8")
    assert "create table if not exists radar.tracking_candidates_snapshot (" in sql
    assert "references radar.pipeline_run (run_id)" in sql
    assert "grant select, insert, update on radar.tracking_candidates_snapshot to radar_writer" in sql
    assert "grant select on radar.tracking_candidates_snapshot to radar_reader" in sql
    assert "delete" not in sql.lower()
    assert "to anon" not in sql and "to authenticated" not in sql


# --- live Postgres (opt-in) ------------------------------------------------
# Set RADAR_TEST_WRITER_URL (login role granted radar_writer) and optionally
# RADAR_TEST_READER_URL (login role granted radar_reader) against a throwaway
# database with the migration applied. Skipped in CI.

WRITER_URL = os.environ.get("RADAR_TEST_WRITER_URL", "").strip()
READER_URL = os.environ.get("RADAR_TEST_READER_URL", "").strip()


@pytest.mark.skipif(not WRITER_URL, reason="RADAR_TEST_WRITER_URL not set")
def test_live_rerun_upserts_without_duplicates() -> None:
    psycopg = pytest.importorskip("psycopg")
    prefix = f"https://test.invalid/{uuid.uuid4().hex}"
    articles = [_article(f"{prefix}/1"), _article(f"{prefix}/2"), _article(f"{prefix}/1?utm_x=1")]
    events = [_event(f"cluster-{uuid.uuid4().hex[:8]}", f"{prefix}/1", ["m1"])]
    hashes = sorted({url_hash(f"{prefix}/1"), url_hash(f"{prefix}/2")})

    for attempt in range(2):
        with psycopg.connect(WRITER_URL) as connection:
            write_radar_run(
                connection,
                run_id=f"test-{uuid.uuid4().hex}",
                started_at=ANCHOR,
                window_hours=72,
                registry_sources=REGISTRY,
                statuses=STATUSES,
                articles=articles,
                events=events,
            )

    with psycopg.connect(WRITER_URL) as connection:
        rows = connection.execute(
            "select url_hash, seen_count, first_run_id <> last_run_id "
            "from radar.article where url_hash = any(%s) order by url_hash",
            (hashes,),
        ).fetchall()
        assert [(row[0], row[1], row[2]) for row in rows] == [(h, 2, True) for h in hashes]
        event_rows = connection.execute(
            "select count(*), max(payload->>'cluster_id') from radar.event where event_id = %s",
            (events[0]["cluster_id"],),
        ).fetchone()
        assert event_rows == (1, events[0]["cluster_id"])
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("delete from radar.article where url_hash = %s", (hashes[0],))


@pytest.mark.skipif(not READER_URL, reason="RADAR_TEST_READER_URL not set")
def test_live_reader_cannot_write() -> None:
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(READER_URL) as connection:
        connection.execute("select count(*) from radar.article").fetchone()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "insert into radar.source (source_id, name, registry_status, enabled) "
                "values ('x', 'x', 'active', true)"
            )


def test_failed_trial_source_does_not_count_toward_run_health() -> None:
    connection = FakeConnection()
    trial_failure = {
        "source_id": "ctee_stock",
        "name": "工商時報 證券",
        "status": "error",
        "items": 0,
        "error": "HTTP 503",
        "trial": True,
    }
    summary = write_radar_run(
        connection,
        run_id="run-1",
        started_at=ANCHOR,
        window_hours=72,
        registry_sources=REGISTRY,
        statuses=[*STATUSES, trial_failure],
        articles=[_article("https://a.tw/1")],
        events=[_event("cluster-a", "https://a.tw/1", ["m1"])],
    )
    assert summary["failed_source_count"] == 1
