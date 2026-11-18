"""Dual-write of each pipeline run into the private Postgres `radar` schema.

The JSON files under data/ remain the published source of truth. This module
only mirrors what a run already produced (sources, per-source run status, raw
articles, clustered events) so the later API layer can read from the DB. Every
DB failure is contained by the caller: JSON publication never depends on it.

All writes for one run happen in a single transaction, so the DB either holds
the whole run or none of it.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = frozenset({"fbclid", "gclid", "mc_cid", "mc_eid"})
_DSN_PATTERN = re.compile(r"postgres(?:ql)?://\S+", re.IGNORECASE)
_KV_SECRET_PATTERN = re.compile(r"(password|passwd|pwd)\s*=\s*\S+", re.IGNORECASE)

SOURCE_UPSERT_SQL = """
INSERT INTO radar.source (
  source_id, name, source_class, fetch_method, feed_url, homepage,
  authority_rank, registry_status, enabled
) VALUES (
  %(source_id)s, %(name)s, %(source_class)s, %(fetch_method)s, %(feed_url)s,
  %(homepage)s, %(authority_rank)s, %(registry_status)s, %(enabled)s
)
ON CONFLICT (source_id) DO UPDATE SET
  name = EXCLUDED.name,
  source_class = EXCLUDED.source_class,
  fetch_method = EXCLUDED.fetch_method,
  feed_url = EXCLUDED.feed_url,
  homepage = EXCLUDED.homepage,
  authority_rank = EXCLUDED.authority_rank,
  registry_status = EXCLUDED.registry_status,
  enabled = EXCLUDED.enabled,
  updated_at = now()
""".strip()

PIPELINE_RUN_INSERT_SQL = """
INSERT INTO radar.pipeline_run (
  run_id, started_at, window_hours, json_article_count, db_article_count,
  duplicate_url_count, json_event_count, db_event_count,
  duplicate_event_count, failed_source_count
) VALUES (
  %(run_id)s, %(started_at)s, %(window_hours)s, %(json_article_count)s,
  %(db_article_count)s, %(duplicate_url_count)s, %(json_event_count)s,
  %(db_event_count)s, %(duplicate_event_count)s, %(failed_source_count)s
)
""".strip()

SOURCE_RUN_INSERT_SQL = """
INSERT INTO radar.source_run (
  run_id, source_id, started_at, status, item_count, elapsed_ms, error, detail
) VALUES (
  %(run_id)s, %(source_id)s, %(started_at)s, %(status)s, %(item_count)s,
  %(elapsed_ms)s, %(error)s, %(detail)s::jsonb
)
""".strip()

ARTICLE_UPSERT_SQL = """
INSERT INTO radar.article (
  url_hash, article_id, source_id, source_class, market_id, url, title,
  summary, extraction_method, published_at, first_fetched_at,
  last_fetched_at, first_run_id, last_run_id
) VALUES (
  %(url_hash)s, %(article_id)s, %(source_id)s, %(source_class)s,
  %(market_id)s, %(url)s, %(title)s, %(summary)s, %(extraction_method)s,
  %(published_at)s, %(fetched_at)s, %(fetched_at)s, %(run_id)s, %(run_id)s
)
ON CONFLICT (url_hash) DO UPDATE SET
  title = EXCLUDED.title,
  summary = EXCLUDED.summary,
  published_at = EXCLUDED.published_at,
  last_fetched_at = GREATEST(radar.article.last_fetched_at, EXCLUDED.last_fetched_at),
  last_run_id = EXCLUDED.last_run_id,
  seen_count = radar.article.seen_count + 1,
  updated_at = now()
""".strip()

EVENT_UPSERT_SQL = """
INSERT INTO radar.event (
  event_id, representative_article_id, representative_url_hash, source_id,
  title, published_at, primary_theme_id, theme_score, decision,
  tw_relevance_status, confirmation_status, cluster_size,
  member_article_ids, official_evidence_count, payload, first_seen_at,
  last_seen_at, first_run_id, last_run_id
) VALUES (
  %(event_id)s, %(representative_article_id)s, %(representative_url_hash)s,
  %(source_id)s, %(title)s, %(published_at)s, %(primary_theme_id)s,
  %(theme_score)s, %(decision)s, %(tw_relevance_status)s,
  %(confirmation_status)s, %(cluster_size)s, %(member_article_ids)s,
  %(official_evidence_count)s, %(payload)s::jsonb, %(seen_at)s, %(seen_at)s,
  %(run_id)s, %(run_id)s
)
ON CONFLICT (event_id) DO UPDATE SET
  title = EXCLUDED.title,
  primary_theme_id = EXCLUDED.primary_theme_id,
  theme_score = EXCLUDED.theme_score,
  decision = EXCLUDED.decision,
  tw_relevance_status = EXCLUDED.tw_relevance_status,
  confirmation_status = EXCLUDED.confirmation_status,
  official_evidence_count = EXCLUDED.official_evidence_count,
  payload = EXCLUDED.payload,
  last_seen_at = GREATEST(radar.event.last_seen_at, EXCLUDED.last_seen_at),
  last_run_id = EXCLUDED.last_run_id,
  updated_at = now()
