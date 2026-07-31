from __future__ import annotations

import json
import hashlib
import inspect
import logging
from datetime import datetime, timezone
from pathlib import Path
from copy import deepcopy

import feedparser
import pytest
import requests

import scripts.update_theme_radar as updater
from scripts.public_theme_ranking import build_public_theme_ranking
from scripts.update_theme_radar import (
    CANDIDATE_THEME_SCORE_MIN,
    SELECTED_THEME_SCORE_MIN,
    build_theme_projection,
    build_theme_payloads,
    classify_taiwan_relevance,
    cluster_theme_events,
    dedupe_records,
    fetch_rss_source,
    load_source_registry,
    normalize_feed_entry,
    rss_sources,
    run_update,
    run_momentum_side_paths,
    source_authority_ranks,
    source_status_payload,
    validate_payload_set,
    write_payload_set,
)
from scripts.theme_relevance import load_theme_taxonomy


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "source_registry.tw.json"
TAXONOMY_PATH = ROOT / "config" / "theme_taxonomy.tw.json"
CNYES_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "cnyes_rss.xml"
TECHNEWS_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "technews_rss.xml"
TECHNEWS_FIXTURE_MANIFEST_PATH = ROOT / "tests" / "fixtures" / "technews_rss.manifest.json"
DIGITIMES_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "digitimes_tw_rss.xml"
DIGITIMES_FIXTURE_MANIFEST_PATH = (
    ROOT / "tests" / "fixtures" / "digitimes_tw_rss.manifest.json"
)
LEGACY_REGRESSION_FIXTURE = (
    ROOT / "tests" / "fixtures" / "theme_benchmark" / "v0.7" / "legacy-regression.json"
)
EXISTING_PAYLOAD_CONTRACT_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "public_theme_ranking"
    / "v0.8"
    / "existing-payload-contracts.json"
)

PRE_V0_7_TOPLEVEL_KEYS = {
    "generated_at",
    "window_hours",
    "max_items",
    "market_id",
    "market_scope",
    "items",
    "total_items",
    "total_items_available",
    "pre_cluster_items",
    "excluded_items",
    "tw_relevance_distribution",
    "tw_relevance_reason_distribution",
    "selected_theme_score_min",
    "candidate_theme_score_min",
}

PRE_V0_7_TOPLEVEL_ADDITIVE_KEYS = {
    "matcher_contract",
    "taxonomy_version",
    "legacy_theme_count",
    "structured_theme_count",
    "theme_match_distribution",
    "theme_veto_distribution",
}

PRE_V0_7_EVENT_ITEM_KEYS = {
    "cluster_event_ids",
    "cluster_id",
    "cluster_size",
    "cluster_sources",
    "decision",
    "direct_symbols",
    "id",
    "matched_themes",
    "primary_theme_id",
    "published_at",
    "related_symbol_codes",
    "related_symbols",
    "source",
    "source_id",
    "summary",
    "symbol_evidence",
    "theme_score",
    "title",
    "title_zh",
    "tw_related_symbols",
    "tw_relevance_reason",
    "tw_relevance_status",
    "url",
}

PRE_V0_7_CANDIDATE_ITEM_KEYS = PRE_V0_7_EVENT_ITEM_KEYS | {"tracking_reason"}


class Entry:
    title = "AI 伺服器液冷散熱需求升溫"
    link = "https://example.com/news/thermal"
    summary = "冷板與水冷供應鏈受惠。"
    published = "Sun, 26 Jul 2026 10:30:00 +0800"


def test_registry_exposes_only_active_rss_sources() -> None:
    registry = load_source_registry(REGISTRY_PATH)
    sources = rss_sources(registry)

    assert registry["market_id"] == "TW_EQUITY"
    assert registry["market_scope"] == ["TW_EQUITY"]
    assert {source["source_id"] for source in sources} == {
        "moneydj",
        "yahoo_finance_tw",
        "cnyes",
        "technews",
        "digitimes_tw",
    }
    assert all(source["feed_url"].startswith("https://") for source in sources)
    assert all(source["fetch_method"] == "rss" for source in sources)
    assert all(source["market_scope"] == ["TW_EQUITY"] for source in sources)
    cnyes = next(source for source in sources if source["source_id"] == "cnyes")
    assert cnyes["status"] == "active"
    assert cnyes["feed_url"] == "https://news.cnyes.com/rss/v1/news/category/all"


def test_registry_marks_technews_and_digitimes_metadata_modes_and_boundaries() -> None:
    registry = load_source_registry(REGISTRY_PATH)
    sources = rss_sources(registry)
    technews = next(source for source in sources if source["source_id"] == "technews")
    digitimes = next(
        source for source in sources if source["source_id"] == "digitimes_tw"
    )

    assert technews["fetch_method"] == "rss"
    assert technews["content_mode"] == "rss_metadata"
    assert technews["feed_url"] == "https://technews.tw/feed/"
    assert technews["timeout_seconds"] == 20
    assert isinstance(technews["max_response_bytes"], int)

    assert digitimes["fetch_method"] == "rss"
    assert digitimes["content_mode"] == "rss_metadata_only"
    assert digitimes["feed_url"] == "https://www.digitimes.com.tw/rss/news.xml"
    assert digitimes["timeout_seconds"] == 20
    assert isinstance(digitimes["max_response_bytes"], int)


def test_registry_exposes_valid_source_authority_ranks() -> None:
    registry = load_source_registry(REGISTRY_PATH)
    active = {
        source["source_id"]: source
        for source in registry["sources"]
        if source["status"] == "active"
    }

    assert active["mops"]["authority_rank"] == 0
    assert active["moneydj"]["authority_rank"] == 10
    assert active["cnyes"]["authority_rank"] == 10
    assert active["yahoo_finance_tw"]["authority_rank"] > 10
    assert all(
        isinstance(source["authority_rank"], int)
        and not isinstance(source["authority_rank"], bool)
        and source["authority_rank"] >= 0
        for source in active.values()
    )


def test_missing_source_authority_defaults_to_lowest_rank() -> None:
    assert source_authority_ranks(
        {"sources": [{"source_id": "unknown", "status": "active"}]}
    ) == {"unknown": 99}


def test_cnyes_fixture_uses_generic_rss_article_contract() -> None:
    parsed = feedparser.parse(CNYES_FIXTURE_PATH.read_bytes())
    fetched_at = datetime(2026, 7, 27, 8, 10, tzinfo=timezone.utc)
    source = {
        "source_id": "cnyes",
        "name": "鉅亨網 Cnyes",
        "source_class": "financial_media",
        "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"],
    }

    assert parsed.bozo is False
    assert parsed.version == "rss20"
    assert len(parsed.entries) == 1

    record = normalize_feed_entry(parsed.entries[0], source, fetched_at)

    assert record is not None
    assert set(record) == {
        "id",
        "title_zh",
        "summary",
        "source",
        "source_id",
        "source_class",
        "market_id",
        "market_scope",
        "published_at",
        "url",
        "extraction_method",
        "fetched_at",
    }
    assert record["id"].startswith("cnyes-")
    assert record["title_zh"] == "投資雷達》韓股為何急跌？科技股還能抱嗎？"
    assert record["source"] == "鉅亨網 Cnyes"
    assert record["source_id"] == "cnyes"
    assert record["published_at"] == "2026-07-27T08:02:09Z"
    assert record["url"] == "https://news.cnyes.com/news/id/6546775"
    assert record["extraction_method"] == "rss"


def test_technews_fixture_uses_generic_rss_metadata_contract() -> None:
    parsed = feedparser.parse(TECHNEWS_FIXTURE_PATH.read_bytes())
    fetched_at = datetime(2026, 7, 28, 8, 30, tzinfo=timezone.utc)
    source = {
        "source_id": "technews",
        "name": "TechNews",
        "source_class": "financial_media",
        "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"],
    }

    assert parsed.bozo is False
    assert parsed.version == "rss20"
    assert len(parsed.entries) == 40

    record = normalize_feed_entry(parsed.entries[0], source, fetched_at)

    assert record is not None
    assert record["id"] == "technews-3449d7403fa9"
    assert record["title_zh"] == parsed.entries[0].title
    assert record["summary"] == parsed.entries[0].summary
    assert record["source"] == "TechNews"
    assert record["source_id"] == "technews"
    assert record["published_at"] == "2026-07-28T08:20:34Z"
    assert (
        record["url"]
        == "https://technews.tw/2026/07/28/philippines-to-build-first-spaceport/"
    )
    assert record["extraction_method"] == "rss"


def test_digitimes_metadata_only_fixture_ignores_full_content_fields_and_is_metadata_focused() -> None:
    parsed = feedparser.parse(DIGITIMES_FIXTURE_PATH.read_bytes())
    fetched_at = datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc)
    source = {
        "source_id": "digitimes_tw",
        "name": "DIGITIMES",
        "source_class": "financial_media",
        "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"],
    }

    assert parsed.bozo is False
    assert parsed.version == "rss20"
    assert len(parsed.entries) == 94

    record = normalize_feed_entry(parsed.entries[0], source, fetched_at)

    assert record is not None
    source_id = "digitimes_tw"
    expected_id = (
        f"{source_id}-{hashlib.sha1((source_id + '|' + record['url'] + '|' + record['title_zh']).encode('utf-8')).hexdigest()[:12]}"
    )
    assert record["id"] == expected_id
    assert record["title_zh"] == parsed.entries[0].title
    assert record["summary"] == parsed.entries[0].summary
    assert record["source"] == "DIGITIMES"
    assert record["source_id"] == "digitimes_tw"
    assert record["published_at"] == "2026-07-28T08:03:06Z"
    assert (
        record["url"]
        == "https://www.digitimes.com.tw/tech/dt/n/shwnws.asp?id=0000763254_ETX3YDML4YMC7X5MV9458"
    )
    assert record["extraction_method"] == "rss"
    assert "content" not in record


def test_technews_and_digitimes_fixture_manifests_track_capture_metadata() -> None:
    technews_manifest = json.loads(TECHNEWS_FIXTURE_MANIFEST_PATH.read_text(encoding="utf-8"))
    digitimes_manifest = json.loads(
        DIGITIMES_FIXTURE_MANIFEST_PATH.read_text(encoding="utf-8")
    )

    assert technews_manifest == {
        "source_id": "technews",
        "source_name": "TechNews",
        "endpoint": "https://technews.tw/feed/",
        "captured_at": "2026-07-28T12:00:00Z",
        "content_type": "application/rss+xml; charset=UTF-8",
        "byte_length": 38077,
        "sha256": "c4e25bf2fb1c756ced08e0ed306106edcf64ab3148e61a31b2012ed125e1886e",
        "item_count": 40,
        "provenance": "verified public RSS metadata only",
    }
    assert digitimes_manifest == {
        "source_id": "digitimes_tw",
        "source_name": "DIGITIMES",
        "endpoint": "https://www.digitimes.com.tw/rss/news.xml",
        "captured_at": "2026-07-28T12:00:00Z",
        "content_type": "text/xml",
        "byte_length": 89630,
        "sha256": "c72051f04c9a00e3eda4e7823d388c77a59c05f4d1d2f6038ec575eb767d740f",
        "item_count": 94,
        "provenance": "verified public RSS metadata only",
    }


def test_normalize_feed_entry_returns_article_contract() -> None:
    fetched_at = datetime(2026, 7, 26, 3, 0, tzinfo=timezone.utc)
    source = {
        "source_id": "moneydj",
        "name": "MoneyDJ",
        "source_class": "financial_media",
        "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"],
    }

    record = normalize_feed_entry(Entry(), source, fetched_at)

    assert record is not None
    assert record["id"].startswith("moneydj-")
    assert record["title_zh"] == Entry.title
    assert record["source"] == "MoneyDJ"
    assert record["source_id"] == "moneydj"
    assert record["source_class"] == "financial_media"
    assert record["market_id"] == "TW_EQUITY"
    assert record["market_scope"] == ["TW_EQUITY"]
    assert record["published_at"] == "2026-07-26T02:30:00Z"
    assert record["url"] == Entry.link
    assert record["extraction_method"] == "rss"


def test_dedupe_records_prefers_newest_unique_url() -> None:
    records = [
        {"id": "old", "url": "https://example.com/a", "published_at": "2026-07-25T01:00:00Z", "title_zh": "舊"},
        {"id": "new", "url": "https://example.com/a", "published_at": "2026-07-26T01:00:00Z", "title_zh": "新"},
        {"id": "b", "url": "https://example.com/b", "published_at": "2026-07-26T00:00:00Z", "title_zh": "另一則"},
    ]

    deduped = dedupe_records(records)

    assert [record["id"] for record in deduped] == ["new", "b"]


