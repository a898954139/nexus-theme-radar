"""Pure deterministic projector for the Nexus Theme Radar v0.8 public ranking."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from typing import Any
from urllib.parse import urlparse


PUBLIC_SCHEMA_VERSION = "nexus_public_theme_ranking.v0.8"
PUBLIC_RANKING_RULE_VERSION = "public_theme_heat_v0.8"
PUBLIC_COMPANY_RULE_VERSION = "public_company_evidence_v0.8"
PUBLIC_WINDOW_HOURS = 72
PUBLIC_MAX_THEMES = 5

MARKET_ID = "TW_EQUITY"
MARKET_SCOPE = [MARKET_ID]
TAIWAN_EXCHANGES = {"TWSE", "TPEX"}
OFFICIAL_MARKER = "近期官方佐證"

_PROJECTION_KEYS = set("retained_records clustered_events candidate_clusters cluster_members_by_id market_id market_scope".split())
_TOP_LEVEL_KEYS = set(
    "schema_version ranking_rule_version company_rule_version generated_at market_id market_scope window_hours max_themes "
    "qualified_theme_count displayed_theme_count threshold_note generation_status failed_source_count official_evidence_status themes".split()
)
_THEME_KEYS = set("rank theme_id name_zh heat_score summaries heat_reason direct_mentions supply_chain_candidates representative_news".split())
_SUMMARY_KEYS = set("event_count source_count tracking_candidate_count taiwan_mapping_count".split())
_HEAT_REASON_KEYS = set("rule_version event_component source_component candidate_component mapping_component single_source_concentration concentration_penalty raw_score".split())
_DIRECT_COMPANY_KEYS = set("instrument_id symbol exchange name_zh direct_event_count latest_mentioned_at".split())
_SUPPLY_COMPANY_KEYS = set("instrument_id symbol exchange name_zh direct_event_count official_evidence_count company_rank_score latest_mentioned_at latest_official_at".split())
_REPRESENTATIVE_KEYS = set("cluster_id id title_zh summary source_id source published_at canonical_url".split())


def _as_decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{label} must be numeric")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    result = Decimal(str(value)) if not isinstance(value, Decimal) else value
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


def _count(value: Any, label: str) -> int:
    number = _as_decimal(value, label)
    if number < 0 or number != number.to_integral_value():
        raise ValueError(f"{label} must be a non-negative integer")
    return int(number)


def _round_three(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def _clamp(value: Decimal, minimum: Decimal, maximum: Decimal) -> Decimal:
    return min(max(value, minimum), maximum)


def _heat_values(counts: Mapping[str, int | float]) -> tuple[Decimal, int, dict[str, Any]]:
    event_count = _count(counts.get("event_count"), "event_count")
    source_count = _count(counts.get("source_count"), "source_count")
    candidate_count = _count(
        counts.get("tracking_candidate_count"),
        "tracking_candidate_count",
    )
    mapping_count = _count(
        counts.get("taiwan_mapping_count"),
        "taiwan_mapping_count",
    )
    direct_count = _count(
        counts.get("direct_mapping_event_count"),
        "direct_mapping_event_count",
    )
    concentration = _as_decimal(
        counts.get("single_source_concentration"),
        "single_source_concentration",
    )

    event_normalized = Decimal(100) * min(event_count, 6) / Decimal(6)
    source_normalized = Decimal(100) * min(source_count, 4) / Decimal(4)
    candidate_normalized = Decimal(100) * min(candidate_count, 4) / Decimal(4)
    mapping_normalized = Decimal(100) * (Decimal("0.60") * min(mapping_count, 3) / Decimal(3) + Decimal("0.40") * min(direct_count, 2) / Decimal(2))
    penalty = Decimal(15) * _clamp(
        (concentration - Decimal("0.60")) / Decimal("0.40"),
        Decimal(0),
        Decimal(1),
    )
    raw_score = Decimal("0.25") * event_normalized + Decimal("0.25") * source_normalized + Decimal("0.20") * candidate_normalized + Decimal("0.30") * mapping_normalized - penalty
    clamped_score = _clamp(raw_score, Decimal(0), Decimal(100))
    heat_score = int((clamped_score + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))
    heat_reason = {
        "rule_version": PUBLIC_RANKING_RULE_VERSION,
        "event_component": {
            "input": event_count,
            "normalized": _round_three(event_normalized),
            "weighted": _round_three(Decimal("0.25") * event_normalized),
        },
        "source_component": {
            "input": source_count,
            "normalized": _round_three(source_normalized),
            "weighted": _round_three(Decimal("0.25") * source_normalized),
        },
        "candidate_component": {
            "input": candidate_count,
            "normalized": _round_three(candidate_normalized),
            "weighted": _round_three(Decimal("0.20") * candidate_normalized),
        },
        "mapping_component": {
            "mapping_count": mapping_count,
            "direct_mapping_event_count": direct_count,
            "normalized": _round_three(mapping_normalized),
            "weighted": _round_three(Decimal("0.30") * mapping_normalized),
        },
        "single_source_concentration": _round_three(concentration),
        "concentration_penalty": _round_three(penalty),
        "raw_score": _round_three(raw_score),
    }
    return raw_score, heat_score, heat_reason


def calculate_public_theme_heat(counts: Mapping[str, int | float]) -> dict[str, Any]:
    """Return exact v0.8 heat arithmetic and its public reason breakdown."""

    raw_score, heat_score, heat_reason = _heat_values(counts)
    return {
        "heat_score": heat_score,
        "raw_score": float(raw_score),
        "heat_reason": heat_reason,
    }


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} must be a valid timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _optional_timestamp(value: Any) -> tuple[datetime, str] | None:
    try:
        return _timestamp(value, "timestamp"), str(value)
    except ValueError:
        return None


def _http_url(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
    *,
    optional: set[str] | None = None,
) -> None:
    optional_keys = optional or set()
    actual = set(value)
    missing = expected - actual
    unexpected = actual - expected - optional_keys
    if missing or unexpected:
        details = sorted(missing | unexpected)
        raise ValueError(f"{label} keys are invalid: {details}")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _instrument(
    value: Any,
    symbol_aliases: Mapping[str, Any],
) -> dict[str, str] | None:
    if isinstance(value, Mapping):
        instrument_id = str(value.get("instrument_id") or "").strip()
        symbol = str(value.get("symbol") or instrument_id.split(":")[-1]).strip()
        declared_exchange = str(value.get("exchange") or "").strip()
        declared_market = str(value.get("market_id") or "").strip()
    elif isinstance(value, str):
        instrument_id = value.strip()
        symbol = instrument_id.split(":")[-1].strip()
        declared_exchange = instrument_id.split(":", 1)[0] if ":" in instrument_id else ""
        declared_market = ""
    else:
        return None

    symbols = symbol_aliases.get("symbols")
    metadata = symbols.get(symbol) if isinstance(symbols, Mapping) else None
    if not isinstance(metadata, Mapping):
        return None
    exchange = str(metadata.get("exchange") or "").strip()
    name_zh = str(metadata.get("name_zh") or "").strip()
    if exchange not in TAIWAN_EXCHANGES or not name_zh:
        return None
    canonical_id = f"{exchange}:{symbol}"
    if instrument_id and ":" in instrument_id and instrument_id != canonical_id:
        return None
    if declared_exchange and declared_exchange != exchange:
        return None
    if declared_market and declared_market != MARKET_ID:
        return None
    return {
        "instrument_id": canonical_id,
        "symbol": symbol,
        "exchange": exchange,
        "name_zh": name_zh,
    }


def _publishers(event: Mapping[str, Any]) -> set[str]:
    if "cluster_sources" not in event:
        source_id = str(event.get("source_id") or "").strip()
        return {source_id} if source_id else set()
    cluster_sources = event.get("cluster_sources")
    if not isinstance(cluster_sources, list):
        return set()
    return {str(source.get("source_id") or "").strip() for source in cluster_sources if isinstance(source, Mapping) and str(source.get("source_id") or "").strip()}


def _direct_stats(
    events: list[Mapping[str, Any]],
    members_by_id: Mapping[str, Any],
    symbol_aliases: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], set[str], int]:
    stats: dict[str, dict[str, Any]] = {}
    direct_cluster_ids: set[str] = set()
    errors = 0
    for event in events:
        cluster_id = str(event["cluster_id"])
        members = members_by_id.get(cluster_id)
        if not isinstance(members, list):
            continue
        seen_in_cluster: set[str] = set()
        for member in sorted(members, key=_canonical):
            if not isinstance(member, Mapping):
                errors += 1
                continue
            mentioned_at = _optional_timestamp(member.get("published_at"))
            direct_symbols = member.get("direct_symbols", [])
            if not isinstance(direct_symbols, list):
                errors += 1
                continue
            if direct_symbols and mentioned_at is None:
                errors += 1
                continue
            for value in direct_symbols:
                company = _instrument(value, symbol_aliases)
                if company is None:
                    errors += 1
                    continue
                instrument_id = company["instrument_id"]
                seen_in_cluster.add(instrument_id)
                current = stats.setdefault(
                    instrument_id,
                    {"company": company, "clusters": set(), "latest": None},
                )
                if mentioned_at is not None and (current["latest"] is None or mentioned_at > current["latest"]):
                    current["latest"] = mentioned_at
        if seen_in_cluster:
            direct_cluster_ids.add(cluster_id)
        for instrument_id in seen_in_cluster:
            stats[instrument_id]["clusters"].add(cluster_id)
    return stats, direct_cluster_ids, errors


def _direct_companies(stats: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    companies = []
    for instrument_id in sorted(stats):
        item = stats[instrument_id]
        latest = item["latest"]
        companies.append(
            {
                **item["company"],
                "direct_event_count": len(item["clusters"]),
                "latest_mentioned_at": latest[1] if latest is not None else None,
            }
        )
    return sorted(
        companies,
        key=lambda company: (
            -company["direct_event_count"],
            -_timestamp(company["latest_mentioned_at"], "latest_mentioned_at").timestamp() if company["latest_mentioned_at"] else float("inf"),
            company["instrument_id"],
        ),
    )


def _candidate_pairs(candidate_clusters: list[Any]) -> set[tuple[str, str]]:
    pairs = set()
    for candidate in candidate_clusters:
        if not isinstance(candidate, Mapping):
            continue
        theme_id = str(candidate.get("primary_theme_id") or "").strip()
        cluster_id = str(candidate.get("cluster_id") or "").strip()
        if theme_id and cluster_id:
            pairs.add((theme_id, cluster_id))
    return pairs


def _representative(
    theme_id: str,
    events: list[Mapping[str, Any]],
    candidates: set[tuple[str, str]],
) -> dict[str, Any] | None:
    ranked: list[tuple[tuple[Any, ...], Mapping[str, Any]]] = []
    for event in events:
        cluster_id = str(event.get("cluster_id") or "").strip()
        required_strings = ("id", "title_zh", "source_id", "source", "published_at")
        if not cluster_id or any(not isinstance(event.get(field), str) or not str(event[field]).strip() for field in required_strings):
            continue
        if not isinstance(event.get("summary"), str) or not _http_url(event.get("url")):
            continue
        published_at = _optional_timestamp(event.get("published_at"))
        try:
            theme_score = _as_decimal(event.get("theme_score"), "theme_score")
        except ValueError:
            continue
        if published_at is None:
            continue
        url = str(event["url"])
        ranked.append(
            (
                (
                    -int((theme_id, cluster_id) in candidates),
                    -len(_publishers(event)),
                    -theme_score,
                    -Decimal(str(published_at[0].timestamp())),
                    cluster_id,
                    url,
                ),
                event,
            )
        )
    if not ranked:
        return None
    chosen = min(ranked, key=lambda item: item[0])[1]
    return {
        "cluster_id": chosen["cluster_id"],
        "id": chosen["id"],
        "title_zh": chosen["title_zh"],
        "summary": chosen["summary"],
        "source_id": chosen["source_id"],
        "source": chosen["source"],
        "published_at": chosen["published_at"],
        "canonical_url": chosen["url"],
    }


def _has_seed_evidence(
    theme_id: str,
    company: Mapping[str, str],
    events: list[Mapping[str, Any]],
    symbol_aliases: Mapping[str, Any],
) -> bool:
    expected = f"taxonomy seed: {theme_id}"
    for record in events:
        related = record.get("related_symbols")
        if not isinstance(related, list):
            continue
        for value in related:
            if not isinstance(value, Mapping) or value.get("evidence") != expected:
                continue
            resolved = _instrument(value, symbol_aliases)
            if resolved and resolved["instrument_id"] == company["instrument_id"]:
                return True
    return False


def _official_ids(
    theme_id: str,
    events: list[Mapping[str, Any]],
    candidate_clusters: list[Any],
) -> set[str]:
    qualifying_ids = {str(event["cluster_id"]) for event in events}
    records: list[Mapping[str, Any]] = list(events)
    records.extend(
        candidate
        for candidate in candidate_clusters
        if isinstance(candidate, Mapping) and str(candidate.get("primary_theme_id") or "") == theme_id and str(candidate.get("cluster_id") or "") in qualifying_ids
    )
    return {
        str(evidence_id).strip()
        for record in records
        for evidence_id in (record.get("official_evidence_ids") if isinstance(record.get("official_evidence_ids"), list) else [])
        if str(evidence_id).strip()
    }


def _official_matches(
    company: Mapping[str, str],
    evidence_ids: set[str],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    symbol_aliases: Mapping[str, Any],
) -> tuple[int, tuple[datetime, str] | None]:
    matches = []
    for evidence_id in sorted(evidence_ids):
        row = evidence_by_id.get(evidence_id)
        if not isinstance(row, Mapping):
            continue
        if str(row.get("evidence_id") or "") != evidence_id:
            continue
        resolved = _instrument(row, symbol_aliases)
        if resolved is None or resolved["instrument_id"] != company["instrument_id"]:
            continue
        latest = max(
            (timestamp for field in ("published_at", "effective_at", "fetched_at") if (timestamp := _optional_timestamp(row.get(field))) is not None),
            default=None,
        )
        matches.append((evidence_id, latest))
    valid_times = [latest for _, latest in matches if latest is not None]
    return len(matches), max(valid_times) if valid_times else None


def _supply_chain_companies(
    theme: Mapping[str, Any],
    events: list[Mapping[str, Any]],
    direct_stats: Mapping[str, Mapping[str, Any]],
    candidate_clusters: list[Any],
    symbol_aliases: Mapping[str, Any],
    official_evidence_by_id: Mapping[str, Mapping[str, Any]],
    official_available: bool,
) -> tuple[list[dict[str, Any]], int]:
    theme_id = str(theme["theme_id"])
    attached_ids = _official_ids(theme_id, events, candidate_clusters) if official_available else set()
    candidates = []
    seen: set[str] = set()
    seeds = theme.get("seed_symbols")
    if not isinstance(seeds, list):
        return [], 1
    errors = 0
    for seed in seeds:
        company = _instrument(seed, symbol_aliases)
        if company is None:
            errors += 1
            continue
        if company["instrument_id"] in seen:
            continue
        seen.add(company["instrument_id"])
        if not _has_seed_evidence(
            theme_id,
            company,
            events,
            symbol_aliases,
        ):
            continue
        direct = direct_stats.get(company["instrument_id"])
        direct_count = len(direct["clusters"]) if direct else 0
        latest_direct = direct["latest"] if direct else None
        official_count, latest_official = _official_matches(
            company,
            attached_ids,
            official_evidence_by_id,
            symbol_aliases,
        )
        score = 4 * min(direct_count, 3) + 3 * min(official_count, 2) + 1
        projected = {
            **company,
            "direct_event_count": direct_count,
            "official_evidence_count": official_count,
            "company_rank_score": score,
            "latest_mentioned_at": latest_direct[1] if latest_direct else None,
            "latest_official_at": latest_official[1] if latest_official else None,
        }
        if official_count:
            projected["official_marker"] = OFFICIAL_MARKER
        candidates.append(projected)
    ranked = sorted(
        candidates,
        key=lambda company: (
            -company["company_rank_score"],
            -company["direct_event_count"],
            -company["official_evidence_count"],
            _descending_time_key(company["latest_mentioned_at"]),
            _descending_time_key(company["latest_official_at"]),
            company["instrument_id"],
        ),
    )[:3]
    return ranked, errors


def _descending_time_key(value: Any) -> tuple[int, float, str]:
    parsed = _optional_timestamp(value)
    if parsed is None:
        return (1, 0.0, "")
    return (0, -parsed[0].timestamp(), parsed[1])


def _theme_definitions(taxonomy: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    if taxonomy.get("market_id") != MARKET_ID or taxonomy.get("market_scope") != MARKET_SCOPE:
        raise ValueError("taxonomy must be TW_EQUITY only")
    themes = taxonomy.get("themes")
    if not isinstance(themes, list):
        raise ValueError("taxonomy.themes must be an array")
    result: dict[str, Mapping[str, Any]] = {}
    for theme in themes:
        if not isinstance(theme, Mapping):
            continue
        theme_id = str(theme.get("theme_id") or "").strip()
        name_zh = str(theme.get("name_zh") or "").strip()
        if theme_id and name_zh and theme_id not in result:
            result[theme_id] = theme
    return result


def _cluster_groups(
    clustered_events: list[Any],
    members_by_id: Mapping[str, Any],
    themes: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, list[Mapping[str, Any]]], set[str], set[str], int]:
    by_cluster: dict[str, list[Mapping[str, Any]]] = {}
    observed: set[str] = set()
    invalid_themes: set[str] = set()
    errors = 0
    for value in clustered_events:
        if not isinstance(value, Mapping):
            errors += 1
            continue
        theme_id = str(value.get("primary_theme_id") or "").strip()
        cluster_id = str(value.get("cluster_id") or "").strip()
        if theme_id:
            observed.add(theme_id)
        if not theme_id or not cluster_id:
            if theme_id in themes:
                invalid_themes.add(theme_id)
            errors += 1
            continue
        by_cluster.setdefault(cluster_id, []).append(value)

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for cluster_id in sorted(by_cluster):
        values = by_cluster[cluster_id]
        if len(values) != 1:
            invalid_themes.update(str(value.get("primary_theme_id") or "") for value in values if str(value.get("primary_theme_id") or "") in themes)
            errors += len(values)
            continue
        event = values[0]
        theme_id = str(event["primary_theme_id"])
        members = members_by_id.get(cluster_id)
        if theme_id not in themes:
            continue
        if _optional_timestamp(event.get("published_at")) is None:
            invalid_themes.add(theme_id)
            errors += 1
            continue
        if not isinstance(members, list) or not members:
            invalid_themes.add(theme_id)
            errors += 1
            continue
        grouped.setdefault(theme_id, []).append(event)
    for events in grouped.values():
        events.sort(key=lambda event: str(event["cluster_id"]))
    return grouped, observed, invalid_themes, errors


def _derive_theme(
    theme: Mapping[str, Any],
    events: list[Mapping[str, Any]],
    *,
    candidates: set[tuple[str, str]],
    candidate_clusters: list[Any],
    members_by_id: Mapping[str, Any],
    symbol_aliases: Mapping[str, Any],
    official_evidence_by_id: Mapping[str, Mapping[str, Any]],
    official_available: bool,
) -> tuple[dict[str, Any] | None, list[str], int]:
    theme_id = str(theme["theme_id"])
    publisher_event_count: dict[str, int] = {}
    mappings: set[str] = set()
    errors = 0
    for event in events:
        for publisher in _publishers(event):
            publisher_event_count[publisher] = publisher_event_count.get(publisher, 0) + 1
        values = event.get("tw_related_symbols")
        if not isinstance(values, list):
            errors += 1
            values = []
        for value in values:
            company = _instrument(value, symbol_aliases)
            if company:
                mappings.add(company["instrument_id"])
            else:
                errors += 1

    direct_stats, direct_cluster_ids, direct_errors = _direct_stats(
        events,
        members_by_id,
        symbol_aliases,
    )
    errors += direct_errors
    cluster_ids = {str(event["cluster_id"]) for event in events}
    candidate_count = len({cluster_id for candidate_theme, cluster_id in candidates if candidate_theme == theme_id and cluster_id in cluster_ids})
    counts = {
        "event_count": len(cluster_ids),
        "source_count": len(publisher_event_count),
        "tracking_candidate_count": candidate_count,
        "taiwan_mapping_count": len(mappings),
        "direct_mapping_event_count": len(direct_cluster_ids),
        "single_source_concentration": (Decimal(max(publisher_event_count.values())) / Decimal(sum(publisher_event_count.values())) if publisher_event_count else Decimal(0)),
    }
    failures = []
    if counts["event_count"] < 2:
        failures.append("events_lt_2")
    if counts["source_count"] < 2:
        failures.append("publishers_lt_2")
    if counts["taiwan_mapping_count"] < 1:
        failures.append("mapping_lt_1")
    if failures:
        return None, failures, errors

    representative = _representative(theme_id, events, candidates)
    if representative is None:
        return None, ["representative_missing"], errors + 1
    raw_score, heat_score, heat_reason = _heat_values(counts)
    newest = max(_timestamp(event["published_at"], "published_at") for event in events)
    direct_mentions = _direct_companies(direct_stats)
    supply_chain, supply_errors = _supply_chain_companies(
        theme,
        events,
        direct_stats,
        candidate_clusters,
        symbol_aliases,
        official_evidence_by_id,
        official_available,
    )
    errors += supply_errors
    projected = {
        "theme_id": theme_id,
        "name_zh": str(theme["name_zh"]),
        "heat_score": heat_score,
        "summaries": {
            "event_count": counts["event_count"],
            "source_count": counts["source_count"],
            "tracking_candidate_count": counts["tracking_candidate_count"],
            "taiwan_mapping_count": counts["taiwan_mapping_count"],
        },
        "heat_reason": heat_reason,
        "direct_mentions": direct_mentions,
        "supply_chain_candidates": supply_chain,
        "representative_news": representative,
        "_sort": {
            "raw_score": raw_score,
            "direct_mapping_event_count": counts["direct_mapping_event_count"],
            "newest": newest,
        },
    }
    return projected, [], errors


def build_public_theme_ranking(
    projection: Mapping[str, Any],
    *,
    taxonomy: Mapping[str, Any],
    symbol_aliases: Mapping[str, Any],
    official_evidence_by_id: Mapping[str, Mapping[str, Any]],
    source_status: Mapping[str, Any],
    generated_at: datetime,
    window_hours: int,
    official_evidence_status: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the public ranking and updater-only diagnostics without mutations."""

    _exact_keys(projection, _PROJECTION_KEYS, "projection")
    if projection.get("market_id") != MARKET_ID or projection.get("market_scope") != MARKET_SCOPE:
        raise ValueError("projection must be TW_EQUITY only")
    if window_hours != PUBLIC_WINDOW_HOURS:
        raise ValueError(f"window_hours must be {PUBLIC_WINDOW_HOURS}")
    if generated_at.tzinfo is None:
        raise ValueError("generated_at must include a timezone")
    if official_evidence_status not in {"available", "unavailable"}:
        raise ValueError("official_evidence_status must be available or unavailable")
    if symbol_aliases.get("market_id") != MARKET_ID or symbol_aliases.get("market_scope") != MARKET_SCOPE:
        raise ValueError("symbol_aliases must be TW_EQUITY only")
    failed_source_count = _count(source_status.get("failed_count"), "failed_count")

    clustered_events = projection.get("clustered_events")
    candidate_clusters = projection.get("candidate_clusters")
    members_by_id = projection.get("cluster_members_by_id")
    retained_records = projection.get("retained_records")
    if not isinstance(clustered_events, list) or not isinstance(candidate_clusters, list):
        raise ValueError("projection event collections must be arrays")
    if not isinstance(members_by_id, Mapping) or not isinstance(retained_records, list):
        raise ValueError("projection member collections are invalid")

    themes = _theme_definitions(taxonomy)
    grouped, observed, invalid_themes, derivation_errors = _cluster_groups(
        clustered_events,
        members_by_id,
        themes,
    )
    candidate_pairs = _candidate_pairs(candidate_clusters)
    failures: set[tuple[str, str]] = {(theme_id, "unknown_theme") for theme_id in observed if theme_id not in themes}
    eligible = []
    for theme_id in sorted(observed & set(themes)):
        projected, theme_failures, errors = _derive_theme(
            themes[theme_id],
            grouped.get(theme_id, []),
            candidates=candidate_pairs,
            candidate_clusters=candidate_clusters,
            members_by_id=members_by_id,
            symbol_aliases=symbol_aliases,
            official_evidence_by_id=official_evidence_by_id,
            official_available=official_evidence_status == "available",
        )
        derivation_errors += errors
        failures.update((theme_id, rule_code) for rule_code in theme_failures)
        if projected is None and theme_id in invalid_themes:
            failures.add((theme_id, "invalid_required_input"))
        if projected is not None:
            eligible.append(projected)

    eligible.sort(
        key=lambda theme: (
            -theme["heat_score"],
            -theme["_sort"]["raw_score"],
            -theme["summaries"]["event_count"],
            -theme["summaries"]["source_count"],
            -theme["summaries"]["tracking_candidate_count"],
            -theme["summaries"]["taiwan_mapping_count"],
            -Decimal(str(theme["_sort"]["newest"].timestamp())),
            theme["theme_id"],
        )
    )
    displayed = [
        {
            "rank": rank,
            **{key: value for key, value in theme.items() if key != "_sort"},
        }
        for rank, theme in enumerate(eligible[:PUBLIC_MAX_THEMES], start=1)
    ]
    generation_status = "partial" if failed_source_count else "complete"
    displayed_count = len(displayed)
    payload = {
        "schema_version": PUBLIC_SCHEMA_VERSION,
        "ranking_rule_version": PUBLIC_RANKING_RULE_VERSION,
        "company_rule_version": PUBLIC_COMPANY_RULE_VERSION,
        "generated_at": generated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "market_id": MARKET_ID,
        "market_scope": list(MARKET_SCOPE),
        "window_hours": PUBLIC_WINDOW_HOURS,
        "max_themes": PUBLIC_MAX_THEMES,
        "qualified_theme_count": len(eligible),
        "displayed_theme_count": displayed_count,
        "threshold_note": (f"目前僅 {displayed_count} 個題材達到上榜門檻" if displayed_count < PUBLIC_MAX_THEMES else None),
        "generation_status": generation_status,
        "failed_source_count": failed_source_count,
        "official_evidence_status": official_evidence_status,
        "themes": displayed,
    }
    validate_public_theme_ranking(payload)
    diagnostics = {
        "public_themes_qualified": len(eligible),
        "public_themes_displayed": displayed_count,
        "public_themes_omitted_invalid": len({theme_id for theme_id, _ in failures}),
        "public_direct_company_count": sum(len(theme["direct_mentions"]) for theme in displayed),
        "public_supply_chain_company_count": sum(len(theme["supply_chain_candidates"]) for theme in displayed),
        "public_derivation_error_count": derivation_errors,
        "public_generation_status": generation_status,
        "eligibility_failures": [{"theme_id": theme_id, "rule_code": rule_code} for theme_id, rule_code in sorted(failures)],
    }
    return payload, diagnostics


