from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import pytest

from scripts.update_theme_radar import (
    build_theme_payloads,
    dedupe_records,
    load_source_registry,
    normalize_feed_entry,
    rss_sources,
    run_update,
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

    def fake_fetch(_session, source, fetched_at):
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

    assert calls == ["moneydj", "cnyes", "yahoo_finance_tw"]
    assert summary["raw_items"] == 2
    assert summary["failed_sources"] == 1
    assert status["successful_sites"] == 2
    assert status["failed_sites"] == ["cnyes"]