def test_build_theme_payloads_from_real_news_contract() -> None:
    taxonomy = load_theme_taxonomy(TAXONOMY_PATH)
    records = [
        {
            "id": "news-1",
            "title_zh": "廣達 AI 伺服器液冷散熱需求升溫",
            "summary": "冷板與水冷供應鏈受惠。",
            "source": "MoneyDJ",
            "source_id": "moneydj",
            "published_at": "2026-07-26T02:30:00Z",
            "url": "https://example.com/news/thermal",
        },
        {
            "id": "noise",
            "title_zh": "一般生活新聞",
            "source": "Yahoo Finance Taiwan",
            "source_id": "yahoo_finance_tw",
            "published_at": "2026-07-26T02:00:00Z",
            "url": "https://example.com/news/noise",
        },
    ]

    events, candidates = build_theme_payloads(
        records,
        taxonomy,
        anchor=datetime(2026, 7, 26, 4, 0, tzinfo=timezone.utc),
        window_hours=24,
        max_events=10,
        max_candidates=10,
    )

    assert events["total_items"] == 1
    assert events["market_id"] == "TW_EQUITY"
    assert events["market_scope"] == ["TW_EQUITY"]
    assert events["items"][0]["primary_theme_id"] == "thermal_cooling"
    assert events["items"][0]["decision"] == "track_watch"
    assert candidates["total_items"] == 1
    assert candidates["market_id"] == "TW_EQUITY"
    assert candidates["market_scope"] == ["TW_EQUITY"]
    candidate = candidates["items"][0]
    assert candidate["decision"] == "track_watch"
    assert candidate["direct_symbols"][0]["symbol"] == "2382"
    assert candidate["direct_symbols"][0]["instrument_id"] == "TWSE:2382"
    assert candidate["symbol_evidence"] == {"2382": "title_zh: 廣達"}
    assert candidate["related_symbols"][0]["instrument_id"] == "TWSE:2382"
    assert candidate["related_symbol_codes"][0] == "2382"


def test_build_theme_payloads_dedupes_duplicate_event_urls() -> None:
    taxonomy = load_theme_taxonomy(TAXONOMY_PATH)
    records = [
        {
            "id": "older",
            "title_zh": "廣達 AI 伺服器需求升溫",
            "summary": "資料中心伺服器持續擴產。",
            "published_at": "2026-07-26T01:00:00Z",
            "url": "https://example.com/news/ai-server",
        },
        {
            "id": "newer",
            "title_zh": "廣達 AI 伺服器需求續強",
            "summary": "資料中心伺服器持續擴產。",
            "published_at": "2026-07-26T02:00:00Z",
            "url": "https://example.com/news/ai-server",
        },
    ]

    events, candidates = build_theme_payloads(
        records,
        taxonomy,
        anchor=datetime(2026, 7, 26, 4, 0, tzinfo=timezone.utc),
        window_hours=24,
        max_events=10,
        max_candidates=10,
    )

    assert [item["id"] for item in events["items"]] == ["newer"]
    assert [item["id"] for item in candidates["items"]] == ["newer"]


def _cluster_record(
    record_id: str,
    title: str,
    *,
    source_id: str,
    published_at: str = "2026-07-27T08:00:00Z",
    theme_id: str = "memory_hbm",
    signals: list[str] | None = None,
    direct_symbol: str | None = None,
    summary: str = "",
    company_name: str = "",
) -> dict[str, object]:
    direct_symbols = (
        [{"symbol": direct_symbol, "instrument_id": f"TWSE:{direct_symbol}"}]
        if direct_symbol
        else []
    )
    return {
        "id": record_id,
        "title_zh": title,
        "summary": summary,
        "company_name": company_name,
        "source": source_id,
        "source_id": source_id,
        "published_at": published_at,
        "url": f"https://example.com/{record_id}",
        "primary_theme_id": theme_id,
        "matched_themes": [
            {
                "theme_id": theme_id,
                "name_zh": theme_id,
                "score": 0.8,
                "signals": signals or ["hbm"],
                "reason": "fixture",
            }
        ],
        "theme_score": 0.8,
        "direct_symbols": direct_symbols,
        "related_symbols": direct_symbols,
        "related_symbol_codes": [direct_symbol] if direct_symbol else [],
        "decision": "track_watch",
    }


def test_cluster_collapses_duplicate_listing_reports_and_keeps_sources() -> None:
    records = [
        _cluster_record(
            "generic-report",
            "長鑫科技啟動A股上市 記憶體產業迎新里程碑",
            source_id="unknown",
            summary="短訊",
        ),
        _cluster_record(
            "professional-report",
            "長鑫科技A股上市 記憶體產業重要里程碑",
            source_id="moneydj",
            summary="長鑫科技完成上市，市場關注記憶體產業供需變化。",
        ),
    ]

    clustered = cluster_theme_events(
        records,
        source_authority={"moneydj": 10},
        window_hours=36,
    )

    assert len(clustered) == 1
    representative = clustered[0]
    assert representative["id"] == "professional-report"
    assert representative["cluster_size"] == 2
    assert representative["cluster_event_ids"] == [
        "generic-report",
        "professional-report",
    ]
    assert [source["source_id"] for source in representative["cluster_sources"]] == [
        "moneydj",
        "unknown",
    ]
    assert representative["cluster_id"].startswith("cluster-")


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (
            _cluster_record("listing", "長鑫科技A股上市募資", source_id="moneydj"),
            _cluster_record("performance", "長鑫科技上市後股價創新高", source_id="cnyes"),
        ),
        (
            _cluster_record(
                "listing-forecast",
                "長鑫科技將於A股上市募資",
                source_id="moneydj",
            ),
            _cluster_record(
                "listing-complete",
                "長鑫科技完成A股上市募資",
                source_id="cnyes",
            ),
        ),
        (
            _cluster_record(
                "company-a",
                "欣興AI載板產能擴充",
                source_id="moneydj",
                theme_id="pcb_abf_hdi",
                signals=["abf"],
                direct_symbol="3037",
            ),
            _cluster_record(
                "company-b",
                "南電AI載板產能擴充",
                source_id="cnyes",
                theme_id="pcb_abf_hdi",
                signals=["abf"],
                direct_symbol="8046",
            ),
        ),
        (
            _cluster_record(
                "earnings",
                "廣達公布季度獲利創新高",
                source_id="moneydj",
                theme_id="ai_server",
                signals=["ai server"],
                direct_symbol="2382",
            ),
            _cluster_record(
                "target",
                "外資調高廣達目標價看好AI伺服器",
                source_id="cnyes",
                theme_id="ai_server",
                signals=["ai server"],
                direct_symbol="2382",
            ),
        ),
        (
            _cluster_record("day-one", "長鑫科技完成A股上市", source_id="moneydj"),
            _cluster_record(
                "day-three",
                "長鑫科技完成A股上市",
                source_id="cnyes",
                published_at="2026-07-24T08:00:00Z",
            ),
        ),
        (
            _cluster_record("timestamped", "長鑫科技完成A股上市", source_id="moneydj"),
            _cluster_record(
                "missing-time",
                "長鑫科技完成A股上市",
                source_id="cnyes",
                published_at="",
            ),
        ),
    ],
)
def test_cluster_does_not_merge_incompatible_company_phase_or_date(
    left: dict[str, object],
    right: dict[str, object],
) -> None:
    assert len(cluster_theme_events([left, right], source_authority={}, window_hours=36)) == 2


@pytest.mark.parametrize(
    ("left_title", "right_title"),
    [
        ("三星HBM擴產計畫正式公布", "美光HBM擴產計畫正式公布"),
        (
            "Samsung Electronics HBM expansion formally announced",
            "Micron Technology HBM expansion formally announced",
        ),
    ],
)
def test_cluster_does_not_merge_different_companies_sharing_technical_signal(
    left_title: str,
    right_title: str,
) -> None:
    records = [
        _cluster_record(
            "left-hbm",
            left_title,
            source_id="moneydj",
            signals=["hbm"],
        ),
        _cluster_record(
            "right-hbm",
            right_title,
            source_id="cnyes",
            signals=["hbm"],
        ),
    ]

    assert len(cluster_theme_events(records, source_authority={}, window_hours=36)) == 2


def test_cluster_merges_abbreviated_and_expanded_same_company_name() -> None:
    records = [
        _cluster_record(
            "samsung-short",
            "Samsung HBM expansion formally announced",
            source_id="moneydj",
            signals=["hbm"],
        ),
        _cluster_record(
            "samsung-expanded",
            "Samsung Electronics HBM expansion formally announced",
            source_id="cnyes",
            signals=["hbm"],
        ),
    ]

    assert len(cluster_theme_events(records, source_authority={}, window_hours=36)) == 1


def test_cluster_merges_explicit_abbreviated_and_expanded_company_names() -> None:
    records = [
        _cluster_record(
            "samsung-explicit-short",
            "Samsung HBM expansion formally announced",
            source_id="moneydj",
            signals=["hbm"],
            company_name="Samsung",
        ),
        _cluster_record(
            "samsung-explicit-expanded",
            "Samsung Electronics HBM expansion formally announced",
            source_id="cnyes",
            signals=["hbm"],
            company_name="Samsung Electronics",
        ),
    ]

    assert len(cluster_theme_events(records, source_authority={}, window_hours=36)) == 1


def test_cluster_is_permutation_invariant_and_uses_completeness_tiebreaker() -> None:
    records = [
        _cluster_record(
            "brief",
            "廣達AI伺服器新產能正式投產",
            source_id="moneydj",
            theme_id="ai_server",
            signals=["ai server"],
            direct_symbol="2382",
        ),
        _cluster_record(
            "complete",
            "廣達AI伺服器新產能正式投產",
            source_id="cnyes",
            theme_id="ai_server",
            signals=["ai server"],
            direct_symbol="2382",
            summary="新產線已正式投產，將支援海外資料中心客戶需求。",
        ),
    ]
    forward = cluster_theme_events(
        records,
        source_authority={"moneydj": 10, "cnyes": 10},
        window_hours=36,
    )
    reversed_result = cluster_theme_events(
        list(reversed(records)),
        source_authority={"moneydj": 10, "cnyes": 10},
        window_hours=36,
    )

    assert forward == reversed_result
    assert forward[0]["id"] == "complete"


def test_technews_cross_source_cluster_compatibility_remains_deterministic() -> None:
    taxonomy = load_theme_taxonomy(TAXONOMY_PATH)
    records = [
        {
            "id": "technews-report",
            "title_zh": "廣達AI 伺服器液冷散熱供應鏈需求升溫",
            "summary": "廣達 AI 伺服器液冷散熱需求升溫，台灣散熱材料受益。",
            "source": "TechNews",
            "source_id": "technews",
            "published_at": "2026-07-28T08:25:00Z",
            "url": "https://technews.tw/2026/07/28/philippines-to-build-first-spaceport/",
            "direct_symbols": [{"symbol": "2382", "instrument_id": "TWSE:2382"}],
            "primary_theme_id": "thermal_cooling",
            "matched_themes": [
                {
                    "theme_id": "thermal_cooling",
                    "name_zh": "液冷散熱",
                    "score": 0.8,
                    "signals": ["thermal_cooling"],
                    "reason": "fixture",
                }
            ],
            "theme_score": 0.8,
            "tw_relevance_status": "direct",
            "tw_related_symbols": ["TWSE:2382"],
            "tw_relevance_reason": "direct Taiwan symbol: TWSE:2382",
            "related_symbols": [{"symbol": "2382", "instrument_id": "TWSE:2382"}],
            "related_symbol_codes": ["2382"],
            "decision": "track_watch",
        },
        {
            "id": "moneydj-current",
            "title_zh": "廣達AI 伺服器液冷散熱需求升溫",
            "summary": "台積電與廣達擴展液冷與散熱鏈，台股題材再度升溫。",
            "source": "MoneyDJ",
            "source_id": "moneydj",
            "published_at": "2026-07-28T08:20:00Z",
            "url": "https://example.com/current-source/thermal-cooling",
            "direct_symbols": [{"symbol": "2382", "instrument_id": "TWSE:2382"}],
            "primary_theme_id": "thermal_cooling",
            "matched_themes": [
                {
                    "theme_id": "thermal_cooling",
                    "name_zh": "液冷散熱",
                    "score": 0.82,
                    "signals": ["thermal_cooling"],
                    "reason": "fixture",
                }
            ],
            "theme_score": 0.82,
            "tw_relevance_status": "direct",
            "tw_related_symbols": ["TWSE:2382"],
            "tw_relevance_reason": "direct Taiwan symbol: TWSE:2382",
            "related_symbols": [{"symbol": "2382", "instrument_id": "TWSE:2382"}],
            "related_symbol_codes": ["2382"],
            "decision": "track_watch",
        },
    ]

    events, candidates = build_theme_payloads(
        records,
        taxonomy,
        anchor=datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc),
        window_hours=24,
        max_events=10,
        max_candidates=10,
        source_authority={"moneydj": 10, "technews": 99},
    )

    assert events["selected_theme_score_min"] == 0.3
    assert candidates["candidate_theme_score_min"] == 0.5
    assert len(events["items"]) == 1
    representative = events["items"][0]
    assert representative["id"] == "moneydj-current"
    assert representative["cluster_size"] == 2
    assert sorted(source["source_id"] for source in representative["cluster_sources"]) == [
        "moneydj",
        "technews",
    ]
    assert sorted(source["url"] for source in representative["cluster_sources"]) == [
        "https://example.com/current-source/thermal-cooling",
        "https://technews.tw/2026/07/28/philippines-to-build-first-spaceport/",
    ]

    forward = build_theme_payloads(
        records,
        taxonomy,
        anchor=datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc),
        window_hours=24,
        max_events=10,
        max_candidates=10,
        source_authority={"moneydj": 10, "technews": 99},
    )
    assert events["items"] == forward[0]["items"]


