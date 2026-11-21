#!/usr/bin/env python3
"""Path backtest: does a transmission path actually move Taiwan stocks? (issue #12)

For every (event x sector) the direction model calls on a path, measure what
the market did afterwards:

* excess return T+1 / T+5: sector index return minus TAIEX return, compounded
  over the k trading days after the base close. For 大盤全體 the TAIEX return
  itself is used (its excess would always be 0).
* foreign net T+1 / T+3: foreign net buy/sell of the sector's member stocks,
  summed over the same days, in 張.

The base close is the last close the event could not have moved: the event's
own trading day if it was published after the 13:30 close, otherwise the
previous trading day. A hit is a signed call (event direction x the sector's
multiplier) with the same sign as the measured move; zero moves are not hits.

The logic is path-agnostic: ``--path all`` or any PATH_RULES id. Sectors the
TWSE index board cannot represent (黃金相關, 航太國防, ...) are listed as
unmapped instead of being approximated.

    python scripts/backtest_path.py --data-dir data --path fed_rates --path all
"""

from __future__ import annotations

import argparse
import bisect
import json
import logging
import os
import statistics
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:  # pragma: no cover
    from scripts.event_direction import PATH_RULES, RULE_VERSION, assess
    from scripts.sector_history import HISTORY_FILE, TAIEX_KEY, load_history
except ModuleNotFoundError:  # pragma: no cover
    from event_direction import PATH_RULES, RULE_VERSION, assess
    from sector_history import HISTORY_FILE, TAIEX_KEY, load_history

LOGGER = logging.getLogger("backtest_path")

TAIPEI = timezone(timedelta(hours=8))
MARKET_CLOSE = time(13, 30)
EVENT_HISTORY = "event-history.json"
RESULT_FILE = "path-backtest.json"
RETURN_HORIZONS = (1, 5)
FLOW_HORIZONS = (1, 3)
MIN_SAMPLE = 5  # below this the UI shows the count but no hit rate
RECENT_OUTCOMES = 400

ELECTRONICS = ("半導體業", "電子零組件業", "光電業", "電腦及週邊設備業", "其他電子業",
               "通信網路業", "電子通路業", "資訊服務業")
ALL_MARKET = "*"

# Path sector name -> (TWSE index short name, registry industries for flows).
SECTOR_TARGETS: dict[str, tuple[str, tuple[str, ...]]] = {
    "大盤全體": (TAIEX_KEY, (ALL_MARKET,)),
    "權值股": (TAIEX_KEY, (ALL_MARKET,)),
    "科技股全體": ("電子工業", ELECTRONICS),
    "電子權值股": ("電子工業", ELECTRONICS),
    "電子出口股": ("電子工業", ELECTRONICS),
    "個股及供應鏈": ("電子工業", ELECTRONICS),
    "半導體": ("半導體", ("半導體業",)),
    "IC設計": ("半導體", ("半導體業",)),
    "AI伺服器": ("電腦及週邊設備", ("電腦及週邊設備業",)),
    "電子代工": ("電腦及週邊設備", ("電腦及週邊設備業",)),
    "散熱": ("電子零組件", ("電子零組件業",)),
    "PCB": ("電子零組件", ("電子零組件業",)),
    "電子零組件": ("電子零組件", ("電子零組件業",)),
    "光通訊": ("通信網路", ("通信網路業",)),
    "金融": ("金融保險", ("金融保險",)),
    "壽險": ("金融保險", ("金融保險",)),
    "航運": ("航運", ("航運業",)),
    "貨櫃航運": ("航運", ("航運業",)),
    "散裝航運": ("航運", ("航運業",)),
    "航空貨運": ("航運", ("航運業",)),
    "油電燃氣": ("油電燃氣", ("油電燃氣業",)),
    "塑化": ("塑膠", ("塑膠工業",)),
    "紡織": ("紡織纖維", ("紡織纖維",)),
    "鋼鐵": ("鋼鐵", ("鋼鐵工業",)),
    "工具機": ("電機機械", ("電機機械",)),
    "水泥": ("水泥", ("水泥工業",)),
    "觀光": ("觀光餐旅", ("觀光餐旅",)),
    "汽車零組件": ("汽車", ("汽車工業",)),
    "綠能": ("綠能環保", ("綠能環保",)),
}


# --- event history ------------------------------------------------------------

def _event_key(event: Mapping[str, Any]) -> str:
    return " ".join(str(event.get("titleEn") or "").split())


