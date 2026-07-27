"""Generate deterministic static MVP data from local sample records."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.theme_relevance import enrich_item_with_themes, load_theme_taxonomy
except ModuleNotFoundError:
    from theme_relevance import enrich_item_with_themes, load_theme_taxonomy


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_PATH = ROOT / "samples" / "theme_records.tw.json"
DEFAULT_OUTPUT_DIR = ROOT / "data"


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _payload(
    *,
    items: list[dict[str, Any]],
    available_count: int,
    generated_at: datetime,
    window_hours: int,
    max_items: int,
    market_id: str,
    market_scope: list[str],
) -> dict[str, Any]:
    return {
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "market_id": market_id,
        "market_scope": market_scope,
        "window_hours": window_hours,
        "max_items": max_items,
        "total_items": len(items),
        "total_items_available": available_count,
        "items": items,
    }


def build_demo_payloads(
    records: list[dict[str, Any]],
    taxonomy: dict[str, Any],
    *,
    now: datetime,
    window_hours: int,
    max_events: int,
    max_candidates: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build bounded theme-event and tracking-candidate payloads."""

    if window_hours <= 0 or max_events <= 0 or max_candidates <= 0:
        raise ValueError("window and item bounds must be positive")
    anchor = now.astimezone(timezone.utc)
    cutoff = anchor - timedelta(hours=window_hours)
    in_window = [
        record
        for record in records
        if record.get("published_at")
        and cutoff <= parse_timestamp(str(record["published_at"])) <= anchor
    ]
    in_window.sort(
        key=lambda record: (
            -parse_timestamp(str(record["published_at"])).timestamp(),
            str(record.get("id") or record.get("url") or ""),
        )
    )
    enriched = [
        enrich_item_with_themes(record, taxonomy)
        for record in in_window
    ]
    matched = [item for item in enriched if item["matched_themes"]]
    candidates = [
        {
            **item,
            "tracking_reason": item["matched_themes"][0]["reason"],
        }
        for item in matched
        if item["theme_score"] >= 0.5
    ]
    event_items = matched[:max_events]
    candidate_items = candidates[:max_candidates]
    market_id = str(taxonomy.get("market_id") or "TW_EQUITY")
    market_scope = list(taxonomy.get("market_scope") or [market_id])
    return (
        _payload(
            items=event_items,
            available_count=len(matched),
            generated_at=anchor,
            window_hours=window_hours,
            max_items=max_events,
            market_id=market_id,
            market_scope=market_scope,
        ),
        _payload(
            items=candidate_items,
            available_count=len(candidates),
            generated_at=anchor,
            window_hours=window_hours,
            max_items=max_candidates,
            market_id=market_id,
            market_scope=market_scope,
        ),
    )


def load_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("sample input must be an array or an object with an items array")
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--taxonomy", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--window-hours", type=int, default=48)
    parser.add_argument("--max-events", type=int, default=50)
    parser.add_argument("--max-candidates", type=int, default=20)
    parser.add_argument(
        "--now",
        help="UTC/ISO window anchor; defaults to the newest sample timestamp",
    )
    args = parser.parse_args()

    records = load_records(args.input)
    if not records:
        raise ValueError("sample input must contain at least one record")
    anchor = (
        parse_timestamp(args.now)
        if args.now
        else max(parse_timestamp(str(record["published_at"])) for record in records)
    )
    taxonomy = load_theme_taxonomy(args.taxonomy) if args.taxonomy else load_theme_taxonomy()
    events, candidates = build_demo_payloads(
        records,
        taxonomy,
        now=anchor,
        window_hours=args.window_hours,
        max_events=args.max_events,
        max_candidates=args.max_candidates,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for filename, payload in (
        ("theme-events.json", events),
        ("tracking-candidates.json", candidates),
    ):
        target = args.output_dir / filename
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {target} ({payload['total_items']} items)")


if __name__ == "__main__":
    main()
