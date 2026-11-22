"""Theme radar reads the 5-minute ingest's articles (job-pipeline breakpoint 1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from scripts import update_theme_radar
from scripts.ingest_runner import fetch_group
from scripts.ingested_articles import (
    INGEST_HEALTH_SQL,
    INGESTED_ARTICLES_SQL,
    ORIGIN_ADAPTER,
    load_ingest_source_ids,
    load_ingested_results,
)
from scripts.update_theme_radar import fetch_rss_source

NOW = datetime(2026, 11, 22, 4, 17, tzinfo=timezone.utc)
CNYES = {"source_id": "cnyes", "name": "鉅亨網", "source_class": "media", "fetch_method": "rss",
         "feed_url": "https://news.cnyes.com/rss", "market_id": "TW_EQUITY", "market_scope": ["TW_EQUITY"]}
MONEYDJ = {**CNYES, "source_id": "moneydj", "name": "MoneyDJ", "feed_url": "https://moneydj/rss"}
MOPS = {"source_id": "mops", "fetch_method": "twse_openapi", "source_class": "official_disclosure"}


class FakeCursor:
    def __init__(self, conn: "FakeConnection") -> None:
        self.conn = conn
        self._rows: list[Any] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, sql: str, params: dict[str, Any]) -> None:
        self.conn.calls.append((sql, params))
        if self.conn.fail:
            raise RuntimeError("password=hunter2 host=db.internal")
        if sql == INGEST_HEALTH_SQL:
            self._rows = [{"source_id": sid, "last_ok_at": at} for sid, at in self.conn.health.items()
                          if sid in params["source_ids"] and at >= params["since"]]
        elif sql == INGESTED_ARTICLES_SQL:
            self._rows = [row for row in self.conn.articles if row["source_id"] in params["source_ids"]
                          and params["since"] <= row["published_at"] <= params["until"]]
        else:  # pragma: no cover
            raise AssertionError(sql)

    def fetchall(self) -> list[Any]:
        return self._rows


class FakeConnection:
    def __init__(self, health=None, articles=None, fail=False) -> None:
        self.health = health or {}
        self.articles = articles or []
        self.fail = fail
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True


def _article(source_id: str, n: int, hours_ago: float) -> dict[str, Any]:
    published = NOW - timedelta(hours=hours_ago)
    return {"article_id": f"{source_id}-{n}", "source_id": source_id, "source_class": "media",
            "market_id": "TW_EQUITY", "url": f"https://{source_id}.example/{n}", "title": f"台積電新聞 {n}",
            "summary": "", "extraction_method": "rss", "published_at": published,
            "first_fetched_at": published + timedelta(minutes=3)}


def _load(conn: FakeConnection, **kwargs: Any) -> dict[str, dict[str, Any]]:
    return load_ingested_results(lambda: conn, [CNYES, MONEYDJ, MOPS], NOW, window_hours=72,
                                 ingest_source_ids={"cnyes", "moneydj", "financialjuice"},
                                 env={}, **kwargs)


def test_ingest_groups_config_lists_the_hourly_media_sources() -> None:
    ids = load_ingest_source_ids()
    assert {"cnyes", "moneydj", "yahoo_finance_tw", "technews", "digitimes_tw"} <= ids


def test_fresh_sources_are_served_from_the_table_in_feed_record_shape() -> None:
    conn = FakeConnection(
        health={"cnyes": NOW - timedelta(minutes=4)},
        articles=[_article("cnyes", 1, 1), _article("cnyes", 2, 70), _article("cnyes", 3, 80),
                  _article("moneydj", 1, 1)],
    )
    results = _load(conn)
    assert set(results) == {"cnyes"}  # moneydj has no fresh ingest -> fetched over RSS
    cnyes = results["cnyes"]
    assert [r["id"] for r in cnyes["records"]] == ["cnyes-1", "cnyes-2"]  # 80h is outside 72h
    record = cnyes["records"][0]
    assert record == {
        "id": "cnyes-1", "title_zh": "台積電新聞 1", "summary": "", "source": "鉅亨網",
        "source_id": "cnyes", "source_class": "media", "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"], "published_at": "2026-11-22T03:17:00Z",
        "url": "https://cnyes.example/1", "extraction_method": "rss",
        "fetched_at": "2026-11-22T03:20:00Z",
    }
    assert cnyes["status"]["adapter"] == ORIGIN_ADAPTER
    assert cnyes["status"]["fetch_method"] == "rss"
    assert cnyes["status"]["status"] == "ok" and cnyes["status"]["items"] == 2
    # Only ingest-run health counts, and only within the staleness bound.
    health_params = conn.calls[0][1]
    assert health_params["since"] == NOW - timedelta(minutes=30)
    assert "run_kind = 'ingest'" in INGEST_HEALTH_SQL
    assert conn.closed


def test_stale_ingest_falls_back_to_rss_for_every_source() -> None:
    conn = FakeConnection(health={"cnyes": NOW - timedelta(minutes=45)}, articles=[_article("cnyes", 1, 1)])
    assert _load(conn) == {}
    assert len(conn.calls) == 1  # never reads articles


def test_db_errors_fail_open_without_leaking_the_dsn(caplog: pytest.LogCaptureFixture) -> None:
    conn = FakeConnection(fail=True)
    assert _load(conn) == {}
    assert "hunter2" not in caplog.text
    assert "ingest_source_fallback reason=db_error" in caplog.text


def test_toggle_and_missing_credential_disable_the_db_read() -> None:
    conn = FakeConnection(health={"cnyes": NOW}, articles=[_article("cnyes", 1, 1)])
    assert load_ingested_results(lambda: conn, [CNYES], NOW, window_hours=72,
                                 ingest_source_ids={"cnyes"}, env={"THEME_RADAR_INGEST_SOURCE": "0"}) == {}
    assert load_ingested_results(None, [CNYES], NOW, window_hours=72, ingest_source_ids={"cnyes"}, env={}) == {}
    assert conn.calls == []


def test_trial_and_non_rss_sources_are_never_served_from_the_table() -> None:
    conn = FakeConnection(health={"cnyes": NOW}, articles=[_article("cnyes", 1, 1)])
    trial = {**CNYES, "status": "trial"}
    assert load_ingested_results(lambda: conn, [trial, MOPS], NOW, window_hours=72,
                                 ingest_source_ids={"cnyes", "mops"}, env={}) == {}


def test_run_update_skips_fetching_ingest_served_feeds(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """The hourly run must not refetch a DB-served feed, and must not mirror it
    back as a source_run (that would push back the ingest's next fetch)."""

    fetched: list[str] = []
    served = {"records": [], "status": {"source_id": "cnyes", "name": "鉅亨網", "adapter": ORIGIN_ADAPTER,
                                        "fetch_method": "rss", "status": "ok", "items": 0, "error": None,
                                        "elapsed_ms": 0, "source_class": "media"}}
    monkeypatch.setattr(update_theme_radar, "load_ingested_results", lambda *a, **k: {"cnyes": served})

    def fake_dispatch(session, sources, fetched_at, **kwargs):
        fetched.extend(str(s["source_id"]) for s in sources)
        return []

    monkeypatch.setattr(update_theme_radar, "dispatch_sources", fake_dispatch)
    captured: dict[str, Any] = {}

    def fake_dual_write(**kwargs):
        captured.update(kwargs)
        return dict(update_theme_radar.RADAR_DUAL_WRITE_DEFAULTS)

    monkeypatch.setattr(update_theme_radar, "run_radar_dual_write", fake_dual_write)
    monkeypatch.setattr(update_theme_radar, "run_momentum_side_paths", lambda **k: {})
    monkeypatch.setenv("THEME_RADAR_FUNDAMENTALS", "0")
    update_theme_radar.run_update(
        registry_path=update_theme_radar.DEFAULT_REGISTRY_PATH, output_dir=tmp_path,
        window_hours=72, max_events=50, max_candidates=50, history_connection_factory=lambda: None,
    )
    assert "cnyes" not in fetched and "moneydj" in fetched
    assert all(status["source_id"] != "cnyes" for status in captured["statuses"])
    status = __import__("json").loads((tmp_path / "source-status.json").read_text(encoding="utf-8"))
    assert any(site["source_id"] == "cnyes" and site["adapter"] == ORIGIN_ADAPTER for site in status["sites"])


class _Resp:
    status_code = 200
    headers: dict[str, str] = {}
    raw = None

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, *args: Any, **kwargs: Any):
        yield b"<rss><channel><item><title>t</title><link>https://x.example/1</link></item></channel></rss>"

    def close(self) -> None:
        return None


class _Session:
    def get(self, *args: Any, **kwargs: Any) -> _Resp:
        return _Resp()

    def close(self) -> None:
        return None


def test_ingest_fetch_group_accepts_the_real_rss_fetcher_envelope() -> None:
    """Regression: fetch_rss_source returns a dict since #30 and fetch_group
    unpacked it as a tuple, so every ingest source was recorded as an error."""

    records, statuses = fetch_group([CNYES], NOW, budget_seconds=5, fetcher=fetch_rss_source,
                                    session_factory=lambda source: _Session())
    assert [s["status"] for s in statuses] == ["ok"]
    assert len(records) == 1 and records[0]["source_id"] == "cnyes"
