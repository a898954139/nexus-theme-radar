"""Monthly operating revenue (月營收) datasets for listed (TWSE) and OTC (TPEx) companies.

Produces company-level events (symbol, period, revenue, MoM, YoY, record-high
flag) for the WS2 positive-polarity path. Runs as a contained side path of the
hourly theme-radar run:

- Fetches only on days 1-10 of the month (Asia/Taipei), at most one successful
  fetch per dataset per day. A failed fetch is retried on the next run.
- A row missing a required field is excluded and counted, never zero-filled.
- A (company, period) pair produces an event once; later runs that see the same
  period again do not re-emit it.
- Every failure is isolated into a source-status envelope; nothing propagates.

``THEME_RADAR_MONTHLY_REVENUE=0`` disables fetching entirely (tests use it).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.source_adapters import _fetch_dataset
except ModuleNotFoundError:
    from source_adapters import _fetch_dataset


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "monthly_revenue_datasets.tw.json"
HISTORY_FILENAME = "monthly-revenue-history.json"
EVENTS_FILENAME = "monthly-revenue-events.json"
DISABLE_ENV = "THEME_RADAR_MONTHLY_REVENUE"
TAIPEI = timezone(timedelta(hours=8))  # Taiwan has no DST
SOURCE_CLASS = "official_dataset"
ADAPTER = "monthly_revenue"
REQUIRED_FIELDS = ("symbol", "period", "revenue", "mom_pct", "yoy_pct")
FETCH_TIMEOUT_SECONDS = 30
FETCH_MAX_ATTEMPTS = 2
FETCH_MAX_RESPONSE_BYTES = 32 * 1024 * 1024
FETCH_MAX_ROWS = 20_000

RowFetcher = Callable[[Any, str], list[dict[str, Any]]]


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def monthly_revenue_enabled() -> bool:
    return os.environ.get(DISABLE_ENV, "1").strip() not in {"0", "false", "False", "no"}


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    datasets = config.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise ValueError("monthly revenue config must contain a non-empty datasets array")
    seen: set[str] = set()
    for dataset in datasets:
        for key in ("dataset_id", "source_id", "url", "exchange", "status"):
            if not str(dataset.get(key) or ""):
                raise ValueError(f"monthly revenue dataset missing {key}")
        if not str(dataset["url"]).startswith("https://"):
            raise ValueError(f"monthly revenue dataset url must be https: {dataset['dataset_id']}")
        if dataset["dataset_id"] in seen:
            raise ValueError(f"duplicate monthly revenue dataset: {dataset['dataset_id']}")
        seen.add(dataset["dataset_id"])
    aliases = config.get("field_aliases") or {}
    for field in REQUIRED_FIELDS:
        if not aliases.get(field):
            raise ValueError(f"monthly revenue config missing field aliases for {field}")
    start, end = config.get("fetch_window_days") or [1, 10]
    if not 1 <= int(start) <= int(end) <= 31:
        raise ValueError("fetch_window_days must be an ordered [start, end] day range")
    return config


# ---------------------------------------------------------------- parsing


def parse_number(value: Any) -> float | None:
    """Parse an official numeric cell. Blank, dash, or non-numeric -> None (never 0)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text in {"-", "--", "N/A", "NA", "不適用"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_period(value: Any) -> str | None:
    """Normalize 資料年月 ('11510', '115/10', '2026-10', '202610') to 'YYYY-MM'."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parts = [part for part in re.split(r"[/\-年月.\s]+", text) if part]
    try:
        if len(parts) == 2:
            year, month = int(parts[0]), int(parts[1])
        else:
            digits = re.sub(r"\D", "", text)
            if len(digits) == 5:  # ROC yyyMM
                year, month = int(digits[:3]), int(digits[3:])
            elif len(digits) == 6:
                year, month = int(digits[:4]), int(digits[4:])
            else:
                return None
    except ValueError:
        return None
    if year < 1911:
        year += 1911
    if not 1 <= month <= 12 or not 1990 <= year <= 2200:
        return None
    return f"{year:04d}-{month:02d}"


def shift_period(period: str, months: int) -> str:
    year, month = (int(part) for part in period.split("-"))
    index = year * 12 + (month - 1) + months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _first(row: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in row and row[name] is not None and str(row[name]).strip():
            return row[name]
    return None


def _pct_change(current: float | None, base: float | None) -> float | None:
    if current is None or base is None or base <= 0:
        return None
    return round((current / base - 1) * 100, 2)


def parse_revenue_row(
    row: dict[str, Any],
    aliases: dict[str, list[str]],
) -> tuple[dict[str, Any] | None, str | None]:
    """Return (record, None) or (None, exclusion_reason)."""
    symbol_raw = _first(row, aliases["symbol"])
    symbol = str(symbol_raw).strip() if symbol_raw is not None else None
    period = parse_period(_first(row, aliases["period"]))
    revenue = parse_number(_first(row, aliases["revenue"]))
    previous = parse_number(_first(row, aliases.get("previous_month_revenue", [])))
    last_year = parse_number(_first(row, aliases.get("last_year_revenue", [])))
    mom = parse_number(_first(row, aliases["mom_pct"]))
    yoy = parse_number(_first(row, aliases["yoy_pct"]))

    derived: list[str] = []
    if mom is None and (mom := _pct_change(revenue, previous)) is not None:
        derived.append("mom_pct")
    if yoy is None and (yoy := _pct_change(revenue, last_year)) is not None:
        derived.append("yoy_pct")

    values = {"symbol": symbol, "period": period, "revenue": revenue, "mom_pct": mom, "yoy_pct": yoy}
    for field in REQUIRED_FIELDS:
        if values[field] is None or values[field] == "":
            return None, f"missing_{field}"

    name_raw = _first(row, aliases.get("company_name", []))
    industry_raw = _first(row, aliases.get("industry", []))
    return (
        {
            "symbol": symbol,
            "company_name": str(name_raw).strip() if name_raw is not None else None,
            "industry": str(industry_raw).strip() if industry_raw is not None else None,
            "period": period,
            "revenue": revenue,
            "previous_month_revenue": previous,
            "last_year_revenue": last_year,
            "mom_pct": mom,
            "yoy_pct": yoy,
            "derived_fields": derived,
        },
        None,
    )


# ---------------------------------------------------------------- state


def empty_history() -> dict[str, Any]:
    return {"version": 1, "updated_at": None, "last_success_on": {}, "emitted": {}, "series": {}}


def load_history(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_history()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_history()
    history = empty_history()
    for key in ("last_success_on", "emitted", "series"):
        if isinstance(payload.get(key), dict):
            history[key] = payload[key]
    history["updated_at"] = payload.get("updated_at")
    return history


def load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = payload.get("items")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        json.dump(payload, temporary, ensure_ascii=False, indent=2, sort_keys=False)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def _record_series(series: dict[str, float], period: str, value: float | None) -> None:
    if value is not None and period not in series:
        series[period] = value


def _prune_series(series: dict[str, float], newest: str, retention_months: int) -> None:
    oldest = shift_period(newest, -(retention_months - 1))
    for period in [period for period in series if period < oldest]:
        del series[period]


# ---------------------------------------------------------------- events


def dataset_due(
    dataset: dict[str, Any],
    history: dict[str, Any],
    anchor: datetime,
    config: dict[str, Any],
    *,
    full_refresh: bool,
) -> tuple[bool, str]:
    if dataset.get("status") != "active":
        return False, "skipped_inactive"
    local = anchor.astimezone(TAIPEI)
    today = local.date().isoformat()
    if full_refresh:
        return True, "fetched"
    start, end = (int(day) for day in config.get("fetch_window_days") or [1, 10])
    if not start <= local.day <= end:
        return False, "skipped_outside_window"
    if history["last_success_on"].get(dataset["dataset_id"]) == today:
        return False, "skipped_already_fetched_today"
    return True, "fetched"


def build_events(
    records: list[dict[str, Any]],
    dataset: dict[str, Any],
    history: dict[str, Any],
    config: dict[str, Any],
    fetched_at: datetime,
) -> list[dict[str, Any]]:
    """Update history with ``records`` and return events for newly seen (company, period)."""
    exchange = str(dataset["exchange"])
    min_history = int(config.get("record_high_min_history_months") or 12)
    retention = int(config.get("history_retention_months") or 72)
    surge = float(config.get("yoy_surge_threshold_pct") or 20)
    events: list[dict[str, Any]] = []

    for record in records:
        key = f"{exchange}:{record['symbol']}"
        period = record["period"]
        series = history["series"].setdefault(key, {})
        # Official values for the comparison months seed history honestly.
        _record_series(series, shift_period(period, -1), record["previous_month_revenue"])
        _record_series(series, shift_period(period, -12), record["last_year_revenue"])
        series[period] = record["revenue"]
        _prune_series(series, max(series), retention)

        last_emitted = history["emitted"].get(key)
        if last_emitted is not None and period <= last_emitted:
            continue
        history["emitted"][key] = period

        prior = [value for month, value in series.items() if month < period]
        if len(prior) >= min_history:
            is_record_high: bool | None = record["revenue"] > max(prior)
        else:
            is_record_high = None

        signals: list[str] = []
        if is_record_high:
            signals.append("record_high")
        if record["yoy_pct"] >= surge:
            signals.append("yoy_surge")
        prior_period = shift_period(period, -1)
        prior_base = shift_period(period, -13)
        prior_yoy = _pct_change(series.get(prior_period), series.get(prior_base))
        if prior_yoy is not None and prior_yoy < 0 < record["yoy_pct"]:
            signals.append("yoy_turned_positive")

        events.append(
            {
                "event_id": f"monthly-revenue-{exchange.lower()}-{record['symbol']}-{period}",
                "event_type": "monthly_revenue",
                "dataset_id": dataset["dataset_id"],
                "source_id": dataset["source_id"],
                "market_id": "TW_EQUITY",
                "exchange": exchange,
                "instrument_id": key,
                "symbol": record["symbol"],
                "company_name": record["company_name"],
                "industry": record["industry"],
                "period": period,
                "revenue_twd_thousands": record["revenue"],
                "mom_pct": record["mom_pct"],
                "yoy_pct": record["yoy_pct"],
                "is_record_high": is_record_high,
                "record_high_basis_months": len(prior),
                "signals": signals,
                "derived_fields": record["derived_fields"],
                "canonical_url": dataset["url"],
                "fetched_at": _utc_text(fetched_at),
            }
        )
    return events


def _default_fetch_rows(session: Any, url: str) -> list[dict[str, Any]]:
    return _fetch_dataset(
        session,
        url,
        timeout=FETCH_TIMEOUT_SECONDS,
        max_attempts=FETCH_MAX_ATTEMPTS,
        max_response_bytes=FETCH_MAX_RESPONSE_BYTES,
        max_rows=FETCH_MAX_ROWS,
    )


def _merge_events(
    previous: list[dict[str, Any]],
    new: list[dict[str, Any]],
    retention_periods: int,
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for event in [*previous, *new]:
        event_id = str(event.get("event_id") or "")
        if event_id and event_id not in by_id:
            by_id[event_id] = event
    if not by_id:
        return []
    newest = max(str(event.get("period") or "") for event in by_id.values())
    oldest = shift_period(newest, -(max(1, retention_periods) - 1))
    kept = [event for event in by_id.values() if str(event.get("period") or "") >= oldest]
    return sorted(kept, key=lambda event: (event["period"], event["instrument_id"]), reverse=True)


def run_monthly_revenue(
    session: Any,
    output_dir: Path,
    anchor: datetime,
    *,
    full_refresh: bool = False,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    fetch_rows: RowFetcher | None = None,
) -> list[dict[str, Any]]:
    """Fetch due datasets, persist history and events, and return per-dataset statuses."""
    if not monthly_revenue_enabled():
        return []
    config = load_config(config_path)
    aliases = config["field_aliases"]
    fetcher = fetch_rows or _default_fetch_rows
    history_path = output_dir / HISTORY_FILENAME
    events_path = output_dir / EVENTS_FILENAME
    history = load_history(history_path)
    today = anchor.astimezone(TAIPEI).date().isoformat()
    statuses: list[dict[str, Any]] = []
    new_events: list[dict[str, Any]] = []

    for dataset in config["datasets"]:
        started = time.monotonic()
        status: dict[str, Any] = {
            "source_id": dataset["source_id"],
            "name": dataset.get("name") or dataset["source_id"],
            "source_class": SOURCE_CLASS,
            "adapter": ADAPTER,
            "fetch_method": ADAPTER,
            "dataset_id": dataset["dataset_id"],
            "endpoint": dataset["url"],
            "status": "ok",
            "fetch_state": None,
            "items": 0,
            "rows": 0,
            "excluded_rows": 0,
            "excluded_reasons": {},
            "error": None,
            "last_success_on": history["last_success_on"].get(dataset["dataset_id"]),
        }
        due, fetch_state = dataset_due(dataset, history, anchor, config, full_refresh=full_refresh)
        status["fetch_state"] = fetch_state
        if due:
            try:
                rows = fetcher(session, str(dataset["url"]))
                records: list[dict[str, Any]] = []
                reasons: dict[str, int] = {}
                for row in rows:
                    record, reason = parse_revenue_row(row, aliases)
                    if record is None:
                        reasons[str(reason)] = reasons.get(str(reason), 0) + 1
                    else:
                        records.append(record)
                status["rows"] = len(rows)
                status["excluded_rows"] = len(rows) - len(records)
                status["excluded_reasons"] = dict(sorted(reasons.items()))
                if rows and not records:
                    raise ValueError(
                        f"no parsable rows out of {len(rows)} (field drift? {status['excluded_reasons']})"
                    )
                events = build_events(records, dataset, history, config, anchor)
                new_events.extend(events)
                status["items"] = len(events)
                history["last_success_on"][dataset["dataset_id"]] = today
                status["last_success_on"] = today
            except Exception as exc:  # noqa: BLE001 - dataset isolation requires a status envelope
                status["status"] = "error"
                status["error"] = str(exc)
        status["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        statuses.append(status)

    if any(status["fetch_state"] == "fetched" and status["status"] == "ok" for status in statuses):
        history["updated_at"] = _utc_text(anchor)
        _atomic_write_json(history_path, history)
        merged = _merge_events(
            load_events(events_path),
            new_events,
            int(config.get("event_retention_periods") or 3),
        )
        _atomic_write_json(
            events_path,
            {
                "generated_at": _utc_text(anchor),
                "market_id": "TW_EQUITY",
                "event_type": "monthly_revenue",
                "revenue_unit": "TWD thousands",
                "total_items": len(merged),
                "new_items_this_run": len(new_events),
                "items": merged,
            },
        )
    return statuses