def _validate_company_identity(company: Mapping[str, Any], label: str) -> None:
    symbol = company.get("symbol")
    exchange = company.get("exchange")
    if not isinstance(symbol, str) or not symbol:
        raise ValueError(f"{label}.symbol must be non-empty")
    if exchange not in TAIWAN_EXCHANGES:
        raise ValueError(f"{label}.exchange must be TWSE or TPEX")
    if company.get("instrument_id") != f"{exchange}:{symbol}":
        raise ValueError(f"{label}.instrument_id is invalid")
    if not isinstance(company.get("name_zh"), str) or not company["name_zh"].strip():
        raise ValueError(f"{label}.name_zh must be non-empty")


def _validate_direct_companies(companies: Any) -> None:
    if not isinstance(companies, list):
        raise ValueError("direct_mentions must be an array")
    seen = set()
    for index, company in enumerate(companies):
        if not isinstance(company, Mapping):
            raise ValueError("direct_mentions entries must be objects")
        _exact_keys(company, _DIRECT_COMPANY_KEYS, f"direct_mentions[{index}]")
        _validate_company_identity(company, f"direct_mentions[{index}]")
        if company["instrument_id"] in seen:
            raise ValueError("direct_mentions instrument_id must be unique")
        seen.add(company["instrument_id"])
        if _count(company.get("direct_event_count"), "direct_event_count") < 1:
            raise ValueError("direct_event_count must be positive")
        _timestamp(company.get("latest_mentioned_at"), "latest_mentioned_at")
    expected = sorted(
        companies,
        key=lambda company: (
            -company["direct_event_count"],
            _descending_time_key(company["latest_mentioned_at"]),
            company["instrument_id"],
        ),
    )
    if companies != expected:
        raise ValueError("direct_mentions ordering is invalid")


