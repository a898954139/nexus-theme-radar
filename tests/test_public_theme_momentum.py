from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from scripts.public_theme_momentum import (
    HEAT_RULE_VERSION,
    INCLUSION_RULE_VERSION,
    MOMENTUM_RULE_VERSION,
    build_public_theme_momentum,
    classify_inclusion,
)
from scripts.public_theme_ranking import (
    build_public_theme_signals,
    calculate_public_theme_heat,
)


OBSERVED_HOUR = datetime(2026, 7, 31, 4, tzinfo=timezone.utc)


def _signal(
    theme_id: str,
    *,
    heat_score: int = 70,
    heat_raw_score: float = 70.0,
    event_count: int = 2,
    source_count: int = 2,
    mapping_count: int = 1,
    latest_at: str = "2026-07-31T03:30:00Z",
) -> dict[str, object]:
    return {
        "theme_id": theme_id,
        "name_zh": f"題材 {theme_id}",
        "heat_score": heat_score,
        "heat_raw_score": heat_raw_score,
        "event_count": event_count,
        "source_count": source_count,
        "tracking_candidate_count": 1,
        "taiwan_mapping_count": mapping_count,
        "direct_mapping_event_count": min(event_count, 1),
        "single_source_concentration": 0.5,
        "latest_qualifying_event_at": latest_at,
    }


def _baseline(
    theme_id: str,
    *,
    hours_ago: int = 24,
    heat_score: int = 45,
    source_count: int = 1,
) -> dict[str, object]:
    return {
        "observed_at": (OBSERVED_HOUR - timedelta(hours=hours_ago))
        .isoformat()
        .replace("+00:00", "Z"),
        "theme_id": theme_id,
        "heat_score": heat_score,
        "source_count": source_count,
    }


@pytest.mark.parametrize(
    ("events", "sources", "mappings", "expected"),
    [
        (2, 2, 1, ("qualified", None)),
        (1, 2, 1, ("near_threshold", "events_1_of_2")),
        (2, 1, 1, ("near_threshold", "sources_1_of_2")),
        (1, 1, 1, None),
        (2, 2, 0, None),
    ],
)
def test_inclusion_is_qualified_or_exactly_one_near_threshold_gate(
    events: int,
    sources: int,
    mappings: int,
    expected: tuple[str, str | None] | None,
) -> None:
    assert classify_inclusion(events, sources, mappings) == expected


def test_formula_uses_exact_24h_baseline_and_decimal_round_half_up() -> None:
    payload, observations = build_public_theme_momentum(
        [_signal("thermal", source_count=3)],
        baseline_rows=[_baseline("thermal", source_count=1)],
        observed_hour=OBSERVED_HOUR,
        generated_at=OBSERVED_HOUR + timedelta(minutes=7),
    )

    theme = payload["themes"][0]
    assert theme["momentum_score"] == 78
    assert theme["heat_change_24h"] == 25
    assert theme["source_change_24h"] == 2
    assert theme["lifecycle_stage"] == "accelerating"
    assert observations[0]["momentum_score"] == 78
    assert payload["heat_rule_version"] == HEAT_RULE_VERSION
    assert payload["ranking_rule_version"] == MOMENTUM_RULE_VERSION
    assert payload["inclusion_rule_version"] == INCLUSION_RULE_VERSION


def test_absent_exact_baseline_never_uses_nearest_hour_or_zero_fill() -> None:
    payload, _ = build_public_theme_momentum(
        [_signal("thermal", heat_score=80, heat_raw_score=80)],
        baseline_rows=[_baseline("thermal", hours_ago=23, heat_score=10)],
        observed_hour=OBSERVED_HOUR,
        generated_at=OBSERVED_HOUR,
    )

    theme = payload["themes"][0]
    assert theme["momentum_score"] == 40
    assert theme["heat_change_24h"] is None
    assert theme["source_change_24h"] is None
    assert theme["lifecycle_stage"] == "new"


@pytest.mark.parametrize(
    ("heat", "sources", "base_heat", "base_sources", "expected"),
    [
        (65, 3, 55, 2, "accelerating"),
        (45, 2, 50, 2, "cooling"),
        (55, 2, 50, 2, "rising"),
        (50, 3, 50, 2, "rising"),
        (52, 2, 50, 2, "steady"),
    ],
)
def test_lifecycle_checks_are_applied_in_locked_order(
    heat: int,
    sources: int,
    base_heat: int,
    base_sources: int,
    expected: str,
) -> None:
    payload, _ = build_public_theme_momentum(
        [_signal("theme", heat_score=heat, heat_raw_score=heat, source_count=sources)],
        baseline_rows=[
            _baseline("theme", heat_score=base_heat, source_count=base_sources)
        ],
        observed_hour=OBSERVED_HOUR,
        generated_at=OBSERVED_HOUR,
    )
    assert payload["themes"][0]["lifecycle_stage"] == expected


