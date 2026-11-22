"""Read the 5-minute ingest's articles back for the hourly theme radar.

``ingest_runner.py`` writes every RSS item of the ingest groups to
``radar.article`` every few minutes. The hourly ``update_theme_radar.py`` used
to fetch the same feeds again and only saw what each feed still listed at that
moment (cnyes keeps ~100 items, a few hours). Reading the table instead gives
the radar the full 72-hour window at 5-minute freshness.

Per source, fail open to the old path: a source is read from the DB only when
its last *successful ingest* fetch is recent (``INGEST_MAX_STALENESS``);
otherwise, or on any DB error, the hourly run fetches that feed itself exactly
as before. ``THEME_RADAR_INGEST_SOURCE=0`` turns the DB read off entirely.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.radar_store import redact_error
except ModuleNotFoundError:
    from radar_store import redact_error

LOGGER = logging.getLogger("ingested_articles")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INGEST_GROUPS_PATH = ROOT / "config" / "ingest_groups.tw.json"
TOGGLE_ENV = "THEME_RADAR_INGEST_SOURCE"
ORIGIN_ADAPTER = "ingest_db"
# Ingest runs every 5 minutes; six missed runs in a row means the Mac or the
# feed is down, and the hourly run should go back to fetching the feed itself.
INGEST_MAX_STALENESS = timedelta(minutes=30)
# Bounds the clustering input (O(n * clusters)); 72h of cnyes is ~600 items.
MAX_ARTICLES_PER_SOURCE = 800

INGEST_HEALTH_SQL = """
SELECT sr.source_id, max(sr.started_at) AS last_ok_at
FROM radar.source_run sr
JOIN radar.pipeline_run pr ON pr.run_id = sr.run_id
WHERE pr.run_kind = 'ingest'
  AND sr.status = 'ok'
  AND sr.source_id = ANY(%(source_ids)s)
  AND sr.started_at >= %(since)s
GROUP BY sr.source_id
""".strip()

INGESTED_ARTICLES_SQL = """
SELECT article_id, source_id, source_class, market_id, url, title, summary,
       extraction_method, published_at, first_fetched_at
FROM (
  SELECT a.*, row_number() OVER (
    PARTITION BY a.source_id ORDER BY a.published_at DESC, a.url_hash
  ) AS rn
  FROM radar.article a
  WHERE a.source_id = ANY(%(source_ids)s)
    AND a.published_at >= %(since)s
    AND a.published_at <= %(until)s
) ranked
WHERE rn <= %(per_source)s
ORDER BY published_at DESC, url
""".strip()


def enabled(env: Mapping[str, str] | None = None) -> bool:
    value = (env if env is not None else os.environ).get(TOGGLE_ENV, "1")
    return value.strip().lower() not in {"0", "false", "off", "no"}


def load_ingest_source_ids(path: str | Path = DEFAULT_INGEST_GROUPS_PATH) -> set[str]:
    """Source ids the 5-minute ingest covers; empty when the config is unreadable."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        LOGGER.warning("ingest_groups_unreadable error=%s", type(error).__name__)
        return set()
    return {
        str(source_id)
        for group in payload.get("groups") or []
        for source_id in group.get("source_ids") or []
    }


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _row(row: Any, columns: Sequence[str]) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    return dict(zip(columns, row))


ARTICLE_COLUMNS = (
    "article_id", "source_id", "source_class", "market_id", "url", "title", "summary",
    "extraction_method", "published_at", "first_fetched_at",
)


def article_record(row: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any] | None:
    """A radar.article row in the shape ``normalize_feed_entry`` produces."""

    published = _utc(row.get("published_at"))
    fetched = _utc(row.get("first_fetched_at")) or published
    title = str(row.get("title") or "").strip()
    url = str(row.get("url") or "").strip()
    if published is None or not title or not url:
        return None
    source_id = str(source["source_id"])
    return {
        "id": str(row.get("article_id") or ""),
        "title_zh": title,
        "summary": str(row.get("summary") or ""),
        "source": source.get("name") or source_id,
        "source_id": source_id,
        "source_class": row.get("source_class") or source.get("source_class"),
        "market_id": row.get("market_id") or source.get("market_id") or "TW_EQUITY",
        "market_scope": source.get("market_scope") or ["TW_EQUITY"],
        "published_at": _iso(published),
        "url": url,
        "extraction_method": row.get("extraction_method") or "rss",
        "fetched_at": _iso(fetched),
    }


