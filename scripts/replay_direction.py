#!/usr/bin/env python3
"""Replay the direction model over every committed pre-market snapshot.

Reads each historical version of data/pre-market-latest.json from git, dedupes
events by English title, and reports what the page showed before the direction
model (one risk-framed list) against what it shows now (bull / bear / neutral
per path). Also scores the undated translation cache, which holds every wire
headline the board has ever translated, for a wider distribution check.

    python scripts/replay_direction.py --output reports/direction/replay-direction-v1.md
"""

from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:  # pragma: no cover
    from scripts.event_direction import RULE_VERSION, assess, label_of
    from scripts.geo_focus import PATH_ID_BY_LABEL, is_noise, match_paths
except ModuleNotFoundError:  # pragma: no cover
    from event_direction import RULE_VERSION, assess, label_of
    from geo_focus import PATH_ID_BY_LABEL, is_noise, match_paths

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = "data/pre-market-latest.json"
CACHE = "data/pre-market-title-zh.json"
MODELLED = ("fed_rates", "tariff", "export_control")
TAIPEI = timezone(timedelta(hours=8))


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def historical_events() -> tuple[dict[str, dict], list[str]]:
    shas = _git("log", "--format=%H", "--", SNAPSHOT).split()
    events: dict[str, dict] = {}
    for sha in reversed(shas):
        try:
            payload = json.loads(_git("show", f"{sha}:{SNAPSHOT}"))
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        for event in payload.get("events", []):
            key = event.get("titleEn")
            if key:
                events[key] = event
    return events, shas


def taipei_day(stamp: str) -> str:
    try:
        moment = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return "unknown"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(TAIPEI).date().isoformat()


def build_report() -> str:
    events, shas = historical_events()
    rows = []
    for title, event in events.items():
        path_id = event.get("pathId") or PATH_ID_BY_LABEL.get(event.get("pathLabel", ""), "")
        result = assess(title, path_id)
        rows.append({
            "day": taipei_day(event.get("publishedAt", "")),
            "tier": event.get("tier", "normal"),
            "path": path_id,
            "titleZh": event.get("titleZh", title),
            "title": title,
            "direction": result.direction,
            "reason": result.reason,
        })
    rows.sort(key=lambda r: (r["day"], r["path"]))
    days = sorted({r["day"] for r in rows})

    out: list[str] = []
    out.append(f"# 方向模型回放報告（{RULE_VERSION}）\n")
    out.append(f"產生時間：{datetime.now(TAIPEI):%Y-%m-%d %H:%M} 台北\n")
    out.append(
        f"資料：`{SNAPSHOT}` 的 {len(shas)} 個歷史版本（git），去重後 {len(rows)} 則事件，"
        f"涵蓋 {days[0] if days else '-'} ~ {days[-1] if days else '-'}（{len(days)} 天，台北日期）。\n"
    )
    out.append(
        "> **限制**：盤前看板自 2026-11-13 才開始 commit 快照，git 內只有約 5–6 天。"
        "Issue 要求的 ≥14 天回放需等快照累積（或取得 Actions 環境的 `pre-market-archive/`）後重跑本腳本："
        "`python scripts/replay_direction.py`。下方另以翻譯快取（全部歷史標題、無日期）補充分佈檢查。\n"
    )

    out.append("## 改判前後：每日統計\n")
    out.append("改判前：所有事件都在同一個風險清單（重大/留意），沒有利多欄。改判後：三條已建模路徑拆成利多/利空/中性。\n")
    out.append("| 日期 | 全部事件 | 三路徑事件 | 利多 | 利空 | 中性 | 改判前利多欄 |")
    out.append("|---|---:|---:|---:|---:|---:|---:|")
    for day in days:
        today = [r for r in rows if r["day"] == day]
        modelled = [r for r in today if r["path"] in MODELLED]
        counts = collections.Counter(r["direction"] for r in modelled)
        out.append(f"| {day} | {len(today)} | {len(modelled)} | {counts[1]} | {counts[-1]} | {counts[0]} | 0 |")
    out.append("")

    out.append("## 各路徑分佈\n")
    out.append("| 路徑 | 利多 | 利空 | 中性 | 中性原因前三 |")
    out.append("|---|---:|---:|---:|---|")
    for path in MODELLED:
        subset = [r for r in rows if r["path"] == path]
        counts = collections.Counter(r["direction"] for r in subset)
        reasons = collections.Counter(r["reason"].split(":")[0] if r["direction"] == 0 else "" for r in subset)
        top = ", ".join(f"{k} ×{v}" for k, v in reasons.most_common() if k)[:120]
        out.append(f"| {path} | {counts[1]} | {counts[-1]} | {counts[0]} | {top} |")
    out.append("")

    out.append("## 改判明細（方向 ≠ 0 的事件）\n")
    out.append("改判前這些事件全部以風險卡呈現；改判後依方向進入利多或利空欄。\n")
    out.append("| 日期 | 層級 | 路徑 | 方向 | 標題 | 命中規則 |")
    out.append("|---|---|---|---|---|---|")
    for r in rows:
        if r["path"] in MODELLED and r["direction"] != 0:
            reason = r["reason"].replace("|", "/")
            title = r["titleZh"].replace("|", "/")
            out.append(f"| {r['day']} | {r['tier']} | {r['path']} | {label_of(r['direction'])} | {title} | `{reason}` |")
    out.append("")

    cache = json.loads((ROOT / CACHE).read_text(encoding="utf-8"))
    dist: dict[str, collections.Counter] = {p: collections.Counter() for p in MODELLED}
    for title in cache:
        if is_noise(title):
            continue
        paths = match_paths(title)
        if not paths:
            continue
        path = max(paths, key=lambda p: p["weight"])["id"]
        if path in dist:
            dist[path][assess(title, path).direction] += 1
    out.append("## 補充：翻譯快取全量分佈（無日期）\n")
    out.append(f"`{CACHE}` 共 {len(cache)} 則標題；落在三條已建模路徑者：\n")
    out.append("| 路徑 | 總數 | 利多 | 利空 | 中性 |")
    out.append("|---|---:|---:|---:|---:|")
    for path, counts in dist.items():
        out.append(f"| {path} | {sum(counts.values())} | {counts[1]} | {counts[-1]} | {counts[0]} |")
    out.append("")
    out.append(
        "中性比例高是刻意的：規則只在有明確動作（降息/升息、加徵/暫緩、收緊/放寬）且通過範圍閘門時才下判斷，"
        "否則留 0，不硬猜。Fed 路徑偏空反映 2026 下半年 Fed 處於升息循環的實際語境。\n"
    )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "direction" / "replay-direction-v1.md")
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_report(), encoding="utf-8")
    print(f"wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
