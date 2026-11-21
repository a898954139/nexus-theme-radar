"""Materialize bounded public momentum history from injected private DB rows."""

from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.public_theme_momentum import (
        HEAT_RULE_VERSION,
        INCLUSION_RULE_VERSION,
        MARKET_ID,
        MARKET_SCOPE,
        MOMENTUM_RULE_VERSION,
        OBSERVATION_SCHEMA_VERSION,
    )
    from scripts.theme_heat_history_store import (
        OBSERVATION_FIELDS,
        map_theme_observation,
    )
except ModuleNotFoundError:
    from public_theme_momentum import (
        HEAT_RULE_VERSION,
        INCLUSION_RULE_VERSION,
        MARKET_ID,
        MARKET_SCOPE,
        MOMENTUM_RULE_VERSION,
        OBSERVATION_SCHEMA_VERSION,
    )
    from theme_heat_history_store import OBSERVATION_FIELDS, map_theme_observation


HISTORY_SCHEMA_VERSION = "nexus_public_theme_momentum_history.v0.9"
RETENTION_HOURS = 720
LOGGER = logging.getLogger(__name__)

PUBLIC_THEME_FIELD_ORDER = (
    "theme_id",
    "rank",
    "qualification_status",
    "near_threshold_reason",
    "momentum_score",
    "lifecycle_stage",
    "heat_score",
    "event_count",
    "source_count",
    "tracking_candidate_count",
    "taiwan_mapping_count",
    "direct_mapping_event_count",
    "single_source_concentration",
    "latest_qualifying_event_at",
)
PUBLIC_THEME_FIELDS = set(PUBLIC_THEME_FIELD_ORDER)
DB_ROW_FIELDS = set(OBSERVATION_FIELDS) | {
    "producer_run_id",
    "created_at",
    "updated_at",
}
HISTORY_QUERY = """
SELECT
  observed_at, theme_id, heat_score, rank, qualification_status,
  near_threshold_reason, momentum_score, lifecycle_stage, event_count,
  source_count, tracking_candidate_count, taiwan_mapping_count,
  direct_mapping_event_count, single_source_concentration,
  latest_qualifying_event_at, heat_rule_version, momentum_rule_version,
  inclusion_rule_version, schema_version, producer_run_id, created_at, updated_at
FROM theme_radar.hourly_theme_heat
WHERE observed_at BETWEEN %s AND %s
ORDER BY observed_at ASC, rank ASC NULLS LAST, theme_id ASC
""".strip()


def _timestamp(value: Any, label: str, *, exact_hour: bool = False) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{label} must be a valid timestamp") from error
    else:
        raise ValueError(f"{label} must be a timestamp")
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    normalized = parsed.astimezone(timezone.utc)
    if exact_hour and normalized != normalized.replace(
        minute=0,
        second=0,
        microsecond=0,
    ):
        raise ValueError(f"{label} must be an exact hour")
    return normalized


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _validated_db_row(
    row: Mapping[str, Any],
    *,
    oldest: datetime,
    newest: datetime,
) -> dict[str, Any]:
    if set(row) != DB_ROW_FIELDS:
        raise ValueError(f"history row fields are invalid: {sorted(set(row) ^ DB_ROW_FIELDS)}")
    observed_at = _timestamp(row.get("observed_at"), "observed_at", exact_hour=True)
    if not oldest <= observed_at <= newest:
        raise ValueError("history row is outside the bounded retention range")
    _timestamp(row.get("created_at"), "created_at")
    _timestamp(row.get("updated_at"), "updated_at")
    observation = {field: row[field] for field in OBSERVATION_FIELDS}
    mapped = map_theme_observation(
        observation,
        producer_run_id=str(row.get("producer_run_id") or ""),
    )
    return {
        "observed_at": observed_at,
        **{field: mapped[field] for field in PUBLIC_THEME_FIELD_ORDER},
    }


def build_public_theme_history(
    rows: Sequence[Mapping[str, Any]],
    *,
    current_observed_hour: datetime,
    generated_at: datetime,
) -> dict[str, Any]:
    """Validate private rows and project only the bounded public contract."""

    newest = _timestamp(
        current_observed_hour,
        "current_observed_hour",
        exact_hour=True,
    )
    oldest = newest - timedelta(hours=RETENTION_HOURS - 1)
    generated = _timestamp(generated_at, "generated_at")
    validated = [
        _validated_db_row(row, oldest=oldest, newest=newest)
        for row in rows
    ]
    keys = [(row["observed_at"], row["theme_id"]) for row in validated]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate history primary key")
    ordered = sorted(
        validated,
        key=lambda row: (
            row["observed_at"],
            row["rank"] if row["rank"] is not None else float("inf"),
            row["theme_id"],
        ),
    )
    grouped: list[dict[str, Any]] = []
    for row in ordered:
        observed_text = _iso(row["observed_at"])
        if not grouped or grouped[-1]["observed_hour"] != observed_text:
            grouped.append({"observed_hour": observed_text, "themes": []})
        grouped[-1]["themes"].append(
            {field: row[field] for field in PUBLIC_THEME_FIELD_ORDER}
        )
    payload = {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "ranking_rule_version": MOMENTUM_RULE_VERSION,
        "inclusion_rule_version": INCLUSION_RULE_VERSION,
        "heat_rule_version": HEAT_RULE_VERSION,
        "generated_at": _iso(generated),
        "market_id": MARKET_ID,
        "market_scope": list(MARKET_SCOPE),
        "retention_hours": RETENTION_HOURS,
        "oldest_observed_hour": _iso(oldest),
        "newest_observed_hour": _iso(newest),
        "observation_count": len(grouped),
        "observations": grouped,
    }
    validate_public_theme_history(payload)
    return payload