def _validate_supply_companies(companies: Any, official_status: str) -> None:
    if not isinstance(companies, list) or len(companies) > 3:
        raise ValueError("supply_chain_candidates must contain at most three entries")
    seen = set()
    for index, company in enumerate(companies):
        if not isinstance(company, Mapping):
            raise ValueError("supply_chain_candidates entries must be objects")
        _exact_keys(
            company,
            _SUPPLY_COMPANY_KEYS,
            f"supply_chain_candidates[{index}]",
            optional={"official_marker"},
        )
        _validate_company_identity(company, f"supply_chain_candidates[{index}]")
        if company["instrument_id"] in seen:
            raise ValueError("supply_chain_candidates instrument_id must be unique")
        seen.add(company["instrument_id"])
        direct_count = _count(company.get("direct_event_count"), "direct_event_count")
        official_count = _count(
            company.get("official_evidence_count"),
            "official_evidence_count",
        )
        expected_score = 4 * min(direct_count, 3) + 3 * min(official_count, 2) + 1
        if company.get("company_rank_score") != expected_score:
            raise ValueError("company_rank_score is invalid")
        if official_status == "unavailable" and official_count:
            raise ValueError("official_evidence_count must be zero when unavailable")
        if official_count and company.get("official_marker") != OFFICIAL_MARKER:
            raise ValueError("official_marker is required")
        if not official_count and "official_marker" in company:
            raise ValueError("official_marker requires official evidence")
        for field in ("latest_mentioned_at", "latest_official_at"):
            if company.get(field) is not None:
                _timestamp(company[field], field)
    expected = sorted(
        companies,
        key=lambda company: (
            -company["company_rank_score"],
            -company["direct_event_count"],
            -company["official_evidence_count"],
            _descending_time_key(company["latest_mentioned_at"]),
            _descending_time_key(company["latest_official_at"]),
            company["instrument_id"],
        ),
    )
    if companies != expected:
        raise ValueError("supply_chain_candidates ordering is invalid")


