"""Money-flow leaderboards, cross-marked against our own symbol universe.

Unlike the per-stock flows, these come from an upstream project rather than an
exchange, so the base URL is a single constant: the current host is the upstream
author's custom domain, and a fork with Pages enabled would only change this
line.

Two hazards, both invisible until the page renders wrong:

The payload shape is not consistent between metrics. ``netbuy`` wraps its rows
in an object carrying the unit and date range; ``change`` is a bare list. Code
written against one reads nothing from the other and shows an empty board
rather than failing.

And the boards are dominated by leveraged and thematic ETFs, whose unit counts
move for reasons unrelated to conviction in a company. Some report a
three-institution holding ratio above 100% -- arithmetically impossible for a
share of shares outstanding, and a sign the denominator is something else.
Both are flagged rather than dropped, so the page can choose and the published
ranks still describe the source data.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping, Sequence

LOGGER = logging.getLogger(__name__)

RANKINGS_FILE = "institutional-rankings.json"
SCHEMA_VERSION = 1

# Upstream is voidful/tw-institutional-stocker, served from the author's custom
# domain. Anthony's fork has Pages disabled and 404s, so switching to it is a
# one-line change here once that is turned on.
INSTITUTIONAL_BASE_URL = "https://eric-lam.com/tw-institutional-stocker/data"

RANKING_METRICS = ("netbuy", "change")
RANKING_WINDOWS = (5, 10, 20, 30)
RANKING_SIDES = ("up", "down")

# A share of shares outstanding cannot exceed 100%. Anything above it is a
# different denominator, not a very crowded stock.
MAX_PLAUSIBLE_RATIO = 100.0

# Taiwan ETF codes start 00. Leveraged/inverse/active variants add a letter.
_ETF_CODE = re.compile(r"^00\d{2,4}[A-Z]?$")


def ranking_key(metric: str, window: int, side: str) -> str:
    return f"top_three_inst_{metric}_{window}_{side}"


def ranking_url(metric: str, window: int, side: str, *, base_url: str = INSTITUTIONAL_BASE_URL) -> str:
    return f"{base_url}/{ranking_key(metric, window, side)}.json"


def is_probable_etf(code: str) -> bool:
    return bool(_ETF_CODE.match(str(code).strip()))


def _rows_and_meta(payload: Any) -> tuple[Sequence[Any], Mapping[str, Any]]:
    """Normalise the two published shapes into (rows, metadata)."""
    if isinstance(payload, Mapping):
        rows = payload.get("data")
        return (rows if isinstance(rows, Sequence) else []), payload
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return payload, {}
    return [], {}


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_ranking(payload: Any, *, universe: set[str]) -> dict[str, Any]:
    """Normalise one leaderboard and mark the entries we care about."""
    rows, meta = _rows_and_meta(payload)

    entries: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        code = str(row.get("code", "")).strip()
        if not code:
            continue

        # The feed calls it "market"; ours is "exchange". TPEX is published as
        # TPEX, matching our instrument ids.
        exchange = str(row.get("market", "TWSE")).strip().upper() or "TWSE"
        instrument_id = f"{exchange}:{code}"
        ratio = _to_float(row.get("three_inst_ratio"))

        entry: dict[str, Any] = {
            "code": code,
            "name": str(row.get("name", "")).strip(),
            "exchange": exchange,
            "instrument_id": instrument_id,
            "in_universe": instrument_id in universe,
            "is_etf": is_probable_etf(code),
            "ratio_out_of_range": ratio is not None and ratio > MAX_PLAUSIBLE_RATIO,
        }
        for field in ("rank", "foreign", "trust", "dealer", "total",
                      "three_inst_ratio", "change"):
            if field in row:
                entry[field] = row[field]
        entries.append(entry)

    return {
        "metric": meta.get("metric"),
        "window": meta.get("window"),
        "side": meta.get("side"),
        "unit": meta.get("unit"),
        "updated": meta.get("updated"),
        "date_range": meta.get("date_range"),
        "entries": entries,
    }


def fetch_ranking(
    session: Any,
    metric: str,
    window: int,
    side: str,
    *,
    universe: set[str],
    base_url: str = INSTITUTIONAL_BASE_URL,
    timeout: float = 30.0,
) -> dict[str, Any]:
    response = session.get(ranking_url(metric, window, side, base_url=base_url), timeout=timeout)
    response.raise_for_status()
    parsed = parse_ranking(response.json(), universe=universe)
    # The bare-list shape carries no metadata, so fill in what we requested.
    parsed["metric"] = parsed["metric"] or metric
    parsed["window"] = parsed["window"] or window
    parsed["side"] = parsed["side"] or side
    return parsed


# ---------------------------------------------------------------------------
# Official net buy/sell boards
#
# The upstream ``netbuy`` boards lag the exchanges by days (their date_range is
# whatever the upstream job last ran on), while scripts/update_institutional_flows.py
# already stores the official TWSE T86 / TPEX per-symbol series for the whole
# market under data/flows/. Ranking from those keeps the board on the same
# trading day as every other flows view. ``change`` (holding-ratio change)
# still comes from upstream: the exchanges' daily files carry no shares
# outstanding to compute it from.
# ---------------------------------------------------------------------------

OFFICIAL_SOURCE = "TWSE T86 / TPEX 三大法人買賣超（官方）"


def _official_rows(payload: Any) -> list[tuple[str, float, float, float, float]]:
    series = payload.get("series") if isinstance(payload, Mapping) else None
    rows: list[tuple[str, float, float, float, float]] = []
    for row in series if isinstance(series, list) else []:
        if not isinstance(row, (list, tuple)) or len(row) < 5 or not isinstance(row[0], str):
            continue
        values = [_to_float(value) for value in row[1:5]]
        if any(value is None for value in values):
            continue
        rows.append((row[0], *values))  # type: ignore[arg-type]
    return rows


def official_netbuy_boards(
    symbol_payloads: Mapping[str, Any],
    *,
    universe: set[str],
    top_n: int,
    generated_at: str,
    windows: Sequence[int] = RANKING_WINDOWS,
) -> dict[str, dict[str, Any]]:
    """Build every ``top_three_inst_netbuy_{window}_{side}`` board from the
    official per-symbol series, in lots (張) like the upstream boards.

    Windows are counted in market trading days (the dates any symbol traded),
    not per-symbol rows, so a symbol that missed a day is summed over the same
    calendar span as everyone else rather than reaching further back.
    """
    per_symbol: dict[str, tuple[str, list[tuple[str, float, float, float, float]]]] = {}
    market_dates: set[str] = set()
    for instrument_id, payload in symbol_payloads.items():
        rows = _official_rows(payload)
        if not rows:
            continue
        name = str(payload.get("name", "")).strip() if isinstance(payload, Mapping) else ""
        per_symbol[instrument_id] = (name, rows)
        market_dates.update(row[0] for row in rows)
    dates = sorted(market_dates, reverse=True)
    boards: dict[str, dict[str, Any]] = {}
    if not dates:
        return boards

    for window in windows:
        span = set(dates[:window])
        start, end = min(span), max(span)
        totals: list[dict[str, Any]] = []
        for instrument_id, (name, rows) in per_symbol.items():
            in_span = [row for row in rows if row[0] in span]
            if not in_span or not any(row[0] == end for row in in_span):
                # Not traded on the latest day: a suspended or delisted symbol
                # should not sit on today's board on old numbers.
                continue
            exchange, _, code = instrument_id.partition(":")
            totals.append({
                "code": code,
                "name": name,
                "exchange": exchange,
                "instrument_id": instrument_id,
                "in_universe": instrument_id in universe,
                "is_etf": is_probable_etf(code),
                "ratio_out_of_range": False,
                "foreign": round(sum(row[1] for row in in_span) / 1000),
                "trust": round(sum(row[2] for row in in_span) / 1000),
                "dealer": round(sum(row[3] for row in in_span) / 1000),
                "total": round(sum(row[4] for row in in_span) / 1000),
                "days": len(in_span),
            })
        for side in RANKING_SIDES:
            ordered = sorted(
                (entry for entry in totals if (entry["total"] > 0 if side == "up" else entry["total"] < 0)),
                key=lambda entry: entry["total"],
                reverse=side == "up",
            )
            ranked = [{**entry, "rank": index} for index, entry in enumerate(ordered, start=1)]
            # top_n stocks and top_n ETFs kept separately: leveraged and
            # inverse ETFs fill the head of the board, and the page hides ETFs
            # by default, so one shared cut would leave it a handful of stocks.
            stocks = [entry for entry in ranked if not entry["is_etf"]]
            etfs = [entry for entry in ranked if entry["is_etf"]]
            keep_ids = {entry["instrument_id"] for entry in stocks[:top_n] + etfs[:top_n]}
            kept = [entry for entry in ranked if entry["instrument_id"] in keep_ids or entry["in_universe"]]
            boards[ranking_key("netbuy", window, side)] = {
                "metric": "net_buy_sell",
                "window": window,
                "side": side,
                "unit": "張",
                "updated": generated_at,
                "date_range": {"start": start, "end": end},
                "source": OFFICIAL_SOURCE,
                "entries": kept,
                "source_rows": len(ranked),
            }
    return boards
