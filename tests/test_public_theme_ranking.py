from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from scripts.public_theme_ranking import (
    PUBLIC_COMPANY_RULE_VERSION,
    PUBLIC_MAX_THEMES,
    PUBLIC_RANKING_RULE_VERSION,
    PUBLIC_SCHEMA_VERSION,
    PUBLIC_WINDOW_HOURS,
    build_public_theme_ranking,
    calculate_public_theme_heat,
    validate_public_theme_ranking,
)


ANCHOR = datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc)
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "public_theme_ranking" / "v0.8" / "ranking-contract.json"

ALIASES = {
    "market_id": "TW_EQUITY",
    "market_scope": ["TW_EQUITY"],
    "symbols": {
        "2330": {"name_zh": "台積電", "exchange": "TWSE", "aliases": ["台積電"]},
        "2382": {"name_zh": "廣達", "exchange": "TWSE", "aliases": ["廣達"]},
        "3105": {"name_zh": "穩懋", "exchange": "TPEX", "aliases": ["穩懋"]},
        "6669": {"name_zh": "緯穎", "exchange": "TWSE", "aliases": ["緯穎"]},
    },
}


def _taxonomy(
    theme_ids: tuple[str, ...] = ("memory_hbm",),
    *,
    seeds: tuple[str, ...] = ("2330", "2382", "6669"),
) -> dict[str, Any]:
    return {
        "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"],
        "themes": [
            {
                "theme_id": theme_id,
                "name_zh": f"題材 {theme_id}",
                "seed_symbols": list(seeds),
            }
            for theme_id in theme_ids
        ],
    }


def _instrument(symbol: str, *, evidence: str | None = None) -> dict[str, str]:
    metadata = ALIASES["symbols"][symbol]
    result = {
        "instrument_id": f"{metadata['exchange']}:{symbol}",
        "symbol": symbol,
        "exchange": metadata["exchange"],
        "name_zh": metadata["name_zh"],
    }
    if evidence is not None:
        result["evidence"] = evidence
    return result


def _member(
    member_id: str,
    *,
    published_at: str,
    direct_symbols: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "id": member_id,
        "published_at": published_at,
        "direct_symbols": [_instrument(symbol) for symbol in direct_symbols],
    }