def _validate_representative(representative: Any) -> None:
    if not isinstance(representative, Mapping):
        raise ValueError("representative_news must be an object")
    _exact_keys(representative, _REPRESENTATIVE_KEYS, "representative_news")
    for field in ("cluster_id", "id", "title_zh", "source_id", "source"):
        if not isinstance(representative.get(field), str) or not representative[field].strip():
            raise ValueError(f"representative_news.{field} must be non-empty")
    if not isinstance(representative.get("summary"), str):
        raise ValueError("representative_news.summary must be a string")
    _timestamp(representative.get("published_at"), "representative_news.published_at")
    if not _http_url(representative.get("canonical_url")):
        raise ValueError("representative_news.canonical_url must be HTTP(S)")


def _validate_heat_reason(
    reason: Mapping[str, Any],
    counts: Mapping[str, int],
    heat_score: Any,
) -> None:
    _exact_keys(reason, _HEAT_REASON_KEYS, "heat_reason")
    if reason.get("rule_version") != PUBLIC_RANKING_RULE_VERSION:
        raise ValueError("heat_reason.rule_version is invalid")
    mapping = reason.get("mapping_component")
    if not isinstance(mapping, Mapping):
        raise ValueError("mapping_component must be an object")
    direct_count = _count(
        mapping.get("direct_mapping_event_count"),
        "direct_mapping_event_count",
    )
    baseline = calculate_public_theme_heat(
        {
            **counts,
            "direct_mapping_event_count": direct_count,
            "single_source_concentration": 0,
        }
    )["heat_reason"]
    for component in ("event_component", "source_component", "candidate_component"):
        if reason.get(component) != baseline[component]:
            raise ValueError(f"{component} arithmetic is invalid")
    if mapping != baseline["mapping_component"]:
        raise ValueError("mapping_component arithmetic is invalid")

    concentration = _as_decimal(
        reason.get("single_source_concentration"),
        "single_source_concentration",
    )
    if not Decimal(0) <= concentration <= Decimal(1):
        raise ValueError("single_source_concentration must be between zero and one")
    penalty = _as_decimal(reason.get("concentration_penalty"), "concentration_penalty")
    interval = Decimal("0.0005")

    def penalty_for(value: Decimal) -> Decimal:
        return Decimal(15) * _clamp(
            (value - Decimal("0.60")) / Decimal("0.40"),
            Decimal(0),
            Decimal(1),
        )

    penalty_low = penalty_for(max(Decimal(0), concentration - interval)) - interval
    penalty_high = penalty_for(min(Decimal(1), concentration + interval)) + interval
    if not penalty_low <= penalty <= penalty_high:
        raise ValueError("concentration_penalty arithmetic is invalid")

    raw_score = _as_decimal(reason.get("raw_score"), "raw_score")
    weighted_total = (
        sum(
            _as_decimal(reason[component]["weighted"], f"{component}.weighted")
            for component in (
                "event_component",
                "source_component",
                "candidate_component",
                "mapping_component",
            )
        )
        - penalty
    )
    if abs(raw_score - weighted_total) > Decimal("0.004"):
        raise ValueError("raw_score arithmetic is invalid")
    score = _count(heat_score, "heat_score")
    possible_low = int((_clamp(raw_score - interval, Decimal(0), Decimal(100)) + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))
    possible_high = int((_clamp(raw_score + interval, Decimal(0), Decimal(100)) + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))
    if score not in range(possible_low, possible_high + 1):
        raise ValueError("heat_score is invalid")


