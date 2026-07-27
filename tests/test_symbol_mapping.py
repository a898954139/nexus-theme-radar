from __future__ import annotations

from pathlib import Path

from scripts.symbol_mapping import extract_direct_symbols, load_symbol_aliases
from scripts.theme_relevance import load_theme_taxonomy


ROOT = Path(__file__).resolve().parents[1]
ALIASES_PATH = ROOT / "config" / "symbol_aliases.tw.json"
TAXONOMY_PATH = ROOT / "config" / "theme_taxonomy.tw.json"


def test_alias_seed_covers_current_taxonomy_symbols() -> None:
    aliases = load_symbol_aliases(ALIASES_PATH)
    taxonomy = load_theme_taxonomy(TAXONOMY_PATH)

    taxonomy_symbols = {
        symbol
        for theme in taxonomy["themes"]
        for symbol in theme["seed_symbols"]
    }

    assert taxonomy_symbols <= set(aliases["symbols"])
    assert aliases["market_id"] == "TW_EQUITY"
    assert aliases["market_scope"] == ["TW_EQUITY"]


def test_extracts_known_direct_code_mention() -> None:
    aliases = load_symbol_aliases(ALIASES_PATH)

    direct_symbols = extract_direct_symbols(
        {"title_zh": "2330.TW 台積電先進封裝需求升溫"},
        aliases,
    )

    assert direct_symbols == [
        {
            "instrument_id": "TWSE:2330",
            "market_id": "TW_EQUITY",
            "asset_class": "equity",
            "symbol": "2330",
            "exchange": "TWSE",
            "name_zh": "台積電",
            "evidence": "title_zh: 2330.TW",
            "reason": "direct stock code mention",
        }
    ]


def test_extracts_suffixed_code_outside_alias_seed() -> None:
    aliases = load_symbol_aliases(ALIASES_PATH)

    direct_symbols = extract_direct_symbols(
        {"title": "2454.TW raises its edge AI outlook"},
        aliases,
    )

    assert direct_symbols == [
        {
            "instrument_id": "TWSE:2454",
            "market_id": "TW_EQUITY",
            "asset_class": "equity",
            "symbol": "2454",
            "exchange": "TWSE",
            "name_zh": "",
            "evidence": "title: 2454.TW",
            "reason": "direct stock code mention",
        }
    ]


def test_extracts_alias_mention_case_insensitively() -> None:
    aliases = load_symbol_aliases(ALIASES_PATH)

    direct_symbols = extract_direct_symbols(
        {"summary": "TSMC expands advanced packaging capacity."},
        aliases,
    )

    assert direct_symbols == [
        {
            "instrument_id": "TWSE:2330",
            "market_id": "TW_EQUITY",
            "asset_class": "equity",
            "symbol": "2330",
            "exchange": "TWSE",
            "name_zh": "台積電",
            "evidence": "summary: TSMC",
            "reason": "direct company alias mention",
        }
    ]


def test_ignores_unknown_four_digit_year() -> None:
    aliases = load_symbol_aliases(ALIASES_PATH)

    assert extract_direct_symbols(
        {"title": "Taiwan AI server outlook for 2026"},
        aliases,
    ) == []
