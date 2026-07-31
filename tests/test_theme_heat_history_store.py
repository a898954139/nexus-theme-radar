from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.public_theme_momentum import (
    HEAT_RULE_VERSION,
    INCLUSION_RULE_VERSION,
    MOMENTUM_RULE_VERSION,
    OBSERVATION_SCHEMA_VERSION,
)
from scripts.theme_heat_history_store import (
    BASELINE_SQL,
    RETENTION_SQL,
    UPSERT_SQL,
    delete_expired_observations,
    load_momentum_baselines,
    map_theme_observation,
    retention_cutoff,
    write_theme_observations,
)


ROOT = Path(__file__).resolve().parents[1]
OBSERVED_HOUR = datetime(2026, 7, 31, 4, tzinfo=timezone.utc)


def _observation(theme_id: str = "thermal") -> dict[str, object]:
    return {
        "observed_at": "2026-07-31T04:00:00Z",
        "theme_id": theme_id,
        "heat_score": 68,
        "rank": 1,
        "qualification_status": "qualified",
        "near_threshold_reason": None,
        "momentum_score": 74,
        "lifecycle_stage": "accelerating",
        "event_count": 3,
        "source_count": 3,
        "tracking_candidate_count": 2,
        "taiwan_mapping_count": 2,
        "direct_mapping_event_count": 2,
        "single_source_concentration": 0.5,
        "latest_qualifying_event_at": "2026-07-31T03:30:00Z",
        "heat_rule_version": HEAT_RULE_VERSION,
        "momentum_rule_version": MOMENTUM_RULE_VERSION,
        "inclusion_rule_version": INCLUSION_RULE_VERSION,
        "schema_version": OBSERVATION_SCHEMA_VERSION,
    }


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
        self.executemany_calls: list[tuple[str, list[dict[str, object]]]] = []
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []
        self.rowcount = 0
        self.rows: list[object] = []

    def executemany(self, sql: str, params: list[dict[str, object]]) -> None:
        self.executemany_calls.append((sql, params))

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.execute_calls.append((sql, params))

    def fetchall(self) -> list[object]:
        return self.rows


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_object = FakeCursor()
        self.transactions = 0
        self.rollbacks = 0

    def transaction(self) -> _Scope:
        return _Scope(self, "transaction")

    def cursor(self) -> _Scope:
        return _Scope(self, "cursor")


def _migration_text() -> str:
    matches = sorted(
        (ROOT / "supabase" / "migrations").glob(
            "*_create_theme_radar_hourly_heat.sql"
        )
    )
    assert len(matches) == 1
    return matches[0].read_text(encoding="utf-8").lower()


def test_migration_defines_private_exact_table_columns_pk_and_indexes() -> None:
    sql = _migration_text()

    assert "create schema if not exists theme_radar" in sql
    assert "create table theme_radar.hourly_theme_heat" in sql
    for column in (
        "observed_at timestamptz not null",
        "theme_id text not null",
        "heat_score smallint not null",
        "rank smallint",
        "qualification_status text not null",
        "near_threshold_reason text",
        "momentum_score smallint not null",
        "lifecycle_stage text not null",
        "event_count integer not null",
        "source_count integer not null",
        "tracking_candidate_count integer not null",
        "taiwan_mapping_count integer not null",
        "direct_mapping_event_count integer not null",
        "single_source_concentration numeric not null",
        "latest_qualifying_event_at timestamptz",
        "heat_rule_version text not null",
        "momentum_rule_version text not null",
        "inclusion_rule_version text not null",
        "schema_version text not null",
        "producer_run_id text not null",
        "created_at timestamptz not null default now()",
        "updated_at timestamptz not null default now()",
        "primary key (observed_at, theme_id)",
    ):
        assert column in sql
    assert "hourly_theme_heat_theme_observed_idx" in sql
    assert "(theme_id, observed_at desc)" in sql
    assert "hourly_theme_heat_observed_rank_idx" in sql
    assert "where rank is not null" in sql


def test_migration_locks_constraints_owner_and_least_privilege() -> None:
    sql = _migration_text()

    for contract in (
        "heat_score between 0 and 100",
        "momentum_score between 0 and 100",
        "rank is null or rank > 0",
        "direct_mapping_event_count between 0 and event_count",
        "single_source_concentration between 0 and 1",
        "observed_at = date_trunc('hour', observed_at)",
        "producer_run_id <> ''",
        f"heat_rule_version = '{HEAT_RULE_VERSION}'",
        f"momentum_rule_version = '{MOMENTUM_RULE_VERSION}'",
        f"inclusion_rule_version = '{INCLUSION_RULE_VERSION}'",
        f"schema_version = '{OBSERVATION_SCHEMA_VERSION}'",
    ):
        assert contract in sql
    assert "alter schema theme_radar owner to postgres" in sql
    assert "alter table theme_radar.hourly_theme_heat owner to postgres" in sql
    assert "revoke all on schema theme_radar from public" in sql
    assert "revoke all on theme_radar.hourly_theme_heat from public" in sql
    assert "grant usage on schema theme_radar to theme_radar_writer" in sql
    assert "grant select, insert, update, delete" in sql
    assert "to theme_radar_writer" in sql
    assert "grant select on theme_radar.hourly_theme_heat to theme_radar_materializer" in sql
    assert "pgrst.db_schemas" not in sql


