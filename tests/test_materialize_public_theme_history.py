from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.materialize_public_theme_history import (
    HISTORY_QUERY,
    HISTORY_SCHEMA_VERSION,
    PUBLIC_THEME_FIELDS,
    _connect_from_environment,
    build_public_theme_history,
    load_history_rows,
    materialize_public_theme_history,
)
from scripts.public_theme_momentum import (
    HEAT_RULE_VERSION,
    INCLUSION_RULE_VERSION,
    MOMENTUM_RULE_VERSION,
    OBSERVATION_SCHEMA_VERSION,
)


CURRENT_HOUR = datetime(2026, 7, 31, 4, tzinfo=timezone.utc)
GENERATED_AT = CURRENT_HOUR + timedelta(minutes=8)
REQUIREMENTS_PATH = Path(__file__).resolve().parents[1] / "requirements.txt"


def test_runtime_requirements_pin_psycopg_binary() -> None:
    psycopg_requirements = [
        line
        for line in REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
        if line.startswith("psycopg")
    ]

    assert psycopg_requirements == ["psycopg[binary]==3.2.13"]


def _row(
    theme_id: str,
    *,
    hours_ago: int = 0,
    rank: int = 1,
) -> dict[str, object]:
    observed_at = CURRENT_HOUR - timedelta(hours=hours_ago)
    return {
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "theme_id": theme_id,
        "heat_score": 68,
        "rank": rank,
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
        "latest_qualifying_event_at": observed_at.isoformat().replace(
            "+00:00", "Z"
        ),
        "heat_rule_version": HEAT_RULE_VERSION,
        "momentum_rule_version": MOMENTUM_RULE_VERSION,
        "inclusion_rule_version": INCLUSION_RULE_VERSION,
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "producer_run_id": "private-run-id",
        "created_at": "2026-07-31T04:01:00Z",
        "updated_at": "2026-07-31T04:02:00Z",
    }


def test_builder_emits_bounded_public_allowlist_and_preserves_gaps() -> None:
    payload = build_public_theme_history(
        [_row("older", hours_ago=2), _row("current")],
        current_observed_hour=CURRENT_HOUR,
        generated_at=GENERATED_AT,
    )

    assert payload["schema_version"] == HISTORY_SCHEMA_VERSION
    assert payload["retention_hours"] == 720
    assert payload["oldest_observed_hour"] == "2026-07-01T05:00:00Z"
    assert payload["newest_observed_hour"] == "2026-07-31T04:00:00Z"
    assert payload["observation_count"] == 2
    assert [item["observed_hour"] for item in payload["observations"]] == [
        "2026-07-31T02:00:00Z",
        "2026-07-31T04:00:00Z",
    ]
    assert set(payload["observations"][0]["themes"][0]) == PUBLIC_THEME_FIELDS
    serialized = json.dumps(payload)
    for forbidden in (
        "producer_run_id",
        "created_at",
        "updated_at",
        "diagnostics",
        "source_ids",
        "evidence",
        "article_body",
        "match_strings",
        "internal_error",
    ):
        assert forbidden not in serialized


def test_builder_orders_themes_by_rank_then_theme_id() -> None:
    payload = build_public_theme_history(
        [_row("z", rank=1), _row("a", rank=1), _row("later", rank=2)],
        current_observed_hour=CURRENT_HOUR,
        generated_at=GENERATED_AT,
    )

    assert [
        theme["theme_id"] for theme in payload["observations"][0]["themes"]
    ] == ["a", "z", "later"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: {**row, "schema_version": "wrong"},
        lambda row: {**row, "observed_at": "2026-07-31T04:30:00Z"},
        lambda row: {**row, "observed_at": "2026-06-01T00:00:00Z"},
        lambda row: {**row, "unexpected_private_field": "leak"},
    ],
)
def test_builder_rejects_versions_hours_bounds_and_unknown_fields(mutate) -> None:
    with pytest.raises(ValueError):
        build_public_theme_history(
            [mutate(_row("thermal"))],
            current_observed_hour=CURRENT_HOUR,
            generated_at=GENERATED_AT,
        )


def test_builder_rejects_duplicate_primary_keys() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        build_public_theme_history(
            [_row("thermal"), _row("thermal")],
            current_observed_hour=CURRENT_HOUR,
            generated_at=GENERATED_AT,
        )


