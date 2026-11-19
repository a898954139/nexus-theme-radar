#!/usr/bin/env python3
"""Build the pre-market homepage payload: focus events, sectors, and flows.

Publishes `data/pre-market-latest.json` -- a 72-hour rolling window the page
fetches directly -- and rolls anything older into `data/pre-market-archive/`,
which is gitignored and never deployed. The hot file stays small enough to sit
in version control so each run can read the previous window and accumulate;
the archive is append-only per month so it cannot become another hourly rewrite.

Run standalone (`python scripts/update_pre_market.py`) rather than from inside
the theme-radar entrypoint, so a wire outage degrades this board alone.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable

import requests

try:  # pragma: no cover - real runs invoke this file by path
    from scripts.backtest_path import RESULT_FILE as BACKTEST_FILE, attach_backtest
    from scripts.event_direction import RULE_VERSION, annotate, impact_rows
    from scripts.geo_focus import (
        FEED_URL, PATH_ID_BY_LABEL, SOURCE_NAME, build_focus_events, strip_prefix,
    )
    from scripts.market_pulse import build_pulse, build_sector_board, fetch_quotes
    from scripts.market_temperature import (
        build_market, fetch_sector_board as fetch_twse_sector_board, fetch_taiex_history,
        merge_taiex_history, requests_getter,
    )
    from scripts.sector_flows import (
        aggregate_sectors,
        build_flow_panels,
        iter_shards,
        load_registry,
    )
    from scripts.radar_store import redact_error, write_pre_market_snapshot
except ModuleNotFoundError:  # pragma: no cover
    from backtest_path import RESULT_FILE as BACKTEST_FILE, attach_backtest
    from event_direction import RULE_VERSION, annotate, impact_rows
    from geo_focus import (
        FEED_URL, PATH_ID_BY_LABEL, SOURCE_NAME, build_focus_events, strip_prefix,
    )
    from market_pulse import build_pulse, build_sector_board, fetch_quotes
    from market_temperature import (
        build_market, fetch_sector_board as fetch_twse_sector_board, fetch_taiex_history,
        merge_taiex_history, requests_getter,
    )
    from sector_flows import (
        aggregate_sectors,
        build_flow_panels,
        iter_shards,
        load_registry,
    )
    from radar_store import redact_error, write_pre_market_snapshot

LOGGER = logging.getLogger("update_pre_market")

SCHEMA_VERSION = 1
WINDOW_HOURS = 72
LATEST_FILE = "pre-market-latest.json"
ARCHIVE_DIR = "pre-market-archive"
TRANSLATION_CACHE = "pre-market-title-zh.json"
TAIEX_HISTORY = "taiex-daily.json"
TAIPEI = timezone(timedelta(hours=8))
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"


def fetch_feed(
    session: requests.Session,
    timeout: int = 25,
    attempts: int = 3,
    sleep: Any = time.sleep,
) -> list[dict[str, Any]]:
    """Parse the wire feed into entries with aware timestamps.

    Retries on 429/5xx: the pre-open schedule fires every 15 minutes and the
    upstream throttles bursts, so a single refused request must not blank the
    board for a whole slot.
    """
    response = None
    for attempt in range(attempts):
        response = session.get(FEED_URL, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        if response.status_code < 400:
            break
        if response.status_code != 429 and response.status_code < 500:
            break
        if attempt < attempts - 1:
            sleep(2 ** attempt * 5)
    assert response is not None
    response.raise_for_status()
    root = ET.fromstring(response.content)
    entries: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        raw_date = item.findtext("pubDate")
        if not raw_date:
            continue
        try:
            published = parsedate_to_datetime(raw_date)
        except (TypeError, ValueError):
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        entries.append({
            "title": item.findtext("title") or "",
            "link": item.findtext("link") or "",
            "published_at": published,
        })
    return entries


def translate_zh_tw(session: requests.Session, text: str, timeout: int = 12) -> str | None:
    """Translate to Traditional Chinese, Taiwan locale.

    zh-TW rather than zh-CN: the audience reads Taiwan financial usage, where
    「聯準會」and「晶片」are the expected terms.
    """
    try:
        response = session.get(
            TRANSLATE_URL,
            params={"client": "gtx", "sl": "en", "tl": "zh-TW", "dt": "t", "q": text},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        translated = "".join(
            segment[0] for segment in payload[0] if segment and segment[0]
        ).strip()
    except (requests.RequestException, ValueError, IndexError, KeyError) as exc:
        LOGGER.warning("translation failed (%s): %s", type(exc).__name__, exc)
        return None
    return translated or None


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def merge_events(
    previous: Iterable[dict[str, Any]],
    fresh: Iterable[dict[str, Any]],
    now: datetime,
    window_hours: int = WINDOW_HOURS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (kept, expired) after folding fresh events into the window.

    Fresh scores win on collision: recency decay means the same story is scored
    differently as it ages, and the newer computation is the correct one.
    """
    cutoff = now - timedelta(hours=window_hours)
    by_key: dict[str, dict[str, Any]] = {}
    for event in previous:
        key = event.get("titleEn") or event.get("id")
        if key:
            by_key[key] = event
    for event in fresh:
        key = event.get("titleEn") or event.get("id")
        if key:
            by_key[key] = event

    kept: list[dict[str, Any]] = []
    expired: list[dict[str, Any]] = []
    for event in by_key.values():
        stamp = event.get("publishedAt")
        try:
            published = datetime.fromisoformat(str(stamp))
        except (TypeError, ValueError):
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        (kept if published >= cutoff else expired).append(event)

    kept.sort(key=lambda e: (e.get("score", 0), e.get("publishedAt", "")), reverse=True)
    return kept, expired