def test_mapper_emits_exact_parameter_row_and_one_run_identity() -> None:
    mapped = map_theme_observation(_observation(), producer_run_id="run-123")

    assert mapped == {
        **_observation(),
        "producer_run_id": "run-123",
    }
    assert not {
        "producer_diagnostics",
        "evidence",
        "article_body",
        "source_ids",
        "match_strings",
    } & set(mapped)


def test_writer_uses_one_parameterized_transaction_and_idempotent_upsert() -> None:
    connection = FakeConnection()
    observations = [_observation("thermal"), _observation("packaging")]

    written = write_theme_observations(
        connection,
        observations,
        producer_run_id="run-123",
    )

    assert written == 2
    assert connection.transactions == 1
    assert len(connection.cursor_object.executemany_calls) == 1
    sql, params = connection.cursor_object.executemany_calls[0]
    assert sql == UPSERT_SQL
    assert "on conflict (observed_at, theme_id) do update" in sql.lower()
    assert "created_at" not in sql.lower().split("do update set", 1)[1]
    assert "updated_at = now()" in sql.lower()
    assert "run-123" not in sql
    assert {row["producer_run_id"] for row in params} == {"run-123"}


def test_writer_rejects_mixed_versions_before_opening_transaction() -> None:
    connection = FakeConnection()
    wrong = {**_observation(), "schema_version": "wrong"}

    with pytest.raises(ValueError, match="version"):
        write_theme_observations(
            connection,
            [_observation("valid"), wrong],
            producer_run_id="run-123",
        )

    assert connection.transactions == 0
    assert connection.cursor_object.executemany_calls == []


def test_writer_empty_batch_is_safe_and_duplicate_keys_fail_before_transaction() -> None:
    connection = FakeConnection()

    assert write_theme_observations(
        connection,
        [],
        producer_run_id="run-123",
    ) == 0
    with pytest.raises(ValueError, match="primary keys"):
        write_theme_observations(
            connection,
            [_observation(), _observation()],
            producer_run_id="run-123",
        )

    assert connection.transactions == 0


def test_exact_24h_baseline_query_validates_versions_and_projects_minimal_rows() -> None:
    connection = FakeConnection()
    baseline_hour = OBSERVED_HOUR - timedelta(hours=24)
    connection.cursor_object.rows = [
        {
            "observed_at": baseline_hour,
            "theme_id": "thermal",
            "heat_score": 51,
            "source_count": 2,
            "heat_rule_version": HEAT_RULE_VERSION,
            "momentum_rule_version": MOMENTUM_RULE_VERSION,
            "inclusion_rule_version": INCLUSION_RULE_VERSION,
            "schema_version": OBSERVATION_SCHEMA_VERSION,
        }
    ]

    rows = load_momentum_baselines(connection, OBSERVED_HOUR)

    assert connection.cursor_object.execute_calls == [
        (BASELINE_SQL, (baseline_hour,))
    ]
    assert rows == [
        {
            "observed_at": "2026-07-30T04:00:00Z",
            "theme_id": "thermal",
            "heat_score": 51,
            "source_count": 2,
        }
    ]


def test_baseline_query_rejects_mixed_versions() -> None:
    connection = FakeConnection()
    connection.cursor_object.rows = [
        {
            "observed_at": OBSERVED_HOUR - timedelta(hours=24),
            "theme_id": "thermal",
            "heat_score": 51,
            "source_count": 2,
            "heat_rule_version": HEAT_RULE_VERSION,
            "momentum_rule_version": "mixed",
            "inclusion_rule_version": INCLUSION_RULE_VERSION,
            "schema_version": OBSERVATION_SCHEMA_VERSION,
        }
    ]

    with pytest.raises(ValueError, match="version"):
        load_momentum_baselines(connection, OBSERVED_HOUR)


def test_retention_boundary_is_inclusive_and_one_instant_before_is_expired() -> None:
    cutoff = retention_cutoff(OBSERVED_HOUR)

    assert cutoff == OBSERVED_HOUR - timedelta(hours=719)
    assert not (cutoff < cutoff)
    assert cutoff - timedelta(microseconds=1) < cutoff
    assert "observed_at <" in RETENTION_SQL.lower()
    assert "interval '719 hours'" in RETENTION_SQL.lower()


def test_retention_executes_in_separate_transaction_and_empty_delete_is_safe() -> None:
    connection = FakeConnection()
    connection.cursor_object.rowcount = 0

    deleted = delete_expired_observations(connection, OBSERVED_HOUR)

    assert deleted == 0
    assert connection.transactions == 1
    assert connection.cursor_object.execute_calls == [
        (RETENTION_SQL, (OBSERVED_HOUR,))
    ]