def _cluster(
    cluster_id: str,
    theme_id: str,
    *,
    published_at: str,
    sources: tuple[str, ...] | None = ("publisher-a",),
    mappings: tuple[str, ...] = ("2330",),
    seed_evidence: tuple[str, ...] = ("2330",),
    theme_score: float = 0.8,
    url: str | None = None,
    official_ids: tuple[str, ...] = (),
    secondary_theme_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    source_id = sources[0] if sources else "fallback-publisher"
    event = {
        "cluster_id": cluster_id,
        "id": f"event-{cluster_id}",
        "title_zh": f"Title {cluster_id}",
        "summary": f"Summary {cluster_id}",
        "source_id": source_id,
        "source": f"Publisher {source_id}",
        "published_at": published_at,
        "url": url if url is not None else f"https://example.com/{cluster_id}",
        "primary_theme_id": theme_id,
        "matched_themes": [
            {"theme_id": theme_id, "score": theme_score},
            *[{"theme_id": secondary_theme_id, "score": theme_score} for secondary_theme_id in secondary_theme_ids],
        ],
        "theme_score": theme_score,
        "tw_related_symbols": [_instrument(symbol)["instrument_id"] for symbol in mappings],
        "related_symbols": [_instrument(symbol, evidence=f"taxonomy seed: {theme_id}") for symbol in seed_evidence],
        "official_evidence_ids": list(official_ids),
    }
    if sources is not None:
        event["cluster_sources"] = [
            {
                "source_id": source,
                "source": f"Publisher {source}",
                "url": f"https://example.com/source/{source}/{cluster_id}",
                "published_at": published_at,
            }
            for source in sources
        ]
    return event


def _projection(
    clusters: list[dict[str, Any]],
    *,
    candidate_ids: tuple[str, ...] = (),
    members: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    cluster_members = members or {
        str(cluster["cluster_id"]): [
            _member(
                f"member-{cluster['cluster_id']}",
                published_at=str(cluster["published_at"]),
            )
        ]
        for cluster in clusters
        if cluster.get("cluster_id")
    }
    candidate_set = set(candidate_ids)
    return {
        "retained_records": [copy.deepcopy(member) for cluster_id in sorted(cluster_members) for member in cluster_members[cluster_id]],
        "clustered_events": copy.deepcopy(clusters),
        "candidate_clusters": [copy.deepcopy(cluster) for cluster in clusters if cluster.get("cluster_id") in candidate_set],
        "cluster_members_by_id": copy.deepcopy(cluster_members),
        "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"],
    }


def _build(
    projection: dict[str, Any],
    *,
    taxonomy: dict[str, Any] | None = None,
    official_evidence: dict[str, dict[str, Any]] | None = None,
    source_status: dict[str, Any] | None = None,
    official_status: str = "available",
) -> tuple[dict[str, Any], dict[str, Any]]:
    return build_public_theme_ranking(
        projection,
        taxonomy=taxonomy or _taxonomy(),
        symbol_aliases=ALIASES,
        official_evidence_by_id=official_evidence or {},
        source_status=source_status or {"failed_count": 0},
        generated_at=ANCHOR,
        window_hours=72,
        official_evidence_status=official_status,
    )


def _eligible_projection(
    theme_id: str = "memory_hbm",
    *,
    first_sources: tuple[str, ...] | None = ("publisher-a",),
    second_sources: tuple[str, ...] | None = ("publisher-b",),
    mappings: tuple[str, ...] = ("2330",),
) -> dict[str, Any]:
    clusters = [
        _cluster(
            "cluster-a",
            theme_id,
            published_at="2026-07-28T07:00:00Z",
            sources=first_sources,
            mappings=mappings,
        ),
        _cluster(
            "cluster-b",
            theme_id,
            published_at="2026-07-28T08:00:00Z",
            sources=second_sources,
            mappings=mappings,
        ),
    ]
    return _projection(clusters)


def _fixture_inputs() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, dict[str, Any]],
]:
    clusters = [
        _cluster(
            "cluster-a",
            "memory_hbm",
            published_at="2026-07-28T07:00:00Z",
            sources=("publisher-a",),
            mappings=("2330", "2382", "6669"),
            seed_evidence=("2330", "2382", "6669"),
            theme_score=0.7,
            official_ids=("official-2330",),
        ),
        _cluster(
            "cluster-b",
            "memory_hbm",
            published_at="2026-07-28T08:00:00Z",
            sources=("publisher-b",),
            mappings=("2330", "2382", "6669"),
            seed_evidence=("2330", "2382", "6669"),
            theme_score=0.9,
        ),
    ]
    members = {
        "cluster-a": [
            _member(
                "member-a",
                published_at="2026-07-28T07:00:00Z",
                direct_symbols=("2330",),
            )
        ],
        "cluster-b": [
            _member(
                "member-b",
                published_at="2026-07-28T08:00:00Z",
                direct_symbols=("2382",),
            )
        ],
    }
    official = {
        "official-2330": {
            "evidence_id": "official-2330",
            "symbol": "2330",
            "instrument_id": "TWSE:2330",
            "published_at": "2026-07-28T06:00:00Z",
        }
    }
    return (
        _projection(clusters, candidate_ids=("cluster-a",), members=members),
        _taxonomy(),
        official,
    )


