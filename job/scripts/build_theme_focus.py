#!/usr/bin/env python3
"""Build data/theme-focus.json: which radar themes the money is following.

News heat alone says what people are talking about. Whether a theme is worth
focusing on also depends on whether institutional money is moving into the
stocks behind it. This joins the two published inputs that already exist:

- data/public-theme-momentum-latest-v0.9.json (+ v0.8 ranking): themes, heat,
  momentum and member stocks
- data/flows/<EXCHANGE>-<code>.json: official TWSE T86 / TPEX per-symbol
  institutional net buy/sell, rows [date, foreign, trust, dealer, total] in shares

and, when present, data/public-stock-watchlist-v1.json for each member's short
and long watch score.

The output is a separate file on purpose: the momentum and ranking payloads
are validated with exact key counts by two front-ends, and a new field there
would blank the page. A missing or stale theme-focus.json only hides the focus
board; nothing else depends on it.

A theme the news named without naming any stock (no event or ranking
symbols) falls back to its taxonomy seed stocks, so the board can still say
whether money is moving into that industry. The taxonomy is passed in by
main(); build_theme_focus itself has no sibling imports.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

LOGGER = logging.getLogger("build_theme_focus")

SCHEMA_VERSION = "nexus_theme_focus.v1"
OUTPUT_FILE = "theme-focus.json"
FLOW_WINDOW_DAYS = 5
TOP_STOCKS = 5
OUTFLOW_STOCKS = 3
DIRECT_WEIGHT = 3

# A theme is "hot" in the news at this heat score. The radar publishes heat on a
# 0-100 scale and qualifies themes around 40; 60 is the upper half of the
# displayed set, which is where "is the money following?" becomes the question.
HOT_HEAT = 60
# Share of members with positive 5-day net. Above 0.55 the buying is broad, not
# one large name; below 0.45 more members are being sold than bought.
BROAD_BREADTH = 0.55
WEAK_BREADTH = 0.45

_SAFE_PART = re.compile(r"^[A-Za-z0-9]{1,12}$")

STANCES = {
    "focus": "新聞與法人同向",
    "money_first": "法人先行、新聞未熱",
    "news_only": "新聞熱、法人未跟",
    "outflow": "法人賣超",
    "watch": "訊號不足",
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _flow_path(flows_dir: Path, instrument_id: str) -> Path | None:
    exchange, _, code = instrument_id.partition(":")
    if not _SAFE_PART.match(exchange) or not _SAFE_PART.match(code):
        return None
    return flows_dir / f"{exchange}-{code}.json"


def _series(payload: Any) -> list[tuple[str, float, float, float, float]]:
    """Rows as (date, foreign, trust, dealer, total), newest first."""
    rows: list[tuple[str, float, float, float, float]] = []
    series = payload.get("series") if isinstance(payload, Mapping) else None
    if not isinstance(series, list):
        return rows
    for row in series:
        if isinstance(row, (list, tuple)) and len(row) >= 5 and isinstance(row[0], str):
            values = [_number(value) for value in row[1:5]]
            if all(value is not None for value in values):
                rows.append((row[0], *values))  # type: ignore[arg-type]
        elif isinstance(row, Mapping) and isinstance(row.get("date"), str):
            values = [_number(row.get(key)) for key in ("foreign_net", "trust_net", "dealer_net", "total_net")]
            if all(value is not None for value in values):
                rows.append((row["date"], *values))  # type: ignore[arg-type]
    rows.sort(key=lambda item: item[0], reverse=True)
    return rows


def summarize_flow(rows: list[tuple[str, float, float, float, float]], as_of: str | None) -> dict[str, Any] | None:
    """5-day institutional summary in lots (1 lot = 1,000 shares).

    Only rows up to the market-wide as_of date count, and the newest row must be
    that date: a symbol whose file stopped updating is reported as missing,
    not silently scored on old days.
    """
    if as_of:
        rows = [row for row in rows if row[0] <= as_of]
    if not rows or (as_of and rows[0][0] != as_of):
        return None
    window = rows[:FLOW_WINDOW_DAYS]
    streak = 0
    for row in rows:
        if row[4] > 0:
            if streak < 0:
                break
            streak += 1
        elif row[4] < 0:
            if streak > 0:
                break
            streak -= 1
        else:
            break
    return {
        "as_of": rows[0][0],
        "days": len(window),
        "total_5d": round(sum(row[4] for row in window) / 1000),
        "foreign_5d": round(sum(row[1] for row in window) / 1000),
        "trust_5d": round(sum(row[2] for row in window) / 1000),
        "total_1d": round(rows[0][4] / 1000),
        "streak": streak,
    }


def _seed_items(symbols: Iterable[str], flows_dir: Path) -> list[dict[str, str]]:
    """Taxonomy seed codes as instruments, exchange resolved from the flows files."""
    items = []
    for symbol in symbols:
        code = str(symbol)
        if not _SAFE_PART.match(code):
            continue
        for exchange in ("TWSE", "TPEX"):
            path = flows_dir / f"{exchange}-{code}.json"
            if path.exists():
                payload = _read_json(path)
                name = payload.get("name") if isinstance(payload, Mapping) else None
                items.append({
                    "instrument_id": f"{exchange}:{code}",
                    "symbol": code,
                    "exchange": exchange,
                    "name_zh": str(name or ""),
                })
                break
    return items


def _members(theme: Mapping[str, Any], ranking: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}

    def add(items: Any, relation: str) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, Mapping):
                continue
            instrument_id = item.get("instrument_id")
            if not isinstance(instrument_id, str) or ":" not in instrument_id:
                continue
            current = seen.get(instrument_id)
            if current is None:
                seen[instrument_id] = {
                    "instrument_id": instrument_id,
                    "symbol": str(item.get("symbol") or instrument_id.split(":", 1)[1]),
                    "exchange": str(item.get("exchange") or instrument_id.split(":", 1)[0]),
                    "name_zh": str(item.get("name_zh") or ""),
                    "relation": relation,
                }
            elif relation == "direct":
                current["relation"] = "direct"

    add(theme.get("direct_symbols"), "direct")
    add(theme.get("related_symbols"), "related")
    if ranking:
        add(ranking.get("direct_mentions"), "direct")
        add(ranking.get("supply_chain_candidates"), "related")
    return list(seen.values())


def _watch_scores(watchlist: Any) -> dict[str, dict[str, Any]]:
    scores: dict[str, dict[str, Any]] = {}
    if not isinstance(watchlist, Mapping):
        return scores
    for view in ("short", "long"):
        block = watchlist.get(view)
        items = block.get("items") if isinstance(block, Mapping) else None
        for item in items or []:
            instrument = item.get("instrument") if isinstance(item, Mapping) else None
            summary = item.get(view) if isinstance(item, Mapping) else None
            if not isinstance(instrument, Mapping) or not isinstance(summary, Mapping):
                continue
            entry = scores.setdefault(str(instrument.get("instrument_id")), {})
            entry[f"{view}_rank"] = summary.get("rank")
            entry[f"{view}_score"] = round(float(summary.get("score") or 0))
    return scores


def classify(heat: float, breadth: float | None) -> str:
    """Stance from news heat and flow breadth.

    Breadth (share of members bought on net over 5 days), not the summed lots,
    decides the money side: one mega-cap being sold by foreign funds moves the
    sum by more than every other member combined, and that says little about
    whether the theme itself is being accumulated. The sum is still published.
    """
    if breadth is None:
        return "watch"
    money_in = breadth >= BROAD_BREADTH
    money_out = breadth <= WEAK_BREADTH
    if heat >= HOT_HEAT and money_in:
        return "focus"
    if money_in:
        return "money_first"
    if heat >= HOT_HEAT and money_out:
        return "news_only"
    if money_out:
        return "outflow"
    return "news_only" if heat >= HOT_HEAT else "watch"


def focus_score(heat: float, breadth: float | None) -> int:
    """Half news heat, half flow breadth, both on 0-100. Kept deliberately
    simple so the number can be read back to its two inputs."""
    if breadth is None:
        return round(heat * 0.5)
    return round(0.5 * heat + 0.5 * breadth * 100)


def _market_as_of(flow_rows: Iterable[list[tuple[str, float, float, float, float]]]) -> str | None:
    counts: dict[str, int] = {}
    for rows in flow_rows:
        if rows:
            counts[rows[0][0]] = counts.get(rows[0][0], 0) + 1
    if not counts:
        return None
    # The latest date that a meaningful share of symbols have reached. A single
    # symbol with a future-dated row must not move every other symbol to missing.
    total = sum(counts.values())
    for date in sorted(counts, reverse=True):
        if counts[date] >= max(1, total * 0.2):
            return date
    return max(counts)


def build_theme_focus(
    data_dir: Path,
    *,
    generated_at: datetime | None = None,
    taxonomy_seeds: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, Any]:
    momentum = _read_json(data_dir / "public-theme-momentum-latest-v0.9.json") or {}
    ranking = _read_json(data_dir / "public-theme-ranking-v0.8.json") or {}
    watchlist = _read_json(data_dir / "public-stock-watchlist-v1.json")
    flows_dir = data_dir / "flows"

    ranking_by_id = {
        theme.get("theme_id"): theme
        for theme in ranking.get("themes", [])
        if isinstance(theme, Mapping)
    }
    themes_in = [theme for theme in momentum.get("themes", []) if isinstance(theme, Mapping)]
    members_by_theme = {
        str(theme.get("theme_id")): _members(theme, ranking_by_id.get(theme.get("theme_id")))
        for theme in themes_in
    }
    for theme_id, members in members_by_theme.items():
        if not members and taxonomy_seeds and taxonomy_seeds.get(theme_id):
            members_by_theme[theme_id] = _members(
                {"related_symbols": _seed_items(taxonomy_seeds[theme_id], flows_dir)}, None
            )

    raw_rows: dict[str, list[tuple[str, float, float, float, float]]] = {}
    for members in members_by_theme.values():
        for member in members:
            instrument_id = member["instrument_id"]
            if instrument_id in raw_rows:
                continue
            path = _flow_path(flows_dir, instrument_id)
            raw_rows[instrument_id] = _series(_read_json(path)) if path else []
    as_of = _market_as_of(raw_rows.values())
    flows = {key: summarize_flow(rows, as_of) for key, rows in raw_rows.items()}
    scores = _watch_scores(watchlist)

    themes_out: list[dict[str, Any]] = []
    for theme in themes_in:
        theme_id = str(theme.get("theme_id"))
        heat = _number(theme.get("heat_score")) or 0.0
        stocks: list[dict[str, Any]] = []
        for member in members_by_theme[theme_id]:
            flow = flows.get(member["instrument_id"])
            stocks.append({**member, "flow": flow, **scores.get(member["instrument_id"], {})})
        with_flow = [stock for stock in stocks if stock["flow"]]
        positive = [stock for stock in with_flow if stock["flow"]["total_5d"] > 0]
        breadth = round(len(positive) / len(with_flow), 3) if with_flow else None
        total_5d = sum(stock["flow"]["total_5d"] for stock in with_flow)
        foreign_5d = sum(stock["flow"]["foreign_5d"] for stock in with_flow)
        trust_5d = sum(stock["flow"]["trust_5d"] for stock in with_flow)
        total_1d = sum(stock["flow"]["total_1d"] for stock in with_flow)

        # Largest 5-day net buying first, with a stock the news names directly
        # weighted 3x: a named stock with real buying is the most explainable
        # pick, but a token +100 lots should not outrank a broad accumulation.
        leaders = sorted(
            positive,
            key=lambda stock: stock["flow"]["total_5d"] * (DIRECT_WEIGHT if stock["relation"] == "direct" else 1),
            reverse=True,
        )
        outflows = sorted(
            [stock for stock in with_flow if stock["flow"]["total_5d"] < 0],
            key=lambda stock: stock["flow"]["total_5d"],
        )
        stance = classify(heat, breadth)
        news = theme.get("representative_news") if isinstance(theme.get("representative_news"), Mapping) else {}
        themes_out.append({
            "theme_id": theme_id,
            "name_zh": str(theme.get("name_zh") or theme_id),
            "rank": theme.get("rank"),
            "heat_score": heat,
            "momentum_score": _number(theme.get("momentum_score")),
            "lifecycle_stage": theme.get("lifecycle_stage"),
            "event_count": theme.get("event_count"),
            "stance": stance,
            "stance_label": STANCES[stance],
            "focus_score": focus_score(heat, breadth),
            "flow": {
                "member_count": len(stocks),
                "covered_count": len(with_flow),
                "positive_count": len(positive),
                "breadth": breadth,
                "total_5d": total_5d,
                "foreign_5d": foreign_5d,
                "trust_5d": trust_5d,
                "total_1d": total_1d,
            },
            "leaders": leaders[:TOP_STOCKS],
            "outflows": outflows[:OUTFLOW_STOCKS],
            "headline": {
                "title": news.get("title_zh") or news.get("title"),
                "source": news.get("source"),
                "published_at": news.get("published_at"),
                "url": news.get("canonical_url") or news.get("url"),
            } if news else None,
        })

    themes_out.sort(key=lambda item: (item["focus_score"], item["heat_score"]), reverse=True)
    for index, item in enumerate(themes_out, start=1):
        item["focus_rank"] = index

    stamp = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": stamp.isoformat().replace("+00:00", "Z"),
        "theme_generated_at": momentum.get("generated_at"),
        "flow_as_of": as_of,
        "flow_window_days": FLOW_WINDOW_DAYS,
        "unit": "lots",
        "flow_source": "TWSE T86 / TPEX 三大法人買賣超（官方）",
        "method": {
            "focus_score": "0.5 × 新聞熱度 + 0.5 × 法人 5 日買超家數占比 × 100",
            "hot_heat": HOT_HEAT,
            "broad_breadth": BROAD_BREADTH,
            "weak_breadth": WEAK_BREADTH,
        },
        "themes": themes_out,
    }


def write_theme_focus(data_dir: Path, payload: Mapping[str, Any]) -> Path:
    path = data_dir / OUTPUT_FILE
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def _load_taxonomy_seeds() -> dict[str, list[str]]:
    """Runtime-expanded taxonomy seeds; empty (no fallback) if it cannot load."""
    try:
        try:
            from scripts.theme_relevance import load_theme_taxonomy
        except ModuleNotFoundError:
            from theme_relevance import load_theme_taxonomy
        taxonomy = load_theme_taxonomy()
    except Exception as error:  # noqa: BLE001 - the fallback is optional
        LOGGER.warning("theme_focus_seed_fallback_unavailable error=%s", error)
        return {}
    return {
        str(theme.get("theme_id")): [str(code) for code in theme.get("seed_symbols") or []]
        for theme in taxonomy.get("themes", [])
        if isinstance(theme, Mapping)
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", default="data", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    payload = build_theme_focus(args.data_dir, taxonomy_seeds=_load_taxonomy_seeds())
    if not payload["themes"]:
        LOGGER.warning("theme_focus_skipped reason=no_themes")
        return 0
    path = write_theme_focus(args.data_dir, payload)
    LOGGER.info(
        "theme_focus_written path=%s themes=%d flow_as_of=%s",
        path, len(payload["themes"]), payload["flow_as_of"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
