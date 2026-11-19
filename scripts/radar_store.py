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

# High-frequency ingest runs (scripts/ingest_runner.py) also record which group
# they ran and how long the whole invocation took. Kept as a separate statement
# so the hourly writer never depends on the columns added by the ingest
# migration: applying that migration late must not break the hourly mirror.
INGEST_PIPELINE_RUN_INSERT_SQL = """
INSERT INTO radar.pipeline_run (
  run_id, started_at, window_hours, json_article_count, db_article_count,
  duplicate_url_count, json_event_count, db_event_count,
  duplicate_event_count, failed_source_count, run_kind, ingest_group,
  elapsed_ms
) VALUES (
  %(run_id)s, %(started_at)s, %(window_hours)s, %(json_article_count)s,
  %(db_article_count)s, %(duplicate_url_count)s, %(json_event_count)s,
  %(db_event_count)s, %(duplicate_event_count)s, %(failed_source_count)s,
  %(run_kind)s, %(ingest_group)s, %(elapsed_ms)s
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


PRE_MARKET_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "generated_at", "window_hours", "sources", "events",
     "pulse", "sectors", "flows"}
)

# Added by #9 (PR #20); optional so either merge order keeps the mirror working.
PRE_MARKET_OPTIONAL_KEYS = frozenset({"direction_rule_version"})

PRE_MARKET_UPSERT_SQL = """
INSERT INTO radar.pre_market_snapshot (
  generated_at, schema_version, window_hours, event_count, payload
) VALUES (
  %(generated_at)s, %(schema_version)s, %(window_hours)s, %(event_count)s,
  %(payload)s::jsonb
)
ON CONFLICT (generated_at) DO UPDATE SET
  schema_version = EXCLUDED.schema_version,
  window_hours = EXCLUDED.window_hours,
  event_count = EXCLUDED.event_count,
  payload = EXCLUDED.payload,
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


# Top-level keys NexusDashboard reads from tracking-candidates.json. Mirrored in
# src/lib/trackingCandidatesContract.js; the API refuses a snapshot missing any.
# Extra keys are allowed: additive fields do not break the consumer.
TRACKING_CANDIDATES_REQUIRED_KEYS = (
    "generated_at", "market_id", "market_scope", "window_hours", "max_items",
    "total_items", "total_items_available", "items", "pre_cluster_items",
    "excluded_items", "tw_relevance_distribution",
    "tw_relevance_reason_distribution", "selected_theme_score_min",
    "candidate_theme_score_min", "matcher_contract", "taxonomy_version",
    "legacy_theme_count", "structured_theme_count", "theme_match_distribution",
    "theme_veto_distribution",
)

TRACKING_CANDIDATES_UPSERT_SQL = """
INSERT INTO radar.tracking_candidates_snapshot (
  generated_at, run_id, item_count, payload
) VALUES (
  %(generated_at)s, %(run_id)s, %(item_count)s, %(payload)s::jsonb
)
ON CONFLICT (generated_at) DO UPDATE SET
  run_id = EXCLUDED.run_id,
  item_count = EXCLUDED.item_count,
  payload = EXCLUDED.payload,
  updated_at = now()
""".strip()


def map_tracking_candidates_snapshot(
    payload: Mapping[str, Any],
    *,
    run_id: str,
) -> dict[str, Any]:
    """Validate tracking-candidates.json and map it to one snapshot row.

    The row stores the payload verbatim; the API serves it unchanged, so a
    payload that would break NexusDashboard is rejected here, not stored.
    """

    if not isinstance(payload, Mapping):
        raise ValueError("tracking-candidates payload must be an object")
    missing = [key for key in TRACKING_CANDIDATES_REQUIRED_KEYS if key not in payload]
    if missing:
        raise ValueError(f"tracking-candidates payload is missing keys {missing}")
    items = payload["items"]
    if not isinstance(items, list):
        raise ValueError("tracking-candidates payload items must be a list")
    return {
        "generated_at": _timestamp(payload["generated_at"], "tracking_candidates.generated_at"),
        "run_id": run_id,
        "item_count": len(items),
        "payload": _json(dict(payload)),
    }


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
    ingest_group: str | None = None,
    elapsed_ms: int | None = None,
    tracking_candidates: Mapping[str, Any] | None = None,
) -> dict[str, int]:
    """Write one pipeline run to the radar schema in a single transaction.

    Mapping and validation happen before the transaction opens, so malformed
    input never leaves a partial run behind.

    ``ingest_group`` marks a high-frequency ingest run; the row then records
    ``run_kind='ingest'``, the group and the invocation's ``elapsed_ms``.
    Without it the statement is byte-identical to the hourly writer's.
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
    snapshot_row = (
        map_tracking_candidates_snapshot(tracking_candidates, run_id=run_id)
        if tracking_candidates is not None
        else None
    )
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
            run_row: dict[str, Any] = {
                "run_id": run_id,
                "started_at": anchor,
                "window_hours": int(window_hours),
                **summary,
            }
            if ingest_group is None:
                cursor.execute(PIPELINE_RUN_INSERT_SQL, run_row)
            else:
                cursor.execute(
                    INGEST_PIPELINE_RUN_INSERT_SQL,
                    {
                        **run_row,
                        "run_kind": "ingest",
                        "ingest_group": ingest_group,
                        "elapsed_ms": (
                            None if elapsed_ms is None else max(int(elapsed_ms), 0)
                        ),
                    },
                )
            if source_runs:
                cursor.executemany(SOURCE_RUN_INSERT_SQL, source_runs)
            if article_rows:
                cursor.executemany(ARTICLE_UPSERT_SQL, article_rows)
            if event_rows:
                cursor.executemany(EVENT_UPSERT_SQL, event_rows)
            if snapshot_row is not None:
                # After pipeline_run: the snapshot's run_id references it.
                cursor.execute(TRACKING_CANDIDATES_UPSERT_SQL, snapshot_row)
    return summary


def map_pre_market_snapshot(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a pre-market payload and map it to one snapshot row.

    The row stores the payload verbatim; the API serves it unchanged, so any
    key drift here would break the front-end contract. Reject rather than store.
    """

    keys = set(payload.keys())
    missing = sorted(PRE_MARKET_TOP_LEVEL_KEYS - keys)
    extra = sorted(keys - PRE_MARKET_TOP_LEVEL_KEYS - PRE_MARKET_OPTIONAL_KEYS)
    if missing or extra:
        raise ValueError(f"pre-market payload keys mismatch missing={missing} extra={extra}")
    events = payload["events"]
    if not isinstance(events, list):
        raise ValueError("pre-market payload events must be a list")
    return {
        "generated_at": _timestamp(payload["generated_at"], "generated_at"),
        "schema_version": int(payload["schema_version"]),
        "window_hours": int(payload["window_hours"]),
        "event_count": len(events),
        "payload": _json(payload),
    }


