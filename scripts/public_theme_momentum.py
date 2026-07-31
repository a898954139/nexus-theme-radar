"""Pure deterministic projector for the Nexus Theme Radar v0.9 momentum view."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


LATEST_SCHEMA_VERSION = "nexus_public_theme_momentum_latest.v0.9"
MOMENTUM_RULE_VERSION = "public_theme_momentum_v0.9"
INCLUSION_RULE_VERSION = "public_theme_momentum_inclusion_v0.9"
HEAT_RULE_VERSION = "public_theme_heat_v0.8"
OBSERVATION_SCHEMA_VERSION = "theme_radar_hourly_theme_heat.v0.9"
MARKET_ID = "TW_EQUITY"
MARKET_SCOPE = [MARKET_ID]
WINDOW_HOURS = 72

_SIGNAL_KEYS = {
    "theme_id",
    "name_zh",
    "heat_score",
    "heat_raw_score",
    "event_count",
    "source_count",
    "tracking_candidate_count",
    "taiwan_mapping_count",
    "direct_mapping_event_count",
    "single_source_concentration",
    "latest_qualifying_event_at",
}


def _utc_hour(value: datetime, label: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    normalized = value.astimezone(timezone.utc)
    if normalized != normalized.replace(minute=0, second=0, microsecond=0):
        raise ValueError(f"{label} must be an exact hour")
    return normalized


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} must be a valid timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _integer(value: Any, label: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be at most {maximum}")
    return value


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{label} must be numeric")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


def classify_inclusion(
    event_count: int,
    source_count: int,
    taiwan_mapping_count: int,
) -> tuple[str, str | None] | None:
    """Return the locked v0.9 inclusion state, or ``None`` when excluded."""

    if taiwan_mapping_count < 1:
        return None
    if event_count >= 2 and source_count >= 2:
        return ("qualified", None)
    if event_count == 1 and source_count >= 2:
        return ("near_threshold", "events_1_of_2")
    if event_count >= 2 and source_count == 1:
        return ("near_threshold", "sources_1_of_2")
    return None


def _baseline_index(
    rows: Sequence[Mapping[str, Any]],
    target_hour: datetime,
) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        observed_at = _timestamp(row.get("observed_at"), "baseline.observed_at")
        if observed_at != target_hour:
            continue
        theme_id = str(row.get("theme_id") or "").strip()
        if not theme_id or theme_id in indexed:
            raise ValueError("exact baseline theme_id values must be non-empty and unique")
        _integer(row.get("heat_score"), "baseline.heat_score", maximum=100)
        _integer(row.get("source_count"), "baseline.source_count")
        indexed[theme_id] = row
    return indexed


def _lifecycle(delta_heat: int, delta_sources: int) -> str:
    if delta_heat >= 10 and delta_sources >= 1:
        return "accelerating"
    if delta_heat <= -5:
        return "cooling"
    if delta_heat >= 5 or delta_sources >= 1:
        return "rising"
    return "steady"


def _project_theme(
    signal: Mapping[str, Any],
    baseline: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if set(signal) != _SIGNAL_KEYS:
        raise ValueError(f"signal keys are invalid: {sorted(set(signal) ^ _SIGNAL_KEYS)}")
    theme_id = str(signal.get("theme_id") or "").strip()
    name_zh = str(signal.get("name_zh") or "").strip()
    if not theme_id or not name_zh:
        raise ValueError("signal theme_id and name_zh must be non-empty")

    heat_score = _integer(signal.get("heat_score"), "heat_score", maximum=100)
    heat_raw_score = _decimal(signal.get("heat_raw_score"), "heat_raw_score")
    event_count = _integer(signal.get("event_count"), "event_count")
    source_count = _integer(signal.get("source_count"), "source_count")
    candidate_count = _integer(
        signal.get("tracking_candidate_count"),
        "tracking_candidate_count",
    )
    mapping_count = _integer(
        signal.get("taiwan_mapping_count"),
        "taiwan_mapping_count",
    )
    direct_count = _integer(
        signal.get("direct_mapping_event_count"),
        "direct_mapping_event_count",
    )
    if direct_count > event_count:
        raise ValueError("direct_mapping_event_count must not exceed event_count")
    concentration = _decimal(
        signal.get("single_source_concentration"),
        "single_source_concentration",
    )
    if not Decimal(0) <= concentration <= Decimal(1):
        raise ValueError("single_source_concentration must be between zero and one")
    latest = _timestamp(
        signal.get("latest_qualifying_event_at"),
        "latest_qualifying_event_at",
    )

    inclusion = classify_inclusion(event_count, source_count, mapping_count)
    if inclusion is None:
        return None
    qualification_status, near_threshold_reason = inclusion

    if baseline is None:
        delta_heat = None
        delta_sources = None
        acceleration = Decimal(0)
        expansion = Decimal(0)
        lifecycle = "new"
    else:
        baseline_heat = _integer(
            baseline.get("heat_score"),
            "baseline.heat_score",
            maximum=100,
        )
        baseline_sources = _integer(
            baseline.get("source_count"),
            "baseline.source_count",
        )
        delta_heat = heat_score - baseline_heat
        delta_sources = source_count - baseline_sources
        support = (
            Decimal(min(event_count, 2))
            / Decimal(2)
            * Decimal(min(source_count, 2))
            / Decimal(2)
        )
        acceleration = (
            Decimal(100)
            * Decimal(min(max(delta_heat, 0), 25))
            / Decimal(25)
            * support
        )
        expansion = (
            Decimal(0)
            if source_count < 2
            else Decimal(100)
            * Decimal(min(max(delta_sources, 0), 3))
            / Decimal(3)
        )
        lifecycle = _lifecycle(delta_heat, delta_sources)

    raw_score = (
        Decimal("0.50") * Decimal(heat_score)
        + Decimal("0.30") * acceleration
        + Decimal("0.20") * expansion
    )
    multiplier = Decimal("1.00") if qualification_status == "qualified" else Decimal("0.85")
    adjusted = min(max(raw_score * multiplier, Decimal(0)), Decimal(100))
    momentum_score = int(adjusted.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return {
        "theme_id": theme_id,
        "name_zh": name_zh,
        "qualification_status": qualification_status,
        "near_threshold_reason": near_threshold_reason,
        "momentum_score": momentum_score,
        "lifecycle_stage": lifecycle,
        "heat_score": heat_score,
        "heat_change_24h": delta_heat,
        "source_change_24h": delta_sources,
        "event_count": event_count,
        "source_count": source_count,
        "tracking_candidate_count": candidate_count,
        "taiwan_mapping_count": mapping_count,
        "direct_mapping_event_count": direct_count,
        "single_source_concentration": float(concentration),
        "latest_qualifying_event_at": _iso(latest),
        "_sort": {
            "adjusted": adjusted,
            "qualified": qualification_status == "qualified",
            "heat_raw": heat_raw_score,
            "acceleration": acceleration,
            "expansion": expansion,
            "latest": latest,
        },
    }


def build_public_theme_momentum(
    signals: Sequence[Mapping[str, Any]],
    *,
    baseline_rows: Sequence[Mapping[str, Any]],
    observed_hour: datetime,
    generated_at: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build latest public momentum and compact DB observations without I/O."""

    current_hour = _utc_hour(observed_hour, "observed_hour")
    if generated_at.tzinfo is None:
        raise ValueError("generated_at must include a timezone")
    baselines = _baseline_index(
        baseline_rows,
        current_hour - timedelta(hours=24),
    )
    projected = [
        item
        for signal in signals
        if (item := _project_theme(signal, baselines.get(str(signal.get("theme_id") or ""))))
        is not None
    ]
    theme_ids = [item["theme_id"] for item in projected]
    if len(theme_ids) != len(set(theme_ids)):
        raise ValueError("signal theme_id values must be unique")
    projected.sort(
        key=lambda item: (
            -item["momentum_score"],
            -item["_sort"]["adjusted"],
            -int(item["_sort"]["qualified"]),
            -item["heat_score"],
            -item["_sort"]["acceleration"],
            -item["_sort"]["expansion"],
            -item["event_count"],
            -item["source_count"],
            -Decimal(str(item["_sort"]["latest"].timestamp())),
            item["theme_id"],
        )
    )
    themes = [
        {
            "rank": rank,
            **{key: value for key, value in item.items() if key != "_sort"},
        }
        for rank, item in enumerate(projected, start=1)
    ]
    payload = {
        "schema_version": LATEST_SCHEMA_VERSION,
        "ranking_rule_version": MOMENTUM_RULE_VERSION,
        "inclusion_rule_version": INCLUSION_RULE_VERSION,
        "heat_rule_version": HEAT_RULE_VERSION,
        "generated_at": _iso(generated_at),
        "observed_hour": _iso(current_hour),
        "market_id": MARKET_ID,
        "market_scope": list(MARKET_SCOPE),
        "window_hours": WINDOW_HOURS,
        "freshness_status": "current",
        "theme_count": len(themes),
        "themes": themes,
    }
    observations = [
        {
            "observed_at": _iso(current_hour),
            **{
                key: theme[key]
                for key in (
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
            },
            "heat_rule_version": HEAT_RULE_VERSION,
            "momentum_rule_version": MOMENTUM_RULE_VERSION,
            "inclusion_rule_version": INCLUSION_RULE_VERSION,
            "schema_version": OBSERVATION_SCHEMA_VERSION,
        }
        for theme in themes
    ]
    return payload, observations
