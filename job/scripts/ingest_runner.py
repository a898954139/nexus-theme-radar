"""High-frequency ingest: fetch one source group and write raw articles to the DB.

Supabase pg_cron calls the Vercel Function ``/api/cron/ingest?group=<id>``
every few minutes (see docs/INGEST_SCHEDULER.md). Each call runs exactly one
group from ``config/ingest_groups.tw.json`` so it stays inside the Vercel Hobby
function duration limit, and only fetches the sources whose per-source minimum
interval has elapsed, so upstream rate limits hold regardless of how often the
scheduler fires (the hourly GitHub Actions run's fetches count too: the check
reads every ``radar.source_run`` row for the source).

This path only captures raw articles plus per-source status. Clustering, MOPS
and the published JSON stay in ``scripts/update_theme_radar.py`` until the
cut-over, so the existing site keeps working and remains the rollback.

The same code runs from the CLI for local checks:

    python scripts/ingest_runner.py --list-groups
    python scripts/ingest_runner.py --group tw-news-a --dry-run
    RADAR_INGEST_DATABASE_URL=... python scripts/ingest_runner.py --group tw-news-a
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

try:
    from scripts.radar_store import redact_error, write_radar_run
    from scripts.update_theme_radar import (
        DEFAULT_REGISTRY_PATH,
        USER_AGENT,
        active_sources,
        fetch_rss_source,
        load_source_registry,
    )
except ModuleNotFoundError:
    from radar_store import redact_error, write_radar_run
    from update_theme_radar import (
        DEFAULT_REGISTRY_PATH,
        USER_AGENT,
        active_sources,
        fetch_rss_source,
        load_source_registry,
    )


LOGGER = logging.getLogger("ingest_runner")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GROUPS_PATH = ROOT / "config" / "ingest_groups.tw.json"
DATABASE_URL_ENV = "RADAR_INGEST_DATABASE_URL"
GROUP_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
# pg_cron fires on the minute but the previous call's source_run.started_at is
# stamped a few seconds into it. Without slack a 5-minute source on a 5-minute
# schedule would see 4m58s elapsed and silently drop to every 10 minutes.
MIN_INTERVAL_GRACE = timedelta(seconds=60)
# Hobby functions are configured with maxDuration 60 in vercel.json; the fetch
# phase must leave room for cold start and the DB write.
MAX_TIME_BUDGET_SECONDS = 45
SUPPORTED_FETCH_METHODS = frozenset({"rss"})

LAST_FETCH_SQL = """
SELECT source_id, max(started_at) AS last_started_at
FROM radar.source_run
WHERE source_id = ANY(%(source_ids)s)
GROUP BY source_id
""".strip()


class IngestConfigError(ValueError):
    """The groups config is inconsistent with the source registry."""


class UnknownGroupError(KeyError):
    """The requested group_id is not configured."""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_ingest_config(
    groups_path: str | Path = DEFAULT_GROUPS_PATH,
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    """Resolve every group to concrete source dicts and validate the whole file.

    A source belongs to at most one group: two groups fetching the same feed
    would double its request rate behind the min-interval check's back when
    both fire in the same minute.
    """

    payload = json.loads(Path(groups_path).read_text(encoding="utf-8"))
    registry = load_source_registry(registry_path)
    defaults = payload.get("defaults") or {}
    default_interval = int(defaults.get("min_interval_minutes") or 5)
    budget = int(payload.get("time_budget_seconds") or 40)
    if not 5 <= budget <= MAX_TIME_BUDGET_SECONDS:
        raise IngestConfigError(
            f"time_budget_seconds must be between 5 and {MAX_TIME_BUDGET_SECONDS}"
        )

    market_id = registry.get("market_id") or "TW_EQUITY"
    available: dict[str, dict[str, Any]] = {
        str(source["source_id"]): source for source in active_sources(registry)
    }
    extra_sources: list[dict[str, Any]] = []
    for raw in payload.get("extra_sources") or []:
        source_id = str(raw.get("source_id") or "").strip()
        if not source_id:
            raise IngestConfigError("extra source is missing source_id")
        if source_id in available or any(
            source.get("source_id") == source_id for source in registry["sources"]
        ):
            raise IngestConfigError(
                f"extra source {source_id} duplicates a registry source"
            )
        source = {
            "market_id": market_id,
            "market_scope": raw.get("market_scope") or [market_id],
            **raw,
        }
        available[source_id] = source
        extra_sources.append(dict(raw))

    groups: dict[str, list[dict[str, Any]]] = {}
    owner: dict[str, str] = {}
    for group in payload.get("groups") or []:
        group_id = str(group.get("group_id") or "")
        if not GROUP_ID_PATTERN.match(group_id):
            raise IngestConfigError(f"invalid group_id: {group_id!r}")
        if group_id in groups:
            raise IngestConfigError(f"duplicate group_id: {group_id}")
        resolved: list[dict[str, Any]] = []
        for raw_id in group.get("source_ids") or []:
            source_id = str(raw_id)
            source = available.get(source_id)
            if source is None:
                raise IngestConfigError(
                    f"group {group_id} references {source_id}, which is not an "
                    "active registry source or an extra_source"
                )
            if source.get("fetch_method") not in SUPPORTED_FETCH_METHODS or not source.get("feed_url"):
                raise IngestConfigError(
                    f"group {group_id} source {source_id} has unsupported "
                    f"fetch_method {source.get('fetch_method')!r}"
                )
            if source_id in owner:
                raise IngestConfigError(
                    f"source {source_id} is in both {owner[source_id]} and {group_id}"
                )
            owner[source_id] = group_id
            interval = int(source.get("min_interval_minutes") or default_interval)
            if interval < 1:
                raise IngestConfigError(f"min_interval_minutes must be >= 1: {source_id}")
            resolved.append({**source, "min_interval_minutes": interval})
        if not resolved:
            raise IngestConfigError(f"group {group_id} has no sources")
        groups[group_id] = resolved
    if not groups:
        raise IngestConfigError("ingest config must define at least one group")

    return {
        "groups": groups,
        "registry_sources": [*registry["sources"], *extra_sources],
        "time_budget_seconds": budget,
    }


def due_sources(
    sources: Sequence[Mapping[str, Any]],
    last_fetched: Mapping[str, datetime],
    now: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a group into sources to fetch now and sources still rate-limited."""

    due: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for source in sources:
        source_id = str(source["source_id"])
        interval = timedelta(minutes=int(source["min_interval_minutes"]))
        last = last_fetched.get(source_id)
        if last is not None and now - last < interval - MIN_INTERVAL_GRACE:
            skipped.append(
                {
                    "source_id": source_id,
                    "reason": "min_interval",
                    "next_due_at": _iso(last + interval - MIN_INTERVAL_GRACE),
                }
            )
        else:
            due.append(dict(source))
    return due, skipped


