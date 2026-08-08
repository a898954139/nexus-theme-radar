from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

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

    optical_cpo = next(theme for theme in themes if theme["theme_id"] == "optical_cpo")
    assert optical_cpo["name_zh"] == "矽光子 CPO"
    assert optical_cpo["related_industries"] == [
        "雷射光源與三五族材料",
        "SiPh 晶圓代工與先進封裝平台",
        "FAU、耦光元件與光模組",
        "光電測試、探針與失效分析",
        "交換器 ASIC 與 AI 網通系統",
    ]
    assert [segment["stage"] for segment in optical_cpo["supply_chain"]] == [
        "上游",
        "中游",
        "中游",
        "中游",
        "下游",
    ]
    assert [
        symbol
        for segment in optical_cpo["supply_chain"]
        for symbol in segment["symbols"]
    ] == optical_cpo["seed_symbols"]
    assert len(optical_cpo["seed_symbols"]) == 20


def test_default_runtime_taxonomy_expands_public_supply_chain_topics() -> None:
    taxonomy = load_theme_taxonomy()

    assert taxonomy["supply_chain_source"] == "industry_supply_chains.tw.json"
    assert taxonomy["supply_chain_theme_count"] >= 190
    merged = next(
        theme
        for theme in taxonomy["themes"]
        if theme["theme_id"] == "optical_cpo"
    )
    assert "19288" in merged["source_tag_ids"]
    assert merged["seed_symbols"]
    assert merged["supply_chain"]

    generated = next(
        theme
        for theme in taxonomy["themes"]
        if theme["theme_id"].startswith("statementdog_tag_")
    )
    assert generated["required_any"]


def test_supply_chain_must_match_related_industries_and_seed_symbols(tmp_path: Path) -> None:
    payload = {
        "themes": [
            {
                "theme_id": "optical_cpo",
                "name_zh": "矽光子 CPO",
                "keywords": ["cpo"],
                "related_industries": ["雷射光源與三五族材料"],
                "seed_symbols": ["3081"],
                "supply_chain": [
                    {
                        "stage": "上游",
                        "industry": "雷射光源與三五族材料",
                        "symbols": ["3081", "2455"],
                    }
                ],
            }
        ]
    }
    custom_path = tmp_path / "theme_taxonomy.tw.json"
    custom_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="supply_chain symbols must match seed_symbols"):
        load_theme_taxonomy(custom_path)


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


def test_theme_taxonomy_validation_supports_dual_schema_contract() -> None:
    payload = {
        "version": "mvp-2",
        "market": "TW",
        "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"],
        "themes": [
            {
                "theme_id": "legacy_cpu",
                "name_zh": "舊版主題",
                "keywords": ["old keyword", "legacy"],
                "related_industries": ["IC"],
                "seed_symbols": ["2382"],
            },
            {
                "theme_id": "candidate_foundry",
                "name_zh": "先進製程",
                "required_any": ["foundry", "fab"],
                "optional": ["euv"],
                "excluded": ["cofos"],
                "related_industries": ["半導體"],
                "seed_symbols": ["2330"],
            },
        ],
    }
    tmp_path = Path("/tmp/nexus-theme-radar-v07-schema")
    tmp_path.mkdir(parents=True, exist_ok=True)
    custom_path = tmp_path / "theme_taxonomy.tw.json"
    custom_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    loaded = load_theme_taxonomy(custom_path)

    assert loaded["themes"][0]["matcher_mode"] == "legacy"
    assert loaded["themes"][1]["matcher_mode"] == "structured"