def _status(source: Mapping[str, Any], items: int) -> dict[str, Any]:
    return {
        "source_id": source["source_id"],
        "name": source.get("name") or source["source_id"],
        "source_class": source.get("source_class"),
        "adapter": ORIGIN_ADAPTER,
        "fetch_method": "rss",
        "feed_url": source.get("feed_url"),
        "status": "ok",
        "items": items,
        "error": None,
        "elapsed_ms": 0,
    }


def load_ingested_results(
    connection_factory: Callable[[], Any] | None,
    sources: Sequence[Mapping[str, Any]],
    anchor: datetime,
    *,
    window_hours: int,
    ingest_source_ids: set[str] | None = None,
    env: Mapping[str, str] | None = None,
    max_staleness: timedelta = INGEST_MAX_STALENESS,
    per_source: int = MAX_ARTICLES_PER_SOURCE,
) -> dict[str, dict[str, Any]]:
    """Return ``{source_id: dispatch result}`` for sources served from the DB.

    A missing source in the result means "fetch it yourself". Never raises.
    """

    if connection_factory is None or not enabled(env):
        return {}
    covered = ingest_source_ids if ingest_source_ids is not None else load_ingest_source_ids()
    candidates = {
        str(source["source_id"]): source
        for source in sources
        if str(source.get("source_id")) in covered
        and source.get("fetch_method") == "rss"
        and source.get("status") != "trial"
    }
    if not candidates:
        return {}
    anchor = anchor.astimezone(timezone.utc)
    connection = None
    try:
        connection = connection_factory()
        with connection.cursor() as cursor:
            cursor.execute(
                INGEST_HEALTH_SQL,
                {"source_ids": sorted(candidates), "since": anchor - max_staleness},
            )
            health = {}
            for raw in cursor.fetchall():
                row = _row(raw, ("source_id", "last_ok_at"))
                last = _utc(row.get("last_ok_at"))
                if last is not None:
                    health[str(row["source_id"])] = last
            fresh = sorted(source_id for source_id in candidates if source_id in health)
            if not fresh:
                LOGGER.warning(
                    "ingest_source_fallback reason=no_fresh_ingest sources=%s",
                    ",".join(sorted(candidates)),
                )
                return {}
            cursor.execute(
                INGESTED_ARTICLES_SQL,
                {
                    "source_ids": fresh,
                    "since": anchor - timedelta(hours=window_hours),
                    "until": anchor,
                    "per_source": per_source,
                },
            )
            rows = [_row(raw, ARTICLE_COLUMNS) for raw in cursor.fetchall()]
    except Exception as error:  # noqa: BLE001 - fail open to the RSS fetch
        LOGGER.warning("ingest_source_fallback reason=db_error error=%s", redact_error(error))
        return {}
    finally:
        if connection is not None:
            close = getattr(connection, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001
                    pass

    records: dict[str, list[dict[str, Any]]] = {source_id: [] for source_id in fresh}
    for row in rows:
        source_id = str(row.get("source_id") or "")
        if source_id not in records:
            continue
        record = article_record(row, candidates[source_id])
        if record is not None:
            records[source_id].append(record)
    results = {
        source_id: {
            "records": items,
            "status": _status(candidates[source_id], len(items)),
        }
        for source_id, items in records.items()
    }
    stale = sorted(set(candidates) - set(fresh))
    LOGGER.info(
        "ingest_source_read sources=%s articles=%d fallback_rss=%s",
        ",".join(fresh),
        sum(len(items) for items in records.values()),
        ",".join(stale) or "-",
    )
    return results


def is_ingest_origin(status: Mapping[str, Any]) -> bool:
    return status.get("adapter") == ORIGIN_ADAPTER
