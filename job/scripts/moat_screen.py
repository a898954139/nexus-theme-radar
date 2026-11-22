"""Moat screen: absolute fundamental gates over the fixed fundamentals universe.

The stock watchlist used to rank whatever the hourly theme candidates were,
with fundamentals only as a percentile *inside* that changing candidate list
(docs/MISTAKES.md M018). This module evaluates every cached statement file in
``data/fundamentals`` (the fixed universe) against absolute thresholds, so a
stock either has the economics or it does not, regardless of which other names
the news happened to touch this hour.

Rule set ``moat_v1`` (user decision 2026-11-22, option C):

* short horizon: ROE TTM >= 8%, 4-quarter average gross margin >= 15%,
  debt ratio <= 60%;
* long horizon: the short rules plus TTM operating cash flow > 0.

Short-term names may burn cash while building inventory in an up-cycle
(memory makers in 2026H2), so cash flow gates only the long horizon.

Every metric is computed from the cached statements; a metric that cannot be
computed is ``None`` and fails its rule (recorded as ``<rule>_missing``). Nothing
is imputed. Rule-based on purpose: the hourly run must be reproducible.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

RULE_VERSION = "moat_v1"
THRESHOLDS = {
    "roe_ttm_min": 0.08,
    "gross_margin_4q_min": 0.15,
    "debt_ratio_max": 0.60,
    "operating_cash_flow_ttm_min_exclusive": 0.0,
}
SHORT_RULES = ("roe_ttm", "gross_margin_4q", "debt_ratio")
LONG_RULES = (*SHORT_RULES, "operating_cash_flow_ttm")
MOAT_SCREEN_FILENAME = "moat-screen.json"
_FILE_PATTERN = re.compile(r"^(TWSE|TPEX)-([A-Z0-9]{1,12})\.json$")
_PERIOD_PATTERN = re.compile(r"^(\d{4})Q([1-4])$")


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _quarter_index(period: str) -> int | None:
    match = _PERIOD_PATTERN.fullmatch(str(period))
    return int(match.group(1)) * 4 + int(match.group(2)) - 1 if match else None


def _latest_consecutive(periods: Mapping[str, Any], count: int = 4) -> list[str] | None:
    """The latest ``count`` quarters, only if they are consecutive."""
    indexed = sorted(
        ((index, period) for period in periods if (index := _quarter_index(period)) is not None),
        reverse=True,
    )[:count]
    if len(indexed) < count:
        return None
    if any(indexed[i][0] - indexed[i + 1][0] != 1 for i in range(count - 1)):
        return None
    return [period for _, period in indexed]


def _ttm_sum(table: Any, field: str) -> float | None:
    if not isinstance(table, Mapping):
        return None
    periods = _latest_consecutive(table)
    if periods is None:
        return None
    values = [_number((table.get(period) or {}).get(field)) for period in periods]
    return sum(values) if all(value is not None for value in values) else None


def moat_metrics(payload: Mapping[str, Any]) -> dict[str, float | None]:
    """Compute the four moat metrics from one cached fundamentals file."""
    statements = payload.get("statements") if isinstance(payload.get("statements"), Mapping) else {}
    net_income_ttm = _ttm_sum(statements.get("income"), "net_income")
    balance = statements.get("balance") if isinstance(statements.get("balance"), Mapping) else {}
    latest_balance = max(balance, key=lambda p: _quarter_index(p) or -1) if balance else None
    equity = _number((balance.get(latest_balance) or {}).get("total_equity")) if latest_balance else None
    roe = net_income_ttm / equity if net_income_ttm is not None and equity and equity > 0 else None

    quarters = [q for q in (payload.get("quarters") or []) if isinstance(q, Mapping)]
    by_period = {str(q.get("period")): q for q in quarters}
    margin_periods = _latest_consecutive(by_period)
    margins = [_number(by_period[p].get("gross_margin")) for p in margin_periods] if margin_periods else []
    gross_margin = sum(margins) / 4 if len(margins) == 4 and all(m is not None for m in margins) else None

    health = payload.get("health") if isinstance(payload.get("health"), Mapping) else {}
    return {
        "roe_ttm": roe,
        "gross_margin_4q": gross_margin,
        "debt_ratio": _number(health.get("debt_ratio")),
        "operating_cash_flow_ttm": _ttm_sum(statements.get("cash_flow"), "operating"),
    }


def failed_rules(metrics: Mapping[str, float | None]) -> list[str]:
    checks = {
        "roe_ttm": lambda v: v >= THRESHOLDS["roe_ttm_min"],
        "gross_margin_4q": lambda v: v >= THRESHOLDS["gross_margin_4q_min"],
        "debt_ratio": lambda v: v <= THRESHOLDS["debt_ratio_max"],
        "operating_cash_flow_ttm": lambda v: v > THRESHOLDS["operating_cash_flow_ttm_min_exclusive"],
    }
    failures = []
    for rule in LONG_RULES:
        value = metrics.get(rule)
        if value is None:
            failures.append(f"{rule}_missing")
        elif not checks[rule](value):
            failures.append(rule)
    return failures


def evaluate(payload: Mapping[str, Any]) -> dict[str, Any]:
    metrics = moat_metrics(payload)
    failures = failed_rules(metrics)
    failed_base = {failure.removesuffix("_missing") for failure in failures}
    return {
        "metrics": metrics,
        "failed": failures,
        "short_pass": not failed_base.intersection(SHORT_RULES),
        "long_pass": not failed_base,
    }


def load_fundamentals_universe(fundamentals_dir: Path) -> dict[str, dict[str, Any]]:
    """instrument_id -> cached statement payload, for every file in the cache."""
    universe: dict[str, dict[str, Any]] = {}
    directory = Path(fundamentals_dir)
    if not directory.is_dir():
        return universe
    for path in sorted(directory.iterdir()):
        match = _FILE_PATTERN.fullmatch(path.name)
        if not match:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            universe[f"{match.group(1)}:{match.group(2)}"] = payload
    return universe


def screen_universe(universe: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    return {instrument_id: evaluate(payload) for instrument_id, payload in sorted(universe.items())}


def screen_summary(
    screened: Mapping[str, Mapping[str, Any]],
    *,
    generated_at: str,
    candidate_ids: set[str] | None = None,
) -> dict[str, Any]:
    """The local ``moat-screen.json`` state file: counts plus per-name detail."""
    def counts(ids: set[str]) -> dict[str, int]:
        rows = [screened[i] for i in ids if i in screened]
        return {
            "evaluated": len(rows),
            "short_pass": sum(1 for r in rows if r["short_pass"]),
            "long_pass": sum(1 for r in rows if r["long_pass"]),
            "no_fundamentals": len(ids) - len(rows),
        }

    failure_counts: dict[str, int] = {}
    for row in screened.values():
        for failure in row["failed"]:
            failure_counts[failure] = failure_counts.get(failure, 0) + 1
    return {
        "rule_version": RULE_VERSION,
        "generated_at": generated_at,
        "thresholds": dict(THRESHOLDS),
        "short_rules": list(SHORT_RULES),
        "long_rules": list(LONG_RULES),
        "universe": counts(set(screened)),
        "candidates": counts(candidate_ids) if candidate_ids is not None else None,
        "failure_counts": dict(sorted(failure_counts.items())),
        "symbols": {
            instrument_id: {
                "short_pass": row["short_pass"],
                "long_pass": row["long_pass"],
                "failed": row["failed"],
                "metrics": {k: (round(v, 6) if v is not None else None) for k, v in row["metrics"].items()},
            }
            for instrument_id, row in screened.items()
        },
    }