def test_heat_uses_exact_caps_and_illustrative_reason_arithmetic() -> None:
    result = calculate_public_theme_heat(
        {
            "event_count": 8,
            "source_count": 3,
            "tracking_candidate_count": 3,
            "taiwan_mapping_count": 3,
            "direct_mapping_event_count": 0,
            "single_source_concentration": Decimal("0.5"),
        }
    )

    assert result["heat_score"] == 77
    assert result["raw_score"] == pytest.approx(76.75)
    assert result["heat_reason"] == {
        "rule_version": PUBLIC_RANKING_RULE_VERSION,
        "event_component": {"input": 8, "normalized": 100.0, "weighted": 25.0},
        "source_component": {"input": 3, "normalized": 75.0, "weighted": 18.75},
        "candidate_component": {"input": 3, "normalized": 75.0, "weighted": 15.0},
        "mapping_component": {
            "mapping_count": 3,
            "direct_mapping_event_count": 0,
            "normalized": 60.0,
            "weighted": 18.0,
        },
        "single_source_concentration": 0.5,
        "concentration_penalty": 0.0,
        "raw_score": 76.75,
    }

    capped = calculate_public_theme_heat(
        {
            "event_count": 600,
            "source_count": 400,
            "tracking_candidate_count": 400,
            "taiwan_mapping_count": 300,
            "direct_mapping_event_count": 200,
            "single_source_concentration": 0,
        }
    )
    at_caps = calculate_public_theme_heat(
        {
            "event_count": 6,
            "source_count": 4,
            "tracking_candidate_count": 4,
            "taiwan_mapping_count": 3,
            "direct_mapping_event_count": 2,
            "single_source_concentration": 0,
        }
    )
    assert capped["heat_score"] == at_caps["heat_score"] == 100
    for component in (
        "event_component",
        "source_component",
        "candidate_component",
        "mapping_component",
    ):
        assert capped["heat_reason"][component]["normalized"] == at_caps["heat_reason"][component]["normalized"]
        assert capped["heat_reason"][component]["weighted"] == at_caps["heat_reason"][component]["weighted"]


def test_concentration_boundaries_round_half_up_and_clamp() -> None:
    base = {
        "event_count": 6,
        "source_count": 4,
        "tracking_candidate_count": 4,
        "taiwan_mapping_count": 3,
        "direct_mapping_event_count": 2,
    }
    assert calculate_public_theme_heat({**base, "single_source_concentration": Decimal("0.60")})["heat_reason"]["concentration_penalty"] == 0.0
    assert calculate_public_theme_heat({**base, "single_source_concentration": Decimal("0.80")})["heat_reason"]["concentration_penalty"] == 7.5
    assert calculate_public_theme_heat({**base, "single_source_concentration": Decimal("1.00")})["heat_reason"]["concentration_penalty"] == 15.0

    half = calculate_public_theme_heat(
        {
            "event_count": 6,
            "source_count": 2,
            "tracking_candidate_count": 0,
            "taiwan_mapping_count": 0,
            "direct_mapping_event_count": 0,
            "single_source_concentration": Decimal(47) / Decimal(75),
        }
    )
    assert half["raw_score"] == pytest.approx(36.5)
    assert half["heat_score"] == 37

    assert (
        calculate_public_theme_heat(
            {
                "event_count": 0,
                "source_count": 0,
                "tracking_candidate_count": 0,
                "taiwan_mapping_count": 0,
                "direct_mapping_event_count": 0,
                "single_source_concentration": 1,
            }
        )["heat_score"]
        == 0
    )


@pytest.mark.parametrize(
    ("projection", "expected_rule"),
    [
        (
            _projection(
                [
                    _cluster(
                        "cluster-a",
                        "memory_hbm",
                        published_at="2026-07-28T07:00:00Z",
                    )
                ]
            ),
            "events_lt_2",
        ),
        (
            _eligible_projection(
                first_sources=("publisher-a",),
                second_sources=("publisher-a",),
            ),
            "publishers_lt_2",
        ),
        (_eligible_projection(mappings=()), "mapping_lt_1"),
    ],
)
def test_eligibility_independently_enforces_each_gate(
    projection: dict[str, Any],
    expected_rule: str,
) -> None:
    payload, diagnostics = _build(projection)

    assert payload["themes"] == []
    assert {failure["rule_code"] for failure in diagnostics["eligibility_failures"]} >= {expected_rule}


