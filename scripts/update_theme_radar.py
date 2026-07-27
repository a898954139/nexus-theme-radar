"""Fetch public Taiwan-market RSS/news feeds and publish static theme radar JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import feedparser
import requests

try:
    from scripts.source_adapters import (
        CONFLICT_TERMS,
        build_official_evidence_payload,
        fetch_twse_openapi_source,
        load_dataset_catalog,
        read_bounded_response,
    )
    from scripts.theme_relevance import enrich_item_with_themes, load_theme_taxonomy
except ModuleNotFoundError:
    from source_adapters import (
        CONFLICT_TERMS,
        build_official_evidence_payload,
        fetch_twse_openapi_source,
        load_dataset_catalog,
        read_bounded_response,
    )
    from theme_relevance import enrich_item_with_themes, load_theme_taxonomy


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = ROOT / "config" / "source_registry.tw.json"
DEFAULT_OUTPUT_DIR = ROOT / "data"
REQUEST_TIMEOUT_SECONDS = 20
MAX_RSS_RESPONSE_BYTES = 8 * 1024 * 1024
USER_AGENT = "TaiwanEquityThemeRadar/0.1 (+https://github.com/)"
MAX_SOURCE_WORKERS = 5


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
    return payload


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


def rss_sources(registry: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        source
        for source in active_sources(registry)
        if source.get("fetch_method") == "rss" and source.get("feed_url")
    ]


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
        "published_at": parse_timestamp(published_raw, fetched_at).isoformat().replace("+00:00", "Z"),
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
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    del full_refresh
    started = time.monotonic()
    feed_url = str(source["feed_url"])
    status = {
        "source_id": source["source_id"],
        "name": source.get("name") or source["source_id"],
        "source_class": source.get("source_class"),
        "fetch_method": "rss",
        "feed_url": feed_url,
        "status": "ok",
        "items": 0,
        "error": None,
        "elapsed_ms": 0,
    }
    response = None
    try:
        max_response_bytes = max(
            1,
            int(source.get("max_response_bytes") or MAX_RSS_RESPONSE_BYTES),
        )
        response = session.get(
            feed_url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            stream=True,
        )
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
        return items, status
    except Exception as exc:  # noqa: BLE001 - source status must capture any fetch failure
        status["status"] = "error"
        status["error"] = str(exc)
        return [], status
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
        return {"records": records, "status": status}
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


def build_theme_payloads(records: list[dict[str, Any]], taxonomy: dict[str, Any], *, anchor: datetime, window_hours: int, max_events: int, max_candidates: int) -> tuple[dict[str, Any], dict[str, Any]]:
    if window_hours <= 0 or max_events <= 0 or max_candidates <= 0:
        raise ValueError("window and item bounds must be positive")
    cutoff = anchor - timedelta(hours=window_hours)
    in_window = [
        record
        for record in dedupe_records(records)
        if record.get("published_at") and cutoff <= parse_timestamp(str(record["published_at"])) <= anchor
    ]
    enriched = [enrich_item_with_themes(record, taxonomy) for record in in_window]
    matched = [item for item in enriched if item["matched_themes"]]
    candidates = [
        {**item, "tracking_reason": item["matched_themes"][0]["reason"]}
        for item in matched
        if item["theme_score"] >= 0.5 and item.get("related_symbols")
    ]
    market_id = str(taxonomy.get("market_id") or "TW_EQUITY")
    market_scope = list(taxonomy.get("market_scope") or [market_id])
    return (
        _payload(
            items=matched[:max_events],
            available_count=len(matched),
            generated_at=anchor,
            window_hours=window_hours,
            max_items=max_events,
            market_id=market_id,
            market_scope=market_scope,
        ),
        _payload(
            items=candidates[:max_candidates],
            available_count=len(candidates),
            generated_at=anchor,
            window_hours=window_hours,
            max_items=max_candidates,
            market_id=market_id,
            market_scope=market_scope,
        ),
    )


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
    failed = sum(1 for status in statuses if status["status"] != "ok")
    successful = len(statuses) - failed
    return {
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "fetched_raw_items": raw_count,
        "items_before_topic_filter": raw_count,
        "successful_sites": successful,
        "failed_count": failed,
        "failed_sites": [status["source_id"] for status in statuses if status["status"] != "ok"],
        "sites": statuses,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
) -> dict[str, Any]:
    anchor = now_utc()
    registry = load_source_registry(registry_path)
    taxonomy = load_theme_taxonomy()
    sources = active_sources(registry)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    results = dispatch_sources(
        session,
        sources,
        anchor,
        max_workers=max_workers,
        full_refresh=full_refresh,
    )
    discovery_records = [
        record
        for result in results
        if result["status"].get("source_class") != "official_disclosure"
        for record in result["records"]
    ]
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

    events, candidates = build_theme_payloads(
        discovery_records,
        taxonomy,
        anchor=anchor,
        window_hours=window_hours,
        max_events=max_events,
        max_candidates=max_candidates,
    )
    events = {
        **events,
        "items": attach_official_evidence(
            events["items"],
            official_payload["items"],
            official_available=official_available,
        ),
    }
    candidates = {
        **candidates,
        "items": attach_official_evidence(
            candidates["items"],
            official_payload["items"],
            official_available=official_available,
        ),
    }
    status_payload = source_status_payload(statuses, anchor, len(discovery_records))
    write_json(output_dir / "theme-events.json", events)
    write_json(output_dir / "tracking-candidates.json", candidates)
    write_json(output_dir / "source-status.json", status_payload)
    write_json(output_dir / "official-evidence.json", official_payload)
    return {
        "raw_items": len(discovery_records),
        "official_evidence": official_payload["total_items"],
        "official_evidence_available": official_payload["total_items_available"],
        "theme_events": events["total_items"],
        "tracking_candidates": candidates["total_items"],
        "failed_sources": status_payload["failed_count"],
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
    parser.add_argument("--window-hours", type=int, default=48)
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
