"""Local half of the daily pre-market report (issue #8).

Runs on the user's own machine from a Claude scheduled task (~07:30 Taipei),
with a DB login that holds only ``radar_analyst``: it can read the day's list
and snapshots and write ``radar.analysis_report``, nothing else.

    pull    read today's list + snapshots into a work dir, plus an input file
            for scripts/analyze_stock_audit_technical.py (local PVA/Nexus)
    push    validate every reports/<symbol>.json and upsert them in one
            transaction; any invalid report aborts the whole push
    status  show which queued symbols already have a report

Credential: ``RADAR_ANALYST_DATABASE_URL`` (local env only, never committed).
Exit codes: 0 ok, 2 invalid reports, 3 no batch for the date, 4 no credential.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from scripts.radar_store import redact_error
except ModuleNotFoundError:
    from radar_store import redact_error


TAIPEI = ZoneInfo("Asia/Taipei")
DATABASE_URL_ENV = "RADAR_ANALYST_DATABASE_URL"

BIAS = ("bullish", "bearish", "neutral")
ACTIONABILITY = ("actionable", "wait_for_confirmation", "no_trade")
LEVEL_KINDS = ("support", "resistance", "trigger", "invalidation", "target")
REPORT_KEYS = frozenset({
    "symbol", "report_date", "data_as_of", "framework_version", "generated_at",
    "bias", "actionability", "conclusion", "market_structure", "key_levels",
    "primary_scenario", "alternative_scenario", "confirmation", "invalidation",
    "no_trade_warning", "news_context",
})
PRIMARY_KEYS = frozenset({"summary", "trigger", "entry_zone", "targets"})
ALTERNATIVE_KEYS = frozenset({"summary", "trigger"})
INVALIDATION_KEYS = frozenset({"price", "condition"})
LEVEL_KEYS = frozenset({"label", "price", "kind"})
# Anything that looks like model reasoning or detector debug output is refused
# wherever it appears; the reader UI must only ever show the final report.
FORBIDDEN_KEY_FRAGMENTS = (
    "thinking", "thought", "reasoning", "scratch", "debug", "trace", "log",
    "prompt", "raw", "detector",
)
TEXT_LIMITS = {
    "conclusion": 400, "market_structure": 600, "confirmation": 400,
    "no_trade_warning": 300, "news_context": 400,
}
PRICE_BAND = (0.5, 1.5)  # every price must sit within 50% of the snapshot close


class ReportError(ValueError):
    pass


def _finite_positive(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
    )


def _walk_keys(value: Any, path: str = "") -> list[str]:
    found = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in FORBIDDEN_KEY_FRAGMENTS):
                found.append(f"{path}{key}")
            found.extend(_walk_keys(child, f"{path}{key}."))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_walk_keys(child, f"{path}{index}."))
    return found


def _exact_keys(value: Any, keys: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReportError(f"{label} must be an object")
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        extra = sorted(actual - keys)
        raise ReportError(f"{label} keys mismatch missing={missing} extra={extra}")
    return value


def _text(value: Any, label: str, *, limit: int, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ReportError(f"{label} must be non-empty text")
    if len(value) > limit:
        raise ReportError(f"{label} exceeds {limit} characters")
    return value.strip()


def validate_report(
    report: Mapping[str, Any],
    *,
    queue_row: Mapping[str, Any],
    data_as_of: date,
    last_close: float,
) -> dict[str, Any]:
    """Validate one LLM report against its queue row and snapshot.

    Returns the DB row. Raises ReportError naming the first problem.
    """

    forbidden = _walk_keys(report)
    if forbidden:
        raise ReportError(f"reasoning/debug fields are not allowed: {forbidden}")
    _exact_keys(report, REPORT_KEYS, "report")
    symbol = queue_row["symbol"]
    if report["symbol"] != symbol:
        raise ReportError(f"symbol {report['symbol']!r} is not {symbol!r}")
    if report["report_date"] != queue_row["report_date"].isoformat():
        raise ReportError("report_date must equal the queued edition")
    if report["data_as_of"] != data_as_of.isoformat():
        raise ReportError("data_as_of must equal the snapshot's data_as_of")
    if not data_as_of < queue_row["report_date"]:
        raise ReportError("data_as_of must precede report_date")
    framework = _text(report["framework_version"], "framework_version", limit=80)
    try:
        generated_at = datetime.fromisoformat(str(report["generated_at"]).replace("Z", "+00:00"))
    except ValueError as error:
        raise ReportError("generated_at must be an ISO timestamp") from error
    if generated_at.tzinfo is None:
        raise ReportError("generated_at must include a timezone")
    if report["bias"] not in BIAS:
        raise ReportError(f"bias must be one of {BIAS}")
    if report["actionability"] not in ACTIONABILITY:
        raise ReportError(f"actionability must be one of {ACTIONABILITY}")
    for key, limit in TEXT_LIMITS.items():
        _text(report[key], key, limit=limit, optional=key in {"no_trade_warning", "news_context"})

    low, high = last_close * PRICE_BAND[0], last_close * PRICE_BAND[1]

    def price(value: Any, label: str) -> float:
        if not _finite_positive(value):
            raise ReportError(f"{label} must be a positive number")
        if not low <= float(value) <= high:
            raise ReportError(f"{label}={value} is outside {low:.2f}-{high:.2f} (close {last_close})")
        return float(value)

    levels = report["key_levels"]
    if not isinstance(levels, list) or not 1 <= len(levels) <= 12:
        raise ReportError("key_levels must list 1-12 levels")
    for index, level in enumerate(levels):
        _exact_keys(level, LEVEL_KEYS, f"key_levels[{index}]")
        _text(level["label"], f"key_levels[{index}].label", limit=40)
        price(level["price"], f"key_levels[{index}].price")
        if level["kind"] not in LEVEL_KINDS:
            raise ReportError(f"key_levels[{index}].kind must be one of {LEVEL_KINDS}")

    primary = _exact_keys(report["primary_scenario"], PRIMARY_KEYS, "primary_scenario")
    _text(primary["summary"], "primary_scenario.summary", limit=400)
    _text(primary["trigger"], "primary_scenario.trigger", limit=200)
    zone = primary["entry_zone"]
    if zone is not None:
        if not isinstance(zone, list) or len(zone) != 2:
            raise ReportError("primary_scenario.entry_zone must be [low, high] or null")
        lo, hi = price(zone[0], "entry_zone[0]"), price(zone[1], "entry_zone[1]")
        if lo > hi:
            raise ReportError("entry_zone low must not exceed high")
    targets = primary["targets"]
    if not isinstance(targets, list) or len(targets) > 4:
        raise ReportError("primary_scenario.targets must be a list of up to 4 prices")
    for index, target in enumerate(targets):
        price(target, f"targets[{index}]")

    alternative = _exact_keys(report["alternative_scenario"], ALTERNATIVE_KEYS, "alternative_scenario")
    _text(alternative["summary"], "alternative_scenario.summary", limit=400)
    _text(alternative["trigger"], "alternative_scenario.trigger", limit=200)

    invalidation = _exact_keys(report["invalidation"], INVALIDATION_KEYS, "invalidation")
    invalidation_price = price(invalidation["price"], "invalidation.price")
    _text(invalidation["condition"], "invalidation.condition", limit=200)

    if report["actionability"] == "no_trade" and not report["no_trade_warning"]:
        raise ReportError("no_trade requires no_trade_warning")
    if report["actionability"] == "actionable" and zone is None:
        raise ReportError("actionable requires primary_scenario.entry_zone")

    return {
        "symbol": symbol,
        "report_date": queue_row["report_date"],
        "framework_version": framework,
        "data_as_of": data_as_of,
        "bias": report["bias"],
        "actionability": report["actionability"],
        "invalidation_price": invalidation_price,
        "last_close": last_close,
        "conclusion": report["conclusion"].strip(),
        "report": json.dumps(dict(report), ensure_ascii=False, sort_keys=True),
        "generated_at": generated_at,
    }


# --- DB ---------------------------------------------------------------------

BATCH_SQL = """
SELECT report_date, data_as_of, selection_rule, selected_count, excluded, prepared_at
FROM radar.analysis_batch WHERE report_date = %s
""".strip()

QUEUE_SQL = """
SELECT q.report_date, q.symbol, q.rank, q.exchange, q.name_zh, q.selected_by,
       q.short_rank, q.long_rank, q.themes,
       t.data_as_of, t.last_close, t.candles, t.metrics, t.candles_sha256,
       f.fiscal_quarter, f.payload, f.missing, f.payload_sha256