def read_last_fetched(connection: Any, source_ids: Sequence[str]) -> dict[str, datetime]:
    with connection.cursor() as cursor:
        cursor.execute(LAST_FETCH_SQL, {"source_ids": list(source_ids)})
        rows = cursor.fetchall()
    result: dict[str, datetime] = {}
    for row in rows:
        source_id, last = (row["source_id"], row["last_started_at"]) if isinstance(row, Mapping) else row
        if isinstance(last, datetime):
            result[str(source_id)] = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
    return result


def default_session_factory(source: Mapping[str, Any]) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": str(source.get("user_agent") or USER_AGENT)})
    return session


def _budget_status(source: Mapping[str, Any], budget_seconds: int) -> dict[str, Any]:
    return {
        "source_id": source["source_id"],
        "name": source.get("name") or source["source_id"],
        "source_class": source.get("source_class"),
        "fetch_method": source.get("fetch_method"),
        "feed_url": source.get("feed_url"),
        "status": "error",
        "items": 0,
        "error": f"time budget exceeded ({budget_seconds}s)",
        "elapsed_ms": budget_seconds * 1000,
    }


def fetch_group(
    sources: Sequence[Mapping[str, Any]],
    fetched_at: datetime,
    *,
    budget_seconds: int,
    fetcher: Callable[..., tuple[list[dict[str, Any]], dict[str, Any]]] = fetch_rss_source,
    session_factory: Callable[[Mapping[str, Any]], Any] = default_session_factory,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch every source concurrently; a source past the budget becomes an error.

    The budget bounds the invocation, not each request: a feed that trickles
    bytes slower than the per-request timeout can notice would otherwise hold
    the whole group past the Hobby duration limit and lose every other
    source's result with it.
    """

    if not sources:
        return [], []

    def run_one(source: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        session = session_factory(source)
        try:
            return fetcher(session, dict(source), fetched_at)
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                close()

    executor = ThreadPoolExecutor(max_workers=len(sources))
    try:
        futures = {executor.submit(run_one, source): source for source in sources}
        done, _ = wait(futures, timeout=budget_seconds)
        records: list[dict[str, Any]] = []
        statuses: list[dict[str, Any]] = []
        for future, source in futures.items():
            if future not in done:
                statuses.append(_budget_status(source, budget_seconds))
                continue
            try:
                items, status = future.result()
            except Exception as error:  # noqa: BLE001 - one source never fails the group
                items = []
                status = {
                    "source_id": source["source_id"],
                    "name": source.get("name") or source["source_id"],
                    "source_class": source.get("source_class"),
                    "fetch_method": source.get("fetch_method"),
                    "status": "error",
                    "items": 0,
                    "error": redact_error(error),
                    "elapsed_ms": None,
                }
            records.extend(items)
            statuses.append(status)
    finally:
        # Do not wait for stragglers: their results are already recorded as
        # budget errors and the function must return before its hard limit.
        executor.shutdown(wait=False, cancel_futures=True)
    statuses.sort(key=lambda status: str(status["source_id"]))
    return records, statuses


def connection_factory_from_environment(
    env: Mapping[str, str] | None = None,
    env_var: str = DATABASE_URL_ENV,
) -> Callable[[], Any] | None:
    """Return a lazy psycopg factory, or None when the credential is absent.

    autocommit keeps the min-interval read from leaving a transaction idle
    while feeds are fetched; the write opens its own explicit transaction.
    prepare_threshold=None keeps it compatible with the Supabase pooler.
    """

    database_url = (env if env is not None else os.environ).get(env_var, "").strip()
    if not database_url:
        return None

    def connect() -> Any:
        import psycopg

        return psycopg.connect(
            database_url,
            autocommit=True,
            prepare_threshold=None,
            connect_timeout=10,
        )

    return connect


def _status_summary(status: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_id": status.get("source_id"),
        "status": status.get("status"),
        "items": status.get("items"),
        "elapsed_ms": status.get("elapsed_ms"),
        "error": status.get("error"),
    }


def run_ingest_group(
    group_id: str,
    *,
    connection_factory: Callable[[], Any],
    config: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    fetcher: Callable[..., Any] = fetch_rss_source,
    session_factory: Callable[[Mapping[str, Any]], Any] = default_session_factory,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Run one group end to end. Raises on DB failure; fetch failures are data."""

    started = clock()
    resolved = config or load_ingest_config()
    groups = resolved["groups"]
    if group_id not in groups:
        raise UnknownGroupError(group_id)
    sources = groups[group_id]
    anchor = (now or now_utc()).astimezone(timezone.utc)

    connection = connection_factory()
    try:
        last_fetched = read_last_fetched(
            connection, [str(source["source_id"]) for source in sources]
        )
        due, skipped = due_sources(sources, last_fetched, anchor)
        summary: dict[str, Any] = {
            "group": group_id,
            "started_at": _iso(anchor),
            "run_id": None,
            "due": [str(source["source_id"]) for source in due],
            "skipped": skipped,
            "sources": [],
            "db_article_count": 0,
            "duplicate_url_count": 0,
            "failed_source_count": 0,
        }
        if not due:
            summary["result"] = "nothing_due"
            summary["elapsed_ms"] = round((clock() - started) * 1000)
            return summary

        records, statuses = fetch_group(
            due,
            anchor,
            budget_seconds=int(resolved["time_budget_seconds"]),
            fetcher=fetcher,
            session_factory=session_factory,
        )
        run_id = f"ingest-{group_id}-{anchor:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
        elapsed_ms = round((clock() - started) * 1000)
        written = write_radar_run(
            connection,
            run_id=run_id,
            started_at=anchor,
            window_hours=0,
            registry_sources=resolved["registry_sources"],
            statuses=statuses,
            articles=records,
            events=[],
            ingest_group=group_id,
            elapsed_ms=elapsed_ms,
        )
    finally:
        close = getattr(connection, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 - close failure is not actionable
                pass

    summary.update(
        {
            "result": "written",
            "run_id": run_id,
            "sources": [_status_summary(status) for status in statuses],
            "db_article_count": written["db_article_count"],
            "duplicate_url_count": written["duplicate_url_count"],
            "failed_source_count": written["failed_source_count"],
            "elapsed_ms": round((clock() - started) * 1000),
        }
    )
    LOGGER.info(
        "radar_ingest_written group=%s run_id=%s articles=%d failed_sources=%d elapsed_ms=%d",
        group_id,
        run_id,
        summary["db_article_count"],
        summary["failed_source_count"],
        summary["elapsed_ms"],
    )
    return summary


def dry_run_group(group_id: str, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Fetch a group without touching the DB or the min-interval check."""

    resolved = config or load_ingest_config()
    if group_id not in resolved["groups"]:
        raise UnknownGroupError(group_id)
    records, statuses = fetch_group(
        resolved["groups"][group_id],
        now_utc(),
        budget_seconds=int(resolved["time_budget_seconds"]),
    )
    return {
        "group": group_id,
        "result": "dry_run",
        "records": len(records),
        "sources": [_status_summary(status) for status in statuses],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--group", help="group_id from config/ingest_groups.tw.json")
    parser.add_argument("--dry-run", action="store_true", help="fetch only; no DB")
    parser.add_argument("--list-groups", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    config = load_ingest_config()
    if args.list_groups:
        print(json.dumps(
            {
                group_id: [source["source_id"] for source in sources]
                for group_id, sources in config["groups"].items()
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    if not args.group:
        parser.error("--group is required")
    if args.dry_run:
        print(json.dumps(dry_run_group(args.group, config), ensure_ascii=False, indent=2))
        return 0
    factory = connection_factory_from_environment()
    if factory is None:
        LOGGER.error("radar_ingest_skipped reason=credential_unavailable env=%s", DATABASE_URL_ENV)
        return 2
    try:
        summary = run_ingest_group(args.group, connection_factory=factory, config=config)
    except Exception as error:  # noqa: BLE001 - redact before anything reaches the log
        LOGGER.error("radar_ingest_failed group=%s error=%s", args.group, redact_error(error))
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
