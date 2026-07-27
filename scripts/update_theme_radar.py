"""Fetch public Taiwan-market RSS/news feeds and publish static theme radar JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import feedparser
import requests

try:
    from scripts.theme_relevance import enrich_item_with_themes, load_theme_taxonomy
except ModuleNotFoundError:
    from theme_relevance import enrich_item_with_themes, load_theme_taxonomy


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = ROOT / "config" / "source_registry.tw.json"
DEFAULT_OUTPUT_DIR = ROOT / "data"
REQUEST_TIMEOUT_SECONDS = 20
USER_AGENT = "TaiwanEquityThemeRadar/0.1 (+https://github.com/)"


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


def rss_sources(registry: dict[str, Any]) -> list[dict[str, Any]]:
    market_id = registry.get("market_id") or "TW_EQUITY"
    market_scope = registry.get("market_scope") or ["TW_EQUITY"]
    return [
        {
            "market_id": market_id,
            "market_scope": market_scope,
            **source,
        }
        for source in registry.get("sources", [])
        if source.get("feed_url") and source.get("status") in {"active", "planned"}
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


def fetch_rss_source(session: requests.Session, source: dict[str, Any], fetched_at: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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
    try:
        response = session.get(feed_url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
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
        status["elapsed_ms"] = round((time.monotonic() - started) * 1000)


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


def run_update(*, registry_path: Path, output_dir: Path, window_hours: int, max_events: int, max_candidates: int) -> dict[str, Any]:
    anchor = now_utc()
    registry = load_source_registry(registry_path)
    taxonomy = load_theme_taxonomy()
    sources = rss_sources(registry)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    all_records: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for source in sources:
        records, status = fetch_rss_source(session, source, anchor)
        all_records.extend(records)
        statuses.append(status)

    events, candidates = build_theme_payloads(
        all_records,
        taxonomy,
        anchor=anchor,
        window_hours=window_hours,
        max_events=max_events,
        max_candidates=max_candidates,
    )
    status_payload = source_status_payload(statuses, anchor, len(all_records))
    write_json(output_dir / "theme-events.json", events)
    write_json(output_dir / "tracking-candidates.json", candidates)
    write_json(output_dir / "source-status.json", status_payload)
    return {
        "raw_items": len(all_records),
        "theme_events": events["total_items"],
        "tracking_candidates": candidates["total_items"],
        "failed_sources": status_payload["failed_count"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--window-hours", type=int, default=48)
    parser.add_argument("--max-events", type=int, default=500)
    parser.add_argument("--max-candidates", type=int, default=200)
    args = parser.parse_args()
    summary = run_update(
        registry_path=args.registry,
        output_dir=args.output_dir,
        window_hours=args.window_hours,
        max_events=args.max_events,
        max_candidates=args.max_candidates,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