def test_digitimes_cross_source_cluster_compatibility_preserves_contract() -> None:
    taxonomy = load_theme_taxonomy(TAXONOMY_PATH)
    records = [
        {
            "id": "digitimes-current",
            "title_zh": "長鑫科技 HBM 供應鏈進一步擴廠",
            "summary": "長鑫科技 HBM 記憶體供應鏈與封裝需求同步回溫。",
            "source": "DIGITIMES",
            "source_id": "digitimes_tw",
            "published_at": "2026-07-28T08:00:00Z",
            "url": "https://www.digitimes.com.tw/tech/dt/n/shwnws.asp?id=0000763254_ETX3YDML4YMC7X5MV9458",
            "direct_symbols": [{"symbol": "2382", "instrument_id": "TWSE:2382"}],
            "primary_theme_id": "memory_hbm",
            "matched_themes": [
            {
                "theme_id": "memory_hbm",
                "name_zh": "記憶體 HBM",
                "score": 0.8,
                "signals": ["hbm", "記憶體"],
                "reason": "fixture",
            }
        ],
            "theme_score": 0.8,
            "tw_relevance_status": "direct",
            "tw_related_symbols": ["TWSE:2382"],
            "tw_relevance_reason": "direct Taiwan symbol: TWSE:2382",
            "related_symbols": [{"symbol": "2382", "instrument_id": "TWSE:2382"}],
            "related_symbol_codes": ["2382"],
            "decision": "track_watch",
        },
        {
            "id": "moneydj-current",
            "title_zh": "長鑫科技 HBM 供應鏈進一步擴廠",
            "summary": "長鑫科技 HBM 擴充與封測合作強化，短訊。",
            "source": "MoneyDJ",
            "source_id": "moneydj",
            "published_at": "2026-07-28T08:05:00Z",
            "url": "https://example.com/current-source/memory-hbm",
            "direct_symbols": [{"symbol": "2382", "instrument_id": "TWSE:2382"}],
            "primary_theme_id": "memory_hbm",
            "matched_themes": [
                {
                    "theme_id": "memory_hbm",
                    "name_zh": "記憶體 HBM",
                    "score": 0.82,
                    "signals": ["hbm", "記憶體"],
                    "reason": "fixture",
                }
            ],
            "theme_score": 0.82,
            "tw_relevance_status": "direct",
            "tw_related_symbols": ["TWSE:2382"],
            "tw_relevance_reason": "direct Taiwan symbol: TWSE:2382",
            "related_symbols": [{"symbol": "2382", "instrument_id": "TWSE:2382"}],
            "related_symbol_codes": ["2382"],
            "decision": "track_watch",
        },
    ]

    events, candidates = build_theme_payloads(
        records,
        taxonomy,
        anchor=datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc),
        window_hours=24,
        max_events=10,
        max_candidates=10,
        source_authority={"moneydj": 10, "digitimes_tw": 99},
    )

    assert events["selected_theme_score_min"] == 0.3
    assert candidates["candidate_theme_score_min"] == 0.5
    assert "matcher_contract" in events
    assert "matcher_contract" in candidates
    assert len(events["items"]) == 1
    representative = events["items"][0]
    assert representative["id"] == "moneydj-current"
    assert representative["tw_relevance_status"] == "direct"
    assert representative["cluster_size"] == 2
    assert sorted(source["source_id"] for source in representative["cluster_sources"]) == [
        "digitimes_tw",
        "moneydj",
    ]
    assert "cluster_sources" in events["items"][0]
    assert candidates["items"] == []
    assert events["items"][0]["url"] == "https://example.com/current-source/memory-hbm"

    shuffled_events, _ = build_theme_payloads(
        list(reversed(records)),
        taxonomy,
        anchor=datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc),
        window_hours=24,
        max_events=10,
        max_candidates=10,
        source_authority={"moneydj": 10, "digitimes_tw": 99},
    )
    assert events["items"] == shuffled_events["items"]


def test_build_theme_payloads_candidates_use_cluster_representatives() -> None:
    taxonomy = load_theme_taxonomy(TAXONOMY_PATH)
    records = [
        {
            "id": "moneydj-event",
            "title_zh": "廣達AI server AI伺服器新產能正式投產",
            "summary": "新產能支援資料中心需求。",
            "source": "MoneyDJ",
            "source_id": "moneydj",
            "published_at": "2026-07-27T08:00:00Z",
            "url": "https://example.com/moneydj-event",
        },
        {
            "id": "unknown-event",
            "title_zh": "廣達AI server AI伺服器新產能投產",
            "summary": "資料中心伺服器需求增加。",
            "source": "Unknown",
            "source_id": "unknown",
            "published_at": "2026-07-27T08:10:00Z",
            "url": "https://example.com/unknown-event",
        },
    ]

    events, candidates = build_theme_payloads(
        records,
        taxonomy,
        anchor=datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc),
        window_hours=24,
        max_events=10,
        max_candidates=10,
        source_authority={"moneydj": 10},
    )

    assert events["total_items"] == 1
    assert candidates["total_items"] == 1
    assert events["items"][0]["id"] == "moneydj-event"
    assert candidates["items"][0]["id"] == "moneydj-event"
    assert candidates["items"][0]["cluster_size"] == 2


def _relevance_record(
    title: str,
    *,
    theme_id: str = "optical_cpo",
    signals: list[str] | None = None,
    direct_symbol: str | None = None,
    existing_related_symbols: list[object] | None = None,
) -> dict[str, object]:
    direct_symbols = (
        [{"symbol": direct_symbol, "instrument_id": f"TWSE:{direct_symbol}"}]
        if direct_symbol
        else []
    )
    return {
        "id": title,
        "title_zh": title,
        "primary_theme_id": theme_id,
        "matched_themes": [
            {
                "theme_id": theme_id,
                "name_zh": theme_id,
                "score": 0.8,
                "signals": signals or ["cpo"],
                "reason": "fixture",
            }
        ],
        "direct_symbols": direct_symbols,
        "_input_related_symbols": existing_related_symbols or [],
    }


def test_taiwan_relevance_retains_direct_alias_and_existing_mapping() -> None:
    taxonomy = load_theme_taxonomy(TAXONOMY_PATH)
    direct = classify_taiwan_relevance(
        _relevance_record("台積電CoWoS擴產", direct_symbol="2330"),
        taxonomy,
    )
    existing = classify_taiwan_relevance(
        _relevance_record(
            "海外光通訊訂單",
            existing_related_symbols=[{"instrument_id": "TPEX:3081", "symbol": "3081"}],
        ),
        taxonomy,
    )

    assert direct["tw_relevance_status"] == "direct"
    assert direct["tw_related_symbols"] == ["TWSE:2330"]
    assert "direct" in direct["tw_relevance_reason"]
    assert existing["tw_relevance_status"] == "direct"
    assert existing["tw_related_symbols"] == ["TPEX:3081"]


def test_taiwan_relevance_retains_strong_supply_chain_mapping() -> None:
    taxonomy = load_theme_taxonomy(TAXONOMY_PATH)

    result = classify_taiwan_relevance(
        _relevance_record(
            "Nvidia與Broadcom推進CPO量產",
            signals=["cpo"],
        ),
        taxonomy,
    )

    assert result["tw_relevance_status"] == "supply_chain"
    assert result["tw_related_symbols"] == ["TPEX:3081", "TPEX:3363", "TPEX:4979"]
    assert "optical_cpo" in result["tw_relevance_reason"]
    assert "cpo" in result["tw_relevance_reason"].casefold()


@pytest.mark.parametrize(
    "record",
    [
        _relevance_record(
            "長鑫科技A股上市 記憶體市值受矚目",
            theme_id="memory_hbm",
            signals=["記憶體"],
        ),
        _relevance_record(
            "韓股科技與記憶體族群市場盤勢",
            theme_id="memory_hbm",
            signals=["記憶體"],
        ),
        _relevance_record(
            "海外AI科技投資評論",
            theme_id="ai_server",
            signals=["ai"],
        ),
        _relevance_record(
            "海外券商調高記憶體公司目標價",
            theme_id="memory_hbm",
            signals=["記憶體"],
        ),
        _relevance_record(
            "海外券商調高Micron HBM目標價",
            theme_id="memory_hbm",
            signals=["hbm"],
        ),
        _relevance_record(
            "Broadcom CPO事業啟動海外IPO上市",
            signals=["cpo"],
        ),
        _relevance_record(
            "韓股CPO族群市場綜述",
            signals=["cpo"],
        ),
    ],
)
def test_taiwan_relevance_excludes_unsupported_overseas_and_generic_terms(
    record: dict[str, object],
) -> None:
    result = classify_taiwan_relevance(record, load_theme_taxonomy(TAXONOMY_PATH))

    assert result["tw_relevance_status"] == "excluded"
    assert result["tw_related_symbols"] == []


def test_relevance_gate_runs_before_clustering_and_preserves_thresholds() -> None:
    taxonomy = load_theme_taxonomy(TAXONOMY_PATH)
    records = [
        {
            "id": "direct-one",
            "title_zh": "廣達AI server AI伺服器新產能正式投產",
            "summary": "資料中心伺服器需求增加。",
            "source": "MoneyDJ",
            "source_id": "moneydj",
            "published_at": "2026-07-27T08:00:00Z",
            "url": "https://example.com/direct-one",
        },
        {
            "id": "direct-two",
            "title_zh": "廣達AI server AI伺服器新產能投產",
            "summary": "資料中心伺服器訂單升溫。",
            "source": "Cnyes",
            "source_id": "cnyes",
            "published_at": "2026-07-27T08:10:00Z",
            "url": "https://example.com/direct-two",
        },
        {
            "id": "supply-chain",
            "title_zh": "Nvidia與Broadcom推進CPO量產",
            "summary": "co-packaged optics進入生產階段。",
            "source": "MoneyDJ",
            "source_id": "moneydj",
            "published_at": "2026-07-27T07:00:00Z",
            "url": "https://example.com/supply-chain",
        },
        {
            "id": "unsupported",
            "title_zh": "長鑫科技A股上市 記憶體市值受矚目",
            "summary": "",
            "source": "Unknown",
            "source_id": "unknown",
            "published_at": "2026-07-27T06:00:00Z",
            "url": "https://example.com/unsupported",
        },
    ]

    events, candidates = build_theme_payloads(
        records,
        taxonomy,
        anchor=datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc),
        window_hours=24,
        max_events=10,
        max_candidates=10,
        source_authority={"moneydj": 10, "cnyes": 10},
    )

    assert SELECTED_THEME_SCORE_MIN == 0.3
    assert CANDIDATE_THEME_SCORE_MIN == 0.5
    assert events["pre_cluster_items"] == 3
    assert events["excluded_items"] == 1
    assert events["total_items"] == 2
    assert {item["tw_relevance_status"] for item in events["items"]} == {
        "direct",
        "supply_chain",
    }
    assert next(item for item in events["items"] if item["tw_relevance_status"] == "direct")[
        "cluster_size"
    ] == 2
    assert all(item["id"] != "unsupported" for item in events["items"])
    assert all(item["id"] != "unsupported" for item in candidates["items"])


