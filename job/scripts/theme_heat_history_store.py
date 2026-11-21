"""Injected database operations for private hourly theme-heat history."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

try:
    from scripts.public_theme_momentum import (
        HEAT_RULE_VERSION,
        INCLUSION_RULE_VERSION,
        MOMENTUM_RULE_VERSION,
        OBSERVATION_SCHEMA_VERSION,
    )
except ModuleNotFoundError:
    from public_theme_momentum import (
        HEAT_RULE_VERSION,
        INCLUSION_RULE_VERSION,
        MOMENTUM_RULE_VERSION,
        OBSERVATION_SCHEMA_VERSION,
    )


VERSION_FIELDS = {
    "heat_rule_version": HEAT_RULE_VERSION,
    "momentum_rule_version": MOMENTUM_RULE_VERSION,
    "inclusion_rule_version": INCLUSION_RULE_VERSION,
    "schema_version": OBSERVATION_SCHEMA_VERSION,
}
OBSERVATION_FIELDS = (
    "observed_at",
    "theme_id",
    "heat_score",
    "rank",
    "qualification_status",
    "near_threshold_reason",
    "momentum_score",
    "lifecycle_stage",
    "event_count",
    "source_count",
    "tracking_candidate_count",
    "taiwan_mapping_count",
    "direct_mapping_event_count",
    "single_source_concentration",
    "latest_qualifying_event_at",
    "heat_rule_version",
    "momentum_rule_version",
    "inclusion_rule_version",
    "schema_version",
)

UPSERT_SQL = """
INSERT INTO theme_radar.hourly_theme_heat (
  observed_at, theme_id, heat_score, rank, qualification_status,
  near_threshold_reason, momentum_score, lifecycle_stage, event_count,
  source_count, tracking_candidate_count, taiwan_mapping_count,
  direct_mapping_event_count, single_source_concentration,
  latest_qualifying_event_at, heat_rule_version, momentum_rule_version,
  inclusion_rule_version, schema_version, producer_run_id
) VALUES (
  %(observed_at)s, %(theme_id)s, %(heat_score)s, %(rank)s,
  %(qualification_status)s, %(near_threshold_reason)s, %(momentum_score)s,
  %(lifecycle_stage)s, %(event_count)s, %(source_count)s,
  %(tracking_candidate_count)s, %(taiwan_mapping_count)s,
  %(direct_mapping_event_count)s, %(single_source_concentration)s,
  %(latest_qualifying_event_at)s, %(heat_rule_version)s,
  %(momentum_rule_version)s, %(inclusion_rule_version)s, %(schema_version)s,
  %(producer_run_id)s
)
ON CONFLICT (observed_at, theme_id) DO UPDATE SET
  heat_score = EXCLUDED.heat_score,
  rank = EXCLUDED.rank,
  qualification_status = EXCLUDED.qualification_status,
  near_threshold_reason = EXCLUDED.near_threshold_reason,
  momentum_score = EXCLUDED.momentum_score,
  lifecycle_stage = EXCLUDED.lifecycle_stage,
  event_count = EXCLUDED.event_count,
  source_count = EXCLUDED.source_count,
  tracking_candidate_count = EXCLUDED.tracking_candidate_count,
  taiwan_mapping_count = EXCLUDED.taiwan_mapping_count,
  direct_mapping_event_count = EXCLUDED.direct_mapping_event_count,
  single_source_concentration = EXCLUDED.single_source_concentration,
  latest_qualifying_event_at = EXCLUDED.latest_qualifying_event_at,
  heat_rule_version = EXCLUDED.heat_rule_version,
  momentum_rule_version = EXCLUDED.momentum_rule_version,
  inclusion_rule_version = EXCLUDED.inclusion_rule_version,
  schema_version = EXCLUDED.schema_version,
  producer_run_id = EXCLUDED.producer_run_id,
  updated_at = now()
""".strip()

RETENTION_SQL = """
DELETE FROM theme_radar.hourly_theme_heat
WHERE observed_at < %s - interval '719 hours'
""".strip()

BASELINE_SQL = """
SELECT observed_at, theme_id, heat_score, source_count,
       heat_rule_version, momentum_rule_version, inclusion_rule_version,
       schema_version
FROM theme_radar.hourly_theme_heat
WHERE observed_at = %s
ORDER BY theme_id ASC
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


