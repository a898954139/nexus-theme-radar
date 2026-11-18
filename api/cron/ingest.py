"""Vercel Function: GET /api/cron/ingest?group=<group_id>

Called by Supabase pg_cron (radar.invoke_ingest) every few minutes. Requires
``Authorization: Bearer <RADAR_INGEST_CRON_SECRET>``; anything else gets 401
before any fetch or DB work happens. The secret is never logged or echoed.

Environment (Vercel project settings, server-side only):
  RADAR_INGEST_CRON_SECRET   shared secret, >= 32 chars, also stored in Supabase Vault
  RADAR_INGEST_DATABASE_URL  Postgres URL of a login role granted radar_writer
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import sys
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ingest_runner import (  # noqa: E402 - path bootstrap above
    GROUP_ID_PATTERN,
    UnknownGroupError,
    connection_factory_from_environment,
    run_ingest_group,
)
from scripts.radar_store import redact_error  # noqa: E402

LOGGER = logging.getLogger("api.cron.ingest")
SECRET_ENV = "RADAR_INGEST_CRON_SECRET"
MIN_SECRET_LENGTH = 32


def is_authorized(authorization: str | None, secret: str) -> bool:
    if not authorization or not authorization.startswith("Bearer "):
        return False
    supplied = authorization[len("Bearer "):].strip()
    return hmac.compare_digest(supplied.encode("utf-8"), secret.encode("utf-8"))


def handle_ingest(
    method: str,
    path: str,
    headers: Mapping[str, str],
    *,
    env: Mapping[str, str] | None = None,
    runner: Callable[..., dict[str, Any]] = run_ingest_group,
) -> tuple[int, dict[str, Any]]:
    """Pure request -> (status, body) mapping so it is testable without HTTP."""

    environment = env if env is not None else os.environ
    if method not in {"GET", "POST"}:
        return 405, {"error": "method_not_allowed"}

    secret = environment.get(SECRET_ENV, "")
    if len(secret) < MIN_SECRET_LENGTH:
        # Fail closed: a missing or weak secret must not leave the endpoint open.
        LOGGER.error("radar_ingest_rejected reason=secret_not_configured")
        return 503, {"error": "not_configured"}
    if not is_authorized(headers.get("Authorization") or headers.get("authorization"), secret):
        return 401, {"error": "unauthorized"}

    query = parse_qs(urlsplit(path).query)
    group = (query.get("group") or [""])[0]
    if not GROUP_ID_PATTERN.match(group):
        return 400, {"error": "invalid_group"}

    factory = connection_factory_from_environment(environment)
    if factory is None:
        LOGGER.error("radar_ingest_rejected reason=credential_unavailable group=%s", group)
        return 503, {"error": "not_configured"}

    try:
        summary = runner(group, connection_factory=factory)
    except UnknownGroupError:
        return 404, {"error": "unknown_group"}
    except Exception as error:  # noqa: BLE001 - redact before it reaches the log
        LOGGER.error("radar_ingest_failed group=%s error=%s", group, redact_error(error))
        return 500, {"error": "ingest_failed", "group": group}
    return 200, summary


class handler(BaseHTTPRequestHandler):  # noqa: N801 - name required by Vercel
    def _respond(self) -> None:
        status, body = handle_ingest(self.command, self.path, self.headers)
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        self._respond()

    def do_POST(self) -> None:  # noqa: N802
        self._respond()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # The default writes the raw request line; keep request logging to
        # Vercel's own access log, which never includes headers.
        return