""".strip()


def redact_error(error: BaseException) -> str:
    """Return a log-safe error string: class name plus message with DSNs removed."""

    message = _DSN_PATTERN.sub("<redacted-dsn>", str(error))
    message = _KV_SECRET_PATTERN.sub(r"\1=<redacted>", message)
    message = " ".join(message.split())[:300]
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


def normalize_url(url: str) -> str:
    """Normalize a URL for dedup: lowercase scheme/host, drop fragment and trackers."""

    raw = str(url or "").strip()
    if not raw:
        raise ValueError("article url must be non-empty")
    parts = urlsplit(raw)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS
        and not key.lower().startswith(TRACKING_QUERY_PREFIXES)
    ]
    netloc = parts.netloc.lower()
    scheme = parts.scheme.lower()
    if (scheme, netloc.rsplit(":", 1)[-1]) in {("http", "80"), ("https", "443")}:
        netloc = netloc.rsplit(":", 1)[0]
    return urlunsplit((scheme, netloc, parts.path or "/", urlencode(query), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


def _timestamp(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{label} must be a valid timestamp") from error
    else:
        raise ValueError(f"{label} must be a timestamp")
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def map_sources(
    registry_sources: Iterable[Mapping[str, Any]],
    *,
    extra_source_ids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Map registry entries to radar.source rows.

    ``extra_source_ids`` covers any source a run reported that is not in the
    registry, so the article/source_run foreign keys can never reject a run.
    """

    rows: dict[str, dict[str, Any]] = {}
    for source in registry_sources:
        source_id = str(source.get("source_id") or "").strip()
        if not source_id:
            continue
        status = str(source.get("status") or "unknown")
        rows[source_id] = {
            "source_id": source_id,
            "name": str(source.get("name") or source_id),
            "source_class": source.get("source_class"),
            "fetch_method": source.get("fetch_method"),
            "feed_url": source.get("feed_url"),
            "homepage": source.get("homepage"),
            "authority_rank": _optional_int(source.get("authority_rank")),
            "registry_status": status,
            "enabled": status == "active" and bool(source.get("fetch_method")),
        }
    for raw_id in extra_source_ids:
        source_id = str(raw_id or "").strip()
        if source_id and source_id not in rows:
            rows[source_id] = {
                "source_id": source_id,
                "name": source_id,
                "source_class": None,
                "fetch_method": None,
                "feed_url": None,
                "homepage": None,
                "authority_rank": None,
                "registry_status": "unregistered",
                "enabled": False,
            }
    return [rows[key] for key in sorted(rows)]


def map_source_runs(
    statuses: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    started_at: datetime,
) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for status in statuses:
        source_id = str(status.get("source_id") or "").strip()
        if not source_id:
            raise ValueError("source status is missing source_id")
        if source_id in rows:
            raise ValueError(f"duplicate source status for {source_id}")
        items = _optional_int(status.get("items"))
        elapsed = _optional_int(status.get("elapsed_ms"))
        error = status.get("error")
        rows[source_id] = {
            "run_id": run_id,
            "source_id": source_id,
            "started_at": started_at,
            "status": str(status.get("status") or "unknown"),
            "item_count": max(items or 0, 0),
            "elapsed_ms": elapsed if elapsed is None or elapsed >= 0 else None,
            "error": None if error in (None, "") else str(error)[:2000],
            "detail": _json(dict(status)),
        }
    return [rows[key] for key in sorted(rows)]


def map_articles(
    records: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    fetched_fallback: datetime,
) -> tuple[list[dict[str, Any]], int]:
    """Map raw discovery records to radar.article rows, deduped by url_hash.

    Returns ``(rows, duplicate_count)``. Within one run the same URL can arrive
    from more than one feed; the first occurrence wins and the rest are counted
    so the JSON-vs-DB reconciliation can explain the difference.
    """

    rows: dict[str, dict[str, Any]] = {}
    duplicates = 0
    for record in records:
        hashed = url_hash(str(record.get("url") or ""))
        if hashed in rows:
            duplicates += 1
            continue
        fetched_raw = record.get("fetched_at")
        fetched_at = (
            _timestamp(fetched_raw, "article.fetched_at")
            if fetched_raw
            else fetched_fallback
        )
        source_id = str(record.get("source_id") or "").strip()
        title = str(record.get("title_zh") or record.get("title") or "").strip()
        if not source_id or not title:
            raise ValueError("article requires source_id and title")
        rows[hashed] = {
            "url_hash": hashed,
            "article_id": str(record.get("id") or hashed),
            "source_id": source_id,
            "source_class": record.get("source_class"),
            "market_id": str(record.get("market_id") or "TW_EQUITY"),
            "url": str(record.get("url")).strip(),
            "title": title,
            "summary": str(record.get("summary") or ""),
            "extraction_method": record.get("extraction_method"),
            "published_at": _timestamp(record.get("published_at"), "article.published_at"),
            "fetched_at": fetched_at,
            "run_id": run_id,
        }
    return list(rows.values()), duplicates