def merge_event_history(history: Mapping[str, Any], events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Append new pre-market events (by English title); first sighting wins."""
    rows = {_event_key(row): row for row in history.get("events") or [] if _event_key(row)}
    added = 0
    for event in events:
        key = _event_key(event)
        if not key or key in rows or not event.get("publishedAt") or not event.get("pathId"):
            continue
        rows[key] = {"id": event.get("id"), "publishedAt": event["publishedAt"],
                     "titleEn": key, "pathId": event["pathId"]}
        added += 1
    ordered = sorted(rows.values(), key=lambda row: (str(row["publishedAt"]), row["titleEn"]))
    return {"schema_version": 1, "events": ordered, "added": added}


def load_event_history(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "events": []}


def write_event_history(path: Path, history: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"schema_version": 1, "events": list(history.get("events") or [])}
    path.write_text(json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def seed_from_git() -> list[dict[str, Any]]:
    """Every event in the git history of data/pre-market-latest.json."""
    try:
        from scripts.replay_direction import read_snapshots
        from scripts.geo_focus import PATH_ID_BY_LABEL
    except ModuleNotFoundError:
        from replay_direction import read_snapshots
        from geo_focus import PATH_ID_BY_LABEL
    events, _ = read_snapshots()
    out = []
    for title, event in events.items():
        path = event.get("pathId") or PATH_ID_BY_LABEL.get(event.get("pathLabel", ""), "")
        out.append({**event, "titleEn": title, "pathId": path})
    return out


# --- calendar & measurements --------------------------------------------------

def _taipei(stamp: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(TAIPEI)


def base_index(calendar: list[str], published: datetime) -> int | None:
    """Index in ``calendar`` of the last close before the event."""
    day = published.date().isoformat()
    position = bisect.bisect_right(calendar, day)  # first trading day after `day`
    if position and calendar[position - 1] == day and published.time() < MARKET_CLOSE:
        position -= 1  # published before today's close: today's close is already "after"
    return position - 1 if position else None


def compound(pcts: Iterable[float]) -> float:
    value = 1.0
    for pct in pcts:
        value *= 1 + pct / 100
    return (value - 1) * 100


def measure(history: Mapping[str, Any], calendar: list[str], base: int, target: str) -> dict[str, float | None]:
    index_name, industries = SECTOR_TARGETS[target]
    indices = history["indices"]
    foreign = history["foreign_net"]
    out: dict[str, float | None] = {}
    for k in RETURN_HORIZONS:
        days = calendar[base + 1: base + 1 + k]
        value = None
        if len(days) == k and all(index_name in indices[d] and TAIEX_KEY in indices[d] for d in days):
            sector = compound(indices[d][index_name] for d in days)
            value = sector if index_name == TAIEX_KEY else sector - compound(indices[d][TAIEX_KEY] for d in days)
        out[f"excess_t{k}"] = None if value is None else round(value, 3)
    for k in FLOW_HORIZONS:
        days = calendar[base + 1: base + 1 + k]
        value = None
        if len(days) == k and all(d in foreign for d in days):
            value = sum(sum(foreign[d].values()) if industries == (ALL_MARKET,)
                        else sum(foreign[d].get(name, 0.0) for name in industries) for d in days)
        out[f"foreign_t{k}"] = None if value is None else round(value, 1)
    return out


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)


def build_outcomes(events: Iterable[Mapping[str, Any]], history: Mapping[str, Any],
                   paths: Iterable[str]) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    """One row per (event x called sector) with its measured follow-through."""
    calendar = sorted(history["indices"])
    wanted = set(paths)
    unmapped: dict[str, set[str]] = {}
    outcomes = []
    for event in events:
        path = str(event.get("pathId") or "")
        if path not in wanted:
            continue
        published = _taipei(event.get("publishedAt"))
        if published is None:
            continue
        result = assess(str(event.get("titleEn") or ""), path)
        if result.direction == 0:
            continue
        base = base_index(calendar, published)
        if base is None:
            continue
        for sector, signed in result.sectors.items():
            if signed == 0:
                continue
            if sector not in SECTOR_TARGETS:
                unmapped.setdefault(path, set()).add(sector)
                continue
            row = {
                "event_id": event.get("id"), "path_id": path, "target_id": sector,
                "published_at": published.isoformat(), "base_date": calendar[base],
                "title": event.get("titleEn"), "direction": signed, "reason": result.reason,
                **measure(history, calendar, base, sector),
            }
            outcomes.append(row)
    return outcomes, unmapped


def summarise(outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hit rate, average move and sample size per (path, target, metric, horizon)."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in outcomes:
        groups.setdefault((row["path_id"], row["target_id"]), []).append(row)
    out = []
    metrics = [("excess_return", k, f"excess_t{k}") for k in RETURN_HORIZONS] + \
              [("foreign_net", k, f"foreign_t{k}") for k in FLOW_HORIZONS]
    for (path, target), rows in sorted(groups.items()):
        for metric, horizon, field in metrics:
            sample = [(row["direction"], row[field]) for row in rows if row[field] is not None]
            if not sample:
                continue
            hits = sum(_sign(value) == direction for direction, value in sample)
            values = [value for _, value in sample]
            out.append({
                "path_id": path, "target_id": target, "metric": metric, "horizon_days": horizon,
                "sample_size": len(sample),
                "days": len({row["base_date"] for row in rows if row[field] is not None}),
                "hit_rate": round(hits / len(sample), 4),
                "avg_value": round(statistics.fmean(values), 3),
                # Direction-adjusted: positive = the market moved the way we called it.
                "avg_signed_value": round(statistics.fmean(d * v for d, v in sample), 3),
                "bull": sum(1 for d, _ in sample if d > 0),
                "bear": sum(1 for d, _ in sample if d < 0),
                "window_start": min(row["base_date"] for row in rows if row[field] is not None),
                "window_end": max(row["base_date"] for row in rows if row[field] is not None),
            })
    return out


def path_badges(summary: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per path: the primary sector's T+1 excess-return hit rate (shown next to the path)."""
    badges: dict[str, dict[str, Any]] = {}
    for path, rule in PATH_RULES.items():
        primary = rule.get("primary")
        if not primary or rule["sectors"].get(primary, 0) == 0:
            primary = next((s for s, m in rule["sectors"].items() if m and s in SECTOR_TARGETS), primary)
        rows = {(r["metric"], r["horizon_days"]): r for r in summary
                if r["path_id"] == path and r["target_id"] == primary}
        ret = rows.get(("excess_return", 1))
        if not ret:
            continue
        flow = rows.get(("foreign_net", 1))
        badges[path] = {
            "target": primary,
            "hitRate": ret["hit_rate"] if ret["sample_size"] >= MIN_SAMPLE else None,
            "n": ret["sample_size"],
            "avgSignedExcessT1": ret["avg_signed_value"],
            "foreignHitRateT1": flow["hit_rate"] if flow and flow["sample_size"] >= MIN_SAMPLE else None,
            "avgForeignT1": flow["avg_value"] if flow else None,
            "window": [ret["window_start"], ret["window_end"]],
        }
    return badges


def build_result(events: list[dict[str, Any]], history: Mapping[str, Any], paths: list[str],
                 now: datetime) -> dict[str, Any]:
    outcomes, unmapped = build_outcomes(events, history, paths)
    summary = summarise(outcomes)
    calendar = sorted(history["indices"])
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "rule_version": RULE_VERSION,
        "paths": paths,
        "calendar": {"start": calendar[0] if calendar else None, "end": calendar[-1] if calendar else None,
                     "trading_days": len(calendar),
                     "foreign_days": len(history["foreign_net"])},
        "event_count": len(events),
        "summary": summary,
        "badges": path_badges(summary),
        "unmapped": {path: sorted(names) for path, names in sorted(unmapped.items())},
        "outcomes": sorted(outcomes, key=lambda r: r["published_at"])[-RECENT_OUTCOMES:],
        "_all_outcomes": outcomes,
    }


