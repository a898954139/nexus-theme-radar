from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from scripts.generate_theme_demo import build_demo_payloads
from scripts.theme_relevance import (
    enrich_item_with_themes,
    load_theme_taxonomy,
    score_theme_relevance,
)


ROOT = Path(__file__).resolve().parents[1]
TAXONOMY_PATH = ROOT / "config" / "theme_taxonomy.tw.json"


def test_taxonomy_contains_market_native_seed_themes() -> None:
    taxonomy = load_theme_taxonomy(TAXONOMY_PATH)
    themes = taxonomy["themes"]

    assert taxonomy["market_id"] == "TW_EQUITY"
    assert taxonomy["market_scope"] == ["TW_EQUITY"]
    assert {theme["theme_id"] for theme in themes} == {
        "ai_server",
        "cowos_supply_chain",
        "defense_drone",
        "energy_grid",
        "memory_hbm",
        "optical_cpo",
        "pcb_abf_hdi",
        "power_supply",
        "robotics",
        "thermal_cooling",
    }
    assert all(theme["name_zh"] for theme in themes)
    assert all(theme["keywords"] for theme in themes)
    assert all(theme["related_industries"] for theme in themes)
    assert all(theme["seed_symbols"] for theme in themes)
    assert all(theme["market_scope"] == ["TW_EQUITY"] for theme in themes)


def test_scores_title_more_strongly_than_summary_and_explains_matches() -> None:
    taxonomy = load_theme_taxonomy(TAXONOMY_PATH)
    item = {
        "title": "AI server liquid cooling demand accelerates",
        "title_zh": "AI 伺服器液冷散熱需求加速",
        "summary": "CoWoS 先進封裝產能也持續擴充。",
        "source": "A source name containing HBM must not affect scoring",
    }

    result = score_theme_relevance(item, taxonomy)

    assert result["primary_theme_id"] == "thermal_cooling"
    assert result["theme_score"] == 1.0
    assert [match["theme_id"] for match in result["matched_themes"]][:2] == [
        "thermal_cooling",
        "ai_server",
    ]
    thermal = result["matched_themes"][0]
    assert "液冷" in thermal["signals"]
    assert "title_zh" in thermal["reason"]
    assert all(match["theme_id"] != "memory_hbm" for match in result["matched_themes"])


def test_matches_case_insensitive_english_keyword_as_a_token() -> None:
    taxonomy = load_theme_taxonomy(TAXONOMY_PATH)

    matched = score_theme_relevance(
        {"content": "Next-generation HBM capacity remains tight."},
        taxonomy,
    )
    not_matched = score_theme_relevance(
        {"content": "The exhibition booth will open tomorrow."},
        taxonomy,
    )

    assert matched["primary_theme_id"] == "memory_hbm"
    assert "hbm" in matched["matched_themes"][0]["signals"]
    assert not_matched == {
        "matched_themes": [],
        "primary_theme_id": None,
        "theme_score": 0.0,
    }


def test_enrichment_adds_related_symbols_without_mutating_input() -> None:
    taxonomy = load_theme_taxonomy(TAXONOMY_PATH)
    item = {
        "id": "thermal-1",
        "title_zh": "廣達液冷散熱成為 AI 伺服器焦點",
    }

    enriched = enrich_item_with_themes(item, taxonomy)

    assert "matched_themes" not in item
    assert enriched["primary_theme_id"] == "thermal_cooling"
    assert enriched["direct_symbols"][0]["symbol"] == "2382"
    assert enriched["direct_symbols"][0]["instrument_id"] == "TWSE:2382"
    assert enriched["symbol_evidence"] == {"2382": "title_zh: 廣達"}
    assert enriched["related_symbols"][0]["instrument_id"] == "TWSE:2382"
    assert [
        instrument["instrument_id"]
        for instrument in enriched["related_symbols"][1:4]
    ] == ["TWSE:3017", "TPEX:3324", "TWSE:3653"]
    assert enriched["related_symbol_codes"][:4] == ["2382", "3017", "3324", "3653"]
    assert enriched["decision"] == "track_watch"
    assert enriched["related_symbols"]
    assert len(enriched["related_symbols"]) == len(
        {instrument["instrument_id"] for instrument in enriched["related_symbols"]}
    )


def test_demo_payloads_apply_sliding_window_and_item_bounds() -> None:
    taxonomy = load_theme_taxonomy(TAXONOMY_PATH)
    records = [
        {
            "id": "newest",
            "title_zh": "液冷散熱需求升溫",
            "published_at": "2026-07-26T11:00:00Z",
        },
        {
            "id": "middle",
            "title": "HBM memory capacity expands",
            "published_at": "2026-07-26T10:00:00Z",
        },
        {
            "id": "old",
            "title_zh": "CPO 光通訊供應鏈",
            "published_at": "2026-07-24T09:00:00Z",
        },
        {
            "id": "irrelevant",
            "title_zh": "一般消費新聞",
            "published_at": "2026-07-26T11:30:00Z",
        },
    ]

    events, candidates = build_demo_payloads(
        records,
        taxonomy,
        now=datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc),
        window_hours=24,
        max_events=1,
        max_candidates=1,
    )

    assert events["window_hours"] == 24
    assert events["market_id"] == "TW_EQUITY"
    assert events["market_scope"] == ["TW_EQUITY"]
    assert events["max_items"] == 1
    assert [item["id"] for item in events["items"]] == ["newest"]
    assert events["items"][0]["decision"] == "track_watch"
    assert candidates["max_items"] == 1
    assert candidates["market_scope"] == ["TW_EQUITY"]
    assert len(candidates["items"]) == 1
    assert candidates["items"][0]["primary_theme_id"] == "thermal_cooling"
    assert candidates["items"][0]["decision"] == "track_watch"
