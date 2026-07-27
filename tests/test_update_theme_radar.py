from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import pytest

from scripts.update_theme_radar import (
    build_theme_payloads,
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
    }
    assert all(source["feed_url"].startswith("https://") for source in sources)
    assert all(source["fetch_method"] == "rss" for source in sources)
    assert all(source["market_scope"] == ["TW_EQUITY"] for source in sources)
    cnyes = next(source for source in sources if source["source_id"] == "cnyes")
    assert cnyes["status"] == "active"
    assert cnyes["feed_url"] == "https://news.cnyes.com/rss/v1/news/category/all"


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
