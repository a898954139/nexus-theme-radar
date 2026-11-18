"""Conditional GET, trial sources, and the 7-day intake store (issue #3)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate_source_overlap import evaluate_source_overlap, tokens_for_overlap  # noqa: E402
from scripts.rss_feed_state import (  # noqa: E402
    build_intake_store,
    conditional_headers,
    record_run_history,
)
from scripts.update_theme_radar import (  # noqa: E402
    fetch_rss_source,
    source_status_payload,
    trial_sources,
)

ANCHOR = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)
FEED = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>\xe5\x8f\xb0\xe7\xa9\x8d\xe9\x9b\xbb\xe6\x93\xb4\xe7\x94\xa2</title><link>https://example.com/a</link>
<pubDate>Wed, 18 Nov 2026 07:00:00 GMT</pubDate></item></channel></rss>"""
SOURCE = {
    "source_id": "demo",
    "name": "Demo",
    "source_class": "financial_media",
    "market_id": "TW_EQUITY",
    "market_scope": ["TW_EQUITY"],
    "feed_url": "https://example.com/feed.xml",
}


class Response:
    def __init__(self, status_code: int, body: bytes = b"", headers: dict | None = None) -> None:
        self.status_code = status_code
        self.content = body
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, _size: int):
        yield self.content

    def close(self) -> None:
        return None