def test_source_status_payload_matches_existing_frontend_contract() -> None:
    generated_at = datetime(2026, 7, 26, 4, 0, tzinfo=timezone.utc)
    payload = source_status_payload(
        [
            {"source_id": "moneydj", "name": "MoneyDJ", "status": "ok", "items": 3},
            {"source_id": "cnyes", "name": "Cnyes", "status": "error", "items": 0, "error": "404"},
        ],
        generated_at,
        raw_count=3,
    )

    assert payload["failed_count"] == 1
    assert payload["successful_sites"] == 1
    assert payload["failed_sites"] == ["cnyes"]
    assert payload["fetched_raw_items"] == 3
    assert payload["items_before_topic_filter"] == 3
    assert len(payload["sites"]) == 2


def _momentum_signal() -> dict[str, object]:
    return {
        "theme_id": "thermal",
        "name_zh": "液冷散熱",
        "heat_score": 70,
        "heat_raw_score": 70.0,
        "event_count": 2,
        "source_count": 2,
        "tracking_candidate_count": 1,
        "taiwan_mapping_count": 1,
        "direct_mapping_event_count": 1,
        "single_source_concentration": 0.5,
        "latest_qualifying_event_at": "2026-07-31T03:30:00Z",
    }


def test_momentum_latest_publishes_without_database_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        updater,
        "build_public_theme_signals",
        lambda *_args, **_kwargs: [_momentum_signal()],
    )

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("database history path must remain unavailable")

    for function_name in (
        "load_momentum_baselines",
        "write_theme_observations",
        "delete_expired_observations",
        "load_history_rows",
        "materialize_public_theme_history",
    ):
        monkeypatch.setattr(updater, function_name, fail_if_called)

    with caplog.at_level(logging.WARNING):
        result = run_momentum_side_paths(
            output_dir=tmp_path,
            projection={},
            taxonomy={},
            symbol_aliases={},
            observed_hour=datetime(2026, 7, 31, 4, tzinfo=timezone.utc),
            generated_at=datetime(2026, 7, 31, 4, 8, tzinfo=timezone.utc),
            producer_run_id="run-without-db",
            connection_factory=None,
        )

    latest = json.loads(
        (tmp_path / updater.MOMENTUM_LATEST_FILENAME).read_text(encoding="utf-8")
    )
    theme = latest["themes"][0]
    assert theme["lifecycle_stage"] == "new"
    assert theme["heat_change_24h"] is None
    assert theme["source_change_24h"] is None
    assert theme["momentum_score"] == 35
    assert result == {
        "producer_run_id": "run-without-db",
        "momentum_latest_published": True,
        "history_rows_upserted": 0,
        "retention_succeeded": False,
        "history_materialized": False,
    }
    assert any(
        "phase=connection error=credential_unavailable" in record.getMessage()
        for record in caplog.records
    )


def test_momentum_latest_publishes_when_connection_factory_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        updater,
        "build_public_theme_signals",
        lambda *_args, **_kwargs: [_momentum_signal()],
    )

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("database history work must remain skipped")

    for function_name in (
        "load_momentum_baselines",
        "write_theme_observations",
        "delete_expired_observations",
        "load_history_rows",
        "materialize_public_theme_history",
    ):
        monkeypatch.setattr(updater, function_name, fail_if_called)

    def fail_connection() -> None:
        calls.append("connection")
        raise RuntimeError("connection refused")

    with caplog.at_level(logging.WARNING):
        result = run_momentum_side_paths(
            output_dir=tmp_path,
            projection={},
            taxonomy={},
            symbol_aliases={},
            observed_hour=datetime(2026, 7, 31, 4, tzinfo=timezone.utc),
            generated_at=datetime(2026, 7, 31, 4, 8, tzinfo=timezone.utc),
            producer_run_id="run-connection-failure",
            connection_factory=fail_connection,
        )

    latest = json.loads(
        (tmp_path / updater.MOMENTUM_LATEST_FILENAME).read_text(encoding="utf-8")
    )
    theme = latest["themes"][0]
    assert calls == ["connection"]
    assert theme["lifecycle_stage"] == "new"
    assert theme["heat_change_24h"] is None
    assert theme["source_change_24h"] is None
    assert theme["momentum_score"] == 35
    assert result == {
        "producer_run_id": "run-connection-failure",
        "momentum_latest_published": True,
        "history_rows_upserted": 0,
        "retention_succeeded": False,
        "history_materialized": False,
    }
    assert "phase=connection error=connection refused" in caplog.text


def test_momentum_side_path_runs_upsert_retention_and_materializer_in_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    connection = object()
    monkeypatch.setattr(
        updater,
        "build_public_theme_signals",
        lambda *_args, **_kwargs: [_momentum_signal()],
    )
    monkeypatch.setattr(
        updater,
        "load_momentum_baselines",
        lambda *_args, **_kwargs: calls.append("baseline") or [],
    )
    monkeypatch.setattr(
        updater,
        "write_momentum_latest",
        lambda *_args, **_kwargs: calls.append("latest"),
    )
    monkeypatch.setattr(
        updater,
        "write_theme_observations",
        lambda *_args, **_kwargs: calls.append("upsert") or 1,
    )
    monkeypatch.setattr(
        updater,
        "delete_expired_observations",
        lambda *_args, **_kwargs: calls.append("retention") or 0,
    )
    monkeypatch.setattr(
        updater,
        "load_history_rows",
        lambda *_args, **_kwargs: calls.append("history_query") or [],
    )

    def materialize(_path, *, row_loader, **_kwargs):
        calls.append("materialize")
        row_loader(datetime(2026, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 31, tzinfo=timezone.utc))
        return {}

    monkeypatch.setattr(updater, "materialize_public_theme_history", materialize)

    result = run_momentum_side_paths(
        output_dir=tmp_path,
        projection={},
        taxonomy={},
        symbol_aliases={},
        observed_hour=datetime(2026, 7, 31, 4, tzinfo=timezone.utc),
        generated_at=datetime(2026, 7, 31, 4, 8, tzinfo=timezone.utc),
        producer_run_id="run-123",
        connection_factory=lambda: connection,
    )

    assert calls == [
        "baseline",
        "latest",
        "upsert",
        "retention",
        "materialize",
        "history_query",
    ]
    assert result == {
        "producer_run_id": "run-123",
        "momentum_latest_published": True,
        "history_rows_upserted": 1,
        "retention_succeeded": True,
        "history_materialized": True,
    }


def test_upsert_failure_is_truthful_and_skips_retention_and_materialization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        updater,
        "build_public_theme_signals",
        lambda *_args, **_kwargs: [_momentum_signal()],
    )
    monkeypatch.setattr(updater, "load_momentum_baselines", lambda *_args: [])
    monkeypatch.setattr(updater, "write_momentum_latest", lambda *_args: calls.append("latest"))

    def fail_upsert(*_args, **_kwargs):
        calls.append("upsert")
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(updater, "write_theme_observations", fail_upsert)
    monkeypatch.setattr(
        updater,
        "delete_expired_observations",
        lambda *_args: calls.append("retention"),
    )
    monkeypatch.setattr(
        updater,
        "materialize_public_theme_history",
        lambda *_args, **_kwargs: calls.append("materialize"),
    )

    with caplog.at_level(logging.WARNING):
        result = run_momentum_side_paths(
            output_dir=tmp_path,
            projection={},
            taxonomy={},
            symbol_aliases={},
            observed_hour=datetime(2026, 7, 31, 4, tzinfo=timezone.utc),
            generated_at=datetime(2026, 7, 31, 4, 8, tzinfo=timezone.utc),
            producer_run_id="run-123",
            connection_factory=lambda: object(),
        )

    assert calls == ["latest", "upsert"]
    assert result["history_rows_upserted"] == 0
    assert not result["retention_succeeded"]
    assert not result["history_materialized"]
    assert "phase=upsert" in caplog.text
    assert "producer_run_id=run-123" in caplog.text
    assert "succeeded" not in caplog.text


def test_retention_failure_warns_but_materialization_continues(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        updater,
        "build_public_theme_signals",
        lambda *_args, **_kwargs: [_momentum_signal()],
    )
    monkeypatch.setattr(updater, "load_momentum_baselines", lambda *_args: [])
    monkeypatch.setattr(updater, "write_momentum_latest", lambda *_args: None)
    monkeypatch.setattr(updater, "write_theme_observations", lambda *_args, **_kwargs: 1)

    def fail_retention(*_args):
        raise RuntimeError("retention failed")

    monkeypatch.setattr(updater, "delete_expired_observations", fail_retention)
    monkeypatch.setattr(updater, "load_history_rows", lambda *_args: [])
    monkeypatch.setattr(
        updater,
        "materialize_public_theme_history",
        lambda *_args, **_kwargs: calls.append("materialize") or {},
    )

    with caplog.at_level(logging.WARNING):
        result = run_momentum_side_paths(
            output_dir=tmp_path,
            projection={},
            taxonomy={},
            symbol_aliases={},
            observed_hour=datetime(2026, 7, 31, 4, tzinfo=timezone.utc),
            generated_at=datetime(2026, 7, 31, 4, 8, tzinfo=timezone.utc),
            producer_run_id="run-123",
            connection_factory=lambda: object(),
        )

    assert calls == ["materialize"]
    assert not result["retention_succeeded"]
    assert result["history_materialized"]
    assert "phase=retention" in caplog.text


def test_existing_payload_publication_precedes_non_blocking_momentum_side_path() -> None:
    source = inspect.getsource(updater.run_update)
    assert source.index("write_payload_set(output_dir, payloads)") < source.index(
        "run_momentum_side_paths("
    )


def test_workflow_gates_history_database_credential_by_environment_and_branch() -> None:
    workflow = (ROOT / ".github" / "workflows" / "update-theme-radar.yml").read_text(
        encoding="utf-8"
    )
    compact_workflow = " ".join(workflow.split())

    assert "db_history_environment:" in workflow
    assert "default: disabled" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert (
        "vars.THEME_RADAR_DB_HISTORY_AUTHORIZED_ENVIRONMENT "
        "== inputs.db_history_environment"
        in workflow
    )
    assert "vars.THEME_RADAR_DB_HISTORY_AUTHORIZED_BRANCH == github.ref_name" in workflow
    assert "github.ref_type == 'branch'" in workflow
    assert (
        "inputs.db_history_environment == 'preview' && github.ref_name != 'master'"
        in compact_workflow
    )
    assert (
        "inputs.db_history_environment == 'production' && github.ref_name == 'master'"
        in compact_workflow
    )
    assert "&& secrets.THEME_RADAR_DATABASE_URL || ''" in compact_workflow
    assert (
        "THEME_RADAR_DATABASE_URL: ${{ secrets.THEME_RADAR_DATABASE_URL }}"
        not in workflow
    )
    assert "service_role" not in workflow.casefold()
    assert "supabase_url" not in workflow.casefold()
    assert "supabase_key" not in workflow.casefold()


