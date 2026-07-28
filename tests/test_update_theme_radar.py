from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from copy import deepcopy

import feedparser
import pytest
import requests

from scripts.update_theme_radar import (
    CANDIDATE_THEME_SCORE_MIN,
    SELECTED_THEME_SCORE_MIN,
    build_theme_payloads,
    classify_taiwan_relevance,
    cluster_theme_events,
    dedupe_records,
    fetch_rss_source,
    load_source_registry,
    normalize_feed_entry,
    rss_sources,
    run_update,
    source_authority_ranks,
    source_status_payload,
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
