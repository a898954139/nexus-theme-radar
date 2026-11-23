"""Fetch public Taiwan-market RSS/news feeds and publish static theme radar JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import tempfile
import time
import uuid
from functools import partial
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import feedparser
import requests

try:
    from scripts.public_theme_ranking import (
        PUBLIC_WINDOW_HOURS,
        build_public_theme_signals,
        build_public_theme_ranking,
        validate_public_theme_ranking,
    )
    from scripts.public_theme_momentum import build_public_theme_momentum
    from scripts.fundamentals_pipeline import (
        DEFAULT_MAX_FETCHES,
        FUNDAMENTALS_CACHE_FILE,
        enrich_with_fundamentals,
        load_fundamentals_cache,
        write_fundamentals_cache,
    )
    from scripts.goodinfo_fundamentals import fetch_symbol_fundamentals
    from scripts.day_trading_activity import (
        DAY_TRADING_CACHE_FILENAME,
        TPEX_DAILY_URL,
        TPEX_INTRADAY_URL,
        TWSE_MI_INDEX_URL,
        TWSE_TWTB4U_URL,
        refresh_day_trading_cache,
        select_settled_target,
        validate_day_trading_cache,
    )
    from scripts.moat_screen import (
        MOAT_SCREEN_FILENAME,
        load_fundamentals_universe,
        screen_summary,
        screen_universe,
    )
    from scripts.stock_watchlist import (
        PUBLIC_STOCK_WATCHLIST_FILENAME,
        build_stock_watchlist,
        write_stock_watchlist,
    )
    from scripts.theme_heat_history_store import (
        delete_expired_observations,
        load_momentum_baselines,
        write_theme_observations,
    )
    from scripts.materialize_public_theme_history import (
        load_history_rows,
        materialize_public_theme_history,
    )
    from scripts.rss_feed_state import (
        FEED_STATE_FILENAME,
        INTAKE_STORE_FILENAME,
        build_intake_store,
        cached_items,
        conditional_headers,
        fresh_entry,
        load_feed_state,
        load_intake_items,
        record_run_history,
        serialize_feed_state,
        write_json_atomic,
    )
    from scripts.monthly_revenue import run_monthly_revenue
    from scripts.radar_store import redact_error, write_radar_run
    from scripts.ingested_articles import is_ingest_origin, load_ingested_results
    from scripts.source_adapters import (
        CONFLICT_TERMS,
        build_official_evidence_payload,
        fetch_twse_openapi_source,
        load_dataset_catalog,
        read_bounded_response,
    )
    from scripts.theme_relevance import (
        enrich_item_with_themes,
        load_theme_taxonomy,
        score_theme_relevance,
    )
    from scripts.symbol_mapping import (
        augment_symbol_aliases_with_registry,
        instrument_for_symbol,
        load_symbol_aliases,
    )
    from scripts.market_impact import (
        IMPACT_KEEP_MIN,
        find_bursts,
        load_market_movers,
        score_impact,
    )
except ModuleNotFoundError:
    from public_theme_ranking import (
        PUBLIC_WINDOW_HOURS,
        build_public_theme_signals,
        build_public_theme_ranking,
        validate_public_theme_ranking,
    )
    from public_theme_momentum import build_public_theme_momentum
    from fundamentals_pipeline import (
        DEFAULT_MAX_FETCHES,
        FUNDAMENTALS_CACHE_FILE,
        enrich_with_fundamentals,
        load_fundamentals_cache,
        write_fundamentals_cache,
    )
    from goodinfo_fundamentals import fetch_symbol_fundamentals
    from day_trading_activity import (
        DAY_TRADING_CACHE_FILENAME,
        TPEX_DAILY_URL,
        TPEX_INTRADAY_URL,
        TWSE_MI_INDEX_URL,
        TWSE_TWTB4U_URL,
        refresh_day_trading_cache,
        select_settled_target,
        validate_day_trading_cache,
    )
    from moat_screen import (
        MOAT_SCREEN_FILENAME,
        load_fundamentals_universe,
        screen_summary,
        screen_universe,
    )
    from stock_watchlist import (
        PUBLIC_STOCK_WATCHLIST_FILENAME,
        build_stock_watchlist,
        write_stock_watchlist,
    )
    from theme_heat_history_store import (
        delete_expired_observations,
        load_momentum_baselines,
        write_theme_observations,
    )
    from materialize_public_theme_history import (
        load_history_rows,
        materialize_public_theme_history,
    )
    from rss_feed_state import (
        FEED_STATE_FILENAME,
        INTAKE_STORE_FILENAME,
        build_intake_store,
        cached_items,
        conditional_headers,
        fresh_entry,
        load_feed_state,
        load_intake_items,
        record_run_history,
        serialize_feed_state,
        write_json_atomic,
    )
    from monthly_revenue import run_monthly_revenue
    from radar_store import redact_error, write_radar_run
    from ingested_articles import is_ingest_origin, load_ingested_results
    from source_adapters import (
        CONFLICT_TERMS,
        build_official_evidence_payload,
        fetch_twse_openapi_source,
        load_dataset_catalog,
        read_bounded_response,
    )
    from theme_relevance import (
        enrich_item_with_themes,
        load_theme_taxonomy,
        score_theme_relevance,
    )
    from symbol_mapping import (
        augment_symbol_aliases_with_registry,
        instrument_for_symbol,
        load_symbol_aliases,
    )
    from market_impact import (
        IMPACT_KEEP_MIN,
        find_bursts,
        load_market_movers,
        score_impact,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = ROOT / "config" / "source_registry.tw.json"
DEFAULT_OUTPUT_DIR = ROOT / "data"
REQUEST_TIMEOUT_SECONDS = 20
MAX_RSS_RESPONSE_BYTES = 8 * 1024 * 1024
USER_AGENT = "TaiwanEquityThemeRadar/0.1 (+https://github.com/)"
MAX_SOURCE_WORKERS = 5
UNKNOWN_AUTHORITY_RANK = 99
DEFAULT_CLUSTER_WINDOW_HOURS = 36
TITLE_TOKEN_SIMILARITY_THRESHOLD = 0.35
SELECTED_THEME_SCORE_MIN = 0.3
CANDIDATE_THEME_SCORE_MIN = 0.5
PAYLOAD_FILENAMES = (
    "theme-events.json",
    "tracking-candidates.json",
    "source-status.json",
    "official-evidence.json",
    "public-theme-ranking-v0.8.json",
)
PUBLIC_OBSERVABILITY_FIELDS = (
    "public_themes_qualified",
    "public_themes_displayed",
    "public_themes_omitted_invalid",
    "public_direct_company_count",
    "public_supply_chain_company_count",
    "public_derivation_error_count",
    "public_generation_status",
)
MOMENTUM_LATEST_FILENAME = "public-theme-momentum-latest-v0.9.json"
MOMENTUM_HISTORY_FILENAME = "public-theme-momentum-history-v0.9.json"
LOGGER = logging.getLogger(__name__)


class StockWatchlistPublishError(RuntimeError):
    """Raised when the required public watchlist cannot be built or written."""
GENERIC_SUPPLY_CHAIN_SIGNALS = {
    "ai",
    "科技",
    "科技股",
    "記憶體",
    "半導體",
    "市場",
}
ENTITY_NOISE_TERMS = (
    "ai",
    "科技",
    "產業",
    "市場",
    "記憶體",
    "伺服器",
    "載板",
    "產能",
    "投產",
    "上市",
    "ipo",
    "a股",
    "股價",
    "目標價",
    "里程碑",
    "正式",
    "完成",
    "啟動",
    "公布",
    "需求",
    "新高",
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: str | None, fallback: datetime | None = None) -> datetime:
    if value:
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return fallback or now_utc()


def stable_id(source_id: str, url: str, title: str) -> str:
    raw = f"{source_id}|{url}|{title}".encode("utf-8")
    return f"{source_id}-{hashlib.sha1(raw).hexdigest()[:12]}"


def load_source_registry(path: str | Path = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("source registry must contain a non-empty sources array")
    for source in sources:
        authority_rank = source.get("authority_rank")
        if authority_rank is not None and (
            not isinstance(authority_rank, int)
            or isinstance(authority_rank, bool)
            or authority_rank < 0
        ):
            raise ValueError(f"invalid source authority rank: {source.get('source_id')}")
    return payload


def source_authority_ranks(registry: dict[str, Any]) -> dict[str, int]:
    return {
        str(source["source_id"]): int(
            source.get("authority_rank", UNKNOWN_AUTHORITY_RANK)
        )
        for source in registry.get("sources", [])
        if source.get("source_id")
    }


def active_sources(registry: dict[str, Any]) -> list[dict[str, Any]]:
    market_id = registry.get("market_id") or "TW_EQUITY"
    market_scope = registry.get("market_scope") or [market_id]
    return sorted(
        [
            {
                "market_id": market_id,
                "market_scope": market_scope,
                **source,
            }
            for source in registry.get("sources", [])
            if source.get("status") == "active" and source.get("fetch_method")
        ],
        key=lambda source: str(source["source_id"]),
    )


def trial_sources(registry: dict[str, Any]) -> list[dict[str, Any]]:
    """RSS sources under evaluation: fetched and health-tracked every run, but
    their records stay out of the public projection until promoted to active."""
    market_id = registry.get("market_id") or "TW_EQUITY"
    market_scope = registry.get("market_scope") or [market_id]
    return sorted(
        [
            {"market_id": market_id, "market_scope": market_scope, **source}
            for source in registry.get("sources", [])
            if source.get("status") == "trial"
            and source.get("fetch_method") == "rss"
            and source.get("feed_url")
        ],
        key=lambda source: str(source["source_id"]),
    )


def rss_sources(registry: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        source
        for source in active_sources(registry)
        if source.get("fetch_method") == "rss" and source.get("feed_url")
    ]


MAX_FUTURE_PUBLISHED_SKEW = timedelta(minutes=15)


def feed_published_at(raw: Any, source: Mapping[str, Any], fetched_at: datetime) -> str:
    """Publish time in UTC, corrected for feeds that mislabel their timezone.

    ``published_at_offset_hours`` fixes a feed that writes local time with a
    UTC designator (e.g. 工商時報 stamps Taipei time as ``+0000``, so the
    registry sets ``-8``). Anything still in the future is clamped to the
    fetch time, so a mislabeled item cannot pin itself to the top of the
    window.
    """
    published = parse_timestamp(raw, fetched_at)
    offset = source.get("published_at_offset_hours")
    if raw and isinstance(offset, (int, float)) and not isinstance(offset, bool):
        published = published + timedelta(hours=offset)
    if published > fetched_at + MAX_FUTURE_PUBLISHED_SKEW:
        published = fetched_at
    return published.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_feed_entry(entry: Any, source: dict[str, Any], fetched_at: datetime) -> dict[str, Any] | None:
    title = str(getattr(entry, "title", "") or "").strip()
    link = str(getattr(entry, "link", "") or "").strip()
    if not title or not link:
        return None
    published_raw = (
        getattr(entry, "published", None)
        or getattr(entry, "updated", None)
        or getattr(entry, "created", None)
    )
    summary = str(getattr(entry, "summary", "") or "").strip()
    source_id = str(source["source_id"])
    return {
        "id": stable_id(source_id, link, title),
        "title_zh": title,
        "summary": summary,
        "source": source.get("name") or source_id,
        "source_id": source_id,
        "source_class": source.get("source_class"),
        "market_id": source.get("market_id") or "TW_EQUITY",
        "market_scope": source.get("market_scope") or ["TW_EQUITY"],
        "published_at": feed_published_at(published_raw, source, fetched_at),
        "url": link,
        "extraction_method": "rss",
        "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
    }


def fetch_rss_source(
    session: requests.Session,
    source: dict[str, Any],
    fetched_at: datetime,
    *,
    full_refresh: bool = False,
    feed_state: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fetch one RSS feed, revalidating with ETag / If-Modified-Since.

    ``feed_state`` is the previous run's per-source cache. When the feed
    answers 304 the cached items are replayed, because every run publishes a
    fresh snapshot and an empty result would drop the source from the window.
    The returned ``feed_state`` entry is persisted by ``run_update``.
    """
    started = time.monotonic()
    feed_url = str(source["feed_url"])
    source_id = str(source["source_id"])
    previous = (feed_state or {}).get(source_id)
    status = {
        "source_id": source_id,
        "name": source.get("name") or source_id,
        "source_class": source.get("source_class"),
        "fetch_method": "rss",
        "feed_url": feed_url,
        "status": "ok",
        "items": 0,
        "error": None,
        "elapsed_ms": 0,
    }
    if source.get("status") == "trial":
        status["trial"] = True
    new_state: dict[str, Any] | None = dict(previous) if previous else None
    response = None
    try:
        max_response_bytes = max(
            1,
            int(source.get("max_response_bytes") or MAX_RSS_RESPONSE_BYTES),
        )
        headers = {} if full_refresh else conditional_headers(previous, feed_url)
        response = session.get(
            feed_url,
            timeout=int(source.get("timeout_seconds") or REQUEST_TIMEOUT_SECONDS),
            stream=True,
            headers=headers or None,
        )
        if getattr(response, "status_code", None) == 304 and headers:
            items = cached_items(previous)
            status["not_modified"] = True
            status["items"] = len(items)
            return {"records": items, "status": status, "feed_state": new_state}
        response.raise_for_status()
        body = read_bounded_response(response, max_bytes=max_response_bytes)
        parsed = feedparser.parse(body)
        if getattr(parsed, "bozo", False) and not getattr(parsed, "entries", None):
            raise ValueError(f"invalid feed: {getattr(parsed, 'bozo_exception', 'unknown')}")
        items = [
            item
            for entry in parsed.entries
            if (item := normalize_feed_entry(entry, source, fetched_at)) is not None
        ]
        status["items"] = len(items)
        response_headers = getattr(response, "headers", None) or {}
        new_state = fresh_entry(
            previous,
            feed_url=feed_url,
            etag=response_headers.get("ETag"),
            last_modified=response_headers.get("Last-Modified"),
            items=items,
        )
        return {"records": items, "status": status, "feed_state": new_state}
    except Exception as exc:  # noqa: BLE001 - source status must capture any fetch failure
        status["status"] = "error"
        status["error"] = str(exc)
        return {"records": [], "status": status, "feed_state": new_state}
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
        status["elapsed_ms"] = round((time.monotonic() - started) * 1000)


