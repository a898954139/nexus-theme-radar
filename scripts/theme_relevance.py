"""Deterministic Taiwan-equity theme relevance scoring MVP."""

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
except ModuleNotFoundError:  # pragma: no cover - fallback execution
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

MATCHER_MODE_LEGACY = "legacy"
MATCHER_MODE_STRUCTURED = "structured"
SUPPLY_CHAIN_STAGES = {"上游", "中游", "下游"}

REQUIRED_LEGACY_FIELDS = {
    "theme_id",
    "name_zh",
    "keywords",
    "related_industries",
    "seed_symbols",
}

REQUIRED_STRUCTURED_FIELDS = {
    "theme_id",
    "name_zh",
    "required_any",
    "optional",
    "excluded",
    "related_industries",
    "seed_symbols",
}


def _validate_phrase_list(values: Any, label: str, *, allow_empty: bool) -> None:
    if not isinstance(values, list):
        raise ValueError(f"{label} must be an array")
    if not allow_empty and not values:
        raise ValueError(f"{label} must be non-empty array")
    if not all(isinstance(value, str) for value in values):
        raise ValueError(f"{label} must contain only strings")
    if not all(str(value).strip() for value in values):
        raise ValueError(f"{label} must contain only non-empty strings")


def _validate_supply_chain(theme: dict[str, Any], theme_id: str) -> None:
    supply_chain = theme.get("supply_chain")
    if supply_chain is None:
        return
    if not isinstance(supply_chain, list) or not supply_chain:
        raise ValueError(f"{theme_id}.supply_chain must be a non-empty array")

    industries: list[str] = []
    symbols: list[str] = []
    for index, segment in enumerate(supply_chain):
        label = f"{theme_id}.supply_chain[{index}]"
        if not isinstance(segment, dict):
            raise ValueError(f"{label} must be a JSON object")

        stage = segment.get("stage")
        industry = segment.get("industry")
        if not isinstance(stage, str) or stage not in SUPPLY_CHAIN_STAGES:
            raise ValueError(f"{label}.stage must be 上游, 中游, or 下游")
        if not isinstance(industry, str) or not industry.strip():
            raise ValueError(f"{label}.industry must be a non-empty string")
        _validate_phrase_list(segment.get("symbols"), f"{label}.symbols", allow_empty=False)

        industries.append(industry)
        symbols.extend(segment["symbols"])

    if len(set(industries)) != len(industries):
        raise ValueError(f"{theme_id}.supply_chain industries must be unique")
    if len(set(symbols)) != len(symbols):
        raise ValueError(f"{theme_id}.supply_chain symbols must be unique")
    if industries != theme["related_industries"]:
        raise ValueError(f"{theme_id}.supply_chain industries must match related_industries")
    if symbols != theme["seed_symbols"]:
        raise ValueError(f"{theme_id}.supply_chain symbols must match seed_symbols")


def _theme_schema_mode(theme: dict[str, Any]) -> str:
    has_legacy = "keywords" in theme
    has_structured = any(field in theme for field in ("required_any", "optional", "excluded"))

    if has_legacy and has_structured:
        raise ValueError("theme cannot mix legacy and structured schema fields")
    if not has_legacy and not has_structured:
        raise ValueError("theme schema mode cannot be inferred")
    if has_legacy:
        return MATCHER_MODE_LEGACY
    return MATCHER_MODE_STRUCTURED


def load_theme_taxonomy(path: str | Path = DEFAULT_TAXONOMY_PATH) -> dict[str, Any]:
    """Load minimal taxonomy contract used by scorer."""

    taxonomy_path = Path(path)
    payload = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    themes = payload.get("themes")
    if not isinstance(themes, list) or not themes:
        raise ValueError("theme taxonomy must contain non-empty themes array")

    normalized_themes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for theme in themes:
        if not isinstance(theme, dict):
            raise ValueError("each theme must be JSON object")

        derived_mode = _theme_schema_mode(theme)
        mode = theme.get("matcher_mode", derived_mode)
        if mode != derived_mode:
            raise ValueError("theme.matcher_mode must match derived schema mode theme fields")
        if mode not in {MATCHER_MODE_LEGACY, MATCHER_MODE_STRUCTURED}:
            raise ValueError("theme.matcher_mode must be legacy or structured")

        required_fields = REQUIRED_LEGACY_FIELDS if mode == MATCHER_MODE_LEGACY else REQUIRED_STRUCTURED_FIELDS
        missing = sorted(required_fields.difference(theme.keys()))
        if missing:
            raise ValueError(
                f"each theme must contain all required fields: {', '.join(missing)}"
            )

        theme_id = theme["theme_id"]
        if not isinstance(theme_id, str) or not theme_id.strip():
            raise ValueError("theme_id must be non-empty string")
        if theme_id in seen_ids:
            raise ValueError("theme_id values must be non-empty unique")
        seen_ids.add(theme_id)

        if mode == MATCHER_MODE_LEGACY:
            _validate_phrase_list(theme["keywords"], f"{theme_id}.keywords", allow_empty=False)
            _validate_phrase_list(
                theme["related_industries"], f"{theme_id}.related_industries", allow_empty=False
            )
            _validate_phrase_list(
                theme["seed_symbols"], f"{theme_id}.seed_symbols", allow_empty=False
            )
        else:
            _validate_phrase_list(
                theme["required_any"], f"{theme_id}.required_any", allow_empty=False
            )
            _validate_phrase_list(
                theme["optional"], f"{theme_id}.optional", allow_empty=True
            )
            _validate_phrase_list(
                theme["excluded"], f"{theme_id}.excluded", allow_empty=True
            )
            _validate_phrase_list(
                theme["related_industries"], f"{theme_id}.related_industries", allow_empty=False
            )
            _validate_phrase_list(
                theme["seed_symbols"], f"{theme_id}.seed_symbols", allow_empty=False
            )

        _validate_supply_chain(theme, theme_id)

        normalized_theme = dict(theme)
        normalized_theme["matcher_mode"] = mode
        normalized_themes.append(normalized_theme)

    normalized = dict(payload)
    normalized["themes"] = normalized_themes
    return normalized