FROM radar.analysis_queue q
JOIN radar.analysis_batch b ON b.report_date = q.report_date
JOIN radar.technical_snapshot t ON t.symbol = q.symbol AND t.data_as_of = b.data_as_of
JOIN radar.fundamental_snapshot f ON f.symbol = q.symbol AND f.data_as_of = b.data_as_of
WHERE q.report_date = %s
ORDER BY q.rank
""".strip()

REPORTED_SQL = """
SELECT symbol, framework_version, generated_at FROM radar.analysis_report
WHERE report_date = %s ORDER BY symbol, generated_at DESC
""".strip()

REPORT_UPSERT_SQL = """
INSERT INTO radar.analysis_report (
  symbol, report_date, framework_version, data_as_of, bias, actionability,
  invalidation_price, last_close, conclusion, report, technical_sha256,
  fundamental_sha256, generated_at
) VALUES (
  %(symbol)s, %(report_date)s, %(framework_version)s, %(data_as_of)s,
  %(bias)s, %(actionability)s, %(invalidation_price)s, %(last_close)s,
  %(conclusion)s, %(report)s::jsonb, %(technical_sha256)s,
  %(fundamental_sha256)s, %(generated_at)s
)
ON CONFLICT (symbol, report_date, framework_version) DO UPDATE SET
  bias = EXCLUDED.bias, actionability = EXCLUDED.actionability,
  invalidation_price = EXCLUDED.invalidation_price,
  last_close = EXCLUDED.last_close, conclusion = EXCLUDED.conclusion,
  report = EXCLUDED.report, technical_sha256 = EXCLUDED.technical_sha256,
  fundamental_sha256 = EXCLUDED.fundamental_sha256,
  generated_at = EXCLUDED.generated_at, updated_at = now()
