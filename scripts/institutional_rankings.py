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