def test_exact_two_events_two_publishers_one_mapping_is_eligible() -> None:
    payload, diagnostics = _build(_eligible_projection())

    assert [theme["theme_id"] for theme in payload["themes"]] == ["memory_hbm"]
    assert payload["themes"][0]["summaries"] == {
        "event_count": 2,
        "source_count": 2,
        "tracking_candidate_count": 0,
        "taiwan_mapping_count": 1,
    }
    assert diagnostics["public_themes_qualified"] == 1


def test_primary_theme_only_and_publisher_fallback_rules_are_exact() -> None:
    projection = _eligible_projection(
        first_sources=None,
        second_sources=("publisher-b",),
    )
    projection["clustered_events"][0]["matched_themes"].append({"theme_id": "robotics", "score": 0.99})
    payload, _ = _build(
        projection,
        taxonomy=_taxonomy(("memory_hbm", "robotics")),
    )
    assert [theme["theme_id"] for theme in payload["themes"]] == ["memory_hbm"]

    projection["clustered_events"][0]["cluster_sources"] = []
    rejected, _ = _build(
        projection,
        taxonomy=_taxonomy(("memory_hbm", "robotics")),
    )
    assert rejected["themes"] == []


def test_candidate_intersection_and_publisher_incidences_are_unique() -> None:
    clusters = [
        _cluster(
            "cluster-a",
            "memory_hbm",
            published_at="2026-07-28T07:00:00Z",
            sources=("publisher-a", "publisher-a", "publisher-b"),
        ),
        _cluster(
            "cluster-b",
            "memory_hbm",
            published_at="2026-07-28T08:00:00Z",
            sources=("publisher-a", "publisher-c"),
        ),
    ]
    projection = _projection(clusters, candidate_ids=("cluster-a",))
    projection["candidate_clusters"].extend(
        [
            copy.deepcopy(projection["candidate_clusters"][0]),
            _cluster(
                "cluster-outside",
                "memory_hbm",
                published_at="2026-07-28T06:00:00Z",
            ),
        ]
    )

    payload, _ = _build(projection)
    theme = payload["themes"][0]
    assert theme["summaries"]["source_count"] == 3
    assert theme["summaries"]["tracking_candidate_count"] == 1
    assert theme["heat_reason"]["single_source_concentration"] == 0.5


def test_repeating_concentration_keeps_unrounded_heat_and_validates() -> None:
    clusters = [
        _cluster(
            "cluster-a",
            "memory_hbm",
            published_at="2026-07-28T07:00:00Z",
            sources=("publisher-a", "publisher-b"),
        ),
        _cluster(
            "cluster-b",
            "memory_hbm",
            published_at="2026-07-28T08:00:00Z",
            sources=("publisher-a",),
        ),
    ]

    payload, _ = _build(_projection(clusters))

    assert payload["themes"][0]["heat_reason"]["single_source_concentration"] == 0.667
    validate_public_theme_ranking(payload)


def test_direct_mentions_use_all_members_and_keep_evidence_classes_separate() -> None:
    projection = _eligible_projection()
    projection["clustered_events"][0]["related_symbols"] = [_instrument("2330", evidence="taxonomy seed: memory_hbm")]
    projection["cluster_members_by_id"] = {
        "cluster-a": [
            _member(
                "representative-member",
                published_at="2026-07-28T07:00:00Z",
            ),
            _member(
                "non-representative-member",
                published_at="2026-07-28T07:30:00Z",
                direct_symbols=("2330",),
            ),
        ],
        "cluster-b": [
            _member(
                "member-b",
                published_at="2026-07-28T08:00:00Z",
                direct_symbols=("2382",),
            )
        ],
    }
    projection["retained_records"] = [copy.deepcopy(member) for members in projection["cluster_members_by_id"].values() for member in members]

    payload, _ = _build(projection)
    theme = payload["themes"][0]
    assert [company["instrument_id"] for company in theme["direct_mentions"]] == [
        "TWSE:2382",
        "TWSE:2330",
    ]
    assert theme["heat_reason"]["mapping_component"]["direct_mapping_event_count"] == 2
    assert "TWSE:2330" in {company["instrument_id"] for company in theme["supply_chain_candidates"]}
    assert "TWSE:2330" in {company["instrument_id"] for company in theme["direct_mentions"]}