def test_materializer_queries_exact_range_and_atomically_replaces(tmp_path: Path) -> None:
    output = tmp_path / "history.json"
    calls: list[tuple[datetime, datetime]] = []

    def load_rows(oldest: datetime, newest: datetime):
        calls.append((oldest, newest))
        return [_row("thermal")]

    payload = materialize_public_theme_history(
        output,
        current_observed_hour=CURRENT_HOUR,
        generated_at=GENERATED_AT,
        row_loader=load_rows,
    )

    assert calls == [(CURRENT_HOUR - timedelta(hours=719), CURRENT_HOUR)]
    assert json.loads(output.read_text()) == payload
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("failure", ["query", "validation"])
def test_failure_preserves_prior_bytes_and_generated_at(
    tmp_path: Path,
    failure: str,
) -> None:
    output = tmp_path / "history.json"
    previous = b'{"generated_at":"2026-07-30T04:08:00Z","old":true}\n'
    output.write_bytes(previous)

    def load_rows(_oldest: datetime, _newest: datetime):
        if failure == "query":
            raise RuntimeError("query failed")
        return [{**_row("thermal"), "momentum_rule_version": "mixed"}]

    with pytest.raises((RuntimeError, ValueError)):
        materialize_public_theme_history(
            output,
            current_observed_hour=CURRENT_HOUR,
            generated_at=GENERATED_AT,
            row_loader=load_rows,
        )

    assert output.read_bytes() == previous


def test_retry_with_same_inputs_is_byte_deterministic(tmp_path: Path) -> None:
    output = tmp_path / "history.json"
    kwargs = {
        "current_observed_hour": CURRENT_HOUR,
        "generated_at": GENERATED_AT,
        "row_loader": lambda _oldest, _newest: [_row("thermal")],
    }

    materialize_public_theme_history(output, **kwargs)
    first = output.read_bytes()
    materialize_public_theme_history(output, **kwargs)

    assert output.read_bytes() == first


class _CursorScope:
    def __init__(self, cursor) -> None:
        self.cursor_object = cursor

    def __enter__(self):
        return self.cursor_object

    def __exit__(self, *_args) -> bool:
        return False


class _QueryCursor:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.description = []

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.calls.append((sql, params))

    def fetchall(self):
        return self.rows


class _QueryConnection:
    def __init__(self, rows) -> None:
        self.cursor_object = _QueryCursor(rows)

    def transaction(self) -> _CursorScope:
        return _CursorScope(object())

    def cursor(self) -> _CursorScope:
        return _CursorScope(self.cursor_object)


def test_injected_history_query_is_parameterized_and_returns_mapping_rows() -> None:
    connection = _QueryConnection([_row("thermal")])
    oldest = CURRENT_HOUR - timedelta(hours=719)

    rows = load_history_rows(connection, oldest, CURRENT_HOUR)

    assert rows == [_row("thermal")]
    assert connection.cursor_object.calls == [
        (HISTORY_QUERY, (oldest, CURRENT_HOUR))
    ]


def test_injected_history_query_maps_db_api_tuple_rows() -> None:
    row = _row("thermal")
    connection = _QueryConnection([tuple(row.values())])
    connection.cursor_object.description = [
        SimpleNamespace(name=field) for field in row
    ]

    rows = load_history_rows(
        connection,
        CURRENT_HOUR - timedelta(hours=719),
        CURRENT_HOUR,
    )

    assert rows == [row]


def test_live_connector_fails_closed_without_scoped_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("THEME_RADAR_DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="THEME_RADAR_DATABASE_URL"):
        _connect_from_environment()


def test_atomic_replace_failure_preserves_previous_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "history.json"
    previous = b'{"generated_at":"old"}\n'
    output.write_bytes(previous)
    original_replace = Path.replace

    def fail_replace(path: Path, target: Path):
        if target == output:
            raise OSError("replace failed")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        materialize_public_theme_history(
            output,
            current_observed_hour=CURRENT_HOUR,
            generated_at=GENERATED_AT,
            row_loader=lambda _oldest, _newest: [_row("thermal")],
        )

    assert output.read_bytes() == previous