def test_run_update_isolates_failed_source(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "market_id": "TW_EQUITY",
                "market_scope": ["TW_EQUITY"],
                "sources": [
                    {
                        "source_id": source_id,
                        "name": source_id,
                        "source_class": "financial_media",
                        "fetch_method": "rss",
                        "status": "active",
                        "feed_url": f"https://example.com/{source_id}.xml",
                    }
                    for source_id in ("moneydj", "cnyes", "yahoo_finance_tw")
                ],
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_fetch(_session, source, fetched_at, **_kwargs):
        source_id = source["source_id"]
        calls.append(source_id)
        status = {
            "source_id": source_id,
            "name": source_id,
            "status": "ok",
            "items": 1,
            "error": None,
        }
        if source_id == "cnyes":
            return [], {**status, "status": "error", "items": 0, "error": "fixture failure"}
        return [
            {
                "id": f"{source_id}-item",
                "title_zh": "一般市場新聞",
                "summary": "",
                "source": source_id,
                "source_id": source_id,
                "published_at": fetched_at.isoformat().replace("+00:00", "Z"),
                "url": f"https://example.com/{source_id}/item",
            }
        ], status

    monkeypatch.setattr("scripts.update_theme_radar.fetch_rss_source", fake_fetch)

    summary = run_update(
        registry_path=registry_path,
        output_dir=tmp_path / "output",
        window_hours=24,
        max_events=10,
        max_candidates=10,
    )
    status = json.loads((tmp_path / "output" / "source-status.json").read_text())

    assert sorted(calls) == ["cnyes", "moneydj", "yahoo_finance_tw"]
    assert summary["raw_items"] == 2
    assert summary["failed_sources"] == 1
    assert status["successful_sites"] == 2
    assert status["failed_sites"] == ["cnyes"]


def test_build_theme_payloads_exposes_matcher_diagnostics_without_changing_contract() -> None:
    taxonomy = load_theme_taxonomy(TAXONOMY_PATH)
    records = [
        {
            "id": "direct-one",
            "title_zh": "廣達AI server AI伺服器新產能正式投產",
            "summary": "資料中心伺服器需求增加。",
            "source": "MoneyDJ",
            "source_id": "moneydj",
            "published_at": "2026-07-27T08:00:00Z",
            "url": "https://example.com/direct-one",
        },
        {
            "id": "direct-two",
            "title_zh": "長鑫科技A股上市 記憶體市值受矚目",
            "summary": "市場關注海外消息。",
            "source": "Cnyes",
            "source_id": "cnyes",
            "published_at": "2026-07-27T07:00:00Z",
            "url": "https://example.com/direct-two",
        },
    ]

    events, candidates = build_theme_payloads(
        records,
        taxonomy,
        anchor=datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc),
        window_hours=24,
        max_events=10,
        max_candidates=10,
    )

    assert events["matcher_contract"] == "hybrid_required_any_v1"
    assert events["taxonomy_version"] == "v0.7"
    assert events["legacy_theme_count"] == 10
    assert events["structured_theme_count"] == 0
    assert candidates["matcher_contract"] == "hybrid_required_any_v1"
    assert candidates["taxonomy_version"] == "v0.7"
    assert candidates["legacy_theme_count"] == 10
    assert candidates["structured_theme_count"] == 0

    assert list(events["theme_match_distribution"].keys()) == [
        "ai_server",
    ]
    assert events["theme_veto_distribution"] == {}
    assert events["selected_theme_score_min"] == 0.3
    assert events["candidate_theme_score_min"] == 0.5

    reversed_records = list(reversed(records))
    reversed_events, _ = build_theme_payloads(
        reversed_records,
        taxonomy,
        anchor=datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc),
        window_hours=24,
        max_events=10,
        max_candidates=10,
    )
    assert events["theme_match_distribution"] == reversed_events["theme_match_distribution"]


def test_build_theme_payloads_infers_theme_mode_for_raw_taxonomy_contract() -> None:
    raw_taxonomy = {
        "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"],
        "themes": [
            {
                "theme_id": "legacy_cpu",
                "name_zh": "舊版主題",
                "keywords": ["legacy"],
                "related_industries": ["IC"],
                "seed_symbols": ["2382"],
            },
            {
                "theme_id": "structured_foundry",
                "name_zh": "先進製程",
                "required_any": ["foundry", "fab"],
                "optional": ["euv"],
                "excluded": ["cowos"],
                "related_industries": ["IC"],
                "seed_symbols": ["2330"],
            },
        ],
    }
    records = [
        {
            "id": "raw-taxonomy",
            "title_zh": "Foundry expansion in Fab and EUV",
            "summary": "Fab and advanced foundry expansion for EUV.",
            "source": "MoneyDJ",
            "source_id": "moneydj",
            "published_at": "2026-07-26T02:30:00Z",
            "url": "https://example.com/taxonomy",
        },
    ]

    events, candidates = build_theme_payloads(
        records,
        raw_taxonomy,
        anchor=datetime(2026, 7, 26, 4, 0, tzinfo=timezone.utc),
        window_hours=24,
        max_events=10,
        max_candidates=10,
    )

    assert events["legacy_theme_count"] == 1
    assert events["structured_theme_count"] == 1
    assert candidates["legacy_theme_count"] == 1
    assert candidates["structured_theme_count"] == 1


def test_run_update_relevance_exclusions_preserve_raw_source_counts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "market_id": "TW_EQUITY",
                "market_scope": ["TW_EQUITY"],
                "sources": [
                    {
                        "source_id": "moneydj",
                        "name": "MoneyDJ",
                        "source_class": "financial_media",
                        "fetch_method": "rss",
                        "status": "active",
                        "authority_rank": 10,
                        "feed_url": "https://example.com/feed.xml",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    records = [
        {
            "id": "direct",
            "title_zh": "廣達AI server AI伺服器新產能正式投產",
            "summary": "",
            "source": "MoneyDJ",
            "source_id": "moneydj",
            "published_at": "2026-07-27T08:00:00Z",
            "url": "https://example.com/direct",
        },
        {
            "id": "excluded",
            "title_zh": "長鑫科技A股上市 記憶體市值受矚目",
            "summary": "",
            "source": "MoneyDJ",
            "source_id": "moneydj",
            "published_at": "2026-07-27T07:00:00Z",
            "url": "https://example.com/excluded",
        },
    ]

    monkeypatch.setattr("scripts.update_theme_radar.now_utc", lambda: datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(
        "scripts.update_theme_radar.dispatch_sources",
        lambda *_args, **_kwargs: [
            {
                "records": records,
                "status": {
                    "source_id": "moneydj",
                    "source_class": "financial_media",
                    "status": "ok",
                    "items": 2,
                },
            }
        ],
    )
    output_dir = tmp_path / "output"

    summary = run_update(
        registry_path=registry_path,
        output_dir=output_dir,
        window_hours=24,
        max_events=10,
        max_candidates=10,
    )
    status = json.loads((output_dir / "source-status.json").read_text(encoding="utf-8"))
    events = json.loads((output_dir / "theme-events.json").read_text(encoding="utf-8"))

    assert summary["raw_items"] == 2
    assert summary["excluded_events"] == 1
    assert status["fetched_raw_items"] == 2
    assert status["sites"][0]["items"] == 2
    assert events["total_items"] == 1
    assert events["items"][0]["id"] == "direct"


def test_rss_adapter_rejects_oversized_response() -> None:
    class Response:
        headers = {"Content-Length": "6"}
        content = b"123456"

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, _chunk_size: int):
            yield self.content

        def close(self) -> None:
            return None

    class Session:
        def get(self, *_args, **_kwargs):
            return Response()

    records, status = fetch_rss_source(
        Session(),
        {
            "source_id": "bounded-rss",
            "name": "Bounded RSS",
            "source_class": "financial_media",
            "market_id": "TW_EQUITY",
            "market_scope": ["TW_EQUITY"],
            "feed_url": "https://example.com/feed.xml",
            "max_response_bytes": 5,
        },
        datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc),
    )

    assert records == []
    assert status["status"] == "error"
    assert "response exceeds 5 bytes" in status["error"]


def test_build_theme_payloads_reports_structured_veto_distribution() -> None:
    taxonomy = deepcopy(load_theme_taxonomy(TAXONOMY_PATH))
    taxonomy["themes"] = [
        *taxonomy["themes"],
        {
            "theme_id": "vetoed_ai_server",
            "name_zh": "AI 伺服器排除關鍵字",
            "required_any": ["ai"],
            "optional": ["server"],
            "excluded": ["cloud"],
            "related_industries": ["AI"],
            "seed_symbols": ["2330"],
        }
    ]

    records = [
        {
            "id": "vetoed-1",
            "title_zh": "台積電 AI 伺服器 cloud 需求增溫",
            "summary": "AI 伺服器雲端關聯題材暫不進場。",
            "source": "MoneyDJ",
            "source_id": "moneydj",
            "published_at": "2026-07-27T09:00:00Z",
            "url": "https://example.com/vetoed-1",
        },
        {
            "id": "direct-1",
            "title_zh": "台積電 AI 伺服器 擴廠新增報告",
            "summary": "AI 伺服器 需求明顯上修。",
            "source": "MoneyDJ",
            "source_id": "moneydj",
            "published_at": "2026-07-27T09:05:00Z",
            "url": "https://example.com/direct-1",
        },
    ]

    events, candidates = build_theme_payloads(
        records,
        taxonomy,
        anchor=datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc),
        window_hours=24,
        max_events=10,
        max_candidates=10,
    )

    assert events["theme_veto_distribution"] == {"vetoed_ai_server": 1}
    assert all("vetoed_theme_ids" not in item for item in events["items"])
    assert all("vetoed_theme_ids" not in item for item in candidates["items"])


def test_legacy_taxonomy_regression_fixture_retains_exact_topline_behavior() -> None:
    payload = json.loads(LEGACY_REGRESSION_FIXTURE.read_text(encoding="utf-8"))
    records = payload["records"]
    expected = payload["expected"]

    events, candidates = build_theme_payloads(
        records,
        load_theme_taxonomy(TAXONOMY_PATH),
        anchor=datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc),
        window_hours=24,
        max_events=20,
        max_candidates=20,
    )

    assert events["selected_theme_score_min"] == expected["selected_theme_score_min"]
    assert events["candidate_theme_score_min"] == expected["candidate_theme_score_min"]
    assert (
        set(events.keys()) - PRE_V0_7_TOPLEVEL_ADDITIVE_KEYS
        == PRE_V0_7_TOPLEVEL_KEYS
    )
    assert (
        set(candidates.keys()) - PRE_V0_7_TOPLEVEL_ADDITIVE_KEYS
        == PRE_V0_7_TOPLEVEL_KEYS
    )
    assert set(events["items"][0].keys()) == PRE_V0_7_EVENT_ITEM_KEYS
    assert set(candidates["items"][0].keys()) == PRE_V0_7_CANDIDATE_ITEM_KEYS
    assert len(events["items"]) == len(expected["events"])
    assert len(candidates["items"]) == len(expected["events"])

    actual_by_id = {item["id"]: item for item in events["items"]}

    for expectation in expected["events"]:
        item = actual_by_id[expectation["id"]]
        matched = item["matched_themes"][0]
        assert item["primary_theme_id"] == expectation["primary_theme_id"]
        assert item["theme_score"] == expectation["theme_score"]
        assert matched["signals"] == expectation["matched_signals"]
        assert matched["reason"] == expectation["matched_reason"]
        assert item["symbol_evidence"] == expectation["symbol_evidence"]
        assert item["decision"] == expectation["decision"]


def _make_fake_fetcher_with_failure(
    failure_source: str,
    failure_mode: str,
    success_source: str = "moneydj",
):
    def fake_fetch(_session, source, _fetched_at, **_kwargs):
        source_id = source["source_id"]

        if source_id == failure_source:
            if failure_mode == "timeout":
                raise requests.Timeout("timeout failure")
            if failure_mode == "invalid_feed":
                raise ValueError("invalid feed")
            raise ValueError("response exceeds 5 bytes")

        return (
            [
                {
                    "id": f"{source_id}-item",
                    "title_zh": "一般市場新聞",
                    "summary": "",
                    "source": source_id,
                    "source_id": source_id,
                    "published_at": "2026-07-28T08:00:00Z",
                    "url": f"https://example.com/{source_id}/item",
                }
            ],
            {
                "source_id": source_id,
                "name": source_id,
                "status": "ok",
                "items": 1,
                "error": None,
            },
        )

    return fake_fetch