# --- pre-market annotation ----------------------------------------------------

def attach_backtest(events: Iterable[dict[str, Any]], result: Mapping[str, Any]) -> int:
    """Put the path's historical hit rate and, once known, the event's own T+1
    foreign flow on each pre-market event. Returns how many got a flow.

    Both keys are removed when there is nothing to show, so a stale value from
    an earlier run cannot linger on a carried-over event.
    """
    badges = result.get("badges") or {}
    by_title: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in result.get("outcomes") or []:
        by_title[(" ".join(str(row.get("title") or "").split()), str(row.get("target_id")))] = row
    with_flow = 0
    for event in events:
        badge = badges.get(str(event.get("pathId") or ""))
        if badge:
            event["pathBacktest"] = dict(badge)
        else:
            event.pop("pathBacktest", None)
        target = (badge or {}).get("target")
        outcome = by_title.get((_event_key(event), str(target))) if target else None
        if outcome and outcome.get("foreign_t1") is not None:
            event["flowAfter"] = {"target": target, "baseDate": outcome["base_date"],
                                  "foreignT1": outcome["foreign_t1"], "excessT1": outcome.get("excess_t1")}
            with_flow += 1
        else:
            event.pop("flowAfter", None)
    return with_flow


# --- report -------------------------------------------------------------------