def test_supply_chain_is_seed_gated_ranked_and_official_joined_by_same_symbol() -> None:
    projection, taxonomy, official = _fixture_inputs()
    projection["clustered_events"][0]["official_evidence_ids"].extend(["official-2330", "wrong-symbol", "non-seed"])
    official.update(
        {
            "wrong-symbol": {
                "evidence_id": "wrong-symbol",
                "symbol": "2382",
                "published_at": "2026-07-28T08:30:00Z",
            },
            "non-seed": {
                "evidence_id": "non-seed",
                "symbol": "3105",
                "published_at": "2026-07-28T08:30:00Z",
            },
        }
    )
    taxonomy["themes"][0]["seed_symbols"].extend(["3105", "9999"])

    payload, _ = _build(
        projection,
        taxonomy=taxonomy,
        official_evidence=official,
    )
    candidates = payload["themes"][0]["supply_chain_candidates"]
    assert [candidate["instrument_id"] for candidate in candidates] == [
        "TWSE:2382",
        "TWSE:2330",
        "TWSE:6669",
    ]
    assert candidates[0]["company_rank_score"] == 8
    assert candidates[0]["official_evidence_count"] == 1
    assert candidates[0]["official_marker"] == "近期官方佐證"
    assert candidates[1]["official_evidence_count"] == 1
    assert candidates[1]["official_marker"] == "近期官方佐證"


def test_supply_chain_taxonomy_evidence_must_be_on_clustered_event() -> None:
    projection, taxonomy, _ = _fixture_inputs()
    theme_id = taxonomy["themes"][0]["theme_id"]
    for event in projection["clustered_events"]:
        event["related_symbols"] = []
    projection["cluster_members_by_id"]["cluster-a"][0]["related_symbols"] = [
        _instrument("2330", evidence=f"taxonomy seed: {theme_id}")
    ]

    payload, _ = _build(projection, taxonomy=taxonomy)

    assert payload["themes"][0]["supply_chain_candidates"] == []


def test_supply_chain_taxonomy_evidence_on_clustered_event_qualifies_seed() -> None:
    projection, taxonomy, _ = _fixture_inputs()
    theme_id = taxonomy["themes"][0]["theme_id"]
    for event in projection["clustered_events"]:
        event["related_symbols"] = []
    projection["clustered_events"][0]["related_symbols"] = [
        _instrument("2330", evidence=f"taxonomy seed: {theme_id}")
    ]

    payload, _ = _build(projection, taxonomy=taxonomy)

    assert [
        candidate["instrument_id"]
        for candidate in payload["themes"][0]["supply_chain_candidates"]
    ] == ["TWSE:2330"]


