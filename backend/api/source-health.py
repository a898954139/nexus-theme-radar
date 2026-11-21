"""Vercel Function: GET /api/source-health

Per-source fetch health from radar.source_run for the 源狀態 page: last
attempt, last success and 24h success rate. Read-only, via a login role granted
radar_reader. Returns 503 when the credential is not configured, and the page
then simply hides the section (the JSON-based table keeps working).

Environment:
  RADAR_API_DATABASE_URL  Postgres URL of a login role granted radar_reader
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from typing import Any

# Same redaction as job/scripts/radar_store.redact_error; duplicated on purpose
# so the backend deploys without the job layer.
_DSN_PATTERN = re.compile(r"postgres(?:ql)?://\S+", re.IGNORECASE)
_KV_SECRET_PATTERN = re.compile(r"(password|passwd|pwd)\s*=\s*\S+", re.IGNORECASE)


def redact_error(error: BaseException) -> str:
    """Return a log-safe error string: class name plus message with DSNs removed."""

    message = _DSN_PATTERN.sub("<redacted-dsn>", str(error))
    message = _KV_SECRET_PATTERN.sub(r"\1=<redacted>", message)
    message = " ".join(message.split())[:300]
    return f"{type(error).__name__}: {message}" if message else type(error).__name__

LOGGER = logging.getLogger("api.source_health")
DATABASE_URL_ENV = "RADAR_API_DATABASE_URL"
CACHE_CONTROL = "public, s-maxage=60, stale-while-revalidate=300"
MAX_ERROR_CHARS = 200

SOURCE_HEALTH_SQL = """
SELECT
  s.source_id,
  s.name,
  last_run.status        AS last_status,
  last_run.started_at    AS last_started_at,
  last_run.item_count    AS last_item_count,
  last_run.elapsed_ms    AS last_elapsed_ms,
  last_run.error         AS last_error,
  last_ok.started_at     AS last_ok_at,
  coalesce(day.runs, 0)  AS runs_24h,
  coalesce(day.ok, 0)    AS ok_24h
FROM radar.source s
LEFT JOIN LATERAL (
  SELECT status, started_at, item_count, elapsed_ms, error
  FROM radar.source_run r
  WHERE r.source_id = s.source_id
  ORDER BY started_at DESC
  LIMIT 1
) last_run ON true
LEFT JOIN LATERAL (
  SELECT started_at
  FROM radar.source_run r
  WHERE r.source_id = s.source_id AND r.status = 'ok'
  ORDER BY started_at DESC
  LIMIT 1
) last_ok ON true
LEFT JOIN LATERAL (
  SELECT count(*) AS runs, count(*) FILTER (WHERE r.status = 'ok') AS ok
  FROM radar.source_run r
  WHERE r.source_id = s.source_id AND r.started_at >= now() - interval '24 hours'
) day ON true
WHERE s.enabled OR s.registry_status = 'ingest_only'
ORDER BY s.source_id
""".strip()

SOURCE_HEALTH_KEYS = (
    "source_id",
    "name",
    "last_status",
    "last_started_at",
    "last_item_count",
    "last_elapsed_ms",
    "last_error",
    "last_ok_at",
    "runs_24h",
    "ok_24h",
)


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return None


def shape_rows(rows: list[Any]) -> list[dict[str, Any]]:
    shaped: list[dict[str, Any]] = []
    for row in rows:
        record = dict(row) if isinstance(row, Mapping) else dict(zip(SOURCE_HEALTH_KEYS, row))
        error = record.get("last_error")
        shaped.append(
            {
                "source_id": record["source_id"],
                "name": record["name"],
                "last_status": record.get("last_status"),
                "last_started_at": _iso(record.get("last_started_at")),
                "last_item_count": record.get("last_item_count"),
                "last_elapsed_ms": record.get("last_elapsed_ms"),
                "last_error": (
                    redact_error(RuntimeError(error)).split(": ", 1)[-1][:MAX_ERROR_CHARS]
                    if error
                    else None
                ),
                "last_ok_at": _iso(record.get("last_ok_at")),
                "runs_24h": int(record.get("runs_24h") or 0),
                "ok_24h": int(record.get("ok_24h") or 0),
            }
        )
    return shaped


def _connect(database_url: str) -> Any:
    import psycopg

    return psycopg.connect(
        database_url, autocommit=True, prepare_threshold=None, connect_timeout=10
    )


def handle_source_health(
    method: str,
    *,
    env: Mapping[str, str] | None = None,
    connect: Callable[[str], Any] = _connect,
    clock: Callable[[], datetime] | None = None,
) -> tuple[int, dict[str, Any], str]:
    environment = env if env is not None else os.environ
    if method != "GET":
        return 405, {"error": "method_not_allowed"}, "no-store"
    database_url = environment.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        return 503, {"error": "not_configured"}, "no-store"
    connection = None
    try:
        connection = connect(database_url)
        with connection.cursor() as cursor:
            cursor.execute(SOURCE_HEALTH_SQL)
            rows = cursor.fetchall()
    except Exception as error:  # noqa: BLE001 - redact before it reaches the log
        LOGGER.error("source_health_failed error=%s", redact_error(error))
        return 502, {"error": "unavailable"}, "no-store"
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:  # noqa: BLE001
                pass
    now = (clock or (lambda: datetime.now().astimezone()))()
    return 200, {"generated_at": _iso(now), "sources": shape_rows(list(rows))}, CACHE_CONTROL


class handler(BaseHTTPRequestHandler):  # noqa: N801 - name required by Vercel
    def do_GET(self) -> None:  # noqa: N802
        status, body, cache = handle_source_health(self.command)
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return