def _contains_keyword(text: str, keyword: str) -> bool:
    normalized_text = text.casefold()
    normalized_keyword = keyword.casefold().strip()
    if not normalized_keyword:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9 .+/_-]*", normalized_keyword):
        pattern = rf"(?<![a-z0-9]){re.escape(normalized_keyword)}(?![a-z0-9])"
        return re.search(pattern, normalized_text) is not None
    return normalized_keyword in normalized_text


def _collect_phrase_matches(text_fields: dict[str, str], phrases: tuple[str, ...]) -> dict[str, list[str]]:
    matches: dict[str, list[str]] = {}
    for phrase_value in phrases:
        phrase = str(phrase_value).strip()
        if not phrase:
            continue

        canonical = phrase.casefold()
        fields: list[str] = [
            field for field, text in text_fields.items() if _contains_keyword(text, phrase)
        ]
        if fields:
            matches[canonical] = fields

    return matches


def _build_match_result(theme: dict[str, Any], signal_fields: dict[str, list[str]]) -> dict[str, Any]:
    if not signal_fields:
        raise ValueError("no matched phrases")

    total_weight = 0.0
    for phrase_fields in signal_fields.values():
        field_weight = max(TEXT_FIELD_WEIGHTS[field] for field in phrase_fields)
        total_weight += field_weight

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


def _score_legacy_theme(
    field_text: dict[str, str],
    theme: dict[str, Any],
) -> tuple[dict[str, Any] | None, bool]:
    signal_fields = _collect_phrase_matches(field_text, tuple(theme["keywords"]))
    if not signal_fields:
        return None, False
    return _build_match_result(theme, signal_fields), False


def _score_structured_theme(
    field_text: dict[str, str],
    theme: dict[str, Any],
) -> tuple[dict[str, Any] | None, bool]:
    required = _collect_phrase_matches(field_text, tuple(theme["required_any"]))
    optional = _collect_phrase_matches(field_text, tuple(theme["optional"]))
    excluded = _collect_phrase_matches(field_text, tuple(theme["excluded"]))

    has_required = bool(required)
    has_optional = bool(optional)

    if excluded and (has_required or has_optional):
        return None, True
    if not has_required:
        return None, bool(excluded)

    signal_fields = {**required, **optional}
    return _build_match_result(theme, signal_fields), False


def _score_theme(item: dict[str, Any], theme: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
    field_text = {
        field: str(item.get(field) or "") for field in TEXT_FIELD_WEIGHTS
    }

    derived_mode = _theme_schema_mode(theme)
    mode = theme.get("matcher_mode", derived_mode)
    if mode != derived_mode:
        raise ValueError("theme.matcher_mode must match derived schema mode theme fields")

    if mode == MATCHER_MODE_STRUCTURED:
        return _score_structured_theme(field_text, theme)
    if mode == MATCHER_MODE_LEGACY:
        return _score_legacy_theme(field_text, theme)

    raise ValueError(f"unsupported matcher mode: {mode}")


def score_theme_relevance(
    item: dict[str, Any],
    taxonomy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score one item with an auditable, deterministic theme result."""

    active_taxonomy = taxonomy or load_theme_taxonomy()
    matches: list[dict[str, Any]] = []
    vetoed_theme_ids: list[str] = []

    for theme in active_taxonomy["themes"]:
        match, is_vetoed = _score_theme(item, theme)
        if is_vetoed:
            vetoed_theme_ids.append(str(theme["theme_id"]))
        if match is not None:
            matches.append(match)

    matches.sort(key=lambda match: (-match["score"], match["theme_id"]))

    if not matches:
        result = {
            "matched_themes": [],
            "primary_theme_id": None,
            "theme_score": 0.0,
        }
        if vetoed_theme_ids:
            result["vetoed_theme_ids"] = sorted(set(vetoed_theme_ids))
        return result

    result = {
        "matched_themes": matches,
        "primary_theme_id": matches[0]["theme_id"],
        "theme_score": matches[0]["score"],
    }
    if vetoed_theme_ids:
        result["vetoed_theme_ids"] = sorted(set(vetoed_theme_ids))
    return result


def _decision_for(
    matched_themes: list[dict[str, Any]], related_symbols: list[dict[str, Any]]
) -> str:
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
    result = dict(score_theme_relevance(item, active_taxonomy))
    result.pop("vetoed_theme_ids", None)
    direct_symbols = extract_direct_symbols(item, active_aliases)
    themes_by_id = {theme["theme_id"]: theme for theme in active_taxonomy["themes"]}

    related_instruments = [
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

    related_symbols = list({instrument["instrument_id"]: instrument for instrument in related_instruments}.values())

    return {
        **item,
        **result,
        "direct_symbols": direct_symbols,
        "symbol_evidence": {direct["symbol"]: direct["evidence"] for direct in direct_symbols},
        "related_symbols": related_symbols,
        "related_symbol_codes": [instrument["symbol"] for instrument in related_symbols],
        "decision": _decision_for(result["matched_themes"], related_symbols),
    }