def archive_expired(expired: list[dict[str, Any]], archive_dir: Path) -> None:
    """Append expired events into month files, deduped by id."""
    if not expired:
        return
    archive_dir.mkdir(parents=True, exist_ok=True)
    by_month: dict[str, list[dict[str, Any]]] = {}
    for event in expired:
        month = str(event.get("publishedAt", ""))[:7] or "unknown"
        by_month.setdefault(month, []).append(event)
    for month, events in by_month.items():
        path = archive_dir / f"{month}.json"
        existing = load_json(path, [])
        merged = {e.get("id"): e for e in existing if isinstance(e, dict)}
        merged.update({e.get("id"): e for e in events})
        ordered = sorted(merged.values(), key=lambda e: str(e.get("publishedAt", "")))
        path.write_text(json.dumps(ordered, ensure_ascii=False, indent=1), encoding="utf-8")
        LOGGER.info("archived %d events into %s", len(events), path.name)


def build_payload(output_dir: Path, now: datetime, skip_translate: bool = False) -> dict[str, Any]:
    session = requests.Session()
    cache_path = output_dir / TRANSLATION_CACHE
    translations: dict[str, str] = load_json(cache_path, {})

    try:
        entries = fetch_feed(session)
        LOGGER.info("fetched %d wire entries", len(entries))
    except (requests.RequestException, ET.ParseError) as exc:
        LOGGER.error("wire feed unavailable: %s", exc)
        entries = []

    if not skip_translate:
        pending = {
            strip_prefix(e["title"]) for e in entries
            if strip_prefix(e["title"]) and strip_prefix(e["title"]) not in translations
        }
        for title in sorted(pending):
            rendered = translate_zh_tw(session, title)
            if rendered:
                translations[title] = rendered
        if pending:
            cache_path.write_text(
                json.dumps(translations, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            LOGGER.info("translated %d new titles", len(pending))

    fresh = build_focus_events(entries, translations, now=now)
    previous = load_json(output_dir / LATEST_FILE, {})
    kept, expired = merge_events(previous.get("events", []), fresh, now)
    # Re-derive direction for carried-over events too: they may predate the
    # direction fields, or an older rule version. The rules are deterministic,
    # so the whole window always reflects the current RULE_VERSION.
    for event in kept:
        annotate(event, event.get("pathId") or PATH_ID_BY_LABEL.get(str(event.get("pathLabel") or "")))
    # #12: historical hit rate per path, and the event's own T+1 foreign flow
    # once the daily backtest has measured it.
    attach_backtest(kept, load_json(output_dir / "backtest" / BACKTEST_FILE, {}))
    archive_expired(expired, output_dir / ARCHIVE_DIR)

    # Market data. A failed source yields an empty board, never the previous
    # run's numbers: carrying them forward is how the board showed August
    # quotes as current for three months.
    sectors: list[dict[str, Any]] = []
    pulse: list[dict[str, Any]] = []
    getter = requests_getter(session)
    sectors_as_of = None
    try:
        twse_board = fetch_twse_sector_board(getter, now.astimezone(TAIPEI).date())
        if twse_board:
            sectors_as_of, sectors = twse_board
            LOGGER.info("built %d sector rows from TWSE MI_INDEX as of %s", len(sectors), sectors_as_of)
    except (requests.RequestException, ValueError) as exc:
        LOGGER.error("TWSE sector indices unavailable: %s", exc)
    try:
        quotes = fetch_quotes(session)
        pulse = build_pulse(quotes, previous.get("pulse", []))
        if not sectors:
            sectors = build_sector_board(quotes)
        LOGGER.info("built %d pulse rows", len(pulse))
    except (requests.RequestException, ValueError) as exc:
        LOGGER.error("quote feed unavailable: %s", exc)

    market = build_market(getter, now, kept, finnhub_key=os.environ.get("FINNHUB_API_KEY", "").strip())
    market["sectors_as_of"] = sectors_as_of
    try:
        history_path = output_dir / "market" / TAIEX_HISTORY
        history = load_json(history_path, {"schema_version": 1, "source": "TWSE FMTQIK (official)",
                                           "unit": "index points", "rows": []})
        merged = merge_taiex_history(history, fetch_taiex_history(getter, now.astimezone(TAIPEI).date()))
        if merged is not history:
            history_path.parent.mkdir(parents=True, exist_ok=True)
            history_path.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    except (requests.RequestException, ValueError, OSError) as exc:
        LOGGER.error("TAIEX history not updated: %s", exc)

    root = output_dir.parent
    flow_as_of, flow_panels = None, []
    try:
        registry = load_registry(root / "config" / "symbol_registry.tw.json")
        flow_as_of, totals = aggregate_sectors(iter_shards(output_dir / "flows"), registry)
        flow_panels = build_flow_panels(totals)
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.error("sector flows unavailable: %s", exc)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "window_hours": WINDOW_HOURS,
        "direction_rule_version": RULE_VERSION,
        "sources": [SOURCE_NAME],
        "events": kept,
        "pulse": pulse,
        "sectors": sectors,
        "flows": {"as_of": flow_as_of, "panels": flow_panels},
        "market": market,
    }


def connection_factory_from_environment() -> Any | None:
    """Lazy direct-Postgres factory, only when the gated credential is present.

    Same secret and workflow gate as the theme-radar dual-write
    (THEME_RADAR_DATABASE_URL); see docs/RADAR_DB.md.
    """

    database_url = os.environ.get("THEME_RADAR_DATABASE_URL", "").strip()
    if not database_url:
        return None

    def connect() -> Any:
        import psycopg

        return psycopg.connect(database_url)

    return connect


def run_pre_market_dual_write(connection_factory: Any | None, payload: dict[str, Any]) -> str:
    """Mirror the payload into radar.pre_market_snapshot; never fails the run.

    Returns "written", "skipped" (no credential) or "failed". The JSON file is
    already on disk when this runs, so a DB outage only leaves the API serving
    an older snapshot, which its staleness guard turns into a JSON fallback.
    """

    if connection_factory is None:
        LOGGER.warning("pre_market_dual_write_skipped reason=credential_unavailable")
        return "skipped"
    connection: Any | None = None
    try:
        connection = connection_factory()
        summary = write_pre_market_snapshot(connection, payload, impact_rows=impact_rows)
    except Exception as error:  # noqa: BLE001 - DB mirror must never fail the run
        LOGGER.warning("pre_market_dual_write_failed error=%s", redact_error(error))
        return "failed"
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:  # noqa: BLE001 - close failure is not actionable
                pass
    LOGGER.info(
        "pre_market_dual_write_written generated_at=%s events=%d focus_events=%d impacts=%d",
        summary["generated_at"], summary["event_count"],
        summary.get("focus_events_written", 0), summary.get("impacts_written", 0),
    )
    return "written"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="data", type=Path)
    parser.add_argument("--skip-translate", action="store_true",
                        help="reuse cached translations only (offline runs)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = build_payload(output_dir, datetime.now(timezone.utc), args.skip_translate)
    target = output_dir / LATEST_FILE
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    critical = sum(1 for e in payload["events"] if e["tier"] == "critical")
    watch = sum(1 for e in payload["events"] if e["tier"] == "watch")
    LOGGER.info(
        "wrote %s: %d events (%d critical, %d watch), %d sectors, %d flow panels",
        target.name, len(payload["events"]), critical, watch,
        len(payload["sectors"]), len(payload["flows"]["panels"]),
    )
    run_pre_market_dual_write(connection_factory_from_environment(), payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