def _validate_theme(theme: Any, expected_rank: int, official_status: str) -> str:
    if not isinstance(theme, Mapping):
        raise ValueError("themes entries must be objects")
    _exact_keys(theme, _THEME_KEYS, "theme")
    if theme.get("rank") != expected_rank:
        raise ValueError("theme.rank must be sequential")
    theme_id = theme.get("theme_id")
    if not isinstance(theme_id, str) or not theme_id:
        raise ValueError("theme_id must be non-empty")
    if not isinstance(theme.get("name_zh"), str) or not theme["name_zh"].strip():
        raise ValueError("name_zh must be non-empty")

    summaries = theme.get("summaries")
    if not isinstance(summaries, Mapping):
        raise ValueError("summaries must be an object")
    _exact_keys(summaries, _SUMMARY_KEYS, "summaries")
    counts = {key: _count(summaries.get(key), key) for key in _SUMMARY_KEYS}
    if counts["event_count"] < 2 or counts["source_count"] < 2:
        raise ValueError("theme eligibility counts are invalid")
    if counts["taiwan_mapping_count"] < 1:
        raise ValueError("theme mapping count is invalid")

    reason = theme.get("heat_reason")
    if not isinstance(reason, Mapping):
        raise ValueError("heat_reason must be an object")
    _validate_heat_reason(reason, counts, theme.get("heat_score"))

    _validate_direct_companies(theme.get("direct_mentions"))
    _validate_supply_companies(theme.get("supply_chain_candidates"), official_status)
    _validate_representative(theme.get("representative_news"))
    return theme_id