def validate_public_theme_history(payload: Mapping[str, Any]) -> None:
    """Fail closed on the exact public history envelope and row allowlist."""

    top_level = {
        "schema_version",
        "ranking_rule_version",
        "inclusion_rule_version",
        "heat_rule_version",
        "generated_at",
        "market_id",
        "market_scope",
        "retention_hours",
        "oldest_observed_hour",
        "newest_observed_hour",
        "observation_count",
        "observations",
    }
    if set(payload) != top_level:
        raise ValueError("public history top-level fields are invalid")
    expected = {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "ranking_rule_version": MOMENTUM_RULE_VERSION,
        "inclusion_rule_version": INCLUSION_RULE_VERSION,
        "heat_rule_version": HEAT_RULE_VERSION,
        "market_id": MARKET_ID,
        "market_scope": MARKET_SCOPE,
        "retention_hours": RETENTION_HOURS,
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise ValueError(f"public history {field} is incompatible")
    generated = _timestamp(payload.get("generated_at"), "generated_at")
    del generated
    oldest = _timestamp(
        payload.get("oldest_observed_hour"),
        "oldest_observed_hour",
        exact_hour=True,
    )
    newest = _timestamp(
        payload.get("newest_observed_hour"),
        "newest_observed_hour",
        exact_hour=True,
    )
    if newest - oldest != timedelta(hours=RETENTION_HOURS - 1):
        raise ValueError("public history bounds are incompatible")
    observations = payload.get("observations")
    if not isinstance(observations, list):
        raise ValueError("observations must be an array")
    if payload.get("observation_count") != len(observations):
        raise ValueError("observation_count is invalid")
    previous_hour: datetime | None = None
    for observation in observations:
        if not isinstance(observation, Mapping) or set(observation) != {
            "observed_hour",
            "themes",
        }:
            raise ValueError("history observation fields are invalid")
        observed = _timestamp(
            observation.get("observed_hour"),
            "observed_hour",
            exact_hour=True,
        )
        if not oldest <= observed <= newest or (
            previous_hour is not None and observed <= previous_hour
        ):
            raise ValueError("history observation ordering is invalid")
        previous_hour = observed
        themes = observation.get("themes")
        if not isinstance(themes, list):
            raise ValueError("history themes must be an array")
        previous_key: tuple[float, str] | None = None
        for theme in themes:
            if not isinstance(theme, Mapping) or set(theme) != PUBLIC_THEME_FIELDS:
                raise ValueError("public history theme fields are invalid")
            rank = theme.get("rank")
            rank_key = float(rank) if rank is not None else float("inf")
            key = (rank_key, str(theme.get("theme_id") or ""))
            if previous_key is not None and key < previous_key:
                raise ValueError("public history theme ordering is invalid")
            previous_key = key


def materialize_public_theme_history(
    output_path: Path,
    *,
    current_observed_hour: datetime,
    generated_at: datetime,
    row_loader: Callable[[datetime, datetime], Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Query, validate, and atomically replace public history on full success."""

    newest = _timestamp(
        current_observed_hour,
        "current_observed_hour",
        exact_hour=True,
    )
    oldest = newest - timedelta(hours=RETENTION_HOURS - 1)
    rows = row_loader(oldest, newest)
    payload = build_public_theme_history(
        rows,
        current_observed_hour=newest,
        generated_at=generated_at,
    )
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(serialized)
            temporary.flush()
        decoded = json.loads(temporary_path.read_text(encoding="utf-8"))
        validate_public_theme_history(decoded)
        temporary_path.replace(output_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return payload


def load_history_rows(
    connection: Any,
    oldest: datetime,
    newest: datetime,
) -> list[Mapping[str, Any]]:
    """Load the inclusive bounded range through an injected DB connection."""

    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(HISTORY_QUERY, (oldest, newest))
            rows = cursor.fetchall()
            if not rows or isinstance(rows[0], Mapping):
                return list(rows)
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row, strict=True)) for row in rows]


def _connect_from_environment() -> Any:
    database_url = os.environ.get("THEME_RADAR_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("THEME_RADAR_DATABASE_URL is required")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "psycopg dependency authorization is required for live DB materialization"
        ) from error
    return psycopg.connect(database_url, row_factory=dict_row)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--current-observed-hour", required=True)
    args = parser.parse_args()
    current_hour = _timestamp(
        args.current_observed_hour,
        "current_observed_hour",
        exact_hour=True,
    )
    try:
        with _connect_from_environment() as connection:
            materialize_public_theme_history(
                args.output,
                current_observed_hour=current_hour,
                generated_at=datetime.now(timezone.utc),
                row_loader=lambda oldest, newest: load_history_rows(
                    connection,
                    oldest,
                    newest,
                ),
            )
    except Exception as error:  # noqa: BLE001 - CLI must report truthful side-path failure
        LOGGER.warning("public_history_materialization_failed phase=materialize error=%s", error)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