def map_events(
    items: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    seen_at: datetime,
) -> tuple[list[dict[str, Any]], int]:
    """Map theme-events.json items to radar.event rows keyed by cluster_id."""

    rows: dict[str, dict[str, Any]] = {}
    duplicates = 0
    for item in items:
        event_id = str(item.get("cluster_id") or "").strip()
        if not event_id:
            raise ValueError("event item is missing cluster_id")
        if event_id in rows:
            duplicates += 1
            continue
        members = [str(member) for member in item.get("cluster_event_ids") or []]
        if not members:
            members = [str(item.get("id") or event_id)]
        theme_score = item.get("theme_score")
        rows[event_id] = {
            "event_id": event_id,
            "representative_article_id": str(item.get("id") or ""),
            "representative_url_hash": url_hash(str(item.get("url") or "")),
            "source_id": str(item.get("source_id") or ""),
            "title": str(item.get("title_zh") or item.get("title") or ""),
            "published_at": _timestamp(item.get("published_at"), "event.published_at"),
            "primary_theme_id": item.get("primary_theme_id"),
            "theme_score": (
                theme_score
                if isinstance(theme_score, (int, float)) and not isinstance(theme_score, bool)
                else None
            ),
            "decision": item.get("decision"),
            "tw_relevance_status": item.get("tw_relevance_status"),
            "confirmation_status": item.get("confirmation_status"),
            "cluster_size": len(members),
            "member_article_ids": members,
            "official_evidence_count": max(_optional_int(item.get("official_evidence_count")) or 0, 0),
            "payload": _json(dict(item)),
            "seen_at": seen_at,
            "run_id": run_id,
        }
    return list(rows.values()), duplicates


def write_radar_run(
    connection: Any,
    *,
    run_id: str,
    started_at: datetime,
    window_hours: int,
    registry_sources: Sequence[Mapping[str, Any]],
    statuses: Sequence[Mapping[str, Any]],
    articles: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    """Write one pipeline run to the radar schema in a single transaction.

    Mapping and validation happen before the transaction opens, so malformed
    input never leaves a partial run behind.
    """

    if not run_id.strip():
        raise ValueError("run_id must be non-empty")
    anchor = _timestamp(started_at, "started_at")
    source_runs = map_source_runs(statuses, run_id=run_id, started_at=anchor)
    trial_source_ids = {str(status["source_id"]) for status in statuses if status.get("trial")}
    article_rows, duplicate_urls = map_articles(
        articles, run_id=run_id, fetched_fallback=anchor
    )
    event_rows, duplicate_events = map_events(events, run_id=run_id, seen_at=anchor)
    source_rows = map_sources(
        registry_sources,
        extra_source_ids=[
            *(row["source_id"] for row in source_runs),
            *(row["source_id"] for row in article_rows),
        ],
    )
    summary = {
        "json_article_count": len(articles),
        "db_article_count": len(article_rows),
        "duplicate_url_count": duplicate_urls,
        "json_event_count": len(events),
        "db_event_count": len(event_rows),
        "duplicate_event_count": duplicate_events,
        # Trial sources (registry status "trial") are recorded per run but,
        # as in source-status.json, do not count toward run health.
        "failed_source_count": sum(
            1
            for row in source_runs
            if row["status"] != "ok" and row["source_id"] not in trial_source_ids
        ),
    }
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.executemany(SOURCE_UPSERT_SQL, source_rows)
            cursor.execute(
                PIPELINE_RUN_INSERT_SQL,
                {
                    "run_id": run_id,
                    "started_at": anchor,
                    "window_hours": int(window_hours),
                    **summary,
                },
            )
            if source_runs:
                cursor.executemany(SOURCE_RUN_INSERT_SQL, source_runs)
            if article_rows:
                cursor.executemany(ARTICLE_UPSERT_SQL, article_rows)
            if event_rows:
                cursor.executemany(EVENT_UPSERT_SQL, event_rows)
    return summary
