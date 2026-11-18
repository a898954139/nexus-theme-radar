"""Prepare the daily pre-market analysis list and its deterministic snapshots.

Cloud half of issue #8. Each trading morning, before 07:00 Taipei, this job:

1. picks up to 10 candidates from ``data/public-stock-watchlist-v1.json``
   (``--short-slots`` by short rank, then ``--long-slots`` by long rank),
2. loads observed daily OHLCV from TWSE/TPEX (cached in ``radar.daily_bar`` so
   only the current month is fetched once history is warm),
3. writes ``technical_snapshot`` (candles + plain arithmetic metrics) and
   ``fundamental_snapshot`` (repo quarterly cache + PE from the snapshot close),
4. freezes the list as ``analysis_batch`` + ``analysis_queue``.

A candidate with missing quotes, too little history, a stale last bar or no
fundamentals is excluded and the next one by rank takes its slot. Nothing is
imputed. The LLM report is NOT written here: the user's local Claude task reads
this list and writes ``radar.analysis_report`` with its own role.

``--mode warm`` only fills the bar cache for the top candidates (run in the
evening so the morning run stays small). Without ``THEME_RADAR_DATABASE_URL``
both modes log ``analysis_queue_skipped`` and exit 0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
import sys
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

try:
    from scripts.radar_store import redact_error
except ModuleNotFoundError:
    from radar_store import redact_error


LOGGER = logging.getLogger("prepare_analysis_queue")
ROOT = Path(__file__).resolve().parents[1]
TAIPEI = ZoneInfo("Asia/Taipei")
WATCHLIST_PATH = ROOT / "data" / "public-stock-watchlist-v1.json"
FUNDAMENTALS_DIR = ROOT / "data" / "fundamentals"
DATABASE_URL_ENV = "THEME_RADAR_DATABASE_URL"

QUEUE_SIZE = 10
DEFAULT_SHORT_SLOTS = 7
DEFAULT_LONG_SLOTS = 3
# analyze_stock_audit_technical.MIN_TECHNICAL_BARS: the local PVA/Nexus
# analyzer refuses less, so a shorter history is excluded here, not later.
MIN_TECHNICAL_BARS = 600
HISTORY_MONTHS = 31
REFERENCE_SYMBOL = ("2330", "TWSE")
DEFAULT_FETCH_BUDGET = {"prepare": 150, "warm": 550}
# From this Taipei time on, a batch is frozen even if some fetches were deferred
# by the budget; before it, a short batch waits for the next cron slot.
FREEZE_PARTIAL_AFTER = (6, 45)
FETCH_SPACING_SECONDS = 2.0
SELECTION_RULE_TEMPLATE = "watchlist_v1 short_top{short}+long_top{long} backfill_by_rank"

TWSE_STOCK_DAY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
TPEX_TRADING_STOCK_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
SAFE_SYMBOL = re.compile(r"^[0-9A-Z]{4,6}$")


class QueueInputError(ValueError):
    """A candidate cannot be prepared from observed data."""


# --- watchlist -------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    symbol: str
    exchange: str
    instrument_id: str
    name_zh: str
    short_rank: int | None
    short_score: float | None
    long_rank: int | None
    long_score: float | None
    themes: tuple[dict[str, Any], ...]


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(float(value)) else None


def _candidate(item: Mapping[str, Any]) -> Candidate | None:
    instrument = item.get("instrument") or {}
    symbol = str(instrument.get("symbol") or "").strip()
    exchange = str(instrument.get("exchange") or "").strip()
    if not SAFE_SYMBOL.match(symbol) or exchange not in {"TWSE", "TPEX"}:
        return None
    short = item.get("short") or {}
    long = item.get("long") or {}
    themes = tuple(
        {
            "theme_id": theme.get("theme_id"),
            "name_zh": theme.get("name_zh"),
            "relation": theme.get("relation"),
        }
        for theme in (item.get("themes") or [])[:5]
        if isinstance(theme, Mapping)
    )
    short_rank = _num(short.get("rank"))
    long_rank = _num(long.get("rank"))
    return Candidate(
        symbol=symbol,
        exchange=exchange,
        instrument_id=str(instrument.get("instrument_id") or f"{exchange}:{symbol}"),
        name_zh=str(instrument.get("name_zh") or symbol),
        short_rank=int(short_rank) if short_rank is not None else None,
        short_score=_num(short.get("score")),
        long_rank=int(long_rank) if long_rank is not None else None,
        long_score=_num(long.get("score")),
        themes=themes,
    )


def candidate_pools(watchlist: Mapping[str, Any]) -> tuple[list[Candidate], list[Candidate]]:
    """Return (short pool, long pool), each ordered by its own rank."""

    pools = []
    for horizon in ("short", "long"):
        items = (watchlist.get(horizon) or {}).get("items") or []
        parsed = [c for c in (_candidate(item) for item in items) if c is not None]
        rank_key = (lambda c: c.short_rank) if horizon == "short" else (lambda c: c.long_rank)
        parsed.sort(key=lambda c: (rank_key(c) is None, rank_key(c) or 0, c.instrument_id))
        pools.append(parsed)
    return pools[0], pools[1]


@dataclass
class Selection:
    picked: list[tuple[Candidate, str]] = field(default_factory=list)
    excluded: list[dict[str, str]] = field(default_factory=list)


def select_candidates(
    short_pool: Sequence[Candidate],
    long_pool: Sequence[Candidate],
    eligible: Callable[[Candidate], str | None],
    *,
    short_slots: int = DEFAULT_SHORT_SLOTS,
    long_slots: int = DEFAULT_LONG_SLOTS,
    limit: int = QUEUE_SIZE,
) -> Selection:
    """Fill short then long slots by rank; an ineligible candidate is replaced
    by the next one from the same pool. If a pool runs dry, the other backfills.

    ``eligible`` returns None when the candidate can be prepared, else a reason.
    It is called at most once per symbol.
    """

    if short_slots + long_slots != limit:
        raise ValueError("short_slots + long_slots must equal the queue size")
    selection = Selection()
    seen: set[str] = set()
    cursors = {"short": iter(short_pool), "long": iter(long_pool)}

    def take(horizon: str, wanted: int) -> int:
        taken = 0
        for candidate in cursors[horizon]:
            if taken >= wanted:
                break
            if candidate.symbol in seen:
                continue
            seen.add(candidate.symbol)
            reason = eligible(candidate)
            if reason:
                selection.excluded.append({"symbol": candidate.symbol, "selected_by": horizon, "reason": reason})
                continue
            selection.picked.append((candidate, horizon))
            taken += 1
            if taken >= wanted:
                break
        return taken

    short_taken = take("short", short_slots)
    long_taken = take("long", long_slots)
    if long_taken < long_slots:
        take("short", long_slots - long_taken)
    if short_taken < short_slots:
        take("long", short_slots - short_taken)
    selection.picked = selection.picked[:limit]
    return selection


# --- exchange daily bars ---------------------------------------------------


def exchange_date(value: Any) -> date:
    parts = [int(part) for part in re.findall(r"\d+", str(value))]
    if len(parts) != 3:
        raise QueueInputError(f"invalid exchange date {value!r}")
    year, month, day = parts
    return date(year + 1911 if year < 1911 else year, month, day)


def _official_number(value: Any) -> float:
    text = str(value).replace(",", "").strip()
    if text in {"", "--", "-", "---", "X"}:
        raise QueueInputError("unpriced")
    result = float(text)
    if not math.isfinite(result):
        raise QueueInputError("non-finite")
    return result


def _field_index(fields: Sequence[str], *names: str) -> int | None:
    normalized = [re.sub(r"\s+", "", str(f)) for f in fields]
    for name in names:
        for index, value in enumerate(normalized):
            if value.startswith(name):
                return index
    return None


def parse_month_payload(payload: Mapping[str, Any], exchange: str) -> list[dict[str, Any]]:
    """Parse one month of official daily quotes into OHLCV bars (volume in shares).

    TWSE ``STOCK_DAY`` puts rows in ``data``; TPEX ``tradingStock`` puts them in
    ``tables[0].data``. Columns are located by their ``fields`` headers when
    present. Zero-volume unpriced rows (trading halts) are skipped, never filled.
    """

    if exchange == "TWSE":
        if payload.get("stat") != "OK":
            raise QueueInputError(f"TWSE stat={payload.get('stat')!r}")
        rows = payload.get("data")
        fields = payload.get("fields") or []
    else:
        if str(payload.get("stat", "")).lower() != "ok":
            raise QueueInputError(f"TPEX stat={payload.get('stat')!r}")
        tables = payload.get("tables") or []
        table = tables[0] if tables and isinstance(tables[0], Mapping) else {}
        rows = table.get("data")
        fields = table.get("fields") or []
    if not isinstance(rows, list):
        raise QueueInputError(f"{exchange} payload has no rows")
    idx = {
        "date": _field_index(fields, "日期", "日 期") if fields else None,
        "volume": _field_index(fields, "成交股數", "成交張數", "成交仟股") if fields else None,
        "open": _field_index(fields, "開盤") if fields else None,
        "high": _field_index(fields, "最高") if fields else None,
        "low": _field_index(fields, "最低") if fields else None,
        "close": _field_index(fields, "收盤") if fields else None,
    }
    defaults = {"date": 0, "volume": 1, "open": 3, "high": 4, "low": 5, "close": 6}
    idx = {key: (value if value is not None else defaults[key]) for key, value in idx.items()}
    volume_header = str(fields[idx["volume"]]) if fields and idx["volume"] < len(fields) else ""
    volume_scale = 1000.0 if ("張" in volume_header or "仟股" in volume_header) else 1.0
    if exchange == "TPEX" and not fields:
        volume_scale = 1000.0  # TPEX reports lots when headers are absent

    bars: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) <= max(idx.values()):
            raise QueueInputError(f"{exchange} row has too few columns")
        day = exchange_date(row[idx["date"]])
        try:
            bar = {
                "date": day.isoformat(),
                "open": _official_number(row[idx["open"]]),
                "high": _official_number(row[idx["high"]]),
                "low": _official_number(row[idx["low"]]),
                "close": _official_number(row[idx["close"]]),
                "volume": _official_number(row[idx["volume"]]) * volume_scale,
            }
        except QueueInputError:
            continue  # halted / unpriced session: omitted, not imputed
        except ValueError as error:
            raise QueueInputError(f"{exchange} malformed row for {day}") from error
        if not 0 < bar["low"] <= min(bar["open"], bar["close"]) <= max(bar["open"], bar["close"]) <= bar["high"]:
            raise QueueInputError(f"{exchange} OHLC out of order on {day}")
        bars.append(bar)
    return bars


def month_url(symbol: str, exchange: str, month: date) -> str:
    if exchange == "TWSE":
        query = {"response": "json", "date": month.strftime("%Y%m01"), "stockNo": symbol}
        return f"{TWSE_STOCK_DAY_URL}?{urlencode(query)}"
    query = {"code": symbol, "date": month.strftime("%Y/%m/01"), "response": "json"}
    return f"{TPEX_TRADING_STOCK_URL}?{urlencode(query)}"


def months_between(start: date, end: date) -> list[date]:
    cursor = start.replace(day=1)
    months = []
    while cursor <= end:
        months.append(cursor)
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return months


def month_end(month: date) -> date:
    return (month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


class BarFetcher:
    """Budgeted, spaced fetcher. Every failure is the symbol's problem only."""

    def __init__(
        self,
        http_get: Callable[[str], Mapping[str, Any]],
        *,
        budget: int,
        spacing: float = FETCH_SPACING_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.http_get = http_get
        self.budget = budget
        self.spacing = spacing
        self.sleep = sleep
        self.requests = 0
        self.deferred: list[str] = []
        self._last = 0.0

    def month(self, symbol: str, exchange: str, month: date) -> list[dict[str, Any]] | None:
        url = month_url(symbol, exchange, month)
        if self.requests >= self.budget:
            self.deferred.append(f"{symbol}:{month:%Y-%m}")
            return None
        if self.requests:
            self.sleep(self.spacing)
        self.requests += 1
        payload = self.http_get(url)
        return parse_month_payload(payload, exchange)


def _requests_get_json(url: str) -> Mapping[str, Any]:
    import requests

    response = requests.get(
        url,
        timeout=30,
        headers={"User-Agent": "nexus-theme-radar/analysis-queue", "Accept": "application/json"},
    )
    response.raise_for_status()
    return response.json()


# --- deterministic snapshot metrics -----------------------------------------


def _round(value: float | None, places: int = 4) -> float | None:
    return None if value is None else round(value, places)


def _sma(values: Sequence[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _atr(candles: Sequence[Mapping[str, float]], window: int = 14) -> float | None:
    if len(candles) <= window:
        return None
    ranges = []
    for previous, current in zip(candles[-window - 1 : -1], candles[-window:]):
        ranges.append(
            max(
                current["high"] - current["low"],
                abs(current["high"] - previous["close"]),
                abs(current["low"] - previous["close"]),
            )
        )
    return sum(ranges) / window


def technical_metrics(candles: Sequence[Mapping[str, float]]) -> dict[str, Any]:
    """Plain arithmetic only. Structure (swing/OB/FVG/PVA) is computed locally
    by the pinned analyzer, never approximated here."""

    closes = [float(c["close"]) for c in candles]
    volumes = [float(c["volume"]) for c in candles]
    last, prev = candles[-1], candles[-2] if len(candles) > 1 else None
    recent20 = candles[-20:]
    recent60 = candles[-60:]
    return {
        "last_close": float(last["close"]),
        "prev_close": float(prev["close"]) if prev else None,
        "change_pct": _round((last["close"] / prev["close"] - 1) * 100, 2) if prev else None,
        "ma5": _round(_sma(closes, 5)),
        "ma20": _round(_sma(closes, 20)),
        "ma60": _round(_sma(closes, 60)),
        "ma120": _round(_sma(closes, 120)),
        "ma240": _round(_sma(closes, 240)),
        "atr14": _round(_atr(candles, 14)),
        "high20": max(float(c["high"]) for c in recent20),
        "low20": min(float(c["low"]) for c in recent20),
        "high60": max(float(c["high"]) for c in recent60),
        "low60": min(float(c["low"]) for c in recent60),
        "volume_ma20": _round(_sma(volumes, 20), 0),
        "last_volume": float(last["volume"]),
    }


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def fundamental_payload(raw: Mapping[str, Any], last_close: float) -> tuple[dict[str, Any], list[str]]:
    """Quarterly facts from the repo cache, plus PE recomputed from the close.

    A metric that cannot be computed is listed in ``missing``, never zeroed.
    """

    quarters = [q for q in raw.get("quarters") or [] if isinstance(q, Mapping)]
    if not quarters:
        raise QueueInputError("fundamentals have no quarters")
    missing = [str(m) for m in raw.get("missing") or []]
    valuation = dict(raw.get("valuation") or {})
    ttm_eps = _num(valuation.get("ttm_eps"))
    if ttm_eps is not None and ttm_eps > 0:
        valuation["pe"] = round(last_close / ttm_eps, 2)
        valuation["pe_basis"] = "snapshot_close / ttm_eps"
    else:
        missing.append("valuation.pe unavailable (ttm_eps missing or non-positive)")
    payload = {
        "fiscal_quarter": raw.get("fiscal_quarter") or quarters[0].get("period"),
        "quarters": quarters[:8],
        "health": raw.get("health") or {},
        "valuation": valuation,
        "basis": raw.get("basis"),
        "currency": raw.get("currency"),
        "source": raw.get("source"),
    }
    return payload, missing


# --- DB ---------------------------------------------------------------------

BAR_UPSERT_SQL = """
INSERT INTO radar.daily_bar (
  symbol, trade_date, exchange, open, high, low, close, volume, source_url, fetched_at
) VALUES (
  %(symbol)s, %(trade_date)s, %(exchange)s, %(open)s, %(high)s, %(low)s,
  %(close)s, %(volume)s, %(source_url)s, %(fetched_at)s
)
ON CONFLICT (symbol, trade_date) DO UPDATE SET
  open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
  close = EXCLUDED.close, volume = EXCLUDED.volume,
  source_url = EXCLUDED.source_url, fetched_at = EXCLUDED.fetched_at,
  updated_at = now()
""".strip()

BARS_SELECT_SQL = """
SELECT trade_date, open, high, low, close, volume, fetched_at
FROM radar.daily_bar WHERE symbol = %s AND trade_date >= %s AND trade_date <= %s
ORDER BY trade_date
""".strip()

BATCH_EXISTS_SQL = "SELECT 1 FROM radar.analysis_batch WHERE report_date = %s"

BATCH_INSERT_SQL = """
INSERT INTO radar.analysis_batch (
  report_date, data_as_of, candidate_as_of, selection_rule, selected_count,
  excluded, prepared_at, prepared_run_id
) VALUES (
  %(report_date)s, %(data_as_of)s, %(candidate_as_of)s, %(selection_rule)s,
  %(selected_count)s, %(excluded)s::jsonb, %(prepared_at)s, %(prepared_run_id)s
)
ON CONFLICT (report_date) DO NOTHING
""".strip()

QUEUE_INSERT_SQL = """
INSERT INTO radar.analysis_queue (
  report_date, symbol, rank, instrument_id, exchange, name_zh, selected_by,
  short_rank, short_score, long_rank, long_score, themes
) VALUES (
  %(report_date)s, %(symbol)s, %(rank)s, %(instrument_id)s, %(exchange)s,
  %(name_zh)s, %(selected_by)s, %(short_rank)s, %(short_score)s,
  %(long_rank)s, %(long_score)s, %(themes)s::jsonb
)
""".strip()

TECHNICAL_UPSERT_SQL = """
INSERT INTO radar.technical_snapshot (
  symbol, data_as_of, exchange, bar_count, last_close, candles, metrics,
  candles_sha256, prepared_at
) VALUES (
  %(symbol)s, %(data_as_of)s, %(exchange)s, %(bar_count)s, %(last_close)s,
  %(candles)s::jsonb, %(metrics)s::jsonb, %(candles_sha256)s, %(prepared_at)s
)
ON CONFLICT (symbol, data_as_of) DO UPDATE SET
  bar_count = EXCLUDED.bar_count, last_close = EXCLUDED.last_close,
  candles = EXCLUDED.candles, metrics = EXCLUDED.metrics,
  candles_sha256 = EXCLUDED.candles_sha256, prepared_at = EXCLUDED.prepared_at,
  updated_at = now()
""".strip()

FUNDAMENTAL_UPSERT_SQL = """
INSERT INTO radar.fundamental_snapshot (
  symbol, data_as_of, fiscal_quarter, payload, missing, source_fetched_at,
  payload_sha256, prepared_at
) VALUES (
  %(symbol)s, %(data_as_of)s, %(fiscal_quarter)s, %(payload)s::jsonb,
  %(missing)s, %(source_fetched_at)s, %(payload_sha256)s, %(prepared_at)s
)
ON CONFLICT (symbol, data_as_of) DO UPDATE SET
  fiscal_quarter = EXCLUDED.fiscal_quarter, payload = EXCLUDED.payload,
  missing = EXCLUDED.missing, source_fetched_at = EXCLUDED.source_fetched_at,
  payload_sha256 = EXCLUDED.payload_sha256, prepared_at = EXCLUDED.prepared_at,
  updated_at = now()
""".strip()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class BarStore:
    """Cached bars per symbol: DB first, then only the months that are not
    closed-and-complete in the cache. New bars are buffered for one write."""

    def __init__(self, connection: Any, fetcher: BarFetcher, *, now: datetime) -> None:
        self.connection = connection
        self.fetcher = fetcher
        self.now = now
        self.pending: list[dict[str, Any]] = []

    def load(self, symbol: str, exchange: str, *, through: date) -> list[dict[str, Any]]:
        start = (through.replace(day=1) - timedelta(days=HISTORY_MONTHS * 31)).replace(day=1)
        with self.connection.cursor() as cursor:
            cursor.execute(BARS_SELECT_SQL, (symbol, start, through))
            rows = cursor.fetchall()
        bars: dict[str, dict[str, Any]] = {}
        complete_months: set[date] = set()
        for trade_date, o, h, low, c, v, fetched_at in rows:
            bars[trade_date.isoformat()] = {
                "date": trade_date.isoformat(), "open": float(o), "high": float(h),
                "low": float(low), "close": float(c), "volume": float(v),
            }
            month = trade_date.replace(day=1)
            fetched_day = fetched_at.astimezone(TAIPEI).date()
            if fetched_day > month_end(month):
                complete_months.add(month)
        for month in months_between(start, through):
            if month in complete_months:
                continue
            fetched = self.fetcher.month(symbol, exchange, month)
            if fetched is None:
                continue  # budget exhausted; logged as deferred
            url = month_url(symbol, exchange, month)
            for bar in fetched:
                if bar["date"] > through.isoformat():
                    continue
                bars[bar["date"]] = bar
                self.pending.append(
                    {"symbol": symbol, "trade_date": bar["date"], "exchange": exchange,
                     **{k: bar[k] for k in ("open", "high", "low", "close", "volume")},
                     "source_url": url, "fetched_at": self.now}
                )
        return [bars[key] for key in sorted(bars)]

    def flush(self) -> int:
        if not self.pending:
            return 0
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.executemany(BAR_UPSERT_SQL, self.pending)
        written = len(self.pending)
        self.pending = []
        return written


# --- orchestration ----------------------------------------------------------


def edition_for(now: datetime) -> date | None:
    """Morning edition date in Taipei, or None on a weekend.

    Exchange holidays on weekdays are not detected here (see docs); the local
    task still refuses a batch whose data_as_of has no new session.
    """

    today = now.astimezone(TAIPEI).date()
    return None if today.weekday() >= 5 else today


def load_fundamentals(symbol: str, exchange: str, directory: Path = FUNDAMENTALS_DIR) -> Mapping[str, Any] | None:
    path = directory / f"{exchange}-{symbol}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@dataclass
class Prepared:
    candidate: Candidate
    candles: list[dict[str, Any]]
    fundamentals: Mapping[str, Any]


def prepare_batch(
    connection: Any,
    *,
    watchlist: Mapping[str, Any],
    report_date: date,
    now: datetime,
    fetcher: BarFetcher,
    short_slots: int = DEFAULT_SHORT_SLOTS,
    long_slots: int = DEFAULT_LONG_SLOTS,
    fundamentals_loader: Callable[[str, str], Mapping[str, Any] | None] = load_fundamentals,
    run_id: str | None = None,
    allow_partial: bool = True,
) -> dict[str, Any]:
    """Prepare and freeze one edition. Returns a run summary."""

    with connection.cursor() as cursor:
        cursor.execute(BATCH_EXISTS_SQL, (report_date,))
        if cursor.fetchone():
            return {"analysis_queue": "already_prepared", "report_date": report_date.isoformat()}

    store = BarStore(connection, fetcher, now=now)
    through = report_date - timedelta(days=1)
    reference = store.load(*REFERENCE_SYMBOL, through=through)
    if not reference:
        raise QueueInputError("reference symbol has no observed session before the edition")
    data_as_of = date.fromisoformat(reference[-1]["date"])
    if (report_date - data_as_of).days > 5:
        raise QueueInputError(f"latest observed session {data_as_of} is too old for {report_date}")

    prepared: dict[str, Prepared] = {}

    def eligible(candidate: Candidate) -> str | None:
        try:
            candles = store.load(candidate.symbol, candidate.exchange, through=through)
        except Exception as error:  # noqa: BLE001 - one symbol never fails the batch
            return f"quote_fetch_failed: {redact_error(error)[:120]}"
        if not candles:
            return "no_observed_quotes"
        if candles[-1]["date"] != data_as_of.isoformat():
            return f"stale_last_bar {candles[-1]['date']}"
        if len(candles) < MIN_TECHNICAL_BARS:
            return f"insufficient_history {len(candles)}<{MIN_TECHNICAL_BARS}"
        raw = fundamentals_loader(candidate.symbol, candidate.exchange)
        if not raw:
            return "fundamentals_missing"
        try:
            fundamental_payload(raw, candles[-1]["close"])
        except QueueInputError as error:
            return f"fundamentals_invalid: {error}"
        prepared[candidate.symbol] = Prepared(candidate, candles, raw)
        return None

    short_pool, long_pool = candidate_pools(watchlist)
    selection = select_candidates(
        short_pool, long_pool, eligible, short_slots=short_slots, long_slots=long_slots
    )
    bars_written = store.flush()
    if fetcher.deferred and len(selection.picked) < QUEUE_SIZE and not allow_partial:
        # The budget, not the data, is short: keep the bars, freeze later.
        return {
            "analysis_queue": "incomplete_retry",
            "report_date": report_date.isoformat(),
            "selected": len(selection.picked),
            "bars_written": bars_written,
            "deferred": len(fetcher.deferred),
        }

    run_id = run_id or f"aq-{report_date:%Y%m%d}-{uuid.uuid4().hex[:8]}"
    technical_rows, fundamental_rows, queue_rows = [], [], []
    for rank, (candidate, horizon) in enumerate(selection.picked, start=1):
        item = prepared[candidate.symbol]
        metrics = technical_metrics(item.candles)
        technical_rows.append({
            "symbol": candidate.symbol, "data_as_of": data_as_of, "exchange": candidate.exchange,
            "bar_count": len(item.candles), "last_close": metrics["last_close"],
            "candles": _json(item.candles), "metrics": _json(metrics),
            "candles_sha256": canonical_sha256(item.candles), "prepared_at": now,
        })
        payload, missing = fundamental_payload(item.fundamentals, metrics["last_close"])
        fetched_raw = item.fundamentals.get("fetched_at")
        fundamental_rows.append({
            "symbol": candidate.symbol, "data_as_of": data_as_of,
            "fiscal_quarter": str(payload["fiscal_quarter"]), "payload": _json(payload),
            "missing": missing,
            "source_fetched_at": (
                datetime.fromisoformat(str(fetched_raw).replace("Z", "+00:00")) if fetched_raw else None
            ),
            "payload_sha256": canonical_sha256(payload), "prepared_at": now,
        })
        queue_rows.append({
            "report_date": report_date, "symbol": candidate.symbol, "rank": rank,
            "instrument_id": candidate.instrument_id, "exchange": candidate.exchange,
            "name_zh": candidate.name_zh, "selected_by": horizon,
            "short_rank": candidate.short_rank, "short_score": candidate.short_score,
            "long_rank": candidate.long_rank, "long_score": candidate.long_score,
            "themes": _json(list(candidate.themes)),
        })

    candidate_as_of = watchlist.get("candidate_as_of")
    batch = {
        "report_date": report_date, "data_as_of": data_as_of,
        "candidate_as_of": (
            datetime.fromisoformat(str(candidate_as_of).replace("Z", "+00:00")) if candidate_as_of else None
        ),
        "selection_rule": SELECTION_RULE_TEMPLATE.format(short=short_slots, long=long_slots),
        "selected_count": len(queue_rows),
        "excluded": _json(selection.excluded + [
            {"symbol": d.split(":")[0], "reason": f"fetch_deferred {d}"} for d in fetcher.deferred
        ]),
        "prepared_at": now, "prepared_run_id": run_id,
    }
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(BATCH_INSERT_SQL, batch)
            if cursor.rowcount == 0:
                return {"analysis_queue": "already_prepared", "report_date": report_date.isoformat()}
            if technical_rows:
                cursor.executemany(TECHNICAL_UPSERT_SQL, technical_rows)
                cursor.executemany(FUNDAMENTAL_UPSERT_SQL, fundamental_rows)
                cursor.executemany(QUEUE_INSERT_SQL, queue_rows)
    return {
        "analysis_queue": "prepared",
        "report_date": report_date.isoformat(),
        "data_as_of": data_as_of.isoformat(),
        "selected": [row["symbol"] for row in queue_rows],
        "excluded": selection.excluded,
        "bars_written": bars_written,
        "requests": fetcher.requests,
        "deferred": fetcher.deferred,
        "run_id": run_id,
    }


def warm_cache(
    connection: Any,
    *,
    watchlist: Mapping[str, Any],
    through: date,
    now: datetime,
    fetcher: BarFetcher,
    depth: int = 20,
) -> dict[str, Any]:
    """Fill the bar cache for the top ``depth`` of each pool (no batch written)."""

    store = BarStore(connection, fetcher, now=now)
    short_pool, long_pool = candidate_pools(watchlist)
    seen: list[Candidate] = []
    for candidate in [*short_pool[:depth], *long_pool[:depth]]:
        if candidate.symbol not in {c.symbol for c in seen}:
            seen.append(candidate)
    failed = []
    for candidate in seen:
        try:
            store.load(candidate.symbol, candidate.exchange, through=through)
        except Exception as error:  # noqa: BLE001
            failed.append({"symbol": candidate.symbol, "error": redact_error(error)[:120]})
    written = store.flush()
    return {"analysis_cache": "warmed", "symbols": len(seen), "bars_written": written,
            "requests": fetcher.requests, "deferred": fetcher.deferred, "failed": failed}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mode", choices=("prepare", "warm"), default="prepare")
    parser.add_argument("--watchlist", type=Path, default=WATCHLIST_PATH)
    parser.add_argument("--report-date", help="YYYY-MM-DD edition (default: today in Taipei)")
    parser.add_argument("--short-slots", type=int, default=DEFAULT_SHORT_SLOTS)
    parser.add_argument("--long-slots", type=int, default=DEFAULT_LONG_SLOTS)
    parser.add_argument("--fetch-budget", type=int, default=None)
    parser.add_argument("--allow-partial", action="store_true",
                        help="freeze even if the fetch budget deferred some months")
    parser.add_argument("--warm-depth", type=int, default=20)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    now = datetime.now(timezone.utc)
    dsn = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not dsn:
        LOGGER.warning("analysis_queue_skipped reason=credential_unavailable")
        print(json.dumps({"analysis_queue": "skipped"}))
        return 0
    report_date = date.fromisoformat(args.report_date) if args.report_date else edition_for(now)
    if args.mode == "prepare" and report_date is None:
        LOGGER.info("analysis_queue_skipped reason=weekend")
        print(json.dumps({"analysis_queue": "skipped", "reason": "weekend"}))
        return 0

    watchlist = json.loads(args.watchlist.read_text(encoding="utf-8"))
    budget = args.fetch_budget or DEFAULT_FETCH_BUDGET[args.mode]
    fetcher = BarFetcher(_requests_get_json, budget=budget)
    local_now = now.astimezone(TAIPEI)
    allow_partial = args.allow_partial or (local_now.hour, local_now.minute) >= FREEZE_PARTIAL_AFTER
    import psycopg

    try:
        with psycopg.connect(dsn, autocommit=True) as connection:
            if args.mode == "warm":
                through = now.astimezone(TAIPEI).date()
                summary = warm_cache(connection, watchlist=watchlist, through=through, now=now,
                                     fetcher=fetcher, depth=args.warm_depth)
            else:
                summary = prepare_batch(
                    connection, watchlist=watchlist, report_date=report_date, now=now,
                    fetcher=fetcher, short_slots=args.short_slots, long_slots=args.long_slots,
                    allow_partial=allow_partial,
                )
    except Exception as error:  # noqa: BLE001 - logged redacted; the next cron slot retries
        LOGGER.error("analysis_queue_failed error=%s", redact_error(error))
        print(json.dumps({"analysis_queue": "failed"}))
        return 1
    print(json.dumps(summary, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