def test_theme_taxonomy_requires_explicit_matcher_mode_to_match_derived_schema() -> None:
    payload = {
        "themes": [
            {
                "theme_id": "mismatch_legacy",
                "name_zh": "錯位舊欄位",
                "keywords": ["foundry"],
                "related_industries": ["IC"],
                "seed_symbols": ["2330"],
                "matcher_mode": "structured",
            },
            {
                "theme_id": "mismatch_structured",
                "name_zh": "錯位新欄位",
                "required_any": ["foundry"],
                "optional": ["fab"],
                "excluded": ["cowos"],
                "related_industries": ["IC"],
                "seed_symbols": ["2330"],
                "matcher_mode": "legacy",
            },
        ]
    }
    tmp_path = Path("/tmp/nexus-theme-radar-v07-schema-mismatch")
    tmp_path.mkdir(parents=True, exist_ok=True)
    custom_path = tmp_path / "theme_taxonomy.tw.json"
    custom_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="matcher_mode must match derived schema mode"):
        load_theme_taxonomy(custom_path)


def test_theme_taxonomy_validation_rejects_schema_mix_and_missing_fields() -> None:
    payload = {
        "version": "mvp-2",
        "market": "TW",
        "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"],
        "themes": [
            {
                "theme_id": "mixed",
                "name_zh": "混合主題",
                "keywords": ["mixed"],
                "required_any": ["foundry"],
                "optional": ["fab"],
                "excluded": ["cowos"],
                "related_industries": ["IC"],
                "seed_symbols": ["2382"],
            },
            {
                "theme_id": "missing-required_any",
                "name_zh": "缺欄位",
                "required_any": ["foundry"],
                "optional": ["fab"],
                "related_industries": ["IC"],
                "seed_symbols": ["2382"],
            },
        ],
    }
    tmp_path = Path("/tmp/nexus-theme-radar-v07-schema-invalid")
    tmp_path.mkdir(parents=True, exist_ok=True)
    custom_path = tmp_path / "theme_taxonomy.tw.json"
    custom_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with pytest.raises(ValueError):
        load_theme_taxonomy(custom_path)


def test_structured_matching_order_and_exclusion_rules_are_deterministic() -> None:
    taxonomy = {
        "themes": [
            {
                "theme_id": "foundry",
                "name_zh": "Foundry",
                "required_any": ["foundry", "fab"],
                "optional": ["euv"],
                "excluded": ["cowos"],
                "related_industries": ["IC"],
                "seed_symbols": ["2330"],
            }
        ]
    }

    required_match = score_theme_relevance(
        {
            "title_zh": "Foundry announces fab expansion",
            "summary": "Company confirms advanced node capacity expansion.",
        },
        taxonomy,
    )
    optional_only = score_theme_relevance(
        {
            "summary": "EUV equipment demand increases",
        },
        taxonomy,
    )
    vetoed = score_theme_relevance(
        {
            "title_zh": "Foundry announces fab expansion",
            "summary": "CoWoS supply update",
            "source": "source should never influence score",
        },
        taxonomy,
    )

    reverse = score_theme_relevance(
        {
            "summary": "Company confirms advanced node capacity expansion.",
            "title_zh": "Foundry announces fab expansion",
        },
        taxonomy,
    )

    assert required_match["matched_themes"][0]["theme_id"] == "foundry"
    assert required_match["theme_score"] == reverse["theme_score"]
    assert required_match["matched_themes"] == reverse["matched_themes"]
    assert optional_only["matched_themes"] == []
    assert vetoed["matched_themes"] == []


def test_structured_match_reports_veto_ids_additively() -> None:
    taxonomy = {
        "themes": [
            {
                "theme_id": "vetoed_foundry",
                "name_zh": "Foundry Veto",
                "required_any": ["foundry"],
                "optional": ["fab"],
                "excluded": ["cowos"],
                "related_industries": ["IC"],
                "seed_symbols": ["2330"],
                "matcher_mode": "structured",
            }
        ]
    }

    result = score_theme_relevance(
        {
            "title_zh": "Foundry plans with CoWoS excluded mention",
            "summary": "Foundry team disclosed expansion in fab area.",
            "source": "source should not leak",
        },
        taxonomy,
    )

    assert result["matched_themes"] == []
    assert result["vetoed_theme_ids"] == ["vetoed_foundry"]
