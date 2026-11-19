#!/usr/bin/env python3
"""Replay the direction model over every committed pre-market snapshot.

Reads each historical version of data/pre-market-latest.json from git, dedupes
events by English title, and compares two rule versions day by day:

* before: direction-v1 (issue #9, three paths), loaded from git so the
  comparison does not depend on keeping old code around;
* after:  the current RULE_VERSION, with the path re-matched by the current
  geo_focus table so the new positive paths (issue #11) get their chance.

It also answers the issue #11 acceptance question directly: on days the market
closed up, is the 利多 column still empty? The market side comes from the
TAIEX daily change in data/market/taiex-daily.json (TWSE FMTQIK).

    python scripts/replay_direction.py --output reports/direction/replay-direction-v2.md
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

try:  # pragma: no cover
    from scripts.event_direction import RULE_VERSION, assess, label_of
    from scripts.geo_focus import PATH_ID_BY_LABEL, is_noise, match_paths
except ModuleNotFoundError:  # pragma: no cover
    from event_direction import RULE_VERSION, assess, label_of
    from geo_focus import PATH_ID_BY_LABEL, is_noise, match_paths

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = "data/pre-market-latest.json"
CACHE = "data/pre-market-title-zh.json"
TAIPEI = timezone(timedelta(hours=8))
V1_COMMIT = "e0a9fbd1"  # PR #20, direction-v1
MARKET = "data/market/taiex-daily.json"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def load_v1() -> ModuleType | None:
    try:
        source = _git("show", f"{V1_COMMIT}:scripts/event_direction.py")
    except subprocess.CalledProcessError:
        return None
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
        handle.write(source)
    spec = importlib.util.spec_from_file_location("event_direction_v1", handle.name)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


def to_taipei(stamp: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(TAIPEI)


def read_snapshots() -> tuple[dict[str, dict], int]:
    """Return (events by title, versions read)."""
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
    return events, len(shas)


def build_rows(events: dict[str, dict], v1: ModuleType | None) -> list[dict[str, Any]]:
    rows = []
    for title, event in events.items():
        published = to_taipei(event.get("publishedAt"))
        if published is None:
            continue
        old_path = event.get("pathId") or PATH_ID_BY_LABEL.get(event.get("pathLabel", ""), "")
        paths = match_paths(title)
        new_path = max(paths, key=lambda p: p["weight"])["id"] if paths else old_path
        before = v1.assess(title, old_path) if v1 else None
        after = assess(title, new_path)
        rows.append({
            "day": published.date().isoformat(),
            "tier": event.get("tier", "normal"),
            "old_path": old_path,
            "path": new_path,
            "titleZh": event.get("titleZh", title),
            "title": title,
            "before": before.direction if before else 0,
            "direction": after.direction,
            "reason": after.reason,
        })
    rows.sort(key=lambda r: (r["day"], r["path"]))
    return rows


def _cell(text: str) -> str:
    return str(text).replace("|", "/")


def load_market(path: Path) -> dict[str, float]:
    """TAIEX daily % change by date, from data/market/taiex-daily.json."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {row["date"]: float(row["pct"]) for row in payload.get("rows", [])
            if isinstance(row, dict) and isinstance(row.get("pct"), (int, float))}


