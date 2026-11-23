"""M026: keep news by market impact first, map it to Taiwan stocks second.

On 2026-11-23 ~120 headlines on 黃仁勳 leaving / returning as NVIDIA CEO (the
reason the US opened sharply higher) were ingested and all dropped at theme
score 0, before anyone asked how much they moved the market.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job" / "scripts"))

from market_impact import (  # noqa: E402
    IMPACT_KEEP_MIN,
    find_bursts,
    load_market_movers,
    score_impact,
)
from geo_focus import build_focus_events  # noqa: E402
from scripts import update_theme_radar as updater  # noqa: E402
from scripts.theme_relevance import load_theme_taxonomy  # noqa: E402

FIXTURE = json.loads(
    (ROOT / "tests/fixtures/market_impact/nvidia-ceo-2026-11-23.json").read_text(encoding="utf-8")
)
ANCHOR = datetime(2026, 11, 23, 14, 17, tzinfo=timezone.utc)
MOVERS = load_market_movers()
SOURCES = ("yahoo_finance_tw", "cnyes", "technews", "digitimes_tw", "cna_finance")


def _record(index: int, title: str, hours_ago: float = 1.0, source: str | None = None) -> dict:
    return {
        "id": f"t{index}",
        "title_zh": title,
        "summary": "",
        "source": source or SOURCES[index % len(SOURCES)],
        "source_id": source or SOURCES[index % len(SOURCES)],
        "published_at": (ANCHOR - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z"),
        "url": f"https://example.test/{index}",
    }


def _taxonomy_without_entity_keywords() -> dict:
    """The real taxonomy, minus every NVIDIA/黃仁勳 keyword: impact alone must keep them."""
    taxonomy = load_theme_taxonomy()
    for theme in taxonomy["themes"]:
        if theme["theme_id"] == "nvidia_supply_chain":
            theme["keywords"] = ["__no_keyword_match__"]
    return taxonomy


def _project(records, taxonomy=None):
    events, candidates, projection = updater.build_theme_projection(
        records,
        taxonomy or _taxonomy_without_entity_keywords(),
        anchor=ANCHOR,
        window_hours=72,
        max_events=500,
        max_candidates=200,
    )
    return events, candidates, projection


def test_market_moving_headlines_are_kept_and_noise_is_not() -> None:
    for title in FIXTURE["must_keep"]:
        impact = score_impact(title, MOVERS)
        assert impact.keep, (title, impact.score, impact.signals)
    for title in FIXTURE["must_drop"] + FIXTURE["context_only"]:
        impact = score_impact(title, MOVERS)
        assert not impact.keep, (title, impact.score, impact.signals)


def test_registry_maps_onto_existing_themes() -> None:
    theme_ids = {theme["theme_id"] for theme in load_theme_taxonomy()["themes"]}
    for mover in MOVERS:
        assert set(mover.tw_theme_ids) <= theme_ids, mover.id


def test_theme_radar_keeps_by_impact_then_maps_to_the_tw_chain() -> None:
    titles = FIXTURE["must_keep"] + FIXTURE["context_only"] + FIXTURE["must_drop"]
    events, candidates, projection = _project([_record(i, t) for i, t in enumerate(titles)])

    by_title = {item["title_zh"]: item for item in events["items"]}
    lead = by_title.get("黃仁勳回鍋輝達執行長！董事會一致通過即刻生效")
    assert lead is not None, "the CEO-return headline must reach the event feed"
    assert lead["tw_relevance_status"] == "market_mover"
    assert lead["primary_theme_id"] == "nvidia_supply_chain"
    assert {"2330", "2317", "2382"} <= set(lead["related_symbol_codes"])
    assert lead["impact_score"] >= IMPACT_KEEP_MIN
    assert any(signal.startswith("mover:nvidia") for signal in lead["impact_signals"])

    # A price-reaction headline is the news itself when the impact is high.
    assert "美股盤前上演大反擊　輝達強彈9%" in by_title

    for title in FIXTURE["must_drop"]:
        assert title not in by_title, title
    assert events["kept_by_impact_items"] >= len(FIXTURE["must_keep"]) - 1  # one may cluster
    assert events["dropped_items"] + events["excluded_items"] >= len(FIXTURE["must_drop"])

    assert any(item["primary_theme_id"] == "nvidia_supply_chain" for item in candidates["items"])
    assert all(event["primary_theme_id"] for event in projection["clustered_events"])


def test_dropped_near_misses_are_listed_not_silent() -> None:
    """Name-only mentions with no market signal stay out, but are listed."""
    titles = FIXTURE["context_only"] + FIXTURE["must_drop"]
    events, _, _ = _project([_record(i, t) for i, t in enumerate(titles)])
    near_misses = {item["title"]: item for item in events["top_dropped_items"]}
    for title in FIXTURE["context_only"]:
        if title in {item["title_zh"] for item in events["items"]}:
            continue  # kept through an ordinary theme match (汽車, AI ...)
        assert title in near_misses, title
        assert near_misses[title]["impact_signals"], title


def test_market_wide_news_is_kept_without_a_chain_and_kept_out_of_theme_ranking() -> None:
    title = "費半狂瀉10% 美股暴跌創四年最大跌幅"
    events, _, projection = _project([_record(0, title)])
    item = next(item for item in events["items"] if item["title_zh"] == title)
    assert item["tw_relevance_status"] == "market_wide"
    assert item["primary_theme_id"] is None
    assert projection["clustered_events"] == []


def test_an_unconfigured_story_is_caught_by_a_coverage_burst() -> None:
    story = [f"神秘病毒擴散第{i}波 各國衛生單位緊急應變{i}" for i in range(32)]
    baseline = [f"台股盤後整理 第{i}則" for i in range(20)]
    records = [_record(i, t, hours_ago=2 + i * 0.1) for i, t in enumerate(story)]
    records += [_record(100 + i, t, hours_ago=30 + i) for i, t in enumerate(baseline)]
    bursts = find_bursts(
        records,
        anchor=ANCHOR,
        window_hours=72,
        title_of=lambda r: r["title_zh"],
        published_of=lambda r: datetime.fromisoformat(r["published_at"].replace("Z", "+00:00")),
        source_of=lambda r: r["source_id"],
    )
    assert "神秘病" in bursts
    assert "台股盤" not in bursts
    impact = score_impact(story[0], MOVERS, bursts)
    assert impact.keep, impact.signals


def test_pre_market_routes_a_mover_with_no_keyword_path() -> None:
    now = datetime(2026, 11, 23, 14, 0, tzinfo=timezone.utc)
    entries = [{
        "title": "Apple CEO Tim Cook to step down, board names successor",
        "link": "https://example.test/apple",
        "published_at": now - timedelta(minutes=10),
    }]
    events = build_focus_events(entries, {}, now=now)
    assert [event["pathId"] for event in events] == ["us_tech_rally"]