FETCHERS = {
    "rss": fetch_rss_source,
    "twse_openapi": fetch_twse_openapi_source,
}


def _dispatch_one(
    session: requests.Session,
    source: dict[str, Any],
    fetched_at: datetime,
    *,
    fetchers: dict[str, Any],
    full_refresh: bool,
) -> dict[str, Any]:
    adapter = str(source.get("fetch_method") or "")
    started = time.monotonic()
    fetcher = fetchers.get(adapter)
    if fetcher is None:
        return {
            "records": [],
            "status": {
                "source_id": source["source_id"],
                "name": source.get("name") or source["source_id"],
                "source_class": source.get("source_class"),
                "adapter": adapter,
                "fetch_method": adapter,
                "status": "error",
                "items": 0,
                "error": f"unsupported adapter: {adapter}",
                "elapsed_ms": round((time.monotonic() - started) * 1000),
            },
        }
    try:
        result = fetcher(session, source, fetched_at, full_refresh=full_refresh)
        if isinstance(result, tuple):
            records, raw_status = result
            envelope = {"records": records, "status": raw_status}
        else:
            envelope = result
        records = list(envelope.get("records", []))
        status = {
            "source_id": source["source_id"],
            "name": source.get("name") or source["source_id"],
            "source_class": source.get("source_class"),
            "adapter": adapter,
            "fetch_method": adapter,
            "status": "ok",
            "items": len(records),
            "error": None,
            **envelope["status"],
        }
        dispatched = {"records": records, "status": status}
        if "feed_state" in envelope:
            dispatched["feed_state"] = envelope["feed_state"]
        return dispatched
    except Exception as exc:  # noqa: BLE001 - source isolation requires an envelope
        return {
            "records": [],
            "status": {
                "source_id": source["source_id"],
                "name": source.get("name") or source["source_id"],
                "source_class": source.get("source_class"),
                "adapter": adapter,
                "fetch_method": adapter,
                "status": "error",
                "items": 0,
                "error": str(exc),
                "elapsed_ms": round((time.monotonic() - started) * 1000),
            },
        }


def dispatch_sources(
    session: requests.Session,
    sources: list[dict[str, Any]],
    fetched_at: datetime,
    *,
    max_workers: int = 4,
    fetchers: dict[str, Any] | None = None,
    full_refresh: bool = False,
    session_factory: Any | None = None,
) -> list[dict[str, Any]]:
    if not 1 <= max_workers <= MAX_SOURCE_WORKERS:
        raise ValueError(f"max_workers must be between 1 and {MAX_SOURCE_WORKERS}")
    selected_fetchers = fetchers or {
        "rss": fetch_rss_source,
        "twse_openapi": fetch_twse_openapi_source,
    }

    def dispatch_one(source: dict[str, Any]) -> dict[str, Any]:
        if session_factory is None:
            return _dispatch_one(
                session,
                source,
                fetched_at,
                fetchers=selected_fetchers,
                full_refresh=full_refresh,
            )
        source_session = session_factory()
        try:
            return _dispatch_one(
                source_session,
                source,
                fetched_at,
                fetchers=selected_fetchers,
                full_refresh=full_refresh,
            )
        finally:
            source_session.close()

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(sources)))) as executor:
        futures = [
            executor.submit(dispatch_one, source)
            for source in sources
        ]
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda result: str(result["status"]["source_id"]))


def dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for record in sorted(records, key=lambda item: item.get("published_at", ""), reverse=True):
        key = (record.get("url") or record.get("title_zh") or record.get("title") or "").strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _payload(
    *,
    items: list[dict[str, Any]],
    available_count: int,
    generated_at: datetime,
    window_hours: int,
    max_items: int,
    market_id: str,
    market_scope: list[str],
) -> dict[str, Any]:
    return {
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "market_id": market_id,
        "market_scope": market_scope,
        "window_hours": window_hours,
        "max_items": max_items,
        "total_items": len(items),
        "total_items_available": available_count,
        "items": items,
    }


def _event_title(record: dict[str, Any]) -> str:
    return str(record.get("title_zh") or record.get("title") or "")


def normalized_event_tokens(record: dict[str, Any]) -> set[str]:
    title = _event_title(record).casefold()
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", title)
        if len(token) >= 2
    }
    for sequence in re.findall(r"[\u3400-\u9fff]+", title):
        for size in (2, 3):
            tokens.update(
                sequence[index:index + size]
                for index in range(len(sequence) - size + 1)
            )
    return tokens


def _event_entities(record: dict[str, Any]) -> set[str]:
    entities = {
        f"symbol:{item.get('symbol') or str(item.get('instrument_id') or '').split(':')[-1]}"
        for item in record.get("direct_symbols", [])
        if isinstance(item, dict)
        and (item.get("symbol") or item.get("instrument_id"))
    }
    for field in ("company_name", "entity", "product", "technology", "policy"):
        value = str(record.get(field) or "").strip().casefold()
        if value:
            entities.add(f"named:{value}")
    combined_text = f"{_event_title(record)} {record.get('summary') or ''}".casefold()
    for match in record.get("matched_themes", []):
        for signal in match.get("signals", []):
            normalized = str(signal).strip().casefold()
            if len(normalized) >= 2 and normalized in combined_text:
                entities.add(f"signal:{normalized}")
    entity_text = "".join(
        re.findall(r"[\u3400-\u9fff]+", _event_title(record).casefold())
    )
    for noise_term in ENTITY_NOISE_TERMS:
        entity_text = entity_text.replace(noise_term, "")
    for size in (2, 3, 4):
        entities.update(
            f"namegram:{entity_text[index:index + size]}"
            for index in range(len(entity_text) - size + 1)
        )
    return entities


def _event_company_entities(record: dict[str, Any]) -> set[str]:
    entities = {
        f"symbol:{item.get('symbol') or str(item.get('instrument_id') or '').split(':')[-1]}"
        for item in record.get("direct_symbols", [])
        if isinstance(item, dict)
        and (item.get("symbol") or item.get("instrument_id"))
    }
    for field in ("company_name", "entity"):
        value = str(record.get(field) or "").strip().casefold()
        if value:
            entities.add(f"company:{value}")
    if entities:
        return entities

    title = _event_title(record).casefold()
    signal_positions = [
        title.index(signal)
        for match in record.get("matched_themes", [])
        for raw_signal in match.get("signals", [])
        if (signal := str(raw_signal).strip().casefold()) and signal in title
    ]
    if not signal_positions:
        return set()

    prefix = title[:min(signal_positions)]
    for noise_term in ENTITY_NOISE_TERMS:
        prefix = prefix.replace(noise_term, "")
    chinese_prefix = "".join(re.findall(r"[\u3400-\u9fff]+", prefix))
    if 2 <= len(chinese_prefix) <= 6:
        return {
            f"company-hint:{chinese_prefix[index:index + 2]}"
            for index in range(len(chinese_prefix) - 1)
        }
    latin_prefix = re.findall(r"[a-z0-9]+", prefix)
    if 1 <= len(latin_prefix) <= 3 and all(len(token) >= 2 for token in latin_prefix):
        return {f"company-hint:{latin_prefix[0]}"}
    return set()