def _count(value: Any, label: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be at most {maximum}")
    return value


def map_theme_observation(
    observation: Mapping[str, Any],
    *,
    producer_run_id: str,
) -> dict[str, Any]:
    """Validate and copy one pure projector observation into DB parameters."""

    if set(observation) != set(OBSERVATION_FIELDS):
        raise ValueError("observation fields do not match the DB contract")
    if not producer_run_id.strip():
        raise ValueError("producer_run_id must be non-empty")
    for field, expected in VERSION_FIELDS.items():
        if observation.get(field) != expected:
            raise ValueError(f"observation version mismatch: {field}")
    observed_at = _timestamp(observation.get("observed_at"), "observed_at", exact_hour=True)
    latest = _timestamp(
        observation.get("latest_qualifying_event_at"),
        "latest_qualifying_event_at",
    )
    theme_id = str(observation.get("theme_id") or "").strip()
    if not theme_id:
        raise ValueError("theme_id must be non-empty")
    heat_score = _count(observation.get("heat_score"), "heat_score", maximum=100)
    momentum_score = _count(
        observation.get("momentum_score"),
        "momentum_score",
        maximum=100,
    )
    rank = observation.get("rank")
    if isinstance(rank, bool) or not isinstance(rank, int) or rank <= 0:
        raise ValueError("rank must be positive")
    counts = {
        field: _count(observation.get(field), field)
        for field in (
            "event_count",
            "source_count",
            "tracking_candidate_count",
            "taiwan_mapping_count",
            "direct_mapping_event_count",
        )
    }
    if counts["direct_mapping_event_count"] > counts["event_count"]:
        raise ValueError("direct_mapping_event_count must not exceed event_count")
    concentration = Decimal(str(observation.get("single_source_concentration")))
    if not concentration.is_finite() or not Decimal(0) <= concentration <= Decimal(1):
        raise ValueError("single_source_concentration must be between zero and one")
    status = observation.get("qualification_status")
    reason = observation.get("near_threshold_reason")
    if not (
        (status == "qualified" and reason is None)
        or (
            status == "near_threshold"
            and reason in {"events_1_of_2", "sources_1_of_2"}
        )
    ):
        raise ValueError("qualification status and reason are incompatible")
    if observation.get("lifecycle_stage") not in {
        "new",
        "accelerating",
        "cooling",
        "rising",
        "steady",
    }:
        raise ValueError("lifecycle_stage is invalid")
    return {
        **{field: observation[field] for field in OBSERVATION_FIELDS},
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "latest_qualifying_event_at": latest.isoformat().replace("+00:00", "Z"),
        "theme_id": theme_id,
        "heat_score": heat_score,
        "momentum_score": momentum_score,
        **counts,
        "single_source_concentration": float(concentration),
        "producer_run_id": producer_run_id,
    }


def write_theme_observations(
    connection: Any,
    observations: Sequence[Mapping[str, Any]],
    *,
    producer_run_id: str,
) -> int:
    """Upsert one producer batch in exactly one injected DB transaction."""

    rows = [
        map_theme_observation(row, producer_run_id=producer_run_id)
        for row in observations
    ]
    if not rows:
        return 0
    keys = [(row["observed_at"], row["theme_id"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("observation primary keys must be unique within a run")
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.executemany(UPSERT_SQL, rows)
    return len(rows)


def load_momentum_baselines(
    connection: Any,
    current_observed_hour: datetime,
) -> list[dict[str, Any]]:
    """Load only the exact compatible 24-hour baseline for momentum."""

    current_hour = _timestamp(
        current_observed_hour,
        "current_observed_hour",
        exact_hour=True,
    )
    target_hour = current_hour - timedelta(hours=24)
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(BASELINE_SQL, (target_hour,))
            raw_rows = cursor.fetchall()
            if raw_rows and not isinstance(raw_rows[0], Mapping):
                columns = [column.name for column in cursor.description]
                raw_rows = [
                    dict(zip(columns, row, strict=True))
                    for row in raw_rows
                ]
    rows = []
    seen = set()
    expected_fields = {
        "observed_at",
        "theme_id",
        "heat_score",
        "source_count",
        *VERSION_FIELDS,
    }
    for raw_row in raw_rows:
        if not isinstance(raw_row, Mapping) or set(raw_row) != expected_fields:
            raise ValueError("baseline row fields are invalid")
        for field, expected in VERSION_FIELDS.items():
            if raw_row.get(field) != expected:
                raise ValueError(f"baseline version mismatch: {field}")
        observed_at = _timestamp(
            raw_row.get("observed_at"),
            "baseline.observed_at",
            exact_hour=True,
        )
        theme_id = str(raw_row.get("theme_id") or "").strip()
        if observed_at != target_hour or not theme_id or theme_id in seen:
            raise ValueError("baseline exact-hour identity is invalid")
        seen.add(theme_id)
        rows.append(
            {
                "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
                "theme_id": theme_id,
                "heat_score": _count(
                    raw_row.get("heat_score"),
                    "baseline.heat_score",
                    maximum=100,
                ),
                "source_count": _count(
                    raw_row.get("source_count"),
                    "baseline.source_count",
                ),
            }
        )
    return rows


def retention_cutoff(current_observed_hour: datetime) -> datetime:
    """Return the oldest inclusive hour retained by the 720-hour window."""

    return _timestamp(
        current_observed_hour,
        "current_observed_hour",
        exact_hour=True,
    ) - timedelta(hours=719)


def delete_expired_observations(
    connection: Any,
    current_observed_hour: datetime,
) -> int:
    """Delete rows strictly before the inclusive 720-hour boundary."""

    current_hour = _timestamp(
        current_observed_hour,
        "current_observed_hour",
        exact_hour=True,
    )
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(RETENTION_SQL, (current_hour,))
            deleted = int(cursor.rowcount or 0)
    return deleted