""".strip()


def _queue(connection: Any, report_date: date) -> tuple[Mapping[str, Any] | None, list[dict[str, Any]]]:
    with connection.cursor() as cursor:
        cursor.execute(BATCH_SQL, (report_date,))
        batch_row = cursor.fetchone()
        if not batch_row:
            return None, []
        batch = dict(zip(("report_date", "data_as_of", "selection_rule", "selected_count",
                          "excluded", "prepared_at"), batch_row))
        cursor.execute(QUEUE_SQL, (report_date,))
        columns = [c.name for c in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    return batch, rows


def _connect() -> Any:
    dsn = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not dsn:
        print(f"{DATABASE_URL_ENV} is not set", file=sys.stderr)
        raise SystemExit(4)
    import psycopg

    return psycopg.connect(dsn, autocommit=True)


def _default_date() -> date:
    return datetime.now(TAIPEI).date()


def cmd_pull(connection: Any, report_date: date, work_dir: Path) -> int:
    batch, rows = _queue(connection, report_date)
    if batch is None:
        print(f"no_batch report_date={report_date}: cloud list not prepared (or not a trading day)")
        return 3
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "reports").mkdir(exist_ok=True)
    queue = {
        "report_date": report_date.isoformat(),
        "data_as_of": batch["data_as_of"].isoformat(),
        "selection_rule": batch["selection_rule"],
        "excluded": batch["excluded"],
        "stocks": [
            {
                "symbol": row["symbol"], "name_zh": row["name_zh"], "rank": row["rank"],
                "exchange": row["exchange"], "selected_by": row["selected_by"],
                "short_rank": row["short_rank"], "long_rank": row["long_rank"],
                "themes": row["themes"], "last_close": float(row["last_close"]),
                "metrics": row["metrics"], "fundamentals": row["payload"],
                "fundamentals_missing": list(row["missing"] or []),
                "fiscal_quarter": row["fiscal_quarter"],
            }
            for row in rows
        ],
    }
    (work_dir / "queue.json").write_text(json.dumps(queue, ensure_ascii=False, indent=2, default=str) + "\n")
    # Input for scripts/analyze_stock_audit_technical.py: it analyses as of the
    # observed session (data_as_of), never the edition date.
    analyzer_input = {
        "report_date": batch["data_as_of"].isoformat(),
        "stocks": [
            {"symbol": row["symbol"], "name": row["name_zh"], "technical_candles": row["candles"]}
            for row in rows
        ],
    }
    (work_dir / "analyzer-input.json").write_text(json.dumps(analyzer_input, ensure_ascii=False) + "\n")
    print(f"pulled report_date={report_date} data_as_of={batch['data_as_of']} stocks={len(rows)} -> {work_dir}")
    return 0


def cmd_push(connection: Any, report_date: date, work_dir: Path) -> int:
    batch, rows = _queue(connection, report_date)
    if batch is None:
        print(f"no_batch report_date={report_date}")
        return 3
    by_symbol = {row["symbol"]: row for row in rows}
    db_rows, errors = [], []
    for path in sorted((work_dir / "reports").glob("*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            row = by_symbol.get(str(report.get("symbol")))
            if row is None:
                raise ReportError(f"{report.get('symbol')!r} is not in the {report_date} list")
            validated = validate_report(
                report, queue_row=row, data_as_of=row["data_as_of"], last_close=float(row["last_close"])
            )
            validated["technical_sha256"] = row["candles_sha256"]
            validated["fundamental_sha256"] = row["payload_sha256"]
            db_rows.append(validated)
        except (ReportError, json.JSONDecodeError, KeyError, TypeError) as error:
            errors.append(f"{path.name}: {error}")
    if errors:
        print("invalid reports; nothing written:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 2
    if db_rows:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.executemany(REPORT_UPSERT_SQL, db_rows)
    missing = sorted(set(by_symbol) - {r["symbol"] for r in db_rows})
    print(f"pushed {len(db_rows)} reports for {report_date}; without report: {missing or 'none'}")
    return 0


def cmd_status(connection: Any, report_date: date) -> int:
    batch, rows = _queue(connection, report_date)
    if batch is None:
        print(f"no_batch report_date={report_date}")
        return 3
    with connection.cursor() as cursor:
        cursor.execute(REPORTED_SQL, (report_date,))
        reported = {symbol for symbol, _, _ in cursor.fetchall()}
    for row in rows:
        mark = "done" if row["symbol"] in reported else "todo"
        print(f"{row['rank']:>2} {row['symbol']} {row['name_zh']} {mark}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("pull", "push", "status"))
    parser.add_argument("--report-date", help="YYYY-MM-DD edition (default: today in Taipei)")
    parser.add_argument("--work-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    report_date = date.fromisoformat(args.report_date) if args.report_date else _default_date()
    work_dir = args.work_dir or Path.home() / ".nexus-radar" / "daily-report" / report_date.isoformat()
    try:
        with _connect() as connection:
            if args.command == "pull":
                return cmd_pull(connection, report_date, work_dir)
            if args.command == "push":
                return cmd_push(connection, report_date, work_dir)
            return cmd_status(connection, report_date)
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001
        print(f"analysis_report_failed error={redact_error(error)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