def _company_entities_are_compatible(left: set[str], right: set[str]) -> bool:
    if not left.isdisjoint(right):
        return True
    left_names = [
        tuple(re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", entity.removeprefix("company:")))
        for entity in left
        if entity.startswith("company:")
    ]
    right_names = [
        tuple(re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", entity.removeprefix("company:")))
        for entity in right
        if entity.startswith("company:")
    ]
    return any(
        shorter and longer[:len(shorter)] == shorter
        for left_name in left_names
        for right_name in right_names
        for shorter, longer in ((left_name, right_name), (right_name, left_name))
    )


def _event_phase(record: dict[str, Any]) -> str:
    text = _event_title(record).casefold()
    phase_patterns = (
        ("market_wrap", ("盤勢", "市場綜述", "market wrap", "韓股", "港股")),
        ("target_price", ("目標價", "target price", "評等")),
        ("price_performance", ("股價", "市值", "漲停", "創新高", "price record")),
        ("prediction", ("預估", "預測", "可望", "將於", "forecast")),
        ("realized", ("完成", "正式", "投產", "已經", "達成")),
        ("listing", ("上市", "ipo", "掛牌", "募資")),
        ("earnings", ("獲利", "財報", "營收", "earnings")),
        ("corporate_action", ("投資", "併購", "擴產", "增資")),
    )
    return next(
        (
            phase
            for phase, patterns in phase_patterns
            if any(pattern in text for pattern in patterns)
        ),
        "generic",
    )


def _title_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_tokens = normalized_event_tokens(left)
    right_tokens = normalized_event_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def events_are_cluster_compatible(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    window_hours: int,
) -> bool:
    if (
        not left.get("primary_theme_id")
        or left.get("primary_theme_id") != right.get("primary_theme_id")
    ):
        return False
    if not left.get("published_at") or not right.get("published_at"):
        return False
    try:
        left_at = parse_timestamp(str(left.get("published_at") or ""))
        right_at = parse_timestamp(str(right.get("published_at") or ""))
    except (TypeError, ValueError):
        return False
    if abs((left_at - right_at).total_seconds()) > window_hours * 3600:
        return False
    if _event_phase(left) != _event_phase(right):
        return False
    left_symbols = {
        entity
        for entity in _event_entities(left)
        if entity.startswith("symbol:")
    }
    right_symbols = {
        entity
        for entity in _event_entities(right)
        if entity.startswith("symbol:")
    }
    if left_symbols and right_symbols and left_symbols.isdisjoint(right_symbols):
        return False
    left_companies = _event_company_entities(left)
    right_companies = _event_company_entities(right)
    if (
        left_companies
        and right_companies
        and not _company_entities_are_compatible(left_companies, right_companies)
    ):
        return False
    if _event_entities(left).isdisjoint(_event_entities(right)):
        return False
    return _title_similarity(left, right) >= TITLE_TOKEN_SIMILARITY_THRESHOLD


def _published_epoch(record: dict[str, Any]) -> float:
    try:
        return parse_timestamp(str(record.get("published_at") or "")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _representative_key(
    record: dict[str, Any],
    source_authority: dict[str, int],
) -> tuple[int, int, float, str]:
    completeness = sum(
        bool(str(record.get(field) or "").strip())
        for field in ("title_zh", "summary", "content")
    )
    completeness += min(len(str(record.get("summary") or "")), 500)
    return (
        source_authority.get(
            str(record.get("source_id") or ""),
            UNKNOWN_AUTHORITY_RANK,
        ),
        -completeness,
        -_published_epoch(record),
        str(record.get("url") or ""),
    )


def _cluster_member_id(record: dict[str, Any]) -> str:
    return str(
        record.get("id")
        or record.get("url")
        or stable_id(
            str(record.get("source_id") or ""),
            str(record.get("url") or ""),
            _event_title(record),
        )
    )


def cluster_theme_events(
    records: list[dict[str, Any]],
    *,
    source_authority: dict[str, int],
    window_hours: int = DEFAULT_CLUSTER_WINDOW_HOURS,
) -> list[dict[str, Any]]:
    ordered = sorted(
        records,
        key=lambda record: (
            _cluster_member_id(record),
            str(record.get("url") or ""),
        ),
    )
    clusters: list[list[dict[str, Any]]] = []
    for record in ordered:
        cluster = next(
            (
                members
                for members in clusters
                if all(
                    events_are_cluster_compatible(
                        record,
                        member,
                        window_hours=window_hours,
                    )
                    for member in members
                )
            ),
            None,
        )
        if cluster is None:
            clusters.append([record])
        else:
            cluster.append(record)

    projected: list[dict[str, Any]] = []
    for members in clusters:
        ranked = sorted(
            members,
            key=lambda record: _representative_key(record, source_authority),
        )
        representative = ranked[0]
        member_ids = sorted(_cluster_member_id(member) for member in members)
        cluster_hash = hashlib.sha256(
            "\n".join(member_ids).encode("utf-8")
        ).hexdigest()[:16]
        projected.append(
            {
                **representative,
                "cluster_id": f"cluster-{cluster_hash}",
                "cluster_size": len(members),
                "cluster_event_ids": member_ids,
                "cluster_sources": [
                    {
                        "source_id": str(member.get("source_id") or ""),
                        "source": str(member.get("source") or member.get("source_id") or ""),
                        "title": _event_title(member),
                        "url": str(member.get("url") or ""),
                        "published_at": member.get("published_at"),
                    }
                    for member in ranked
                ],
            }
        )
    return sorted(
        projected,
        key=lambda record: (-_published_epoch(record), str(record["cluster_id"])),
    )


def _configured_instrument_ids(
    values: list[Any],
    symbol_aliases: dict[str, Any],
) -> list[str]:
    instruments: dict[str, str] = {}
    for value in values:
        if isinstance(value, dict):
            symbol = str(
                value.get("symbol")
                or str(value.get("instrument_id") or "").split(":")[-1]
            )
        else:
            symbol = str(value).split(":")[-1]
        if symbol not in symbol_aliases["symbols"]:
            continue
        instrument = instrument_for_symbol(
            symbol,
            symbol_aliases,
            evidence="existing related_symbols mapping",
            reason="existing Taiwan symbol mapping",
        )
        instruments[instrument["instrument_id"]] = instrument["instrument_id"]
    return sorted(instruments)


def classify_taiwan_relevance(
    record: dict[str, Any],
    taxonomy: dict[str, Any],
    symbol_aliases: dict[str, Any] | None = None,
) -> dict[str, Any]:
    aliases = symbol_aliases or load_symbol_aliases()
    public_record = {
        key: value
        for key, value in record.items()
        if key != "_input_related_symbols"
    }
    direct_ids = _configured_instrument_ids(
        list(record.get("direct_symbols") or []),
        aliases,
    )
    if direct_ids:
        return {
            **public_record,
            "tw_relevance_status": "direct",
            "tw_relevance_reason": f"direct Taiwan symbol: {', '.join(direct_ids)}",
            "tw_related_symbols": direct_ids,
        }

    existing_ids = _configured_instrument_ids(
        list(record.get("_input_related_symbols") or []),
        aliases,
    )
    if existing_ids:
        return {
            **public_record,
            "tw_relevance_status": "direct",
            "tw_relevance_reason": (
                f"existing Taiwan related_symbols mapping: {', '.join(existing_ids)}"
            ),
            "tw_related_symbols": existing_ids,
        }

    if record.get("kept_by") == "market_impact":
        mapped = _configured_instrument_ids(
            [item.get("symbol") for item in record.get("related_symbols") or [] if isinstance(item, dict)],
            aliases,
        )
        signals = "; ".join(record.get("impact_signals") or [])
        if mapped:
            return {
                **public_record,
                "tw_relevance_status": "market_mover",
                "tw_relevance_reason": f"market mover -> {record.get('primary_theme_id')}: {signals}",
                "tw_related_symbols": mapped,
            }
        return {
            **public_record,
            "tw_relevance_status": "market_wide",
            "tw_relevance_reason": f"market mover, no TW chain mapped: {signals}",
            "tw_related_symbols": [],
        }

    phase = _event_phase(record)
    # A price move is the news itself when the market impact is high
    # ("輝達盤前飆逾7%"): only low-impact price chatter is excluded here.
    if (
        phase in {"listing", "market_wrap", "price_performance", "target_price"}
        and float(record.get("impact_score") or 0) < IMPACT_KEEP_MIN
    ):
        return {
            **public_record,
            "tw_relevance_status": "excluded",
            "tw_relevance_reason": f"unsupported overseas event phase: {phase}",
            "tw_related_symbols": [],
        }

    themes_by_id = {
        str(theme["theme_id"]): theme
        for theme in taxonomy.get("themes", [])
    }
    for match in record.get("matched_themes", []):
        theme_id = str(match.get("theme_id") or "")
        strong_signals = sorted(
            {
                str(signal).strip()
                for signal in match.get("signals", [])
                if str(signal).strip()
                and str(signal).strip().casefold()
                not in {term.casefold() for term in GENERIC_SUPPLY_CHAIN_SIGNALS}
            },
            key=str.casefold,
        )
        theme = themes_by_id.get(theme_id)
        if not theme or not strong_signals:
            continue
        related_ids = _configured_instrument_ids(
            list(theme.get("seed_symbols") or []),
            aliases,
        )
        if related_ids:
            return {
                **public_record,
                "tw_relevance_status": "supply_chain",
                "tw_relevance_reason": (
                    f"configured theme {theme_id}; strong signal: {strong_signals[0]}"
                ),
                "tw_related_symbols": related_ids,
            }

    return {
        **public_record,
        "tw_relevance_status": "excluded",
        "tw_relevance_reason": "no direct Taiwan symbol or strong configured supply-chain signal",
        "tw_related_symbols": [],
    }


def _count_values(records: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = str(record.get(field) or "")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _derive_matcher_mode(theme: dict[str, Any]) -> str:
    explicit = str(theme.get("matcher_mode") or "").strip() or None
    has_legacy = "keywords" in theme
    has_structured = any(field in theme for field in ("required_any", "optional", "excluded"))
    if has_legacy and has_structured:
        raise ValueError("theme contains mixed matcher schema fields")
    if not has_legacy and not has_structured:
        raise ValueError("theme schema mode cannot be inferred")

    derived = "legacy" if has_legacy else "structured"
    if explicit is not None and explicit != derived:
        raise ValueError("theme.matcher_mode must match derived schema mode theme fields")
    return derived


def _normalize_matcher_mode(themes: list[dict[str, Any]]) -> tuple[int, int, str]:
    legacy_count = 0
    structured_count = 0

    for theme in themes:
        mode = _derive_matcher_mode(theme)
        if mode == "legacy":
            legacy_count += 1
        elif mode == "structured":
            structured_count += 1
        else:
            raise ValueError("unsupported matcher mode")

    return legacy_count, structured_count, "hybrid_required_any_v1"


def _sort_counts(values: dict[str, int]) -> dict[str, int]:
    return dict(sorted(values.items()))


def _map_market_mover(
    item: dict[str, Any],
    impact: Any,
    themes_by_id: Mapping[str, Mapping[str, Any]],
    aliases: dict[str, Any],
) -> dict[str, Any]:
    """Map a high-impact headline with no theme match onto Taiwan stocks."""

    theme_ids: list[str] = []
    for mover in impact.movers:
        for theme_id in mover.tw_theme_ids:
            if theme_id in themes_by_id and theme_id not in theme_ids:
                theme_ids.append(theme_id)
    names = [mover.id for mover in impact.movers]
    reason = "market mover: " + "; ".join(impact.signals)
    matched_themes = [
        {
            "theme_id": theme_id,
            "name_zh": themes_by_id[theme_id].get("name_zh") or theme_id,
            "score": impact.score,
            "signals": names,
            "reason": reason,
        }
        for theme_id in theme_ids
    ]
    related = list(item.get("related_symbols") or [])
    seen = {str(symbol.get("instrument_id")) for symbol in related if isinstance(symbol, dict)}
    for theme_id in theme_ids:
        for code in themes_by_id[theme_id].get("seed_symbols") or []:
            try:
                instrument = instrument_for_symbol(
                    str(code),
                    aliases,
                    evidence=f"market mover chain: {theme_id}",
                    reason="market mover chain",
                )
            except (KeyError, ValueError):
                continue
            if instrument["instrument_id"] not in seen:
                seen.add(instrument["instrument_id"])
                related.append(instrument)
    return {
        **item,
        "kept_by": "market_impact",
        "matched_themes": matched_themes,
        "primary_theme_id": theme_ids[0] if theme_ids else None,
        "theme_score": impact.score,
        "related_symbols": related,
        "related_symbol_codes": [symbol["symbol"] for symbol in related],
        "decision": "track_watch" if related else "market_wide",
    }


def _top_dropped(dropped: list[dict[str, Any]], limit: int = 15) -> list[dict[str, Any]]:
    """The dropped headlines closest to the keep line, so a miss is visible."""

    ranked = sorted(
        dropped,
        key=lambda item: (-float(item.get("impact_score") or 0), str(item.get("published_at") or "")),
    )
    return [
        {
            "title": _event_title(item),
            "source_id": item.get("source_id"),
            "published_at": item.get("published_at"),
            "impact_score": item.get("impact_score"),
            "impact_signals": item.get("impact_signals") or [],
        }
        for item in ranked[:limit]
        if float(item.get("impact_score") or 0) > 0
    ]


def build_theme_projection(
    records: list[dict[str, Any]],
    taxonomy: dict[str, Any],
    *,
    anchor: datetime,
    window_hours: int,
    max_events: int,
    max_candidates: int,
    source_authority: dict[str, int] | None = None,
    symbol_aliases: dict[str, Any] | None = None,
    market_movers: list[Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if window_hours <= 0 or max_events <= 0 or max_candidates <= 0:
        raise ValueError("window item bounds must be positive")

    cutoff = anchor - timedelta(hours=window_hours)
    in_window = [
        record
        for record in dedupe_records(records)
        if record.get("published_at") and cutoff <= parse_timestamp(str(record["published_at"])) <= anchor
    ]

    legacy_theme_count, structured_theme_count, matcher_contract = _normalize_matcher_mode(
        [dict(theme) for theme in taxonomy.get("themes", [])]
    )

    active_aliases = symbol_aliases if symbol_aliases is not None else load_symbol_aliases()
    enriched = [
        {
            **enrich_item_with_themes(record, taxonomy, active_aliases),
            "_input_related_symbols": list(record.get("related_symbols") or []),
        }
        for record in in_window
    ]

    theme_veto_distribution: dict[str, int] = {}
    for record in in_window:
        matcher_record = {
            **record,
            "summary": record.get("summary") or record.get("description", ""),
        }
        score = score_theme_relevance(matcher_record, taxonomy=taxonomy)
        for theme_id in score.get("vetoed_theme_ids", []):
            theme_veto_distribution[str(theme_id)] = (
                theme_veto_distribution.get(str(theme_id), 0) + 1
            )

    # Keep by market impact first, map to Taiwan stocks second (M026). A theme
    # match is one way in; a high market-impact headline is the other, and
    # whatever is still dropped is counted and listed in the diagnostics.
    active_movers = load_market_movers() if market_movers is None else market_movers
    bursts = find_bursts(
        in_window,
        anchor=anchor,
        window_hours=window_hours,
        title_of=_event_title,
        published_of=lambda record: parse_timestamp(str(record["published_at"])),
        source_of=lambda record: record.get("source_id") or record.get("source"),
    )
    themes_by_id = {str(theme["theme_id"]): theme for theme in taxonomy.get("themes", [])}
    matched = []
    dropped: list[dict[str, Any]] = []
    kept_by_impact = 0
    for item in enriched:
        impact = score_impact(_event_title(item), active_movers, bursts)
        item["impact_score"] = impact.score
        item["impact_signals"] = list(impact.signals)
        if item["matched_themes"] and item["theme_score"] >= SELECTED_THEME_SCORE_MIN:
            matched.append(item)
        elif impact.keep:
            matched.append(_map_market_mover(item, impact, themes_by_id, active_aliases))
            kept_by_impact += 1
        else:
            dropped.append(item)
    classified = [
        classify_taiwan_relevance(item, taxonomy, active_aliases)
        for item in matched
    ]
    retained = [item for item in classified if item["tw_relevance_status"] != "excluded"]
    excluded = [item for item in classified if item["tw_relevance_status"] == "excluded"]
    clustered = cluster_theme_events(
        retained,
        source_authority=source_authority or {},
    )
    candidates = [
        {**item, "tracking_reason": item["matched_themes"][0]["reason"]}
        for item in clustered
        if item["theme_score"] >= CANDIDATE_THEME_SCORE_MIN and item.get("related_symbols")
    ]

    market_id = str(taxonomy.get("market_id") or "TW_EQUITY")
    market_scope = list(taxonomy.get("market_scope") or [market_id])

    event_payload = _payload(
        items=clustered[:max_events],
        available_count=len(clustered),
        generated_at=anchor,
        window_hours=window_hours,
        max_items=max_events,
        market_id=market_id,
        market_scope=market_scope,
    )
    candidate_payload = _payload(
        items=candidates[:max_candidates],
        available_count=len(candidates),
        generated_at=anchor,
        window_hours=window_hours,
        max_items=max_candidates,
        market_id=market_id,
        market_scope=market_scope,
    )

    relevance_distribution = _count_values(retained, "tw_relevance_status")
    relevance_reason_distribution = _count_values(classified, "tw_relevance_reason")
    theme_match_distribution = _count_values(
        [item for item in retained if item.get("primary_theme_id")],
        "primary_theme_id",
    )
    diagnostics = {
        "pre_cluster_items": len(retained),
        "excluded_items": len(excluded),
        "tw_relevance_distribution": relevance_distribution,
        "tw_relevance_reason_distribution": relevance_reason_distribution,
        "selected_theme_score_min": SELECTED_THEME_SCORE_MIN,
        "candidate_theme_score_min": CANDIDATE_THEME_SCORE_MIN,
        "matcher_contract": matcher_contract,
        "taxonomy_version": "v0.7",
        "legacy_theme_count": legacy_theme_count,
        "structured_theme_count": structured_theme_count,
        "theme_match_distribution": _sort_counts(theme_match_distribution),
        "theme_veto_distribution": _sort_counts(theme_veto_distribution),
        "impact_keep_min": IMPACT_KEEP_MIN,
        "kept_by_impact_items": kept_by_impact,
        "dropped_items": len(dropped),
        "top_dropped_items": _top_dropped(dropped),
        "burst_terms": [
            {"term": burst.term, "headlines": burst.headlines, "sources": burst.sources, "ratio": burst.ratio}
            for burst in sorted(bursts.values(), key=lambda b: (-b.headlines, b.term))[:20]
        ],
    }

    retained_by_id: dict[str, dict[str, Any]] = {}
    for record in retained:
        member_id = _cluster_member_id(record).strip()
        if not member_id or member_id in retained_by_id:
            raise ValueError("projection member IDs must be non-empty and unique")
        retained_by_id[member_id] = record

    mapped_member_ids: set[str] = set()
    cluster_members_by_id: dict[str, list[dict[str, Any]]] = {}
    for event in clustered:
        cluster_id = str(event.get("cluster_id") or "").strip()
        member_ids = event.get("cluster_event_ids")
        if (
            not cluster_id
            or cluster_id in cluster_members_by_id
            or not isinstance(member_ids, list)
            or not member_ids
        ):
            raise ValueError("projection clusters require unique IDs and members")
        members: list[dict[str, Any]] = []
        for raw_member_id in member_ids:
            member_id = str(raw_member_id or "").strip()
            if not member_id or member_id in mapped_member_ids:
                raise ValueError("each projection member must map to one cluster")
            member = retained_by_id.get(member_id)
            if member is None:
                raise ValueError("projection cluster references an unknown member")
            mapped_member_ids.add(member_id)
            members.append(member)
        cluster_members_by_id[cluster_id] = members

    if mapped_member_ids != set(retained_by_id):
        raise ValueError("every retained projection member must belong to a cluster")

    # Theme ranking only ranks themes: market-wide items (no TW chain) stay in
    # the event feed but are not handed to it.
    themed_clusters = [event for event in clustered if event.get("primary_theme_id")]
    themed_ids = {str(event.get("cluster_id")) for event in themed_clusters}
    projection = {
        "retained_records": [item for item in retained if item.get("primary_theme_id")],
        "clustered_events": themed_clusters,
        "candidate_clusters": list(candidates),
        "cluster_members_by_id": {
            cluster_id: members
            for cluster_id, members in cluster_members_by_id.items()
            if cluster_id in themed_ids
        },
        "market_id": market_id,
        "market_scope": list(market_scope),
    }
    return (
        {**event_payload, **diagnostics},
        {**candidate_payload, **diagnostics},
        projection,
    )


def build_theme_payloads(
    records: list[dict[str, Any]],
    taxonomy: dict[str, Any],
    *,
    anchor: datetime,
    window_hours: int,
    max_events: int,
    max_candidates: int,
    source_authority: dict[str, int] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    events, candidates, _ = build_theme_projection(
        records,
        taxonomy,
        anchor=anchor,
        window_hours=window_hours,
        max_events=max_events,
        max_candidates=max_candidates,
        source_authority=source_authority,
    )
    return events, candidates


def _event_symbols(event: dict[str, Any]) -> set[str]:
    symbols = {
        str(item.get("symbol") or item.get("instrument_id") or "").split(":")[-1]
        for item in event.get("related_symbols", [])
        if isinstance(item, dict)
    }
    symbols.update(str(symbol) for symbol in event.get("related_symbol_codes", []))
    return {symbol for symbol in symbols if symbol}


def _normalized_match_text(value: Any) -> str:
    return "".join(character.lower() for character in str(value or "") if character.isalnum())


def _record_corroborates(event: dict[str, Any], record: dict[str, Any]) -> bool:
    event_text = _normalized_match_text(
        f"{event.get('title_zh') or ''} {event.get('summary') or ''}"
    )
    company_name = _normalized_match_text(record.get("company_name"))
    if not company_name or company_name not in event_text:
        return False

    event_without_company = event_text.replace(company_name, "")
    evidence_text = _normalized_match_text(
        f"{record.get('title') or ''} {record.get('summary') or ''}"
    ).replace(company_name, "")
    title_overlap = (
        len(event_without_company) >= 4
        and len(evidence_text) >= 4
        and (
            event_without_company in evidence_text
            or evidence_text in event_without_company
        )
    )

    event_categories = {
        _normalized_match_text(value)
        for value in [
            event.get("category"),
            *(event.get("categories") or []),
        ]
        if value
    }
    category_overlap = (
        _normalized_match_text(record.get("category")) in event_categories
        if event_categories
        else False
    )
    return title_overlap or category_overlap


def attach_official_evidence(
    events: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    *,
    official_available: bool,
    match_window_hours: int = 72,
) -> list[dict[str, Any]]:
    attached: list[dict[str, Any]] = []
    for event in events:
        symbols = _event_symbols(event)
        if not symbols:
            state = "not_required"
            matches: list[dict[str, Any]] = []
        elif not official_available:
            state = "unavailable"
            matches = []
        else:
            event_at = parse_timestamp(str(event.get("published_at") or ""))
            matches = []
            for record in evidence:
                evidence_symbol = str(record.get("symbol") or "").strip()
                if evidence_symbol not in symbols:
                    continue
                evidence_at_text = (
                    record.get("published_at")
                    or record.get("effective_at")
                    or record.get("fetched_at")
                )
                if not evidence_at_text:
                    continue
                evidence_at = parse_timestamp(str(evidence_at_text))
                if (
                    abs((event_at - evidence_at).total_seconds())
                    > match_window_hours * 3600
                ):
                    continue
                if not _record_corroborates(event, record):
                    continue
                matches.append(record)
            matches = sorted(matches, key=lambda item: str(item["evidence_id"]))
            conflicting = any(
                term in f"{record.get('title') or ''} {record.get('summary') or ''}"
                for record in matches
                for term in CONFLICT_TERMS
            )
            state = "conflicting" if conflicting else ("confirmed" if matches else "unconfirmed")
        ids = [str(record["evidence_id"]) for record in matches]
        attached.append(
            {
                **event,
                "confirmation_status": state,
                "official_evidence_ids": ids,
                "official_evidence_count": len(ids),
            }
        )
    return attached


def source_status_payload(statuses: list[dict[str, Any]], generated_at: datetime, raw_count: int) -> dict[str, Any]:
    # Trial sources are listed in ``sites`` so the status page shows their
    # fetch results, but they do not move the public health counters.
    counted = [status for status in statuses if not status.get("trial")]
    failed = sum(1 for status in counted if status["status"] != "ok")
    successful = len(counted) - failed
    return {
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "fetched_raw_items": raw_count,
        "items_before_topic_filter": raw_count,
        "successful_sites": successful,
        "failed_count": failed,
        "failed_sites": [status["source_id"] for status in counted if status["status"] != "ok"],
        "sites": statuses,
    }


def validate_payload_set(
    payloads: Mapping[str, Mapping[str, Any]],
    *,
    generated_at: datetime,
    market_id: str,
    market_scope: list[str],
    window_hours: int,
) -> None:
    if set(payloads) != set(PAYLOAD_FILENAMES):
        raise ValueError("payload set must contain exactly five approved files")
    if (
        generated_at.tzinfo is None
        or market_id != "TW_EQUITY"
        or market_scope != ["TW_EQUITY"]
        or window_hours != PUBLIC_WINDOW_HOURS
    ):
        raise ValueError("payload set requires the v0.8 Taiwan 72-hour envelope")

    generated_text = (
        generated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    for filename in PAYLOAD_FILENAMES:
        payload = payloads[filename]
        if not isinstance(payload, Mapping):
            raise ValueError(f"{filename} must contain an object")
        if payload.get("generated_at") != generated_text:
            raise ValueError(f"{filename} generated_at does not match the run anchor")
        if "market_id" in payload and payload.get("market_id") != market_id:
            raise ValueError(f"{filename} market_id is incompatible")
        if "market_scope" in payload and payload.get("market_scope") != market_scope:
            raise ValueError(f"{filename} market_scope is incompatible")
        if "window_hours" in payload and payload.get("window_hours") != window_hours:
            raise ValueError(f"{filename} window_hours is incompatible")

    validate_public_theme_ranking(payloads["public-theme-ranking-v0.8.json"])


def write_payload_set(
    output_dir: Path,
    payloads: Mapping[str, Mapping[str, Any]],
) -> None:
    if set(payloads) != set(PAYLOAD_FILENAMES):
        raise ValueError("payload set must contain exactly five approved files")

    serialized = {
        filename: json.dumps(
            payloads[filename],
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
        for filename in PAYLOAD_FILENAMES
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary_paths: dict[str, Path] = {}
    try:
        for filename in PAYLOAD_FILENAMES:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=output_dir,
                prefix=f".{filename}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_paths[filename] = Path(temporary.name)
                temporary.write(serialized[filename])
                temporary.flush()

        for filename in PAYLOAD_FILENAMES:
            temporary_paths[filename].replace(output_dir / filename)
            del temporary_paths[filename]
    finally:
        for path in temporary_paths.values():
            path.unlink(missing_ok=True)


def _candidate_theme_ids(candidate: Mapping[str, Any]) -> list[str]:
    theme_ids = [str(candidate.get("primary_theme_id") or "").strip()]
    theme_ids.extend(
        str(match.get("theme_id") or "").strip()
        for match in candidate.get("matched_themes", [])
    )
    return list(dict.fromkeys(theme_id for theme_id in theme_ids if theme_id))


def _deduplicated_candidate_symbols(
    candidates: list[Mapping[str, Any]],
    field: str,
) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        for value in candidate.get(field, []):
            identity = str(
                value.get("instrument_id") or value.get("symbol") or ""
            ).strip()
            if not identity or identity in seen:
                continue
            seen.add(identity)
            symbols.append(dict(value))
    return symbols


def _representative_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate.get("id"),
        "title_zh": candidate.get("title_zh") or candidate.get("title"),
        "summary": candidate.get("summary") or "",
        "source_id": candidate.get("source_id"),
        "source": candidate.get("source"),
        "published_at": candidate.get("published_at"),
        "canonical_url": candidate.get("url"),
    }


def _attach_quarterly_fundamentals(
    payload: Mapping[str, Any], output_dir: Path, generated_at: datetime,
) -> dict[str, Any]:
    """Attach quarterly statements to the published symbols, fetching only what
    the quarterly throttle says is due.

    Publishing a cached statement and scraping a third party are different
    risks, so they are gated separately: whatever is already in the committed
    cache is always attached, while ``THEME_RADAR_FUNDAMENTALS`` controls
    whether this run may reach out to Goodinfo for what is missing. Fetching
    is on by default -- the quarterly throttle already keeps it to a handful
    of requests per quarter -- and setting the variable to 0/false/off turns
    it off without disturbing the cached statements already published.

    Fully contained: this is a side-source on a pipeline whose actual job is
    theme momentum, so any failure here leaves the payload as it was rather
    than propagating.
    """
    may_fetch = os.environ.get("THEME_RADAR_FUNDAMENTALS", "1").strip().lower() not in {"0", "false", "off"}
    cache_path = output_dir / FUNDAMENTALS_CACHE_FILE
    try:
        import requests

        session = requests.Session()
        enriched, cache = enrich_with_fundamentals(
            payload,
            cache=load_fundamentals_cache(cache_path),
            as_of=generated_at,
            fetch=lambda ticker: fetch_symbol_fundamentals(
                session, ticker, fetched_at=generated_at,
            ),
            max_fetches=DEFAULT_MAX_FETCHES if may_fetch else 0,
        )
        if may_fetch:
            write_fundamentals_cache(cache_path, cache)
        return enriched
    except Exception as error:  # noqa: BLE001 - side-source stays isolated
        LOGGER.warning("theme_fundamentals_side_path_failed error=%s", error)
        return dict(payload)


# Another theme's seed stocks count toward this theme only when the two seed
# sets mostly coincide (Jaccard). 0.3 keeps 記憶體 <-> SSD / 記憶卡 and
# 機器人 <-> 人形機器人 / 自動化, and drops 機器人 <-> 稀土 / 蘋果 (~0.1).
THEME_FAMILY_MIN_JACCARD = 0.3
_SEED_EVIDENCE_PREFIX = "taxonomy seed: "


def _theme_family(taxonomy: Mapping[str, Any] | None) -> dict[str, set[str]]:
    """theme_id -> theme ids whose seed symbols may be attributed to it."""
    if not taxonomy:
        return {}
    seeds = {
        str(theme.get("theme_id")): set(theme.get("seed_symbols") or [])
        for theme in taxonomy.get("themes", [])
        if isinstance(theme, Mapping)
    }
    family: dict[str, set[str]] = {}
    for theme_id, own in seeds.items():
        members = {theme_id}
        for other_id, other in seeds.items():
            union = own | other
            if other_id != theme_id and union and len(own & other) / len(union) >= THEME_FAMILY_MIN_JACCARD:
                members.add(other_id)
        family[theme_id] = members
    return family


def _theme_related_symbols(
    symbols: list[dict[str, Any]],
    theme_id: str,
    family: Mapping[str, set[str]],
) -> list[dict[str, Any]]:
    """Drop seed stocks a multi-topic article pulled in from unrelated themes.

    An event's related_symbols carry the seeds of every theme it matched, so a
    digest that mentions memory and humanoid robots used to list robot-part
    makers under 記憶體與 HBM. Direct mentions in the article are kept.
    """
    allowed = family.get(theme_id)
    if not allowed:
        return symbols
    kept = []
    for symbol in symbols:
        evidence = str(symbol.get("evidence") or "")
        if evidence.startswith(_SEED_EVIDENCE_PREFIX) and evidence[len(_SEED_EVIDENCE_PREFIX):] not in allowed:
            continue
        kept.append(symbol)
    return kept


# A ranked theme whose news named no stock (and matched no tracking candidate)
# used to publish zero symbols, so it never reached the stock radar: 11 of 20
# ranked themes on 2026-11-23, including 航空 and the pre-market 航運 call.
# Such a theme falls back to its own taxonomy seeds, taken round-robin across
# its supply-chain stages so one segment cannot fill the list.
SEED_FALLBACK_MAX = 8
SEED_FALLBACK_REASON = "theme seed symbol (no stock named in this theme's news)"


def _seed_fallback_symbols(
    theme: Mapping[str, Any] | None,
    symbol_aliases: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if not theme or not symbol_aliases or not isinstance(symbol_aliases.get("symbols"), Mapping):
        return []
    known = symbol_aliases["symbols"]
    groups: list[list[str]] = []
    for segment in theme.get("supply_chain") or []:
        if isinstance(segment, Mapping):
            groups.append([str(code) for code in segment.get("symbols") or []])
    if not groups:
        groups = [[str(code) for code in theme.get("seed_symbols") or []]]
    ordered: list[str] = []
    depth = max((len(group) for group in groups), default=0)
    for index in range(depth):
        for group in groups:
            if index < len(group) and group[index] not in ordered:
                ordered.append(group[index])
    theme_id = str(theme.get("theme_id") or "")
    return [
        instrument_for_symbol(
            code,
            dict(symbol_aliases),
            evidence=f"{_SEED_EVIDENCE_PREFIX}{theme_id}",
            reason=SEED_FALLBACK_REASON,
        )
        for code in ordered
        if code in known
    ][:SEED_FALLBACK_MAX]


def enrich_momentum_latest(
    momentum_payload: Mapping[str, Any],
    tracking_candidates: list[Mapping[str, Any]],
    taxonomy: Mapping[str, Any] | None = None,
    symbol_aliases: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Add deterministic tracking-candidate context without changing momentum rank."""

    family = _theme_family(taxonomy)
    taxonomy_by_id = {
        str(theme.get("theme_id")): theme
        for theme in (taxonomy or {}).get("themes", [])
        if isinstance(theme, Mapping)
    }

    candidates_by_theme: dict[str, list[Mapping[str, Any]]] = {}
    for candidate in tracking_candidates:
        for theme_id in _candidate_theme_ids(candidate):
            candidates_by_theme.setdefault(theme_id, []).append(candidate)

    themes = []
    for theme in momentum_payload.get("themes", []):
        theme_id = str(theme.get("theme_id") or "")
        theme_candidates = candidates_by_theme.get(theme_id, [])
        direct_symbols = _deduplicated_candidate_symbols(theme_candidates, "direct_symbols")
        related_symbols = _theme_related_symbols(
            _deduplicated_candidate_symbols(theme_candidates, "related_symbols"),
            theme_id,
            family,
        )
        if not direct_symbols and not related_symbols:
            related_symbols = _seed_fallback_symbols(taxonomy_by_id.get(theme_id), symbol_aliases)
        themes.append(
            {
                **theme,
                "representative_news": (
                    _representative_candidate(theme_candidates[0])
                    if theme_candidates
                    else None
                ),
                "direct_symbols": direct_symbols,
                "related_symbols": related_symbols,
            }
        )
    return {**momentum_payload, "themes": themes}


def write_momentum_latest(output_dir: Path, payload: Mapping[str, Any]) -> None:
    """Atomically publish v0.9 latest without changing the v0.8 payload set."""

    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / MOMENTUM_LATEST_FILENAME
    temporary_path: Path | None = None
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_dir,
            prefix=f".{MOMENTUM_LATEST_FILENAME}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(serialized)
            temporary.flush()
        if json.loads(temporary_path.read_text(encoding="utf-8")) != payload:
            raise ValueError("momentum latest temporary validation failed")
        temporary_path.replace(destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _watchlist_fundamentals(momentum_payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    fundamentals: dict[str, Mapping[str, Any]] = {}
    for theme in momentum_payload.get("themes", []):
        if not isinstance(theme, Mapping):
            continue
        for field in ("direct_symbols", "related_symbols"):
            for symbol in theme.get(field, []) or []:
                if not isinstance(symbol, Mapping):
                    continue
                instrument_id = str(symbol.get("instrument_id") or "")
                payload = symbol.get("fundamentals")
                if instrument_id and isinstance(payload, Mapping) and payload:
                    fundamentals.setdefault(instrument_id, payload)
    return fundamentals


def _watchlist_instrument_ids(momentum_payload: Mapping[str, Any]) -> set[str]:
    instrument_ids: set[str] = set()
    for theme in momentum_payload.get("themes", []):
        if not isinstance(theme, Mapping):
            continue
        for field in ("direct_symbols", "related_symbols"):
            for symbol in theme.get(field, []) or []:
                if not isinstance(symbol, Mapping):
                    continue
                instrument_id = str(symbol.get("instrument_id") or "")
                if instrument_id:
                    instrument_ids.add(instrument_id)
    return instrument_ids


def _flow_filename(output_dir: Path, instrument_id: str) -> str | None:
    exchange, separator, code = instrument_id.partition(":")
    if separator != ":" or exchange not in {"TWSE", "TPEX"}:
        return None
    if not re.fullmatch(r"[A-Za-z0-9]{1,12}", code):
        return None

    index_path = output_dir / "flows" / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        index = {}
    symbols = index.get("symbols") if isinstance(index, Mapping) else None
    record = symbols.get(code) if isinstance(symbols, Mapping) else None
    records = [record] if isinstance(record, Mapping) else []
    if isinstance(record, Mapping):
        records.extend(item for item in record.get("alternates", []) or [] if isinstance(item, Mapping))
    for item in records:
        filename = item.get("file")
        if item.get("exchange") == exchange and isinstance(filename, str):
            if filename == Path(filename).name and re.fullmatch(
                rf"{exchange}-[A-Za-z0-9]{{1,12}}\.json", filename
            ):
                return filename
    return f"{exchange}-{code}.json"


def _load_institutional_flows(
    output_dir: Path,
    instrument_ids: set[str] | None = None,
) -> dict[str, Any]:
    symbols: dict[str, Any] = {}
    path = output_dir / "institutional-flows.json"
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        compact = payload.get("symbols") if isinstance(payload, Mapping) else None
        if isinstance(compact, Mapping):
            symbols.update(compact)

    for instrument_id in sorted(instrument_ids or set()):
        if instrument_id in symbols:
            continue
        filename = _flow_filename(output_dir, instrument_id)
        if filename is None:
            continue
        flow_path = output_dir / "flows" / filename
        try:
            flow_payload = json.loads(flow_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(flow_payload, Mapping)
            and flow_payload.get("instrument_id") == instrument_id
            and isinstance(flow_payload.get("series"), list)
        ):
            symbols[instrument_id] = dict(flow_payload)
    return symbols


def _official_trading_dates(institutional_flows: Mapping[str, Any]) -> list[str]:
    dates: set[str] = set()
    for rows in institutional_flows.values():
        series = rows.get("series", []) if isinstance(rows, Mapping) else rows
        if not isinstance(series, list):
            continue
        for row in series:
            if isinstance(row, Mapping):
                value = row.get("date")
            elif isinstance(row, (list, tuple)) and row:
                value = row[0]
            else:
                value = None
            if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                dates.add(value)
    return sorted(dates, reverse=True)


def _load_day_trading_cache(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_day_trading_cache(payload)
        return payload
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _unavailable_day_trading_view(
    prior: Mapping[str, Any],
    error: Exception,
) -> dict[str, Any]:
    message = f"{type(error).__name__}: {error}"
    prior_sources = prior.get("sources") if isinstance(prior.get("sources"), Mapping) else {}
    prior_symbols = prior.get("symbols") if isinstance(prior.get("symbols"), Mapping) else {}
    urls = {
        "TWSE": (TWSE_TWTB4U_URL, TWSE_MI_INDEX_URL),
        "TPEX": (TPEX_INTRADAY_URL, TPEX_DAILY_URL),
    }
    sources: dict[str, dict[str, Any]] = {}
    symbols: dict[str, dict[str, Any]] = {}
    for exchange in ("TWSE", "TPEX"):
        source = prior_sources.get(exchange)
        rows = {
            instrument_id: row
            for instrument_id, row in prior_symbols.items()
            if instrument_id.startswith(f"{exchange}:") and isinstance(row, Mapping)
        }
        numerator_url, denominator_url = urls[exchange]
        if isinstance(source, Mapping) and source.get("as_of") and rows:
            sources[exchange] = {
                "as_of": source["as_of"],
                "finality": "settled_t_plus_2",
                "numerator_url": numerator_url,
                "denominator_url": denominator_url,
                "status": "stale",
                "error": message,
            }
            for instrument_id, row in rows.items():
                symbols[instrument_id] = {
                    **row,
                    "status": "stale",
                    "stale": True,
                    "missing_reason": f"stale_official_cache: {message}",
                }
        else:
            sources[exchange] = {
                "as_of": None,
                "finality": "settled_t_plus_2",
                "numerator_url": numerator_url,
                "denominator_url": denominator_url,
                "status": "missing",
                "error": message,
            }
    return {"sources": sources, "symbols": symbols}


MOAT_FUNDAMENTALS_DIR = "fundamentals"


def _long_rank_nullable(connection: Any | None) -> bool:
    """Whether radar.watchlist_item.long_rank accepts NULL in the target DB.

    The moat long gate leaves short-only names without a long rank. Until the
    20261122090000 migration drops NOT NULL, publishing such a row would fail
    the hourly run, so the long gate stays off (and says so) until then.
    No database configured means nothing to break: the gate is on.
    """
    if connection is None:
        return os.environ.get("THEME_RADAR_DATABASE_URL", "").strip() == ""
    try:
        cursor = connection.execute(
            "select is_nullable from information_schema.columns "
            "where table_schema = 'radar' and table_name = 'watchlist_item' and column_name = 'long_rank'"
        )
        row = cursor.fetchone()
    except Exception as error:  # noqa: BLE001 - unknown schema keeps the safe v1 long list
        LOGGER.warning("moat_long_gate_schema_check_failed error=%s", error)
        try:
            connection.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False
    if row is None:
        return False
    value = row["is_nullable"] if isinstance(row, Mapping) else row[0]
    return str(value).upper() == "YES"


def _moat_inputs(
    output_dir: Path,
    candidate_ids: set[str],
    generated_at_text: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Screen the fixed fundamentals universe (data/moat-screen.json is written
    by write_moat_screen once the watchlist exists).

    Returns (universe payloads, screen) or (None, None) when there is no cache,
    in which case the watchlist falls back to the v1 behaviour.
    """
    if os.environ.get("THEME_RADAR_MOAT", "1").strip().lower() in {"0", "false", "off"}:
        LOGGER.warning("moat_screen_disabled env=THEME_RADAR_MOAT")
        return None, None
    universe = load_fundamentals_universe(output_dir / MOAT_FUNDAMENTALS_DIR)
    if not universe:
        LOGGER.warning("moat_screen_skipped reason=no_fundamentals_cache")
        return None, None
    screened = screen_universe(universe)
    summary = screen_summary(screened, generated_at=generated_at_text, candidate_ids=candidate_ids)
    LOGGER.info(
        "moat_screen universe=%s short_pass=%s long_pass=%s candidates=%s candidate_short_pass=%s candidate_long_pass=%s",
        summary["universe"]["evaluated"],
        summary["universe"]["short_pass"],
        summary["universe"]["long_pass"],
        len(candidate_ids),
        summary["candidates"]["short_pass"],
        summary["candidates"]["long_pass"],
    )
    return universe, screened


def publish_stock_watchlist(
    *,
    output_dir: Path,
    momentum_payload: Mapping[str, Any],
    generated_at: datetime,
    connection: Any | None = None,
) -> None:
    generated_at_text = generated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    institutional_flows = _load_institutional_flows(
        output_dir,
        _watchlist_instrument_ids(momentum_payload),
    )
    activity_path = output_dir / DAY_TRADING_CACHE_FILENAME
    day_trading_activity = _load_day_trading_cache(activity_path)
    if os.environ.get("THEME_RADAR_DAY_TRADING", "1") != "0":
        try:
            target_date = select_settled_target(
                generated_at.date(),
                _official_trading_dates(institutional_flows),
            )
            day_trading_activity = refresh_day_trading_cache(
                activity_path,
                target_date=target_date,
                generated_at=generated_at_text,
            )
        except Exception as error:  # noqa: BLE001 - watchlist still publishes explicit missing values
            LOGGER.warning("day_trading_activity_refresh_failed error=%s", error)
            day_trading_activity = _unavailable_day_trading_view(day_trading_activity, error)

    universe, screened = _moat_inputs(
        output_dir, _watchlist_instrument_ids(momentum_payload), generated_at_text
    )
    long_gate = screened is not None and _long_rank_nullable(connection)
    if screened is not None and not long_gate:
        LOGGER.warning("moat_long_gate_off reason=watchlist_item.long_rank_not_nullable")
    payload = build_stock_watchlist(
        momentum_payload=momentum_payload,
        fundamentals_by_instrument=_watchlist_fundamentals(momentum_payload),
        reference_fundamentals=universe,
        moat=screened,
        long_moat_gate=long_gate,
        institutional_flows=institutional_flows,
        day_trading_activity=day_trading_activity,
        generated_at=generated_at_text,
        candidate_as_of=str(
            momentum_payload.get("observed_hour")
            or momentum_payload.get("generated_at")
            or generated_at_text
        ),
    )
    write_stock_watchlist(output_dir, payload)
    if screened is not None:
        write_moat_screen(output_dir, screened, payload)


def write_moat_screen(output_dir: Path, screened: Mapping[str, Any], watchlist: Mapping[str, Any]) -> None:
    """data/moat-screen.json: the screen plus a per-candidate report, keyed to
    the watchlist it gated (same generated_at). Published as dataset moat-screen."""
    summary = screen_summary(
        screened,
        generated_at=str(watchlist["generated_at"]),
        candidate_ids={row["instrument"]["instrument_id"] for row in watchlist["searchable"]},
        searchable=watchlist["searchable"],
    )
    (output_dir / MOAT_SCREEN_FILENAME).write_text(
        json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def history_connection_factory_from_environment() -> Any | None:
    """Return a lazy direct-Postgres factory only when the scoped URL is set."""

    database_url = os.environ.get("THEME_RADAR_DATABASE_URL", "").strip()
    if not database_url:
        return None

    def connect() -> Any:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "psycopg dependency authorization is required for live theme history"
            ) from error
        return psycopg.connect(database_url, row_factory=dict_row)

    return connect


RADAR_DUAL_WRITE_DEFAULTS: dict[str, Any] = {
    "radar_dual_write": "skipped",
    "radar_articles_upserted": 0,
    "radar_events_upserted": 0,
    "radar_tracking_candidates_snapshot": False,
}


def run_radar_dual_write(
    *,
    connection_factory: Any | None,
    producer_run_id: str,
    started_at: datetime,
    window_hours: int,
    registry_sources: list[dict[str, Any]],
    statuses: list[dict[str, Any]],
    articles: list[dict[str, Any]],
    events: list[dict[str, Any]],
    tracking_candidates: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Mirror this run into the private radar schema; never affects JSON output.

    Fails closed: without the scoped credential (same authorization gate as the
    momentum history path) nothing is written. Errors are logged with DSNs
    redacted and the run continues.
    """

    if connection_factory is None:
        LOGGER.warning(
            "radar_dual_write_skipped producer_run_id=%s reason=credential_unavailable",
            producer_run_id,
        )
        return dict(RADAR_DUAL_WRITE_DEFAULTS)
    connection: Any | None = None
    try:
        connection = connection_factory()
        summary = write_radar_run(
            connection,
            run_id=producer_run_id,
            started_at=started_at,
            window_hours=window_hours,
            registry_sources=registry_sources,
            statuses=statuses,
            articles=articles,
            events=events,
            tracking_candidates=tracking_candidates,
        )
    except Exception as error:  # noqa: BLE001 - DB mirror must never fail the run
        LOGGER.warning(
            "radar_dual_write_failed producer_run_id=%s error=%s",
            producer_run_id,
            redact_error(error),
        )
        return {**RADAR_DUAL_WRITE_DEFAULTS, "radar_dual_write": "failed"}
    finally:
        if connection is not None:
            close = getattr(connection, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 - close failure is not actionable
                    pass
    LOGGER.info(
        "radar_dual_write_reconcile producer_run_id=%s json_articles=%d db_articles=%d "
        "duplicate_urls=%d json_events=%d db_events=%d duplicate_events=%d",
        producer_run_id,
        summary["json_article_count"],
        summary["db_article_count"],
        summary["duplicate_url_count"],
        summary["json_event_count"],
        summary["db_event_count"],
        summary["duplicate_event_count"],
    )
    return {
        "radar_dual_write": "written",
        "radar_articles_upserted": summary["db_article_count"],
        "radar_events_upserted": summary["db_event_count"],
        "radar_tracking_candidates_snapshot": tracking_candidates is not None,
    }


def run_momentum_side_paths(
    *,
    output_dir: Path,
    projection: Mapping[str, Any],
    taxonomy: Mapping[str, Any],
    symbol_aliases: Mapping[str, Any],
    observed_hour: datetime,
    generated_at: datetime,
    producer_run_id: str,
    connection_factory: Any | None,
) -> dict[str, Any]:
    """Publish v0.9 latest and run optional DB/history side paths."""

    result = {
        "producer_run_id": producer_run_id,
        "momentum_latest_published": False,
        "history_rows_upserted": 0,
        "retention_succeeded": False,
        "history_materialized": False,
    }
    connection: Any | None = None
    baselines: list[dict[str, Any]] = []
    if connection_factory is None:
        LOGGER.warning(
            "theme_momentum_side_path_failed producer_run_id=%s phase=connection error=credential_unavailable",
            producer_run_id,
        )
    else:
        try:
            connection = connection_factory()
        except Exception as error:  # noqa: BLE001 - optional connection stays isolated
            LOGGER.warning(
                "theme_momentum_side_path_failed producer_run_id=%s phase=connection error=%s",
                producer_run_id,
                error,
            )

    try:
        try:
            if connection is not None:
                baselines = load_momentum_baselines(connection, observed_hour)
            signals = build_public_theme_signals(
                projection,
                taxonomy=taxonomy,
                symbol_aliases=symbol_aliases,
            )
            latest_payload, observations = build_public_theme_momentum(
                signals,
                baseline_rows=baselines,
                observed_hour=observed_hour,
                generated_at=generated_at,
            )
            latest_payload = enrich_momentum_latest(
                latest_payload,
                projection.get("candidate_clusters", []),
                taxonomy,
                symbol_aliases,
            )
            latest_payload = _attach_quarterly_fundamentals(latest_payload, output_dir, generated_at)
        except Exception as error:  # noqa: BLE001 - query/validation is fail closed
            LOGGER.warning(
                "theme_momentum_side_path_failed producer_run_id=%s phase=baseline_or_projection error=%s",
                producer_run_id,
                error,
            )
            return result

        try:
            write_momentum_latest(output_dir, latest_payload)
            result = {**result, "momentum_latest_published": True}
        except Exception as error:  # noqa: BLE001 - DB history may still be stored
            LOGGER.warning(
                "theme_momentum_side_path_failed producer_run_id=%s phase=latest_publish error=%s",
                producer_run_id,
                error,
            )

        try:
            publish_stock_watchlist(
                output_dir=output_dir,
                momentum_payload=latest_payload,
                generated_at=generated_at,
                connection=connection,
            )
        except Exception as error:  # noqa: BLE001 - required watchlist publication must fail the run
            LOGGER.warning(
                "theme_momentum_side_path_failed producer_run_id=%s phase=stock_watchlist error=%s",
                producer_run_id,
                error,
            )
            raise StockWatchlistPublishError(str(error)) from error

        if connection is None:
            return result

        try:
            written = write_theme_observations(
                connection,
                observations,
                producer_run_id=producer_run_id,
            )
            result = {**result, "history_rows_upserted": written}
        except Exception as error:  # noqa: BLE001 - downstream requires current rows
            LOGGER.warning(
                "theme_momentum_side_path_failed producer_run_id=%s phase=upsert error=%s",
                producer_run_id,
                error,
            )
            return result

        try:
            delete_expired_observations(connection, observed_hour)
            result = {**result, "retention_succeeded": True}
        except Exception as error:  # noqa: BLE001 - extra old rows are repairable
            LOGGER.warning(
                "theme_momentum_side_path_failed producer_run_id=%s phase=retention error=%s",
                producer_run_id,
                error,
            )

        try:
            materialize_public_theme_history(
                output_dir / MOMENTUM_HISTORY_FILENAME,
                current_observed_hour=observed_hour,
                generated_at=generated_at,
                row_loader=lambda oldest, newest: load_history_rows(
                    connection,
                    oldest,
                    newest,
                ),
            )
            result = {**result, "history_materialized": True}
        except Exception as error:  # noqa: BLE001 - prior history bytes remain valid
            LOGGER.warning(
                "theme_momentum_side_path_failed producer_run_id=%s phase=materialize error=%s",
                producer_run_id,
                error,
            )
        return result
    finally:
        if connection is not None:
            close = getattr(connection, "close", None)
            if callable(close):
                close()


def _previous_official_records(output_dir: Path) -> list[dict[str, Any]]:
    path = output_dir / "official-evidence.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = payload.get("items")
    return items if isinstance(items, list) else []


def run_update(
    *,
    registry_path: Path,
    output_dir: Path,
    window_hours: int,
    max_events: int,
    max_candidates: int,
    official_window_hours: int = 72,
    max_official_items: int = 500,
    max_workers: int = 4,
    full_refresh: bool = False,
    history_connection_factory: Any | None = None,
) -> dict[str, Any]:
    # v0.8 fixes the public run window while retaining the existing caller signature.
    window_hours = PUBLIC_WINDOW_HOURS
    anchor = now_utc()
    registry = load_source_registry(registry_path)
    taxonomy = load_theme_taxonomy()
    symbol_aliases = augment_symbol_aliases_with_registry(load_symbol_aliases())
    sources = active_sources(registry)
    trial = trial_sources(registry)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    feed_state_path = output_dir / FEED_STATE_FILENAME
    feed_state = load_feed_state(feed_state_path)
    connection_factory = (
        history_connection_factory
        if history_connection_factory is not None
        else history_connection_factory_from_environment()
    )
    # Sources the 5-minute ingest keeps fresh are read from radar.article
    # (full window, 5-minute freshness); stale or unreachable ones fall back
    # to fetching the feed here, as before.
    ingested = load_ingested_results(
        connection_factory,
        sources,
        anchor,
        window_hours=window_hours,
    )

    results = dispatch_sources(
        session,
        [
            source
            for source in [*sources, *trial]
            if str(source["source_id"]) not in ingested
        ],
        anchor,
        max_workers=max_workers,
        fetchers={
            "rss": partial(fetch_rss_source, feed_state=feed_state),
            "twse_openapi": fetch_twse_openapi_source,
        },
        full_refresh=full_refresh,
    )
    results = sorted(
        [*results, *ingested.values()],
        key=lambda result: str(result["status"]["source_id"]),
    )
    rss_records = [
        record
        for result in results
        if result["status"].get("fetch_method") == "rss"
        for record in result["records"]
    ]
    # Trial-source records feed only the intake store, never the projection.
    discovery_records = [
        record
        for result in results
        if result["status"].get("source_class") != "official_disclosure"
        and not result["status"].get("trial")
        for record in result["records"]
    ]
    for result in results:
        if result.get("feed_state") is not None:
            feed_state[str(result["status"]["source_id"])] = result["feed_state"]
    health = record_run_history(feed_state, [result["status"] for result in results], anchor)
    for result in results:
        result["status"].update(health.get(str(result["status"]["source_id"]), {}))
    current_official_records = [
        record
        for result in results
        if result["status"].get("source_class") == "official_disclosure"
        for record in result["records"]
    ]
    statuses = [result["status"] for result in results]
    mops_source = next(
        (
            source
            for source in sources
            if source.get("fetch_method") == "twse_openapi"
            and source.get("catalog_path")
        ),
        None,
    )
    dataset_policies = (
        load_dataset_catalog(str(mops_source["catalog_path"]))["datasets"]
        if mops_source
        else []
    )
    official_payload = build_official_evidence_payload(
        [*_previous_official_records(output_dir), *current_official_records],
        generated_at=anchor,
        window_hours=official_window_hours,
        max_items=max_official_items,
        dataset_policies=dataset_policies,
    )
    official_statuses = [
        status
        for status in statuses
        if status.get("source_class") == "official_disclosure"
    ]
    official_available = any(
        status.get("status") in {"ok", "partial"} and status.get("datasets_ok", 0) > 0
        for status in official_statuses
    )

    events, candidates, projection = build_theme_projection(
        discovery_records,
        taxonomy,
        anchor=anchor,
        window_hours=window_hours,
        max_events=max_events,
        max_candidates=max_candidates,
        source_authority=source_authority_ranks(registry),
        symbol_aliases=symbol_aliases,
    )
    attached_events = attach_official_evidence(
        projection["clustered_events"],
        official_payload["items"],
        official_available=official_available,
    )
    attached_candidates = attach_official_evidence(
        projection["candidate_clusters"],
        official_payload["items"],
        official_available=official_available,
    )
    projection = {
        **projection,
        "clustered_events": attached_events,
        "candidate_clusters": attached_candidates,
    }
    events = {
        **events,
        "items": attached_events[:max_events],
    }
    candidates = {
        **candidates,
        "items": attached_candidates[:max_candidates],
    }
    # Monthly revenue is a contained side path: its sites are reported in
    # source-status.json only, never in the public-ranking source health.
    try:
        revenue_statuses = run_monthly_revenue(
            session,
            output_dir,
            anchor,
            full_refresh=full_refresh,
        )
    except Exception as error:  # noqa: BLE001 - must never break the main snapshots
        LOGGER.warning("monthly_revenue_side_path_failed error=%s", error)
        revenue_statuses = []
    status_payload = source_status_payload(
        [*statuses, *revenue_statuses],
        anchor,
        len(discovery_records),
    )
    discovery_statuses = [
        status
        for status in statuses
        if status.get("source_class") != "official_disclosure"
    ]
    public_source_status = source_status_payload(
        discovery_statuses,
        anchor,
        len(discovery_records),
    )
    official_evidence_by_id = {
        str(item["evidence_id"]): item
        for item in official_payload["items"]
        if isinstance(item, dict) and item.get("evidence_id")
    }
    public_payload, public_diagnostics = build_public_theme_ranking(
        projection,
        taxonomy=taxonomy,
        symbol_aliases=symbol_aliases,
        official_evidence_by_id=official_evidence_by_id,
        source_status=public_source_status,
        generated_at=anchor,
        window_hours=window_hours,
        official_evidence_status="available" if official_available else "unavailable",
    )
    payloads = {
        "theme-events.json": events,
        "tracking-candidates.json": candidates,
        "source-status.json": status_payload,
        "official-evidence.json": official_payload,
        "public-theme-ranking-v0.8.json": public_payload,
    }
    validate_payload_set(
        payloads,
        generated_at=anchor,
        market_id=str(projection["market_id"]),
        market_scope=list(projection["market_scope"]),
        window_hours=window_hours,
    )
    write_payload_set(output_dir, payloads)
    # Fetch state and the overlap intake store are side files: a failure here
    # must never fail the published payloads (next run just fetches
    # unconditionally).
    try:
        write_json_atomic(feed_state_path, serialize_feed_state(feed_state, anchor))
        intake_path = output_dir / INTAKE_STORE_FILENAME
        write_json_atomic(
            intake_path,
            build_intake_store(load_intake_items(intake_path), rss_records, anchor),
        )
    except Exception as error:  # noqa: BLE001 - side files are best effort
        LOGGER.warning("rss feed state was not persisted: %s", error)
    producer_run_id = f"{anchor.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex}"
    ingest_origin_ids = {
        str(status["source_id"]) for status in statuses if is_ingest_origin(status)
    }
    # JSON is already on disk above; the DB mirror runs strictly after it.
    radar_summary = run_radar_dual_write(
        connection_factory=connection_factory,
        producer_run_id=producer_run_id,
        started_at=anchor,
        window_hours=window_hours,
        registry_sources=list(registry.get("sources", [])),
        # Ingest-served sources were not fetched by this run: a source_run row
        # would read as a fetch to the ingest's min-interval check, and their
        # articles are already in radar.article.
        statuses=[status for status in statuses if not is_ingest_origin(status)],
        articles=[
            record
            for record in discovery_records
            if str(record.get("source_id")) not in ingest_origin_ids
        ],
        events=list(events["items"]),
        tracking_candidates=candidates,
    )
    try:
        momentum_summary = run_momentum_side_paths(
            output_dir=output_dir,
            projection=projection,
            taxonomy=taxonomy,
            symbol_aliases=symbol_aliases,
            observed_hour=anchor.astimezone(timezone.utc).replace(
                minute=0,
                second=0,
                microsecond=0,
            ),
            generated_at=anchor,
            producer_run_id=producer_run_id,
            connection_factory=connection_factory,
        )
    except StockWatchlistPublishError:
        raise
    except Exception as error:  # noqa: BLE001 - main snapshots are already valid
        LOGGER.warning(
            "theme_momentum_side_path_failed producer_run_id=%s phase=unexpected error=%s",
            producer_run_id,
            error,
        )
        momentum_summary = {
            "producer_run_id": producer_run_id,
            "momentum_latest_published": False,
            "history_rows_upserted": 0,
            "retention_succeeded": False,
            "history_materialized": False,
        }
    for failure in public_diagnostics["eligibility_failures"]:
        LOGGER.warning(
            "public_theme_eligibility_failure theme_id=%s rule_code=%s",
            failure["theme_id"],
            failure["rule_code"],
        )
    return {
        "raw_items": len(discovery_records),
        "official_evidence": official_payload["total_items"],
        "official_evidence_available": official_payload["total_items_available"],
        "theme_events": events["total_items"],
        "pre_cluster_events": events["pre_cluster_items"],
        "excluded_events": events["excluded_items"],
        "taiwan_relevance_states": events["tw_relevance_distribution"],
        "taiwan_relevance_reasons": events["tw_relevance_reason_distribution"],
        "tracking_candidates": candidates["total_items"],
        "failed_sources": status_payload["failed_count"],
        **momentum_summary,
        **radar_summary,
        **{
            key: public_diagnostics[key] for key in PUBLIC_OBSERVABILITY_FIELDS
        },
        "confirmation_states": {
            state: sum(
                item.get("confirmation_status") == state
                for item in events["items"]
            )
            for state in (
                "confirmed",
                "unconfirmed",
                "conflicting",
                "not_required",
                "unavailable",
            )
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--window-hours", type=int, default=PUBLIC_WINDOW_HOURS)
    parser.add_argument("--max-events", type=int, default=500)
    parser.add_argument("--max-candidates", type=int, default=200)
    parser.add_argument("--official-window-hours", type=int, default=72)
    parser.add_argument("--max-official-items", type=int, default=500)
    parser.add_argument("--max-workers", type=int, default=4, choices=range(1, MAX_SOURCE_WORKERS + 1))
    parser.add_argument("--full-refresh", action="store_true")
    args = parser.parse_args()
    summary = run_update(
        registry_path=args.registry,
        output_dir=args.output_dir,
        window_hours=args.window_hours,
        max_events=args.max_events,
        max_candidates=args.max_candidates,
        official_window_hours=args.official_window_hours,
        max_official_items=args.max_official_items,
        max_workers=args.max_workers,
        full_refresh=args.full_refresh,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