METRIC_LABEL = {"excess_return": "超額報酬 %", "foreign_net": "外資買賣超 張"}


def render_report(result: Mapping[str, Any]) -> str:
    cal = result["calendar"]
    lines = [f"# 路徑回測（{result['rule_version']}）\n",
             f"產生時間：{result['generated_at'][:16]} 台北\n",
             f"- 類股指數：TWSE MI_INDEX，{cal['start']} ~ {cal['end']}，{cal['trading_days']} 個交易日。",
             f"- 外資類股買賣超：data/flows 個股外資淨額依官方產業加總，{cal['foreign_days']} 個交易日。",
             f"- 事件：盤前看板歷史 {result['event_count']} 則，方向以目前規則重算。",
             "- 命中 = 方向（事件方向 × 類股乘數）與事後變動同號；0 不算命中。"
             "T+k 從事件前最後一個收盤起算（13:30 後的事件以當天收盤為基準）。\n"]
    for path in result["paths"]:
        rows = [r for r in result["summary"] if r["path_id"] == path]
        lines.append(f"## {path}\n")
        if not rows:
            lines.append("沒有可回測的樣本（無方向事件或資料區間未涵蓋）。\n")
            continue
        lines.append("| 類股 | 指標 | T+k | 樣本 | 交易日 | 命中率 | 平均值 | 方向調整平均 | 利多/利空 | 區間 |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|---|---|")
        for r in rows:
            lines.append(f"| {r['target_id']} | {METRIC_LABEL[r['metric']]} | {r['horizon_days']} | {r['sample_size']} | "
                         f"{r['days']} | {r['hit_rate']:.0%} | {r['avg_value']:+,.2f} | {r['avg_signed_value']:+,.2f} | "
                         f"{r['bull']}/{r['bear']} | {r['window_start']} ~ {r['window_end']} |")
        if result["unmapped"].get(path):
            lines.append(f"\n未對應到官方類股指數（不硬湊）：{', '.join(result['unmapped'][path])}")
        lines.append("")
    return "\n".join(lines) + "\n"


# --- DB -----------------------------------------------------------------------

PATH_BACKTEST_UPSERT_SQL = """
INSERT INTO radar.path_backtest (
  path_id, target_id, rule_version, metric, horizon_days, sample_size, trading_days,
  hit_rate, avg_value, avg_signed_value, window_start, window_end, computed_at
) VALUES (
  %(path_id)s, %(target_id)s, %(rule_version)s, %(metric)s, %(horizon_days)s, %(sample_size)s,
  %(days)s, %(hit_rate)s, %(avg_value)s, %(avg_signed_value)s, %(window_start)s, %(window_end)s,
  %(computed_at)s
)
ON CONFLICT (path_id, target_id, rule_version, metric, horizon_days) DO UPDATE SET
  sample_size = EXCLUDED.sample_size,
  trading_days = EXCLUDED.trading_days,
  hit_rate = EXCLUDED.hit_rate,
  avg_value = EXCLUDED.avg_value,
  avg_signed_value = EXCLUDED.avg_signed_value,
  window_start = EXCLUDED.window_start,
  window_end = EXCLUDED.window_end,
  computed_at = EXCLUDED.computed_at,
  updated_at = now()
""".strip()

EVENT_OUTCOME_UPSERT_SQL = """
INSERT INTO radar.event_outcome (
  event_id, target_id, rule_version, path_id, published_at, base_date, direction,
  excess_t1, excess_t5, foreign_t1, foreign_t3, computed_at
) VALUES (
  %(event_id)s, %(target_id)s, %(rule_version)s, %(path_id)s, %(published_at)s, %(base_date)s,
  %(direction)s, %(excess_t1)s, %(excess_t5)s, %(foreign_t1)s, %(foreign_t3)s, %(computed_at)s
)
ON CONFLICT (event_id, target_id, rule_version) DO UPDATE SET
  path_id = EXCLUDED.path_id,
  published_at = EXCLUDED.published_at,
  base_date = EXCLUDED.base_date,
  direction = EXCLUDED.direction,
  excess_t1 = EXCLUDED.excess_t1,
  excess_t5 = EXCLUDED.excess_t5,
  foreign_t1 = EXCLUDED.foreign_t1,
  foreign_t3 = EXCLUDED.foreign_t3,
  computed_at = EXCLUDED.computed_at,
  updated_at = now()
""".strip()