def test_near_threshold_multiplier_sorting_and_inputs_are_deterministic() -> None:
    signals = [
        _signal("qualified-z", heat_score=50, heat_raw_score=50),
        _signal(
            "near-a",
            heat_score=60,
            heat_raw_score=60,
            event_count=2,
            source_count=1,
        ),
    ]
    original = deepcopy(signals)

    first, _ = build_public_theme_momentum(
        signals,
        baseline_rows=[],
        observed_hour=OBSERVED_HOUR,
        generated_at=OBSERVED_HOUR,
    )
    second, _ = build_public_theme_momentum(
        list(reversed(signals)),
        baseline_rows=[],
        observed_hour=OBSERVED_HOUR,
        generated_at=OBSERVED_HOUR,
    )

    assert first == second
    assert signals == original
    assert [theme["theme_id"] for theme in first["themes"]] == [
        "near-a",
        "qualified-z",
    ]
    assert first["themes"][0]["momentum_score"] == 26
    assert [theme["rank"] for theme in first["themes"]] == [1, 2]


def test_heat_score_is_exactly_the_v08_projector_result() -> None:
    counts = {
        "event_count": 4,
        "source_count": 3,
        "tracking_candidate_count": 2,
        "taiwan_mapping_count": 2,
        "direct_mapping_event_count": 2,
        "single_source_concentration": 0.5,
    }
    heat = calculate_public_theme_heat(counts)
    payload, _ = build_public_theme_momentum(
        [
            {
                **_signal("compat"),
                **counts,
                "heat_score": heat["heat_score"],
                "heat_raw_score": heat["raw_score"],
            }
        ],
        baseline_rows=[],
        observed_hour=OBSERVED_HOUR,
        generated_at=OBSERVED_HOUR,
    )

    assert payload["themes"][0]["heat_score"] == heat["heat_score"]


def test_shared_uncapped_signal_projection_includes_qualified_and_near_threshold() -> None:
    projection = {
        "retained_records": [],
        "clustered_events": [
            {
                "cluster_id": "cluster-qualified-1",
                "id": "event-qualified-1",
                "title_zh": "液冷需求升溫",
                "summary": "",
                "source_id": "source-a",
                "source": "Source A",
                "published_at": "2026-07-31T03:00:00Z",
                "url": "https://example.test/q1",
                "theme_score": 0.9,
                "primary_theme_id": "qualified",
                "cluster_sources": [{"source_id": "source-a"}],
                "tw_related_symbols": ["TWSE:2330"],
            },
            {
                "cluster_id": "cluster-qualified-2",
                "id": "event-qualified-2",
                "title_zh": "液冷供應鏈擴產",
                "summary": "",
                "source_id": "source-b",
                "source": "Source B",
                "published_at": "2026-07-31T02:00:00Z",
                "url": "https://example.test/q2",
                "theme_score": 0.8,
                "primary_theme_id": "qualified",
                "cluster_sources": [{"source_id": "source-b"}],
                "tw_related_symbols": ["TWSE:2330"],
            },
            {
                "cluster_id": "cluster-near",
                "id": "event-near",
                "title_zh": "封裝題材聚焦",
                "summary": "",
                "source_id": "source-a",
                "source": "Source A",
                "published_at": "2026-07-31T01:00:00Z",
                "url": "https://example.test/n1",
                "theme_score": 0.7,
                "primary_theme_id": "near",
                "cluster_sources": [
                    {"source_id": "source-a"},
                    {"source_id": "source-b"},
                ],
                "tw_related_symbols": ["TWSE:2330"],
            },
        ],
        "candidate_clusters": [],
        "cluster_members_by_id": {
            "cluster-qualified-1": [
                {
                    "published_at": "2026-07-31T03:00:00Z",
                    "direct_symbols": ["TWSE:2330"],
                }
            ],
            "cluster-qualified-2": [
                {
                    "published_at": "2026-07-31T02:00:00Z",
                    "direct_symbols": [],
                }
            ],
            "cluster-near": [
                {
                    "published_at": "2026-07-31T01:00:00Z",
                    "direct_symbols": ["TWSE:2330"],
                }
            ],
        },
        "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"],
    }
    original = deepcopy(projection)
    taxonomy = {
        "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"],
        "themes": [
            {"theme_id": "qualified", "name_zh": "液冷"},
            {"theme_id": "near", "name_zh": "先進封裝"},
        ],
    }
    aliases = {
        "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"],
        "symbols": {
            "2330": {"exchange": "TWSE", "name_zh": "台積電"},
        },
    }

    signals = build_public_theme_signals(
        projection,
        taxonomy=taxonomy,
        symbol_aliases=aliases,
    )

    assert projection == original
    assert [signal["theme_id"] for signal in signals] == ["near", "qualified"]
    assert signals[0]["event_count"] == 1
    assert signals[0]["source_count"] == 2
    expected_heat = calculate_public_theme_heat(
        {
            key: signals[1][key]
            for key in (
                "event_count",
                "source_count",
                "tracking_candidate_count",
                "taiwan_mapping_count",
                "direct_mapping_event_count",
                "single_source_concentration",
            )
        }
    )
    assert signals[1]["heat_score"] == expected_heat["heat_score"]