def validate_public_theme_ranking(payload: Mapping[str, Any]) -> None:
    """Validate the exact fail-closed public v0.8 payload contract."""

    if not isinstance(payload, Mapping):
        raise ValueError("payload must be an object")
    _exact_keys(payload, _TOP_LEVEL_KEYS, "payload")
    expected_scalars = {
        "schema_version": PUBLIC_SCHEMA_VERSION,
        "ranking_rule_version": PUBLIC_RANKING_RULE_VERSION,
        "company_rule_version": PUBLIC_COMPANY_RULE_VERSION,
        "market_id": MARKET_ID,
        "market_scope": MARKET_SCOPE,
        "window_hours": PUBLIC_WINDOW_HOURS,
        "max_themes": PUBLIC_MAX_THEMES,
    }
    for key, expected in expected_scalars.items():
        if payload.get(key) != expected:
            raise ValueError(f"{key} must be {expected!r}")
    _timestamp(payload.get("generated_at"), "generated_at")
    if payload.get("generation_status") not in {"complete", "partial"}:
        raise ValueError("generation_status must be complete or partial")
    official_status = payload.get("official_evidence_status")
    if official_status not in {"available", "unavailable"}:
        raise ValueError("official_evidence_status must be available or unavailable")

    failed_count = _count(payload.get("failed_source_count"), "failed_source_count")
    expected_generation = "partial" if failed_count else "complete"
    if payload.get("generation_status") != expected_generation:
        raise ValueError("generation_status is inconsistent with failed_source_count")
    qualified = _count(payload.get("qualified_theme_count"), "qualified_theme_count")
    displayed = _count(payload.get("displayed_theme_count"), "displayed_theme_count")
    themes = payload.get("themes")
    if not isinstance(themes, list):
        raise ValueError("themes must be an array")
    if qualified < displayed or displayed != len(themes) or displayed > PUBLIC_MAX_THEMES:
        raise ValueError("displayed_theme_count or qualified_theme_count is invalid")
    expected_note = f"目前僅 {displayed} 個題材達到上榜門檻" if displayed < PUBLIC_MAX_THEMES else None
    if payload.get("threshold_note") != expected_note:
        raise ValueError("threshold_note is invalid")

    theme_ids = [_validate_theme(theme, rank, str(official_status)) for rank, theme in enumerate(themes, start=1)]
    if len(theme_ids) != len(set(theme_ids)):
        raise ValueError("theme_id values must be unique")