def db_rows(result: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    computed = result["generated_at"]
    rv = result["rule_version"]
    summary = [{**row, "rule_version": rv, "computed_at": computed} for row in result["summary"]]
    outcomes = [{**row, "rule_version": rv, "computed_at": computed}
                for row in result["_all_outcomes"] if row.get("event_id")]
    return summary, outcomes


def write_backtest(connection: Any, result: Mapping[str, Any]) -> dict[str, int]:
    summary, outcomes = db_rows(result)
    with connection.transaction():
        with connection.cursor() as cursor:
            if summary:
                cursor.executemany(PATH_BACKTEST_UPSERT_SQL, summary)
            if outcomes:
                cursor.executemany(EVENT_OUTCOME_UPSERT_SQL, outcomes)
    return {"summary_rows": len(summary), "outcome_rows": len(outcomes)}


def dual_write(result: Mapping[str, Any]) -> None:
    dsn = os.environ.get("THEME_RADAR_DATABASE_URL", "").strip()
    if not dsn:
        LOGGER.info("backtest_dual_write_skipped reason=no_database_url")
        return
    try:
        import psycopg

        try:
            from scripts.radar_store import redact_error
        except ModuleNotFoundError:
            from radar_store import redact_error
        with psycopg.connect(dsn, connect_timeout=15) as connection:
            counts = write_backtest(connection, result)
        LOGGER.info("backtest_dual_write_written summary=%d outcomes=%d",
                    counts["summary_rows"], counts["outcome_rows"])
    except Exception as exc:  # noqa: BLE001 - fail closed: JSON output is unaffected
        message = redact_error(exc) if "redact_error" in locals() else type(exc).__name__
        LOGGER.warning("backtest_dual_write_failed error=%s", message)


# --- CLI ----------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--path", action="append", dest="paths",
                        help="PATH_RULES id, repeatable; 'all' = every path (default fed_rates)")
    parser.add_argument("--seed-from-git", action="store_true",
                        help="Add every event from the git history of the pre-market snapshot")
    parser.add_argument("--report-dir", type=Path, default=Path("reports/backtest"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    requested = args.paths or ["fed_rates"]
    paths = list(PATH_RULES) if "all" in requested else [p for p in requested if p in PATH_RULES]
    unknown = [p for p in requested if p != "all" and p not in PATH_RULES]
    if unknown:
        parser.error(f"unknown path(s): {', '.join(unknown)}")

    backtest_dir = args.data_dir / "backtest"
    history_path = backtest_dir / EVENT_HISTORY
    event_history = load_event_history(history_path)
    incoming: list[Mapping[str, Any]] = []
    if args.seed_from_git:
        incoming.extend(seed_from_git())
    try:
        latest = json.loads((args.data_dir / "pre-market-latest.json").read_text(encoding="utf-8"))
        incoming.extend(latest.get("events") or [])
    except (OSError, json.JSONDecodeError):
        pass
    event_history = merge_event_history(event_history, incoming)
    write_event_history(history_path, event_history)

    sector = load_history(args.data_dir / "market" / HISTORY_FILE)
    if not sector["indices"]:
        LOGGER.warning("backtest_no_sector_history run scripts/sector_history.py first")
        return 0
    result = build_result(event_history["events"], sector, paths, datetime.now(TAIPEI))
    public = {key: value for key, value in result.items() if not key.startswith("_")}
    (backtest_dir / RESULT_FILE).write_text(
        json.dumps(public, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    args.report_dir.mkdir(parents=True, exist_ok=True)
    (args.report_dir / "path-backtest.md").write_text(render_report(result), encoding="utf-8")
    LOGGER.info("backtest_written paths=%s outcomes=%d summary=%d trading_days=%d",
                ",".join(paths), len(result["_all_outcomes"]), len(result["summary"]),
                result["calendar"]["trading_days"])
    dual_write(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