def test_supply_chain_official_tie_break_uses_latest_timestamp_across_fields_and_rows() -> None:
    projection, taxonomy, _ = _fixture_inputs()
    for members in projection["cluster_members_by_id"].values():
        for member in members:
            member["direct_symbols"] = []
    official = {
        "official-2330-fields": {
            "evidence_id": "official-2330-fields",
            "symbol": "2330",
            "published_at": "2026-07-28T06:00:00Z",
            "effective_at": "2026-07-28T08:45:00Z",
            "fetched_at": "2026-07-28T08:15:00Z",
        },
        "official-2330-row": {
            "evidence_id": "official-2330-row",
            "symbol": "2330",
            "published_at": "2026-07-28T07:00:00Z",
        },
        "official-2382-row": {
            "evidence_id": "official-2382-row",
            "symbol": "2382",
            "published_at": "2026-07-28T08:30:00Z",
        },
        "official-2382-fetched": {
            "evidence_id": "official-2382-fetched",
            "symbol": "2382",
            "fetched_at": "2026-07-28T08:00:00Z",
        },
    }
    projection["clustered_events"][0]["official_evidence_ids"] = list(official)
    projection["clustered_events"][1]["official_evidence_ids"] = []

    payload, _ = _build(
        projection,
        taxonomy=taxonomy,
        official_evidence=official,
    )
    candidates = payload["themes"][0]["supply_chain_candidates"]

    assert [candidate["instrument_id"] for candidate in candidates[:2]] == [
        "TWSE:2330",
        "TWSE:2382",
    ]
    assert [candidate["official_evidence_count"] for candidate in candidates[:2]] == [2, 2]
    assert candidates[0]["latest_official_at"] == "2026-07-28T08:45:00Z"


def test_representative_selection_prefers_candidate_and_preserves_attribution() -> None:
    projection, taxonomy, official = _fixture_inputs()
    payload, _ = _build(
        projection,
        taxonomy=taxonomy,
        official_evidence=official,
    )

    assert payload["themes"][0]["representative_news"] == {
        "cluster_id": "cluster-a",
        "id": "event-cluster-a",
        "title_zh": "Title cluster-a",
        "summary": "Summary cluster-a",
        "source_id": "publisher-a",
        "source": "Publisher publisher-a",
        "published_at": "2026-07-28T07:00:00Z",
        "canonical_url": "https://example.com/cluster-a",
    }


def test_official_evidence_has_zero_theme_or_representative_influence() -> None:
    projection, taxonomy, official = _fixture_inputs()
    available, _ = _build(
        projection,
        taxonomy=taxonomy,
        official_evidence=official,
    )
    unavailable, _ = _build(
        projection,
        taxonomy=taxonomy,
        official_evidence=official,
        official_status="unavailable",
    )

    stable_fields = (
        "rank",
        "theme_id",
        "name_zh",
        "heat_score",
        "summaries",
        "heat_reason",
        "direct_mentions",
        "representative_news",
    )
    assert {field: available["themes"][0][field] for field in stable_fields} == {field: unavailable["themes"][0][field] for field in stable_fields}
    assert all(candidate["official_evidence_count"] == 0 and "official_marker" not in candidate for candidate in unavailable["themes"][0]["supply_chain_candidates"])


def test_invalid_representative_url_omits_theme_and_records_derivation_error() -> None:
    projection = _eligible_projection()
    for cluster in projection["clustered_events"]:
        cluster["url"] = "javascript:alert(1)"

    payload, diagnostics = _build(projection)

    assert payload["themes"] == []
    assert diagnostics["public_derivation_error_count"] >= 1
    assert {failure["rule_code"] for failure in diagnostics["eligibility_failures"]} >= {"representative_missing"}


def test_malformed_member_and_cluster_inputs_fail_closed_with_diagnostics() -> None:
    projection = _eligible_projection()
    projection["cluster_members_by_id"]["cluster-a"] = [
        {
            "id": "bad-member",
            "published_at": "not-a-timestamp",
            "direct_symbols": [_instrument("2330")],
        }
    ]
    payload, diagnostics = _build(projection)
    assert payload["themes"][0]["direct_mentions"] == []
    assert diagnostics["public_derivation_error_count"] >= 1

    projection["clustered_events"][0]["published_at"] = "not-a-timestamp"
    rejected, diagnostics = _build(projection)
    assert rejected["themes"] == []
    assert {failure["rule_code"] for failure in diagnostics["eligibility_failures"]} >= {"invalid_required_input"}