def build_report(window_days: int = 21, market_file: Path = ROOT / MARKET) -> str:
    events, versions = read_snapshots()
    market = load_market(market_file)
    v1 = load_v1()
    rows = build_rows(events, v1)
    all_days = sorted({r["day"] for r in rows})
    if not all_days:
        return "# 方向模型回放報告\n\n沒有可回放的快照。\n"
    last = datetime.fromisoformat(all_days[-1]).date()
    window = [d for d in all_days if datetime.fromisoformat(d).date() > last - timedelta(days=window_days)]

    out: list[str] = []
    out.append(f"# 方向模型回放報告（{RULE_VERSION}）\n")
    out.append(f"產生時間：{datetime.now(TAIPEI):%Y-%m-%d %H:%M} 台北\n")
    out.append(
        f"資料：`{SNAPSHOT}` 的 {versions} 個歷史版本（git），去重後 {len(rows)} 則事件，"
        f"涵蓋 {all_days[0]} ~ {all_days[-1]}（{len(all_days)} 個台北日期）。"
        f"下表取最近 {window_days} 天（{window[0]} ~ {window[-1]}）。\n"
    )
    out.append(
        "- 改判前 = direction-v1（#9，只有 Fed / 關稅 / 出口管制三條路徑），從 git 載入原始規則重算。\n"
        f"- 改判後 = {RULE_VERSION}（#11，全部路徑 + 正向路徑；路徑以目前 geo_focus 重新比對）。\n"
        f"- 大盤 = 加權指數當日漲跌幅（TWSE FMTQIK，`{MARKET}`）。盤前快照裡的類股/國際指數自 8 月起是"
        "報價源失敗後沿用的舊值，不能當大盤錨點（#10 已改用官方來源）。\n"
    )

    out.append("## 每日：改判前後的利多 / 利空欄\n")
    out.append("| 日期 | 加權指數 | 事件 | 改判前 利多 | 改判前 利空 | 改判後 利多 | 改判後 利空 | 上漲日利多欄 |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---|")
    up_day_empty_before = up_day_empty_after = up_days = 0
    recent_up_empty: list[str] = []
    recent_cut = last - timedelta(days=7)
    for day in window:
        today = [r for r in rows if r["day"] == day]
        before = collections.Counter(r["before"] for r in today)
        after = collections.Counter(r["direction"] for r in today)
        proxy = market.get(day)
        flag = "—"
        if proxy is not None and proxy > 0:
            up_days += 1
            up_day_empty_before += before[1] == 0
            up_day_empty_after += after[1] == 0
            flag = "空" if after[1] == 0 else f"有（{after[1]}）"
            if after[1] == 0 and datetime.fromisoformat(day).date() > recent_cut:
                recent_up_empty.append(day)
        proxy_text = f"{proxy:+.2f}%" if proxy is not None else "休市/無資料"
        out.append(f"| {day} | {proxy_text} | {len(today)} | {before[1]} | {before[-1]} | "
                   f"{after[1]} | {after[-1]} | {flag} |")
    out.append("")
    out.append(
        f"**上漲日利多欄為空**：改判前 {up_day_empty_before}/{up_days} 天，改判後 {up_day_empty_after}/{up_days} 天。"
        f"近 7 天上漲日仍為空：{', '.join(recent_up_empty) if recent_up_empty else '無'}。\n"
    )

    out.append("## 各路徑分佈（改判後，回放視窗）\n")
    out.append("| 路徑 | 利多 | 利空 | 中性 | 中性原因前三 |")
    out.append("|---|---:|---:|---:|---|")
    windowed = [r for r in rows if r["day"] in window]
    for path in sorted({r["path"] for r in windowed}):
        subset = [r for r in windowed if r["path"] == path]
        counts = collections.Counter(r["direction"] for r in subset)
        reasons = collections.Counter(r["reason"].split(":")[0] for r in subset if r["direction"] == 0)
        top = ", ".join(f"{k} ×{v}" for k, v in reasons.most_common(3))
        out.append(f"| {path} | {counts[1]} | {counts[-1]} | {counts[0]} | {_cell(top)} |")
    out.append("")

    out.append("## 改判明細（回放視窗內方向有變的事件）\n")
    out.append("| 日期 | 層級 | 路徑 | 改判前 | 改判後 | 標題 | 命中規則 |")
    out.append("|---|---|---|---|---|---|---|")
    for r in windowed:
        if r["before"] != r["direction"]:
            path = r["path"] if r["path"] == r["old_path"] else f"{r['old_path']}→{r['path']}"
            out.append(f"| {r['day']} | {r['tier']} | {path} | {label_of(r['before'])} | "
                       f"{label_of(r['direction'])} | {_cell(r['titleZh'])} | `{_cell(r['reason'])}` |")
    out.append("")

    cache = json.loads((ROOT / CACHE).read_text(encoding="utf-8"))
    dist: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for title in cache:
        if is_noise(title):
            continue
        paths = match_paths(title)
        if paths:
            path = max(paths, key=lambda p: p["weight"])["id"]
            dist[path][assess(title, path).direction] += 1
    out.append("## 補充：翻譯快取全量分佈（無日期）\n")
    out.append(f"`{CACHE}` 共 {len(cache)} 則標題：\n")
    out.append("| 路徑 | 總數 | 利多 | 利空 | 中性 |")
    out.append("|---|---:|---:|---:|---:|")
    for path in sorted(dist):
        counts = dist[path]
        out.append(f"| {path} | {sum(counts.values())} | {counts[1]} | {counts[-1]} | {counts[0]} |")
    out.append("")
    out.append(
        "中性比例高是刻意的：規則只在有明確動作且通過範圍閘門時才下判斷，否則留 0，不硬猜。"
        "俄烏例行攻擊、紅海以外的黑海航運、非台幣的匯率、1% 以內的油價結算都被閘門擋在中性。\n"
    )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "reports" / "direction" / f"replay-{RULE_VERSION}.md")
    parser.add_argument("--window-days", type=int, default=21)
    parser.add_argument("--market-file", type=Path, default=ROOT / MARKET)
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_report(args.window_days, args.market_file), encoding="utf-8")
    print(f"wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