@pytest.mark.parametrize(
    "failure_mode",
    ["timeout", "invalid_feed", "oversized"],
)
def test_technews_update_isolation_for_failure_modes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_mode: str,
) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "market_id": "TW_EQUITY",
                "market_scope": ["TW_EQUITY"],
                "sources": [
                    {
                        "source_id": "moneydj",
                        "name": "MoneyDJ",
                        "source_class": "financial_media",
                        "fetch_method": "rss",
                        "status": "active",
                        "feed_url": "https://example.com/moneydj.xml",
                    },
                    {
                        "source_id": "technews",
                        "name": "TechNews",
                        "source_class": "financial_media",
                        "fetch_method": "rss",
                        "status": "active",
                        "feed_url": "https://technews.tw/feed/",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "scripts.update_theme_radar.fetch_rss_source",
        _make_fake_fetcher_with_failure("technews", failure_mode),
    )

    summary = run_update(
        registry_path=registry_path,
        output_dir=tmp_path / "output",
        window_hours=24,
        max_events=10,
        max_candidates=10,
    )
    status = json.loads((tmp_path / "output" / "source-status.json").read_text(encoding="utf-8"))

    assert summary["raw_items"] == 1
    assert summary["failed_sources"] == 1
    assert status["failed_sites"] == ["technews"]
    assert status["successful_sites"] == 1


@pytest.mark.parametrize(
    "failure_mode",
    ["timeout", "invalid_feed", "oversized"],
)
def test_digitimes_update_isolation_for_failure_modes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_mode: str,
) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "market_id": "TW_EQUITY",
                "market_scope": ["TW_EQUITY"],
                "sources": [
                    {
                        "source_id": "moneydj",
                        "name": "MoneyDJ",
                        "source_class": "financial_media",
                        "fetch_method": "rss",
                        "status": "active",
                        "feed_url": "https://example.com/moneydj.xml",
                    },
                    {
                        "source_id": "digitimes_tw",
                        "name": "DIGITIMES",
                        "source_class": "financial_media",
                        "fetch_method": "rss",
                        "status": "active",
                        "feed_url": "https://www.digitimes.com.tw/rss/news.xml",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "scripts.update_theme_radar.fetch_rss_source",
        _make_fake_fetcher_with_failure("digitimes_tw", failure_mode),
    )

    summary = run_update(
        registry_path=registry_path,
        output_dir=tmp_path / "output",
        window_hours=24,
        max_events=10,
        max_candidates=10,
    )
    status = json.loads((tmp_path / "output" / "source-status.json").read_text(encoding="utf-8"))

    assert summary["raw_items"] == 1
    assert summary["failed_sources"] == 1
    assert status["failed_sites"] == ["digitimes_tw"]
    assert status["successful_sites"] == 1


def test_digitimes_metadata_only_flow_requests_only_feed_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class Response:
        def __init__(self, url: str) -> None:
            self.url = url
            self.status_code = 200
            self.headers = {"content-type": "text/xml"}
            self.content = DIGITIMES_FIXTURE_PATH.read_bytes()
            self.headers = {"content-type": "text/xml"}

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, _chunk_size: int):
            yield self.content

        def close(self) -> None:
            return None

    requests_log: list[str] = []

    class SpySession:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        def get(self, url: str, *_args, **_kwargs):
            requests_log.append(url)
            assert url == "https://www.digitimes.com.tw/rss/news.xml"
            return Response(url)

        def close(self) -> None:
            return None

    monkeypatch.setattr("requests.Session", SpySession)

    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "market_id": "TW_EQUITY",
                "market_scope": ["TW_EQUITY"],
                "sources": [
                    {
                        "source_id": "digitimes_tw",
                        "name": "DIGITIMES",
                        "source_class": "financial_media",
                        "fetch_method": "rss",
                        "status": "active",
                        "feed_url": "https://www.digitimes.com.tw/rss/news.xml",
                        "timeout_seconds": 20,
                        "max_response_bytes": 8 * 1024 * 1024,
                        "content_mode": "rss_metadata_only",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    run_update(
        registry_path=registry_path,
        output_dir=tmp_path / "output",
        window_hours=24,
        max_events=10,
        max_candidates=10,
    )

    assert requests_log == ["https://www.digitimes.com.tw/rss/news.xml"]

def test_run_update_keeps_tw_relevance_distribution_to_retained_records_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    records = [
        {
            "id": "direct-1",
            "title_zh": "廣達 AI server AI伺服器新產能正式投產",
            "summary": "資料中心伺服器持續擴產。",
            "source": "MoneyDJ",
            "source_id": "moneydj",
            "published_at": "2026-07-27T08:00:00Z",
            "url": "https://example.com/direct-1",
            "direct_symbols": [{"symbol": "2382", "instrument_id": "TWSE:2382"}],
        },
        {
            "id": "excluded-1",
            "title_zh": "長鑫科技 A股上市 記憶體市值受矚目",
            "summary": "市場關注海外消息。",
            "source": "MoneyDJ",
            "source_id": "moneydj",
            "published_at": "2026-07-27T07:00:00Z",
            "url": "https://example.com/excluded-1",
        },
    ]

    def fake_score(record: dict[str, object], taxonomy: dict[str, object] | None = None) -> dict[str, object]:
        if record["id"] == "direct-1":
            return {
                "theme_score": 0.8,
                "matched_themes": [
                    {
                        "theme_id": "thermal_cooling",
                        "name_zh": "AI 伺服器液冷散熱",
                        "score": 0.8,
                        "signals": ["AI"],
                        "reason": "fixture",
                    }
                ],
                "vetoed_theme_ids": [],
            }
        return {"matched_themes": [], "vetoed_theme_ids": []}

    monkeypatch.setattr("scripts.theme_relevance.score_theme_relevance", fake_score)
    monkeypatch.setattr("scripts.update_theme_radar.score_theme_relevance", fake_score)
    monkeypatch.setattr("scripts.update_theme_radar.now_utc", lambda: datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(
        "scripts.update_theme_radar.dispatch_sources",
        lambda *_args, **_kwargs: [
            {
                "records": records,
                "status": {
                    "source_id": "moneydj",
                    "source_class": "financial_media",
                    "status": "ok",
                    "items": 2,
                },
            }
        ],
    )

    summary = run_update(
        registry_path=REGISTRY_PATH,
        output_dir=tmp_path / "output",
        window_hours=24,
        max_events=10,
        max_candidates=10,
    )

    events = json.loads((tmp_path / "output" / "theme-events.json").read_text(encoding="utf-8"))

    assert events["tw_relevance_distribution"] == {"direct": 1}
    assert summary["taiwan_relevance_states"] == {"direct": 1}


def test_build_theme_payloads_maps_rss_description_to_score_theme_relevance_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_score(record: dict[str, object], taxonomy: dict[str, object] | None = None) -> dict[str, object]:
        calls.append(dict(record))
        return {
            "theme_score": 0.7,
            "matched_themes": [
                {
                    "theme_id": "thermal_cooling",
                    "name_zh": "AI 伺服器液冷散熱",
                    "score": 0.7,
                    "signals": ["冷卻"],
                    "reason": "fixture",
                }
            ],
            "vetoed_theme_ids": [],
        }

    monkeypatch.setattr("scripts.theme_relevance.score_theme_relevance", fake_score)
    monkeypatch.setattr("scripts.update_theme_radar.score_theme_relevance", fake_score)
    taxonomy = load_theme_taxonomy(TAXONOMY_PATH)
    records = [
        {
            "id": "rss-no-summary",
            "title_zh": "DIGITIMES title",
            "description": "Detailed DIGITIMES description",
            "summary": "",
            "source": "DIGITIMES",
            "source_id": "digitimes_tw",
            "published_at": "2026-07-27T10:00:00Z",
            "url": "https://example.com/rss",
            "primary_theme_id": "thermal_cooling",
        }
    ]

    events, _ = build_theme_payloads(
        records,
        taxonomy,
        anchor=datetime(2026, 7, 27, 11, 0, tzinfo=timezone.utc),
        window_hours=24,
        max_events=10,
        max_candidates=10,
    )

    assert calls, "score_theme_relevance should be invoked during build_theme_payloads"
    assert any(call.get("summary") == "Detailed DIGITIMES description" for call in calls)
    assert events["total_items"] == 1


def _projection_contract_inputs() -> tuple[
    dict[str, object],
    list[dict[str, object]],
    datetime,
]:
    taxonomy: dict[str, object] = {
        "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"],
        "themes": [
            {
                "theme_id": "alpha_foundry",
                "name_zh": "Alpha",
                "keywords": ["alpha", "foundry"],
                "related_industries": ["IC"],
                "seed_symbols": ["2330"],
            },
            {
                "theme_id": "beta_server",
                "name_zh": "Beta",
                "keywords": ["beta", "server"],
                "related_industries": ["Server"],
                "seed_symbols": ["2382"],
            },
        ],
    }
    records: list[dict[str, object]] = [
        {
            "id": "alpha-representative",
            "title_zh": "alpha foundry expansion advances",
            "summary": "capacity",
            "source": "MoneyDJ",
            "source_id": "moneydj",
            "source_class": "financial_media",
            "market_id": "TW_EQUITY",
            "market_scope": ["TW_EQUITY"],
            "published_at": "2026-07-29T08:00:00Z",
            "url": "https://example.com/alpha-a",
            "extraction_method": "rss",
            "fetched_at": "2026-07-29T09:00:00Z",
        },
        {
            "id": "alpha-member",
            "title_zh": "台積電 alpha foundry expansion advances",
            "summary": "capacity",
            "source": "Unknown",
            "source_id": "unknown",
            "source_class": "financial_media",
            "market_id": "TW_EQUITY",
            "market_scope": ["TW_EQUITY"],
            "published_at": "2026-07-29T08:10:00Z",
            "url": "https://example.com/alpha-b",
            "extraction_method": "rss",
            "fetched_at": "2026-07-29T09:00:00Z",
        },
        {
            "id": "beta-one",
            "title_zh": "廣達 beta server demand expands",
            "summary": "capacity",
            "source": "Cnyes",
            "source_id": "cnyes",
            "source_class": "financial_media",
            "market_id": "TW_EQUITY",
            "market_scope": ["TW_EQUITY"],
            "published_at": "2026-07-29T07:00:00Z",
            "url": "https://example.com/beta",
            "extraction_method": "rss",
            "fetched_at": "2026-07-29T09:00:00Z",
        },
    ]
    return taxonomy, records, datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc)


def test_build_theme_projection_exposes_full_collections_before_caps() -> None:
    taxonomy, records, anchor = _projection_contract_inputs()

    events, candidates, projection = build_theme_projection(
        records,
        taxonomy,
        anchor=anchor,
        window_hours=72,
        max_events=1,
        max_candidates=1,
        source_authority={"moneydj": 1, "cnyes": 2, "unknown": 99},
    )

    assert len(events["items"]) == 1
    assert len(candidates["items"]) == 1
    assert len(projection["retained_records"]) == 3
    assert len(projection["clustered_events"]) == 2
    assert len(projection["candidate_clusters"]) == 2
    assert projection["market_id"] == "TW_EQUITY"
    assert projection["market_scope"] == ["TW_EQUITY"]


def test_projection_maps_every_cluster_member_to_one_cluster() -> None:
    taxonomy, records, anchor = _projection_contract_inputs()

    _, _, projection = build_theme_projection(
        records,
        taxonomy,
        anchor=anchor,
        window_hours=72,
        max_events=1,
        max_candidates=1,
        source_authority={"moneydj": 1, "cnyes": 2, "unknown": 99},
    )

    members_by_id = projection["cluster_members_by_id"]
    clustered = projection["clustered_events"]
    expected_member_ids = {
        member_id
        for event in clustered
        for member_id in event["cluster_event_ids"]
    }
    actual_member_ids = {
        member["id"]
        for members in members_by_id.values()
        for member in members
    }
    alpha_cluster = next(
        event for event in clustered if event["primary_theme_id"] == "alpha_foundry"
    )
    alpha_member = next(
        member
        for member in members_by_id[alpha_cluster["cluster_id"]]
        if member["id"] == "alpha-member"
    )

    assert set(members_by_id) == {event["cluster_id"] for event in clustered}
    assert actual_member_ids == expected_member_ids
    assert len(actual_member_ids) == sum(len(members) for members in members_by_id.values())
    assert alpha_cluster["id"] == "alpha-representative"
    assert [symbol["instrument_id"] for symbol in alpha_member["direct_symbols"]] == [
        "TWSE:2330"
    ]


def test_build_theme_payloads_keeps_two_value_compatibility() -> None:
    taxonomy, records, anchor = _projection_contract_inputs()

    result = build_theme_payloads(
        records,
        taxonomy,
        anchor=anchor,
        window_hours=72,
        max_events=1,
        max_candidates=1,
        source_authority={"moneydj": 1, "cnyes": 2, "unknown": 99},
    )

    assert isinstance(result, tuple)
    assert len(result) == 2


def test_projection_does_not_rerun_matcher_or_clustering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    taxonomy, records, anchor = _projection_contract_inputs()
    matcher_calls = 0
    clustering_calls = 0
    original_matcher = updater.enrich_item_with_themes
    original_clustering = updater.cluster_theme_events

    def count_matcher(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal matcher_calls
        matcher_calls += 1
        return original_matcher(*args, **kwargs)

    def count_clustering(*args: object, **kwargs: object) -> list[dict[str, object]]:
        nonlocal clustering_calls
        clustering_calls += 1
        return original_clustering(*args, **kwargs)

    monkeypatch.setattr(updater, "enrich_item_with_themes", count_matcher)
    monkeypatch.setattr(updater, "cluster_theme_events", count_clustering)

    build_theme_projection(
        records,
        taxonomy,
        anchor=anchor,
        window_hours=72,
        max_events=1,
        max_candidates=1,
        source_authority={"moneydj": 1, "cnyes": 2, "unknown": 99},
    )

    assert matcher_calls == len(records)
    assert clustering_calls == 1


PUBLIC_ANCHOR = datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc)
PUBLIC_THEME_ID = "memory_hbm"
PUBLIC_ALIASES = {
    "market_id": "TW_EQUITY",
    "market_scope": ["TW_EQUITY"],
    "symbols": {
        "2330": {
            "name_zh": "台積電",
            "exchange": "TWSE",
            "aliases": ["台積電"],
        },
        "NVDA": {
            "name_zh": "NVIDIA",
            "exchange": "NASDAQ",
            "aliases": ["NVIDIA"],
        },
    },
}
PUBLIC_TAXONOMY = {
    "market_id": "TW_EQUITY",
    "market_scope": ["TW_EQUITY"],
    "themes": [
        {
            "theme_id": PUBLIC_THEME_ID,
            "name_zh": "記憶體與 HBM",
            "seed_symbols": ["2330", "NVDA"],
        }
    ],
}


def _public_integration_cluster(
    cluster_id: str,
    *,
    source_id: str,
    published_at: str,
) -> dict[str, object]:
    return {
        "cluster_id": cluster_id,
        "cluster_event_ids": [f"member-{cluster_id}"],
        "cluster_size": 1,
        "id": f"event-{cluster_id}",
        "title_zh": f"台積電 HBM {cluster_id}",
        "summary": "記憶體需求增加",
        "source_id": source_id,
        "source": source_id,
        "published_at": published_at,
        "url": f"https://example.com/{cluster_id}",
        "primary_theme_id": PUBLIC_THEME_ID,
        "matched_themes": [{"theme_id": PUBLIC_THEME_ID, "score": 0.8}],
        "theme_score": 0.8,
        "tw_related_symbols": ["TWSE:2330", "NASDAQ:NVDA"],
        "related_symbols": [
            {
                "instrument_id": "TWSE:2330",
                "symbol": "2330",
                "exchange": "TWSE",
                "name_zh": "台積電",
                "evidence": f"taxonomy seed: {PUBLIC_THEME_ID}",
            },
            {
                "instrument_id": "NASDAQ:NVDA",
                "symbol": "NVDA",
                "exchange": "NASDAQ",
                "name_zh": "NVIDIA",
                "evidence": f"taxonomy seed: {PUBLIC_THEME_ID}",
            },
        ],
        "cluster_sources": [
            {
                "source_id": source_id,
                "source": source_id,
                "title": f"台積電 HBM {cluster_id}",
                "url": f"https://example.com/{cluster_id}",
                "published_at": published_at,
            }
        ],
    }


def _public_integration_projection(cluster_count: int = 2) -> dict[str, object]:
    clusters = [
        _public_integration_cluster(
            "cluster-a",
            source_id="publisher-a",
            published_at="2026-07-29T08:00:00Z",
        ),
        _public_integration_cluster(
            "cluster-b",
            source_id="publisher-b",
            published_at="2026-07-29T07:00:00Z",
        ),
    ][:cluster_count]
    members_by_id = {
        cluster["cluster_id"]: [
            {
                "id": cluster["cluster_event_ids"][0],
                "published_at": cluster["published_at"],
                "direct_symbols": [
                    {
                        "instrument_id": "TWSE:2330",
                        "symbol": "2330",
                        "exchange": "TWSE",
                        "name_zh": "台積電",
                    },
                    {
                        "instrument_id": "NASDAQ:NVDA",
                        "symbol": "NVDA",
                        "exchange": "NASDAQ",
                        "name_zh": "NVIDIA",
                    },
                ],
                "related_symbols": deepcopy(cluster["related_symbols"]),
            }
        ]
        for cluster in clusters
    }
    return {
        "retained_records": [
            deepcopy(member)
            for cluster_id in sorted(members_by_id)
            for member in members_by_id[cluster_id]
        ],
        "clustered_events": deepcopy(clusters),
        "candidate_clusters": deepcopy(clusters),
        "cluster_members_by_id": members_by_id,
        "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"],
    }