def _many_theme_inputs(
    count: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    theme_ids = tuple(f"theme-{index:02d}" for index in range(count))
    clusters: list[dict[str, Any]] = []
    for theme_id in theme_ids:
        clusters.extend(
            [
                _cluster(
                    f"{theme_id}-a",
                    theme_id,
                    published_at="2026-07-28T07:00:00Z",
                    sources=("publisher-a",),
                ),
                _cluster(
                    f"{theme_id}-b",
                    theme_id,
                    published_at="2026-07-28T08:00:00Z",
                    sources=("publisher-b",),
                ),
            ]
        )
    return _projection(clusters), _taxonomy(theme_ids)


@pytest.mark.parametrize("count", range(0, 7))
def test_threshold_note_top_five_and_final_theme_id_tie_are_deterministic(
    count: int,
) -> None:
    projection, taxonomy = _many_theme_inputs(count)
    payload, _ = _build(projection, taxonomy=taxonomy)

    displayed = min(count, PUBLIC_MAX_THEMES)
    assert payload["qualified_theme_count"] == count
    assert payload["displayed_theme_count"] == displayed
    assert len(payload["themes"]) == displayed
    assert [theme["theme_id"] for theme in payload["themes"]] == sorted(theme["theme_id"] for theme in payload["themes"])
    expected_note = f"目前僅 {displayed} 個題材達到上榜門檻" if displayed < PUBLIC_MAX_THEMES else None
    assert payload["threshold_note"] == expected_note


def test_payload_and_diagnostics_are_permutation_invariant_and_inputs_immutable() -> None:
    projection, taxonomy, official = _fixture_inputs()
    originals = copy.deepcopy((projection, taxonomy, ALIASES, official))
    baseline = _build(
        projection,
        taxonomy=taxonomy,
        official_evidence=official,
    )

    permuted_projection = {
        "retained_records": list(reversed(projection["retained_records"])),
        "clustered_events": list(reversed(projection["clustered_events"])),
        "candidate_clusters": list(reversed(projection["candidate_clusters"])),
        "cluster_members_by_id": {key: list(reversed(value)) for key, value in reversed(list(projection["cluster_members_by_id"].items()))},
        "market_id": projection["market_id"],
        "market_scope": list(reversed(projection["market_scope"])),
    }
    permuted_taxonomy = {
        "themes": list(reversed(taxonomy["themes"])),
        "market_scope": taxonomy["market_scope"],
        "market_id": taxonomy["market_id"],
    }
    permuted_aliases = {
        "symbols": dict(reversed(list(ALIASES["symbols"].items()))),
        "market_scope": ALIASES["market_scope"],
        "market_id": ALIASES["market_id"],
    }
    permuted_official = dict(reversed(list(official.items())))
    permuted = build_public_theme_ranking(
        permuted_projection,
        taxonomy=permuted_taxonomy,
        symbol_aliases=permuted_aliases,
        official_evidence_by_id=permuted_official,
        source_status={"failed_count": 0},
        generated_at=ANCHOR,
        window_hours=72,
        official_evidence_status="available",
    )

    assert json.dumps(
        baseline,
        ensure_ascii=False,
        separators=(",", ":"),
    ) == json.dumps(permuted, ensure_ascii=False, separators=(",", ":"))
    assert (projection, taxonomy, ALIASES, official) == originals


def test_validate_public_payload_accepts_exact_v08_contract() -> None:
    projection, taxonomy, official = _fixture_inputs()
    payload, _ = _build(
        projection,
        taxonomy=taxonomy,
        official_evidence=official,
    )

    validate_public_theme_ranking(payload)
    assert payload["schema_version"] == PUBLIC_SCHEMA_VERSION
    assert payload["ranking_rule_version"] == PUBLIC_RANKING_RULE_VERSION
    assert payload["company_rule_version"] == PUBLIC_COMPANY_RULE_VERSION
    assert payload["window_hours"] == PUBLIC_WINDOW_HOURS


def test_validate_public_payload_rejects_wrong_schema_rule_market_window_or_bounds() -> None:
    projection, taxonomy, official = _fixture_inputs()
    payload, _ = _build(
        projection,
        taxonomy=taxonomy,
        official_evidence=official,
    )
    mutations = [
        ("schema_version", "wrong"),
        ("ranking_rule_version", "wrong"),
        ("company_rule_version", "wrong"),
        ("market_id", "US_EQUITY"),
        ("market_scope", ["US_EQUITY"]),
        ("window_hours", 24),
        ("max_themes", 6),
        ("generation_status", "stale"),
        ("official_evidence_status", "error"),
    ]
    for key, value in mutations:
        invalid = copy.deepcopy(payload)
        invalid[key] = value
        with pytest.raises(ValueError, match=key):
            validate_public_theme_ranking(invalid)

    invalid = copy.deepcopy(payload)
    invalid["themes"][0]["heat_score"] = 101
    with pytest.raises(ValueError, match="heat_score"):
        validate_public_theme_ranking(invalid)


def test_invalid_theme_company_and_representative_entities_fail_closed() -> None:
    projection = _eligible_projection()
    projection["cluster_members_by_id"]["cluster-a"][0]["direct_symbols"] = [
        {"instrument_id": "NASDAQ:AAPL", "symbol": "AAPL", "exchange": "NASDAQ"},
        {"instrument_id": "TWSE:9999", "symbol": "9999", "exchange": "TWSE"},
    ]
    payload, diagnostics = _build(projection)
    assert payload["themes"][0]["direct_mentions"] == []
    assert diagnostics["public_derivation_error_count"] >= 1

    invalid_contract = copy.deepcopy(payload)
    invalid_contract["themes"][0]["representative_news"]["canonical_url"] = "data:text/plain,unsafe"
    with pytest.raises(ValueError, match="canonical_url"):
        validate_public_theme_ranking(invalid_contract)

    invalid_contract = copy.deepcopy(payload)
    invalid_contract["themes"][0]["direct_mentions"] = [
        {
            "instrument_id": "NASDAQ:AAPL",
            "symbol": "AAPL",
            "exchange": "NASDAQ",
            "name_zh": "Apple",
            "direct_event_count": 1,
            "latest_mentioned_at": "2026-07-28T08:00:00Z",
        }
    ]
    with pytest.raises(ValueError, match="exchange"):
        validate_public_theme_ranking(invalid_contract)


def test_forbidden_public_evidence_and_diagnostic_fields_are_rejected() -> None:
    projection, taxonomy, official = _fixture_inputs()
    payload, _ = _build(
        projection,
        taxonomy=taxonomy,
        official_evidence=official,
    )
    for forbidden_key in (
        "official_evidence_ids",
        "raw_reference",
        "match_strings",
        "rejected_themes",
        "source_diagnostics",
        "momentum_score",
    ):
        invalid = copy.deepcopy(payload)
        invalid["themes"][0][forbidden_key] = []
        with pytest.raises(ValueError, match=forbidden_key):
            validate_public_theme_ranking(invalid)


def test_complete_payload_matches_the_single_frozen_contract_fixture() -> None:
    projection, taxonomy, official = _fixture_inputs()
    payload, diagnostics = _build(
        projection,
        taxonomy=taxonomy,
        official_evidence=official,
    )

    expected = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload == expected
    assert diagnostics == {
        "public_themes_qualified": 1,
        "public_themes_displayed": 1,
        "public_themes_omitted_invalid": 0,
        "public_direct_company_count": 2,
        "public_supply_chain_company_count": 3,
        "public_derivation_error_count": 0,
        "public_generation_status": "complete",
        "eligibility_failures": [],
    }


def test_partial_discovery_status_preserves_gates_and_official_status_is_independent() -> None:
    complete, _ = _build(_eligible_projection())
    partial, diagnostics = _build(
        _eligible_projection(),
        source_status={"failed_count": 2},
        official_status="unavailable",
    )

    assert partial["generation_status"] == "partial"
    assert partial["failed_source_count"] == 2
    assert partial["official_evidence_status"] == "unavailable"
    assert partial["themes"] == complete["themes"]
    assert diagnostics["public_generation_status"] == "partial"