EVENT_IMPACT_UPSERT_SQL = """
INSERT INTO radar.event_impact (
  event_id, target_type, target_id, rule_version, path_id, direction,
  magnitude, horizon, reason
) VALUES (
  %(event_id)s, %(target_type)s, %(target_id)s, %(rule_version)s, %(path_id)s,
  %(direction)s, %(magnitude)s, %(horizon)s, %(reason)s
)
ON CONFLICT (event_id, target_id, rule_version) DO UPDATE SET
  target_type = EXCLUDED.target_type,
  path_id = EXCLUDED.path_id,
  direction = EXCLUDED.direction,
  magnitude = EXCLUDED.magnitude,
  horizon = EXCLUDED.horizon,
  reason = EXCLUDED.reason,
  updated_at = now()
""".strip()

FOCUS_SOURCE_ID = "financialjuice"


def focus_event_id(title: str) -> str:
    """Stable id for a wire headline: the same story keeps one radar.event row."""

    digest = hashlib.sha1(" ".join(str(title or "").split()).encode("utf-8")).hexdigest()
    return f"{FOCUS_SOURCE_ID}-{digest[:16]}"


def map_focus_events(
    payload: Mapping[str, Any],
    impact_rows: Any,
    rule_version: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Map pre-market focus events to radar.event + radar.event_impact rows.

    ``impact_rows`` is event_direction.impact_rows, injected so this module does
    not import the rule engine. Events without a direction (written before #9)
    are skipped: an impact row without a rule decision would be invented.
    """

    generated_at = _timestamp(payload["generated_at"], "generated_at")
    run_id = f"pre-market-{generated_at.isoformat()}"
    events: list[dict[str, Any]] = []
    impacts: list[dict[str, Any]] = []
    for item in payload.get("events") or []:
        title = str(item.get("titleEn") or "").strip()
        if not title or "direction" not in item:
            continue
        try:
            published_at = _timestamp(item.get("publishedAt"), "publishedAt")
        except ValueError:
            continue  # one malformed row must not cost the snapshot
        event_id = focus_event_id(title)
        url = str(item.get("url") or "")
        try:
            rep_hash = url_hash(url)
        except ValueError:
            rep_hash = hashlib.sha256(title.encode("utf-8")).hexdigest()
        members = [event_id] + [
            focus_event_id(str(rel.get("title") or rel.get("url") or index))
            for index, rel in enumerate(item.get("related") or [])
            if isinstance(rel, Mapping)
        ]
        members = list(dict.fromkeys(members))
        events.append({
            "event_id": event_id,
            "representative_article_id": event_id,
            "representative_url_hash": rep_hash,
            "source_id": FOCUS_SOURCE_ID,
            "title": title,
            "published_at": published_at,
            "primary_theme_id": item.get("pathId"),
            "theme_score": item.get("score"),
            "decision": item.get("tier"),
            "tw_relevance_status": None,
            "confirmation_status": None,
            "cluster_size": len(members),
            "member_article_ids": members,
            "official_evidence_count": 0,
            "payload": _json(item),
            "seen_at": generated_at,
            "run_id": run_id,
        })
        for row in impact_rows({**item, "id": event_id}, rule_version=rule_version):
            impacts.append(row)
    return events, impacts


def write_pre_market_snapshot(
    connection: Any,
    payload: Mapping[str, Any],
    *,
    impact_rows: Any = None,
) -> dict[str, Any]:
    """Upsert one pre-market snapshot -- and, with ``impact_rows``, its focus
    events and their (event x sector) directions -- in one transaction."""

    row = map_pre_market_snapshot(payload)
    events: list[dict[str, Any]] = []
    impacts: list[dict[str, Any]] = []
    if impact_rows is not None:
        rule_version = str(payload.get("direction_rule_version") or "")
        if rule_version:
            events, impacts = map_focus_events(payload, impact_rows, rule_version)
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(PRE_MARKET_UPSERT_SQL, row)
            if events:
                # Events first: event_impact references radar.event.
                cursor.executemany(EVENT_UPSERT_SQL, events)
            if impacts:
                cursor.executemany(EVENT_IMPACT_UPSERT_SQL, impacts)
    return {
        "generated_at": row["generated_at"].isoformat(),
        "event_count": row["event_count"],
        "focus_events_written": len(events),
        "impacts_written": len(impacts),
    }
