#!/usr/bin/env python3
"""Maintainer probe for RSS sources: reachability, conditional-GET support,
and a single-snapshot duplicate rate against the active sources.

Not part of the hourly run. It exists so a source change can be checked from
CI (`.github/workflows/probe-rss-sources.yml`) when the editing environment
has no outbound network. The snapshot duplicate rate is an early signal only;
the acceptance number comes from the 7-day intake store:

    python scripts/evaluate_source_overlap.py --candidate-from-baseline \\
        --baseline data/source-intake-7d.json --site-id <id> --source-name <name>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import feedparser
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluate_source_overlap import evaluate_source_overlap  # noqa: E402

USER_AGENT = "TaiwanEquityThemeRadar/0.1 (+https://github.com/)"


def _published(entry: Any) -> str | None:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=UTC).isoformat().replace("+00:00", "Z")


def probe(source_id: str, name: str, url: str, role: str) -> dict[str, Any]:
    result: dict[str, Any] = {"source_id": source_id, "name": name, "url": url, "role": role}
    try:
        response = requests.get(url, timeout=25, headers={"User-Agent": USER_AGENT})
        result.update(
            http=response.status_code,
            final_url=response.url,
            content_type=response.headers.get("Content-Type"),
            bytes=len(response.content),
            etag=response.headers.get("ETag"),
            last_modified=response.headers.get("Last-Modified"),
        )
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        entries = list(parsed.entries)
        stamps = sorted(stamp for entry in entries if (stamp := _published(entry)))
        result.update(
            entries=len(entries),
            bozo=bool(getattr(parsed, "bozo", False)),
            oldest=stamps[0] if stamps else None,
            newest=stamps[-1] if stamps else None,
            sample_titles=[str(getattr(entry, "title", ""))[:80] for entry in entries[:3]],
            items=[
                {
                    "site_id": source_id,
                    "site_name": name,
                    "title": str(getattr(entry, "title", "") or ""),
                    "url": str(getattr(entry, "link", "") or ""),
                    "published_at": _published(entry),
                }
                for entry in entries
                if getattr(entry, "title", None) and getattr(entry, "link", None)
            ],
        )
        conditional: dict[str, str] = {}
        if result["etag"]:
            conditional["If-None-Match"] = result["etag"]
        if result["last_modified"]:
            conditional["If-Modified-Since"] = result["last_modified"]
        if conditional:
            again = requests.get(url, timeout=25, headers={"User-Agent": USER_AGENT, **conditional})
            result["conditional_http"] = again.status_code
        result["ok"] = bool(entries)
    except Exception as exc:  # noqa: BLE001 - a probe reports, never raises
        result["ok"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", default=str(ROOT / "config" / "source_registry.tw.json"))
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        metavar="ID=URL",
        help="Extra candidate feed to probe (repeatable); not added to the registry",
    )
    parser.add_argument("--output", default="", help="Optional JSON report path")
    args = parser.parse_args()

    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    targets: list[tuple[str, str, str, str]] = []
    for source in registry["sources"]:
        if source.get("fetch_method") == "rss" and source.get("feed_url") and source.get("status") in {"active", "trial"}:
            role = "baseline" if source["status"] == "active" else "candidate"
            targets.append((source["source_id"], source.get("name") or source["source_id"], source["feed_url"], role))
    for spec in args.url:
        source_id, _, url = spec.partition("=")
        targets.append((source_id, source_id, url, "candidate"))

    results = [probe(*target) for target in targets]
    baseline = [item for result in results if result["role"] == "baseline" for item in result.get("items", [])]
    now = datetime.now(UTC)
    for result in results:
        if result["role"] != "candidate" or not result.get("items"):
            continue
        report = evaluate_source_overlap(
            result["items"],
            baseline,
            candidate={"site_id": result["source_id"], "site_name": result["name"], "url": result["url"]},
            generated_at=now,
            lookback_days=7,
        )
        result["snapshot_overlap"] = {
            **report["overlap"],
            "decision": report["recommendation"]["decision"],
            "top_overlapping_sources": report["top_overlapping_sources"][:3],
            "sample_matches": [
                {"candidate": match["candidate_title"], "matched": match["matched_title"], "score": match["score"]}
                for match in report["matches"][:3]
            ],
        }

    lines = [
        "| source | role | ok | http | entries | newest | ETag | Last-Modified | conditional | snapshot dup | decision |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        overlap = r.get("snapshot_overlap") or {}
        lines.append(
            f"| {r['source_id']} | {r['role']} | {'✅' if r.get('ok') else '❌'} | {r.get('http', '-')} "
            f"| {r.get('entries', '-')} | {r.get('newest') or '-'} | {'yes' if r.get('etag') else 'no'} "
            f"| {'yes' if r.get('last_modified') else 'no'} | {r.get('conditional_http', '-')} "
            f"| {overlap.get('duplicate_rate', '-')} | {overlap.get('decision', '-')} |"
        )
    table = "\n".join(lines)
    print(table)
    for r in results:
        slim = {key: value for key, value in r.items() if key != "items"}
        print(json.dumps(slim, ensure_ascii=False))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("## RSS source probe\n\n" + table + "\n")
    if args.output:
        Path(args.output).write_text(
            json.dumps([{k: v for k, v in r.items() if k != "items"} for r in results], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