class Session:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.calls: list[dict] = []

    def get(self, url, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_first_fetch_stores_validators_and_sends_no_conditional_headers() -> None:
    session = Session(Response(200, FEED, {"ETag": '"v1"', "Last-Modified": "Wed, 18 Nov 2026 07:00:00 GMT"}))
    result = fetch_rss_source(session, dict(SOURCE), ANCHOR, feed_state={})

    assert session.calls[0]["headers"] is None
    assert result["status"]["status"] == "ok"
    assert len(result["records"]) == 1
    assert result["feed_state"]["etag"] == '"v1"'
    assert result["feed_state"]["items"] == result["records"]


def test_not_modified_replays_cached_items() -> None:
    first = fetch_rss_source(
        Session(Response(200, FEED, {"ETag": '"v1"'})), dict(SOURCE), ANCHOR, feed_state={}
    )
    state = {"demo": first["feed_state"]}
    session = Session(Response(304))
    result = fetch_rss_source(session, dict(SOURCE), ANCHOR + timedelta(hours=1), feed_state=state)

    assert session.calls[0]["headers"] == {"If-None-Match": '"v1"'}
    assert result["status"]["status"] == "ok"
    assert result["status"]["not_modified"] is True
    assert result["records"] == first["records"]


def test_full_refresh_and_changed_url_skip_conditional_headers() -> None:
    entry = {"feed_url": SOURCE["feed_url"], "etag": '"v1"', "items": [{"id": "x"}]}
    assert conditional_headers(entry, "https://example.com/other.xml") == {}
    assert conditional_headers({**entry, "items": []}, SOURCE["feed_url"]) == {}
    session = Session(Response(200, FEED))
    fetch_rss_source(session, dict(SOURCE), ANCHOR, feed_state={"demo": entry}, full_refresh=True)
    assert session.calls[0]["headers"] is None


def test_error_keeps_previous_state_and_history_tracks_success_rate() -> None:
    previous = {"feed_url": SOURCE["feed_url"], "etag": '"v1"', "items": [{"id": "x"}], "history": []}
    result = fetch_rss_source(Session(Response(503)), dict(SOURCE), ANCHOR, feed_state={"demo": previous})
    assert result["status"]["status"] == "error"
    assert result["feed_state"]["etag"] == '"v1"'

    state = {"demo": {**previous, "history": [{"at": "2026-11-01T00:00:00Z", "ok": False}]}}
    ok = {"source_id": "demo", "fetch_method": "rss", "status": "ok", "items": 3}
    record_run_history(state, [ok], ANCHOR - timedelta(hours=1))
    stats = record_run_history(state, [{**ok, "status": "error"}], ANCHOR)
    # The 2026-11-01 run is outside the 7-day window and was pruned.
    assert stats["demo"] == {"runs_7d": 2, "success_rate_7d": 0.5}


def test_trial_sources_are_listed_but_do_not_move_health_counters() -> None:
    registry = {
        "market_id": "TW_EQUITY",
        "sources": [
            {"source_id": "a", "status": "active", "fetch_method": "rss", "feed_url": "https://a"},
            {"source_id": "t", "status": "trial", "fetch_method": "rss", "feed_url": "https://t"},
            {"source_id": "p", "status": "planned", "fetch_method": "rss", "feed_url": "https://p"},
        ],
    }
    assert [s["source_id"] for s in trial_sources(registry)] == ["t"]

    payload = source_status_payload(
        [
            {"source_id": "a", "status": "ok"},
            {"source_id": "t", "status": "error", "trial": True},
        ],
        ANCHOR,
        1,
    )
    assert payload["successful_sites"] == 1
    assert payload["failed_count"] == 0
    assert payload["failed_sites"] == []
    assert [site["source_id"] for site in payload["sites"]] == ["a", "t"]


def test_intake_store_keeps_first_seen_and_prunes_after_seven_days() -> None:
    old = {"site_id": "demo", "url": "https://old", "title": "x", "first_seen_at": "2026-11-01T00:00:00Z"}
    kept = {"site_id": "demo", "url": "https://example.com/a", "title": "y", "first_seen_at": "2026-11-17T00:00:00Z"}
    record = {"source_id": "demo", "source": "Demo", "title_zh": "y", "url": "https://example.com/a",
              "published_at": "2026-11-18T07:00:00Z", "fetched_at": "2026-11-18T08:00:00Z"}
    store = build_intake_store([old, kept], [record], ANCHOR)

    assert store["item_count"] == 1
    assert store["items"][0]["first_seen_at"] == "2026-11-17T00:00:00Z"


def test_chinese_rewritten_headline_is_found_by_overlap_index() -> None:
    assert {"台積", "積電"} <= tokens_for_overlap("台積電擴產")
    candidate = [{"site_id": "new", "title": "台積電宣布美國廠擴產計畫", "url": "https://n/1",
                  "published_at": "2026-11-18T07:00:00Z"}]
    baseline = [{"site_id": "cnyes", "title": "台積電今宣布美國廠擴產計畫", "url": "https://c/1",
                 "published_at": "2026-11-18T06:00:00Z"}]
    report = evaluate_source_overlap(candidate, baseline, candidate={"site_id": "new"},
                                     generated_at=ANCHOR, lookback_days=7)
    assert report["overlap"]["duplicate_count"] == 1


def test_mislabeled_timezone_is_corrected_and_future_items_are_clamped() -> None:
    from scripts.update_theme_radar import feed_published_at

    fetched = datetime(2026, 11, 18, 7, 21, tzinfo=timezone.utc)
    # 工商時報 writes Taipei wall-clock time with a UTC designator.
    ctee = {"published_at_offset_hours": -8}
    assert feed_published_at("Wed, 18 Nov 2026 14:37:36 +0000", ctee, fetched) == "2026-11-18T06:37:36Z"
    assert feed_published_at("Wed, 18 Nov 2026 14:37:36 +0000", {}, fetched) == "2026-11-18T07:21:00Z"
    assert feed_published_at("Wed, 18 Nov 2026 06:00:00 +0000", {}, fetched) == "2026-11-18T06:00:00Z"


def test_run_update_isolates_trial_sources_and_replays_304(monkeypatch, tmp_path) -> None:
    import json

    from scripts import update_theme_radar as updater

    monkeypatch.setenv("THEME_RADAR_FUNDAMENTALS", "0")
    monkeypatch.setattr(updater, "now_utc", lambda: ANCHOR)
    active_feed = FEED.replace(b"https://example.com/a", b"https://active.example/a")
    trial_feed = FEED.replace(b"https://example.com/a", b"https://trial.example/a")
    calls: list[tuple[str, dict | None]] = []

    class FakeSession:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        def get(self, url, **kwargs):
            calls.append((url, kwargs.get("headers")))
            if url == "https://active.example/feed":
                if (kwargs.get("headers") or {}).get("If-None-Match") == '"a1"':
                    return Response(304)
                return Response(200, active_feed, {"ETag": '"a1"'})
            return Response(200, trial_feed)

        def close(self) -> None:
            return None

    monkeypatch.setattr("requests.Session", FakeSession)
    registry = tmp_path / "registry.json"
    base = {"source_class": "financial_media", "fetch_method": "rss"}
    registry.write_text(
        json.dumps(
            {
                "market_id": "TW_EQUITY",
                "market_scope": ["TW_EQUITY"],
                "sources": [
                    {**base, "source_id": "act", "name": "Active", "status": "active",
                     "feed_url": "https://active.example/feed"},
                    {**base, "source_id": "tri", "name": "Trial", "status": "trial",
                     "feed_url": "https://trial.example/feed"},
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output"

    def run() -> dict:
        updater.run_update(registry_path=registry, output_dir=output, window_hours=72,
                           max_events=10, max_candidates=10)
        return json.loads((output / "source-status.json").read_text(encoding="utf-8"))

    first = run()
    assert first["fetched_raw_items"] == 1  # trial record excluded from discovery
    assert first["successful_sites"] == 1 and first["failed_count"] == 0
    trial_site = next(site for site in first["sites"] if site["source_id"] == "tri")
    assert trial_site["trial"] is True and trial_site["success_rate_7d"] == 1.0
    intake = json.loads((output / "source-intake-7d.json").read_text(encoding="utf-8"))
    assert {item["site_id"] for item in intake["items"]} == {"act", "tri"}

    second = run()
    active_site = next(site for site in second["sites"] if site["source_id"] == "act")
    assert active_site["not_modified"] is True
    assert active_site["items"] == 1
    assert second["fetched_raw_items"] == 1
    assert active_site["runs_7d"] == 2
    assert ("https://active.example/feed", {"If-None-Match": '"a1"'}) in calls
    events = json.loads((output / "theme-events.json").read_text(encoding="utf-8"))
    assert all(item.get("source_id") != "tri" for item in events["items"])