def _legacy_integration_payload(
    items: list[dict[str, object]],
    *,
    available_count: int,
    max_items: int,
) -> dict[str, object]:
    return {
        "generated_at": PUBLIC_ANCHOR.isoformat().replace("+00:00", "Z"),
        "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"],
        "window_hours": 72,
        "max_items": max_items,
        "total_items": len(items),
        "total_items_available": available_count,
        "items": deepcopy(items),
        "pre_cluster_items": available_count,
        "excluded_items": 0,
        "tw_relevance_distribution": {"direct": available_count},
        "tw_relevance_reason_distribution": {"direct Taiwan symbol match": available_count},
        "selected_theme_score_min": 0.3,
        "candidate_theme_score_min": 0.5,
        "matcher_contract": "hybrid_required_any_v1",
        "taxonomy_version": "v0.7",
        "legacy_theme_count": 1,
        "structured_theme_count": 0,
        "theme_match_distribution": {PUBLIC_THEME_ID: available_count},
        "theme_veto_distribution": {},
    }


def _official_integration_payload() -> dict[str, object]:
    return {
        "generated_at": PUBLIC_ANCHOR.isoformat().replace("+00:00", "Z"),
        "window_hours": 72,
        "max_items": 500,
        "total_items": 1,
        "total_items_available": 1,
        "items": [
            {
                "evidence_id": "official-2330",
                "instrument_id": "TWSE:2330",
                "symbol": "2330",
                "exchange": "TWSE",
                "company_name": "台積電",
                "title": "台積電 HBM",
                "summary": "記憶體需求增加",
                "published_at": "2026-07-29T06:00:00Z",
            }
        ],
    }


def _public_integration_registry() -> dict[str, object]:
    return {
        "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"],
        "sources": [
            {
                "source_id": "publisher-a",
                "name": "Publisher A",
                "source_class": "financial_media",
                "fetch_method": "rss",
                "status": "active",
                "authority_rank": 1,
            },
            {
                "source_id": "publisher-b",
                "name": "Publisher B",
                "source_class": "financial_media",
                "fetch_method": "rss",
                "status": "active",
                "authority_rank": 2,
            },
            {
                "source_id": "mops",
                "name": "MOPS",
                "source_class": "official_disclosure",
                "fetch_method": "rss",
                "status": "active",
                "authority_rank": 3,
            },
        ],
    }


def _public_integration_results(
    *,
    discovery_failure: bool = False,
    official_available: bool = True,
) -> list[dict[str, object]]:
    return [
        {
            "records": [{"id": "raw-a"}],
            "status": {
                "source_id": "publisher-a",
                "source_class": "financial_media",
                "status": "ok",
                "items": 1,
            },
        },
        {
            "records": [] if discovery_failure else [{"id": "raw-b"}],
            "status": {
                "source_id": "publisher-b",
                "source_class": "financial_media",
                "status": "error" if discovery_failure else "ok",
                "items": 0 if discovery_failure else 1,
                "error": "fixture failure" if discovery_failure else None,
            },
        },
        {
            "records": [{"evidence_id": "official-2330"}] if official_available else [],
            "status": {
                "source_id": "mops",
                "source_class": "official_disclosure",
                "status": "ok" if official_available else "error",
                "items": 1 if official_available else 0,
                "datasets_ok": 1 if official_available else 0,
                "error": None if official_available else "fixture failure",
            },
        },
    ]


def _install_public_integration_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cluster_count: int = 2,
    discovery_failure: bool = False,
    official_available: bool = True,
) -> dict[str, object]:
    calls: dict[str, object] = {
        "projection": 0,
        "attach_sizes": [],
        "projector": 0,
        "aliases": 0,
    }
    projection = _public_integration_projection(cluster_count)

    def fake_projection(*_args: object, **_kwargs: object) -> tuple[
        dict[str, object],
        dict[str, object],
        dict[str, object],
    ]:
        calls["projection"] = int(calls["projection"]) + 1
        clusters = projection["clustered_events"]
        candidates = projection["candidate_clusters"]
        return (
            _legacy_integration_payload(
                clusters[:1],
                available_count=len(clusters),
                max_items=1,
            ),
            _legacy_integration_payload(
                candidates[:1],
                available_count=len(candidates),
                max_items=1,
            ),
            deepcopy(projection),
        )

    def fake_attach(
        events: list[dict[str, object]],
        _evidence: list[dict[str, object]],
        *,
        official_available: bool,
        **_kwargs: object,
    ) -> list[dict[str, object]]:
        calls["attach_sizes"].append(len(events))
        evidence_ids = ["official-2330"] if official_available else []
        return [
            {
                **event,
                "confirmation_status": (
                    "confirmed" if official_available else "unavailable"
                ),
                "official_evidence_ids": evidence_ids,
                "official_evidence_count": len(evidence_ids),
            }
            for event in events
        ]

    def fake_aliases(*_args: object, **_kwargs: object) -> dict[str, object]:
        calls["aliases"] = int(calls["aliases"]) + 1
        return deepcopy(PUBLIC_ALIASES)

    def count_projector(*args: object, **kwargs: object) -> tuple[
        dict[str, object],
        dict[str, object],
    ]:
        calls["projector"] = int(calls["projector"]) + 1
        return build_public_theme_ranking(*args, **kwargs)

    monkeypatch.setattr(updater, "now_utc", lambda: PUBLIC_ANCHOR)
    monkeypatch.setattr(
        updater,
        "load_source_registry",
        lambda _path: deepcopy(_public_integration_registry()),
    )
    monkeypatch.setattr(
        updater,
        "load_theme_taxonomy",
        lambda: deepcopy(PUBLIC_TAXONOMY),
    )
    monkeypatch.setattr(updater, "load_symbol_aliases", fake_aliases)
    monkeypatch.setattr(
        updater,
        "dispatch_sources",
        lambda *_args, **_kwargs: deepcopy(
            _public_integration_results(
                discovery_failure=discovery_failure,
                official_available=official_available,
            )
        ),
    )
    monkeypatch.setattr(updater, "build_theme_projection", fake_projection)
    monkeypatch.setattr(updater, "attach_official_evidence", fake_attach)
    monkeypatch.setattr(
        updater,
        "build_official_evidence_payload",
        lambda *_args, **_kwargs: deepcopy(_official_integration_payload()),
    )
    monkeypatch.setattr(updater, "build_public_theme_ranking", count_projector)
    return calls


def test_run_update_public_ranking_integration_uses_full_collections_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls = _install_public_integration_fakes(monkeypatch)
    output_dir = tmp_path / "output"

    summary = run_update(
        registry_path=tmp_path / "registry.json",
        output_dir=output_dir,
        window_hours=72,
        max_events=1,
        max_candidates=1,
    )

    public_payload = json.loads(
        (output_dir / "public-theme-ranking-v0.8.json").read_text(encoding="utf-8")
    )
    legacy_events = json.loads(
        (output_dir / "theme-events.json").read_text(encoding="utf-8")
    )
    legacy_candidates = json.loads(
        (output_dir / "tracking-candidates.json").read_text(encoding="utf-8")
    )

    assert calls == {
        "projection": 1,
        "attach_sizes": [2, 2],
        "projector": 1,
        "aliases": 1,
    }
    assert len(legacy_events["items"]) == 1
    assert len(legacy_candidates["items"]) == 1
    assert public_payload["generated_at"] == "2026-07-29T09:00:00Z"
    assert public_payload["market_id"] == "TW_EQUITY"
    assert public_payload["market_scope"] == ["TW_EQUITY"]
    assert public_payload["window_hours"] == 72
    assert public_payload["qualified_theme_count"] == 1
    assert public_payload["themes"][0]["summaries"]["event_count"] == 2
    assert public_payload["themes"][0]["summaries"]["tracking_candidate_count"] == 2
    assert all(
        company["exchange"] in {"TWSE", "TPEX"}
        for key in ("direct_mentions", "supply_chain_candidates")
        for company in public_payload["themes"][0][key]
    )
    assert "NVDA" not in json.dumps(public_payload, ensure_ascii=False)
    assert summary["public_themes_qualified"] == 1


