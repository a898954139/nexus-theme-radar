"""Theme membership hygiene: years are not stock codes, multi-topic articles
do not leak one theme's seed stocks into another, and curated themes absorb
their same-industry source tags."""

from __future__ import annotations

from scripts import update_theme_radar as updater
from scripts.symbol_mapping import extract_direct_symbols
from scripts.theme_relevance import load_theme_taxonomy

ALIASES = {
    "market_id": "TW_EQUITY",
    "symbols": {
        "2027": {"exchange": "TWSE", "name_zh": "大成鋼", "aliases": ["大成鋼"]},
        "2344": {"exchange": "TWSE", "name_zh": "華邦電", "aliases": ["華邦電"]},
    },
}


def _codes(text: str) -> list[str]:
    return [item["symbol"] for item in extract_direct_symbols({"title_zh": text}, ALIASES)]


def test_a_year_in_the_headline_is_not_a_stock_code() -> None:
    assert _codes("CSP 下修訂單，2027 年 NAND Flash 價格") == []
    assert _codes("台廠人形機器人零組件2027拚送樣驗證") == []


def test_a_bracketed_or_named_code_in_the_year_range_still_counts() -> None:
    assert _codes("大成鋼(2027)營收創高") == ["2027"]
    assert _codes("鋼價回升（2027）") == ["2027"]
    assert _codes("大成鋼 2027 受惠") == ["2027"]
    assert _codes("華邦電 2344 漲停") == ["2344"]


def _seed(symbol: str, theme_id: str) -> dict[str, str]:
    return {"instrument_id": f"TWSE:{symbol}", "symbol": symbol, "evidence": f"taxonomy seed: {theme_id}"}


def test_unrelated_theme_seeds_from_a_multi_topic_article_are_dropped() -> None:
    taxonomy = {"themes": [
        {"theme_id": "memory", "seed_symbols": ["2344", "2408", "8299"]},
        {"theme_id": "ssd", "seed_symbols": ["2344", "2408", "8299", "3260"]},
        {"theme_id": "robot", "seed_symbols": ["2049", "4576"]},
    ]}
    family = updater._theme_family(taxonomy)
    assert family["memory"] == {"memory", "ssd"}
    symbols = [
        _seed("2344", "memory"),
        _seed("3260", "ssd"),
        _seed("2049", "robot"),
        {"instrument_id": "TWSE:2330", "symbol": "2330", "evidence": "title_zh: 台積電"},
    ]
    kept = updater._theme_related_symbols(symbols, "memory", family)
    assert [item["symbol"] for item in kept] == ["2344", "3260", "2330"]


def test_enrich_momentum_latest_filters_only_when_given_a_taxonomy() -> None:
    momentum = {"themes": [{"theme_id": "memory", "rank": 1}]}
    candidate = {
        "id": "a", "primary_theme_id": "memory", "matched_theme_ids": ["memory", "robot"],
        "direct_symbols": [], "related_symbols": [_seed("2344", "memory"), _seed("2049", "robot")],
    }
    taxonomy = {"themes": [
        {"theme_id": "memory", "seed_symbols": ["2344"]},
        {"theme_id": "robot", "seed_symbols": ["2049"]},
    ]}
    without = updater.enrich_momentum_latest(momentum, [candidate])
    with_taxonomy = updater.enrich_momentum_latest(momentum, [candidate], taxonomy)
    if without["themes"][0]["related_symbols"]:
        assert {item["symbol"] for item in without["themes"][0]["related_symbols"]} == {"2344", "2049"}
        assert [item["symbol"] for item in with_taxonomy["themes"][0]["related_symbols"]] == ["2344"]


def test_curated_themes_absorb_their_named_source_tags() -> None:
    themes = {theme["theme_id"]: theme for theme in load_theme_taxonomy()["themes"]}
    memory = themes["memory_hbm"]
    assert {"2337", "3260", "6239"} <= set(memory["seed_symbols"])
    assert {"187", "243"} <= set(memory.get("source_tag_ids", []))
    assert "statementdog_tag_187" not in themes and "statementdog_tag_243" not in themes
    assert "2383" in themes["pcb_abf_hdi"]["seed_symbols"]
    assert "2330" not in themes["pcb_abf_hdi"]["seed_symbols"]
