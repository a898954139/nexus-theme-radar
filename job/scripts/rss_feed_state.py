"""Persistent per-feed state for the hourly RSS fetch.

Three concerns live here, all keyed by ``source_id``:

* Conditional GET (ETag / If-Modified-Since). A feed that answers ``304`` has
  no new entries, but each run publishes a fresh snapshot, so the items from
  the last ``200`` are cached and replayed. Without that replay a 304 would
  silently drop the source from the 72-hour window.
* A rolling 7-day run history per feed, from which ``success_rate_7d`` is
  derived for the source status page and for trial-source promotion.
* A rolling 7-day intake store (title / url / timestamps only) that
  ``scripts/evaluate_source_overlap.py --candidate-from-baseline`` reads, so a
  trial source's duplicate rate is measured over a real 7-day window instead
  of a single RSS snapshot.

Every loader here is fail-open: a missing or corrupt state file degrades to an
unconditional fetch, never to a failed run.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

FEED_STATE_FILENAME = "rss-fetch-state.json"
INTAKE_STORE_FILENAME = "source-intake-7d.json"
FEED_STATE_VERSION = 1
HISTORY_DAYS = 7
INTAKE_DAYS = 7
MAX_CACHED_ITEMS_PER_FEED = 200
INTAKE_FIELDS = ("site_id", "site_name", "title", "url", "published_at", "first_seen_at")


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary.write(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


# --- conditional GET -------------------------------------------------------


def load_feed_state(path: Path) -> dict[str, dict[str, Any]]:
    payload = _read_json_object(path)
    if payload.get("version") != FEED_STATE_VERSION:
        return {}
    feeds = payload.get("feeds")
    if not isinstance(feeds, dict):
        return {}
    return {str(key): value for key, value in feeds.items() if isinstance(value, dict)}


def conditional_headers(entry: Mapping[str, Any] | None, feed_url: str) -> dict[str, str]:
    """Validators to send, or none when a 304 could not be served from cache."""
    if not entry or entry.get("feed_url") != feed_url:
        return {}
    if not isinstance(entry.get("items"), list) or not entry["items"]:
        return {}
    headers: dict[str, str] = {}
    if entry.get("etag"):
        headers["If-None-Match"] = str(entry["etag"])
    if entry.get("last_modified"):
        headers["If-Modified-Since"] = str(entry["last_modified"])
    return headers


def cached_items(entry: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not entry or not isinstance(entry.get("items"), list):
        return []
    return [item for item in entry["items"] if isinstance(item, dict)]


def fresh_entry(
    previous: Mapping[str, Any] | None,
    *,
    feed_url: str,
    etag: str | None,
    last_modified: str | None,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "feed_url": feed_url,
        "etag": etag or None,
        "last_modified": last_modified or None,
        "items": items[:MAX_CACHED_ITEMS_PER_FEED],
        "history": list((previous or {}).get("history") or []),
    }


# --- run history -----------------------------------------------------------


def record_run_history(
    state: dict[str, dict[str, Any]],
    statuses: Iterable[Mapping[str, Any]],
    anchor: datetime,
) -> dict[str, dict[str, Any]]:
    """Append this run's outcome per RSS source and return 7-day health stats."""
    cutoff = anchor - timedelta(days=HISTORY_DAYS)
    stats: dict[str, dict[str, Any]] = {}
    for status in statuses:
        if status.get("fetch_method") != "rss":
            continue
        source_id = str(status["source_id"])
        entry = state.setdefault(source_id, {"feed_url": status.get("feed_url"), "items": []})
        history = [
            run
            for run in entry.get("history") or []
            if isinstance(run, dict) and (ts := _parse_utc(run.get("at"))) and ts >= cutoff
        ]
        history.append(
            {
                "at": _utc_text(anchor),
                "ok": status.get("status") == "ok",
                "not_modified": bool(status.get("not_modified")),
                "items": int(status.get("items") or 0),
            }
        )
        entry["history"] = history
        ok_runs = sum(1 for run in history if run.get("ok"))
        stats[source_id] = {
            "runs_7d": len(history),
            "success_rate_7d": round(ok_runs / len(history), 3),
        }
    return stats


def serialize_feed_state(state: Mapping[str, Mapping[str, Any]], anchor: datetime) -> dict[str, Any]:
    return {
        "version": FEED_STATE_VERSION,
        "generated_at": _utc_text(anchor),
        "feeds": {key: state[key] for key in sorted(state)},
    }


# --- 7-day intake store ----------------------------------------------------


def load_intake_items(path: Path) -> list[dict[str, Any]]:
    items = _read_json_object(path).get("items")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def build_intake_store(
    previous: list[dict[str, Any]],
    records: Iterable[Mapping[str, Any]],
    anchor: datetime,
) -> dict[str, Any]:
    """Merge this run's RSS records into the rolling intake store.

    ``first_seen_at`` survives across runs so the window is measured from when
    the radar first saw an item, which is what overlap timing compares.
    """
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for item in previous:
        key = (str(item.get("site_id") or ""), str(item.get("url") or ""))
        if all(key):
            merged[key] = {field: item.get(field) for field in INTAKE_FIELDS}
    for record in records:
        site_id = str(record.get("source_id") or "")
        url = str(record.get("url") or "")
        if not site_id or not url:
            continue
        existing = merged.get((site_id, url))
        merged[(site_id, url)] = {
            "site_id": site_id,
            "site_name": record.get("source") or site_id,
            "title": record.get("title_zh") or record.get("title") or "",
            "url": url,
            "published_at": record.get("published_at"),
            "first_seen_at": (existing or {}).get("first_seen_at") or record.get("fetched_at") or _utc_text(anchor),
        }
    cutoff = anchor - timedelta(days=INTAKE_DAYS)
    kept = [
        item
        for item in merged.values()
        if (ts := _parse_utc(item.get("first_seen_at"))) is not None and ts >= cutoff
    ]
    kept.sort(key=lambda item: (str(item.get("first_seen_at")), item["site_id"], item["url"]), reverse=True)
    return {
        "generated_at": _utc_text(anchor),
        "window_days": INTAKE_DAYS,
        "item_count": len(kept),
        "items": kept,
    }
