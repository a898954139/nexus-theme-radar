"""Deterministic Taiwan-equity theme relevance scoring for the MVP."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    from scripts.symbol_mapping import (
        extract_direct_symbols,
        instrument_for_symbol,
        load_symbol_aliases,
    )
except ModuleNotFoundError:
    from symbol_mapping import (
        extract_direct_symbols,
        instrument_for_symbol,
        load_symbol_aliases,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAXONOMY_PATH = ROOT / "config" / "theme_taxonomy.tw.json"
TEXT_FIELD_WEIGHTS = {
    "title": 3.0,
    "title_zh": 3.0,
    "summary": 1.5,
    "content": 1.0,
}
SCORE_DENOMINATOR = 9.0


def load_theme_taxonomy(path: str | Path = DEFAULT_TAXONOMY_PATH) -> dict[str, Any]:
    """Load and validate the minimal taxonomy contract used by the scorer."""

    taxonomy_path = Path(path)
    payload = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    themes = payload.get("themes")
    if not isinstance(themes, list) or not themes:
        raise ValueError("theme taxonomy must contain a non-empty themes array")

    required_fields = {
        "theme_id",
        "name_zh",
        "keywords",
        "related_industries",
        "seed_symbols",
    }
    seen_ids: set[str] = set()
    for theme in themes:
        if not isinstance(theme, dict) or not required_fields.issubset(theme):
            raise ValueError("each theme must contain all required fields")
        theme_id = theme["theme_id"]
        if not isinstance(theme_id, str) or not theme_id or theme_id in seen_ids:
            raise ValueError("theme_id values must be non-empty and unique")
        seen_ids.add(theme_id)
        for field in ("keywords", "related_industries", "seed_symbols"):
            if not isinstance(theme[field], list) or not theme[field]:
                raise ValueError(f"{theme_id}.{field} must be a non-empty array")
    return payload


def _contains_keyword(text: str, keyword: str) -> bool:
    normalized_text = text.casefold()
    normalized_keyword = keyword.casefold().strip()
    if not normalized_keyword:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9 .+/_-]*", normalized_keyword):
        pattern = rf"(?<![a-z0-9]){re.escape(normalized_keyword)}(?![a-z0-9])"
        return re.search(pattern, normalized_text) is not None
    return normalized_keyword in normalized_text


def _score_theme(item: dict[str, Any], theme: dict[str, Any]) -> dict[str, Any] | None:
    field_text = {
        field: str(item.get(field) or "")
        for field in TEXT_FIELD_WEIGHTS
    }
    signal_fields: dict[str, list[str]] = {}
    total_weight = 0.0

    for keyword_value in theme["keywords"]:
        keyword = str(keyword_value).strip()
        matched_fields = [
            field
            for field, text in field_text.items()
            if text and _contains_keyword(text, keyword)
        ]
        if not matched_fields:
            continue
        signal_fields[keyword.casefold()] = matched_fields
        total_weight += max(TEXT_FIELD_WEIGHTS[field] for field in matched_fields)

    if not signal_fields:
        return None

    signals = sorted(signal_fields)
    field_reasons = [
        f"{field}: {', '.join(signal for signal in signals if field in signal_fields[signal])}"
        for field in TEXT_FIELD_WEIGHTS
        if any(field in signal_fields[signal] for signal in signals)
    ]
    return {
        "theme_id": theme["theme_id"],
        "name_zh": theme["name_zh"],
        "score": round(min(1.0, total_weight / SCORE_DENOMINATOR), 3),
        "signals": signals,
        "reason": "; ".join(field_reasons),
    }


def score_theme_relevance(
    item: dict[str, Any],
    taxonomy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score one item and return an auditable, deterministic theme result."""

    active_taxonomy = taxonomy or load_theme_taxonomy()
    matches = [
        match
        for theme in active_taxonomy["themes"]
        if (match := _score_theme(item, theme)) is not None
    ]
    matches.sort(key=lambda match: (-match["score"], match["theme_id"]))
    if not matches:
        return {
            "matched_themes": [],
            "primary_theme_id": None,
            "theme_score": 0.0,
        }
    return {
        "matched_themes": matches,
        "primary_theme_id": matches[0]["theme_id"],
        "theme_score": matches[0]["score"],
    }


def _decision_for(matched_themes: list[dict[str, Any]], related_symbols: list[dict[str, Any]]) -> str:
    if not matched_themes:
        return "skip_noise"
    if not related_symbols:
        return "quarantined"
    return "track_watch"


def enrich_item_with_themes(
    item: dict[str, Any],
    taxonomy: dict[str, Any] | None = None,
    symbol_aliases: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a new item with theme fields and deduplicated related symbols."""

    active_taxonomy = taxonomy or load_theme_taxonomy()
    active_aliases = symbol_aliases if symbol_aliases is not None else load_symbol_aliases()
    result = score_theme_relevance(item, active_taxonomy)
    direct_symbols = extract_direct_symbols(item, active_aliases)
    themes_by_id = {
        theme["theme_id"]: theme
        for theme in active_taxonomy["themes"]
    }
    related_symbols = list(
        {
            instrument["instrument_id"]: instrument
            for instrument in [
                *(
                    instrument_for_symbol(
                        direct["symbol"],
                        active_aliases,
                        evidence=direct["evidence"],
                        reason=direct["reason"],
                    )
                    for direct in direct_symbols
                ),
                *(
                    instrument_for_symbol(
                        symbol,
                        active_aliases,
                        evidence=f"taxonomy seed: {match['theme_id']}",
                        reason="theme seed symbol",
                    )
                    for match in result["matched_themes"]
                    for symbol in themes_by_id[match["theme_id"]]["seed_symbols"]
                ),
            ]
        }.values()
    )
    return {
        **item,
        **result,
        "direct_symbols": direct_symbols,
        "symbol_evidence": {
            direct["symbol"]: direct["evidence"]
            for direct in direct_symbols
        },
        "related_symbols": related_symbols,
        "related_symbol_codes": [instrument["symbol"] for instrument in related_symbols],
        "decision": _decision_for(result["matched_themes"], related_symbols),
    }