def test_discovery_failure_is_partial_without_lowering_public_eligibility(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_public_integration_fakes(
        monkeypatch,
        cluster_count=1,
        discovery_failure=True,
    )
    output_dir = tmp_path / "output"

    run_update(
        registry_path=tmp_path / "registry.json",
        output_dir=output_dir,
        window_hours=72,
        max_events=1,
        max_candidates=1,
    )

    payload = json.loads(
        (output_dir / "public-theme-ranking-v0.8.json").read_text(encoding="utf-8")
    )
    assert payload["generation_status"] == "partial"
    assert payload["failed_source_count"] == 1
    assert payload["qualified_theme_count"] == 0
    assert payload["themes"] == []


def test_official_unavailable_changes_only_company_official_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = {"available": True}
    calls = _install_public_integration_fakes(monkeypatch)

    def dispatch_for_state(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return deepcopy(
            _public_integration_results(official_available=state["available"])
        )

    monkeypatch.setattr(updater, "dispatch_sources", dispatch_for_state)
    available_dir = tmp_path / "available"
    run_update(
        registry_path=tmp_path / "registry.json",
        output_dir=available_dir,
        window_hours=72,
        max_events=1,
        max_candidates=1,
    )
    state["available"] = False
    unavailable_dir = tmp_path / "unavailable"
    run_update(
        registry_path=tmp_path / "registry.json",
        output_dir=unavailable_dir,
        window_hours=72,
        max_events=1,
        max_candidates=1,
    )

    available = json.loads(
        (available_dir / "public-theme-ranking-v0.8.json").read_text(encoding="utf-8")
    )
    unavailable = json.loads(
        (unavailable_dir / "public-theme-ranking-v0.8.json").read_text(
            encoding="utf-8"
        )
    )
    available_theme = available["themes"][0]
    unavailable_theme = unavailable["themes"][0]

    assert calls["projection"] == 2
    assert calls["projector"] == 2
    assert available["official_evidence_status"] == "available"
    assert unavailable["official_evidence_status"] == "unavailable"
    assert unavailable["generation_status"] == "complete"
    assert unavailable["failed_source_count"] == 0
    assert available_theme["theme_id"] == unavailable_theme["theme_id"]
    assert available_theme["heat_score"] == unavailable_theme["heat_score"]
    assert available_theme["summaries"] == unavailable_theme["summaries"]
    assert available_theme["representative_news"] == unavailable_theme[
        "representative_news"
    ]
    assert any(
        company.get("official_marker") == "近期官方佐證"
        for company in available_theme["supply_chain_candidates"]
    )
    assert all(
        "official_marker" not in company
        for company in unavailable_theme["supply_chain_candidates"]
    )


def _json_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise AssertionError(f"unsupported fixture value type: {type(value).__name__}")


def _existing_contract_payloads() -> dict[str, dict[str, object]]:
    taxonomy, records, anchor = _projection_contract_inputs()
    events, candidates, _ = build_theme_projection(
        records,
        taxonomy,
        anchor=anchor,
        window_hours=72,
        max_events=1,
        max_candidates=1,
        source_authority={"moneydj": 1, "cnyes": 2, "unknown": 99},
    )
    events = {
        **events,
        "items": updater.attach_official_evidence(
            events["items"],
            [],
            official_available=False,
        ),
    }
    candidates = {
        **candidates,
        "items": updater.attach_official_evidence(
            candidates["items"],
            [],
            official_available=False,
        ),
    }
    source_status = source_status_payload(
        [
            {
                "source_id": "moneydj",
                "name": "MoneyDJ",
                "source_class": "financial_media",
                "adapter": "generic_rss",
                "fetch_method": "rss",
                "status": "ok",
                "items": 3,
                "error": None,
                "feed_url": "https://example.com/feed.xml",
                "elapsed_ms": 10,
            }
        ],
        anchor,
        3,
    )
    official_evidence = {
        "generated_at": anchor.isoformat().replace("+00:00", "Z"),
        "market_id": "TW_EQUITY",
        "window_hours": 72,
        "max_items": 500,
        "total_items": 1,
        "total_items_available": 1,
        "allocation_policy": "dataset_round_robin_v1",
        "datasets_represented": 1,
        "dataset_distribution": {"material_information": 1},
        "items": [
            {
                "evidence_id": "official-contract",
                "source_id": "mops",
                "source_class": "official_disclosure",
                "adapter": "twse_openapi",
                "dataset_id": "material_information",
                "category": "material_information",
                "market_id": "TW_EQUITY",
                "instrument_id": "TWSE:2330",
                "symbol": "2330",
                "company_name": "台積電",
                "title": "台積電重大訊息",
                "summary": None,
                "published_at": "2026-07-29T08:00:00Z",
                "effective_at": None,
                "canonical_url": "https://mops.twse.com.tw/example",
                "raw_reference": "fixture",
                "fetched_at": "2026-07-29T09:00:00Z",
            }
        ],
    }
    return {
        "theme-events.json": events,
        "tracking-candidates.json": candidates,
        "source-status.json": source_status,
        "official-evidence.json": official_evidence,
    }


def _valid_payload_set() -> dict[str, dict[str, object]]:
    payloads = _existing_contract_payloads()
    public_payload, _ = build_public_theme_ranking(
        _public_integration_projection(),
        taxonomy=deepcopy(PUBLIC_TAXONOMY),
        symbol_aliases=deepcopy(PUBLIC_ALIASES),
        official_evidence_by_id={},
        source_status={"failed_count": 0},
        generated_at=PUBLIC_ANCHOR,
        window_hours=72,
        official_evidence_status="unavailable",
    )
    return {**payloads, "public-theme-ranking-v0.8.json": public_payload}


def test_existing_payload_contract_fixture_freezes_keys_types_thresholds_and_caps() -> None:
    fixture = json.loads(EXISTING_PAYLOAD_CONTRACT_FIXTURE.read_text(encoding="utf-8"))
    payloads = _existing_contract_payloads()

    for filename, payload in payloads.items():
        expected = fixture[filename]
        assert {key: _json_type(value) for key, value in payload.items()} == expected[
            "top_level"
        ]
        collection = payload["sites"] if filename == "source-status.json" else payload["items"]
        assert {
            key: _json_type(value) for key, value in collection[0].items()
        } == expected["item"]

    constants = fixture["constants"]
    assert payloads["theme-events.json"]["selected_theme_score_min"] == constants[
        "selected_theme_score_min"
    ]
    assert payloads["theme-events.json"]["candidate_theme_score_min"] == constants[
        "candidate_theme_score_min"
    ]
    assert payloads["theme-events.json"]["max_items"] == constants["event_cap"]
    assert payloads["tracking-candidates.json"]["max_items"] == constants[
        "candidate_cap"
    ]
    assert payloads["theme-events.json"]["total_items_available"] == 2
    assert payloads["tracking-candidates.json"]["total_items_available"] == 2


def test_validate_payload_set_requires_exact_five_shared_payloads() -> None:
    payloads = _valid_payload_set()

    validate_payload_set(
        payloads,
        generated_at=PUBLIC_ANCHOR,
        market_id="TW_EQUITY",
        market_scope=["TW_EQUITY"],
        window_hours=72,
    )

    for filename, field, invalid in (
        ("source-status.json", "generated_at", "2026-07-29T08:00:00Z"),
        ("theme-events.json", "market_id", "US_EQUITY"),
        ("tracking-candidates.json", "market_scope", ["US_EQUITY"]),
        ("official-evidence.json", "window_hours", 24),
    ):
        changed = deepcopy(payloads)
        changed[filename][field] = invalid
        with pytest.raises(ValueError):
            validate_payload_set(
                changed,
                generated_at=PUBLIC_ANCHOR,
                market_id="TW_EQUITY",
                market_scope=["TW_EQUITY"],
                window_hours=72,
            )

    missing = deepcopy(payloads)
    missing.pop("source-status.json")
    with pytest.raises(ValueError):
        validate_payload_set(
            missing,
            generated_at=PUBLIC_ANCHOR,
            market_id="TW_EQUITY",
            market_scope=["TW_EQUITY"],
            window_hours=72,
        )


def test_write_failure_before_replacement_preserves_all_destination_bytes(
    tmp_path: Path,
) -> None:
    payloads = _valid_payload_set()
    expected_bytes = {}
    for filename in payloads:
        path = tmp_path / filename
        original = f"original:{filename}\n".encode()
        path.write_bytes(original)
        expected_bytes[filename] = original
    payloads["source-status.json"]["sites"].append({"not_serializable": {1, 2}})

    with pytest.raises(TypeError):
        write_payload_set(tmp_path, payloads)

    assert {
        filename: (tmp_path / filename).read_bytes() for filename in payloads
    } == expected_bytes
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(payloads)


def test_write_payload_set_replaces_in_fixed_order_and_cleans_temps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payloads = _valid_payload_set()
    replacement_order: list[str] = []
    original_replace = Path.replace

    def track_replace(path: Path, target: Path) -> Path:
        replacement_order.append(Path(target).name)
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", track_replace)
    write_payload_set(tmp_path, payloads)

    assert replacement_order == [
        "theme-events.json",
        "tracking-candidates.json",
        "source-status.json",
        "official-evidence.json",
        "public-theme-ranking-v0.8.json",
    ]
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(payloads)
    for filename, payload in payloads.items():
        assert json.loads((tmp_path / filename).read_text(encoding="utf-8")) == payload
        assert (tmp_path / filename).read_bytes().endswith(b"\n")


def test_write_failure_during_first_replacement_cleans_temp_siblings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payloads = _valid_payload_set()
    expected_bytes = {}
    for filename in payloads:
        path = tmp_path / filename
        original = f"original:{filename}\n".encode()
        path.write_bytes(original)
        expected_bytes[filename] = original

    def fail_replace(_path: Path, _target: Path) -> Path:
        raise OSError("fixture replacement failure")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="fixture replacement failure"):
        write_payload_set(tmp_path, payloads)

    assert {
        filename: (tmp_path / filename).read_bytes() for filename in payloads
    } == expected_bytes
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(payloads)


def test_run_update_validates_complete_payload_set_before_first_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_public_integration_fakes(monkeypatch)
    trace: list[str] = []
    original_validate = updater.validate_payload_set
    original_replace = Path.replace

    def track_validate(*args: object, **kwargs: object) -> None:
        trace.append("validate")
        original_validate(*args, **kwargs)

    def track_replace(path: Path, target: Path) -> Path:
        trace.append(f"replace:{Path(target).name}")
        return original_replace(path, target)

    monkeypatch.setattr(updater, "validate_payload_set", track_validate)
    monkeypatch.setattr(Path, "replace", track_replace)

    run_update(
        registry_path=tmp_path / "registry.json",
        output_dir=tmp_path / "output",
        window_hours=72,
        max_events=1,
        max_candidates=1,
    )

    assert trace == [
        "validate",
        "replace:theme-events.json",
        "replace:tracking-candidates.json",
        "replace:source-status.json",
        "replace:official-evidence.json",
        "replace:public-theme-ranking-v0.8.json",
        "replace:public-theme-momentum-latest-v0.9.json",
    ]


def test_public_observability_summary_and_failure_logging_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _install_public_integration_fakes(
        monkeypatch,
        cluster_count=1,
        discovery_failure=True,
    )
    caplog.set_level("WARNING")

    summary = run_update(
        registry_path=tmp_path / "registry.json",
        output_dir=tmp_path / "output",
        window_hours=72,
        max_events=1,
        max_candidates=1,
    )

    observability_fields = {
        "public_themes_qualified",
        "public_themes_displayed",
        "public_themes_omitted_invalid",
        "public_direct_company_count",
        "public_supply_chain_company_count",
        "public_derivation_error_count",
        "public_generation_status",
    }
    assert observability_fields <= set(summary)
    assert "eligibility_failures" not in summary
    messages = [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("public_theme_eligibility_failure ")
    ]
    assert messages
    assert all(
        message.split()
        == [
            "public_theme_eligibility_failure",
            f"theme_id={PUBLIC_THEME_ID}",
            message.split()[2],
        ]
        and message.split()[2].startswith("rule_code=")
        and message.split()[2][len("rule_code=") :].replace("_", "").isalnum()
        for message in messages
    )
    assert all("https://" not in message and "HBM" not in message for message in messages)
