"""Deterministic stock watchlist projector for the public theme radar."""

from __future__ import annotations

import json
import math
import re
import tempfile
from collections.abc import Mapping
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

PUBLIC_STOCK_WATCHLIST_FILENAME = "public-stock-watchlist-v1.json"
SCHEMA_VERSION = "nexus_stock_watchlist.v1"
METHODOLOGY_VERSION = "stock_watchlist_v1"

SHORT_WEIGHTS = {
    "theme_attention": 0.55,
    "institutional_short_activity": 0.20,
    "daytrade_activity": 0.15,
    "fundamental_defense": 0.10,
}
LONG_WEIGHTS = {
    "fundamental_quality": 0.60,
    "institutional_support": 0.20,
    "theme_persistence": 0.15,
    "trading_stability": 0.05,
}

TOP_KEYS = {
    "schema_version",
    "methodology_version",
    "generated_at",
    "candidate_as_of",
    "sources",
    "methodology",
    "coverage",
    "short",
    "long",
    "searchable",
}
ITEM_KEYS = {
    "instrument",
    "themes",
    "short",
    "long",
    "institutional",
    "trading_activity",
    "fundamentals",
    "flags",
    "coverage",
}
INSTRUMENT_KEYS = {"instrument_id", "symbol", "exchange", "name_zh"}
THEME_KEYS = {
    "theme_id",
    "name_zh",
    "relation",
    "heat_score",
    "heat_change_24h",
    "momentum_score",
}
COMPONENT_KEYS = {"raw", "normalized", "base_weight", "effective_weight", "available"}
SEARCHABLE_KEYS = {
    "instrument",
    "themes",
    "selected_top50",
    "short_rank",
    "long_rank",
    "flags",
}
SCORE_KEYS = {"rank", "score", "components"}
SHORT_SCORE_KEYS = SCORE_KEYS | {"risk_adjustment"}
INSTITUTIONAL_KEYS = {"direction", "as_of", "observation_count", "five_day_net"}
TRADING_ACTIVITY_KEYS = {
    "as_of",
    "day_trading_volume",
    "total_volume",
    "day_trading_volume_ratio",
    "overnight_risk",
    "overnight_missing_reason",
}
FUNDAMENTALS_KEYS = {
    "score",
    "fiscal_quarter",
    "comparison_basis",
    "revenue_growth",
    "revenue_direction",
    "eps_growth",
    "eps_direction",
    "gross_margin",
    "operating_margin",
    "operating_cash_flow",
    "operating_cash_flow_margin",
    "debt_ratio",
}
FLAG_KEYS = {"key", "type"}
COVERAGE_KEYS = {"short_ratio", "long_ratio", "missing"}
LIST_KEYS = {"count", "items"}
TOP_COVERAGE_KEYS = {"eligible_count", "selected_count", "metrics", "missing_reasons"}
SOURCES_KEYS = {"momentum", "institutional", "fundamentals", "day_trading_activity"}
MOMENTUM_SOURCE_KEYS = {"generated_at", "observed_hour"}
INSTITUTIONAL_SOURCE_KEYS = {"as_of"}
FUNDAMENTALS_SOURCE_KEYS = {"fiscal_quarters"}
METHODOLOGY_KEYS = {
    "missing_values",
    "top50",
    "short_weights",
    "long_weights",
    "fundamental_quality_weights",
}
DAY_TRADING_SOURCE_KEYS = {
    "as_of",
    "finality",
    "numerator_url",
    "denominator_url",
    "status",
    "error",
}
SAFE_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{1,12}$")


def _round_half_up(value: float, places: int = 2) -> float:
    quant = Decimal("1") if places == 0 else Decimal("1").scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def average_rank_percentiles(values: Mapping[str, float | int | None]) -> dict[str, int]:
    available = {key: float(value) for key, value in values.items() if value is not None}
    if not available:
        return {}
    if len(available) == 1 or len(set(available.values())) == 1:
        return {key: 50 for key in available}

    sorted_items = sorted(available.items(), key=lambda item: (item[1], item[0]))
    denominator = len(sorted_items) - 1
    result: dict[str, int] = {}
    index = 0
    while index < len(sorted_items):
        value = sorted_items[index][1]
        end = index
        while end + 1 < len(sorted_items) and sorted_items[end + 1][1] == value:
            end += 1
        average_rank = (index + end) / 2
        percentile = int(_round_half_up((average_rank / denominator) * 100, 0))
        for position in range(index, end + 1):
            result[sorted_items[position][0]] = percentile
        index = end + 1
    return result


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _instrument(symbol: Mapping[str, Any]) -> dict[str, Any] | None:
    instrument_id = str(symbol.get("instrument_id") or "").strip()
    market_id = str(symbol.get("market_id") or "").strip()
    asset_class = str(symbol.get("asset_class") or "").strip()
    if not instrument_id or market_id != "TW_EQUITY" or asset_class != "equity":
        return None
    exchange, _, code = instrument_id.partition(":")
    declared_exchange = str(symbol.get("exchange") or "").strip()
    declared_symbol = str(symbol.get("symbol") or "").strip()
    if (
        exchange not in {"TWSE", "TPEX"}
        or declared_exchange != exchange
        or declared_symbol != code
        or not SAFE_SYMBOL_PATTERN.fullmatch(code)
    ):
        return None
    return {
        "instrument_id": instrument_id,
        "symbol": code,
        "exchange": exchange,
        "name_zh": str(symbol.get("name_zh") or symbol.get("name") or code).strip(),
    }


def _candidate_index(momentum_payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for theme in momentum_payload.get("themes", []):
        for relation, factor, field in (
            ("direct", 1.0, "direct_symbols"),
            ("related", 0.85, "related_symbols"),
        ):
            for symbol in theme.get(field, []) or []:
                instrument = _instrument(symbol)
                if instrument is None:
                    continue
                instrument_id = instrument["instrument_id"]
                row = candidates.setdefault(
                    instrument_id,
                    {"instrument": instrument, "themes": [], "theme_attention_raw": None},
                )
                heat = _number(theme.get("heat_score"))
                momentum = _number(theme.get("momentum_score"))
                link_attention = (
                    (0.65 * heat + 0.35 * momentum) * factor
                    if heat is not None and momentum is not None
                    else None
                )
                theme_row = {
                    "theme_id": str(theme.get("theme_id") or ""),
                    "name_zh": str(theme.get("name_zh") or theme.get("theme_id") or ""),
                    "relation": relation,
                    "heat_score": heat,
                    "heat_change_24h": _number(theme.get("heat_change_24h")),
                    "momentum_score": momentum,
                    "_link_attention": link_attention,
                }
                if not any(existing["theme_id"] == theme_row["theme_id"] for existing in row["themes"]):
                    row["themes"].append(theme_row)
                if link_attention is not None:
                    current_attention = row["theme_attention_raw"]
                    row["theme_attention_raw"] = (
                        link_attention
                        if current_attention is None
                        else max(current_attention, link_attention)
                    )
    for row in candidates.values():
        row["themes"].sort(
            key=lambda theme: (
                theme["_link_attention"] is None,
                -theme["_link_attention"] if theme["_link_attention"] is not None else 0,
                theme["theme_id"],
            )
        )
        if row["theme_attention_raw"] is not None:
            row["theme_attention_raw"] = min(
                100.0,
                row["theme_attention_raw"] + 5 * min(max(len(row["themes"]) - 1, 0), 2),
            )
        for theme in row["themes"]:
            theme.pop("_link_attention", None)
    return candidates


def _series_rows(flow: Any) -> list[tuple[str | None, float]]:
    series = flow.get("series", []) if isinstance(flow, Mapping) else flow
    if not isinstance(series, list):
        return []
    rows: list[tuple[str | None, float]] = []
    for row in series:
        if isinstance(row, Mapping):
            value = _number(row.get("total_net"))
            as_of = str(row.get("date") or "").strip() or None
        elif isinstance(row, (list, tuple)) and row:
            value = _number(row[-1])
            as_of = str(row[0] or "").strip() or None
        else:
            continue
        if value is not None:
            rows.append((as_of, value))
    rows.sort(key=lambda item: item[0] or "", reverse=True)
    return rows[:5]


def _institutional(flow: Any) -> dict[str, Any]:
    rows = _series_rows(flow)
    if len(rows) < 3:
        return {
            "direction": "insufficient",
            "as_of": rows[0][0] if rows else None,
            "observation_count": len(rows),
            "five_day_net": None,
        }
    five_day_net = sum(value for _, value in rows)
    if five_day_net > 0:
        direction = "positive"
    elif five_day_net < 0:
        direction = "negative"
    else:
        direction = "flat"
    return {
        "direction": direction,
        "as_of": rows[0][0],
        "observation_count": len(rows),
        "five_day_net": five_day_net,
    }


def _growth(latest: Any, compare: Any) -> float | None:
    if latest is None or compare in (None, 0):
        return None
    try:
        return ((float(latest) - float(compare)) / abs(float(compare))) * 100
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _direction(value: float | None) -> str:
    if value is None:
        return "unknown"
    if abs(value) < 1:
        return "flat"
    return "up" if value > 0 else "down"


def _period_year_ago(period: Any) -> str | None:
    match = re.fullmatch(r"(\d{4})(Q[1-4])", str(period or ""))
    if not match:
        return None
    return f"{int(match.group(1)) - 1}{match.group(2)}"


def _latest_cash_flow(payload: Mapping[str, Any], latest_period: Any) -> float | None:
    health = payload.get("health") or {}
    if not isinstance(health, Mapping):
        return None
    return _number(health.get(f"operating_cash_flow_{latest_period}"))


def _fundamentals(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or not payload:
        return {
            "score": None,
            "fiscal_quarter": None,
            "comparison_basis": None,
            "revenue_growth": None,
            "revenue_direction": "unknown",
            "eps_growth": None,
            "eps_direction": "unknown",
            "gross_margin": None,
            "operating_margin": None,
            "operating_cash_flow": None,
            "operating_cash_flow_margin": None,
            "debt_ratio": None,
            "_metrics": {},
        }
    quarters = list(payload.get("quarters", []) or [])
    latest = quarters[0] if quarters else {}
    previous = quarters[1] if len(quarters) > 1 else {}
    year_ago_period = _period_year_ago(latest.get("period"))
    prior = next(
        (quarter for quarter in quarters[1:] if quarter.get("period") == year_ago_period),
        {},
    )
    revenue_growth_yoy = _growth(latest.get("revenue"), prior.get("revenue"))
    eps_growth_yoy = _growth(latest.get("eps"), prior.get("eps"))
    if revenue_growth_yoy is not None and eps_growth_yoy is not None:
        revenue_growth = revenue_growth_yoy
        eps_growth = eps_growth_yoy
        basis = "YoY"
    else:
        revenue_growth = _growth(latest.get("revenue"), previous.get("revenue"))
        eps_growth = _growth(latest.get("eps"), previous.get("eps"))
        basis = "QoQ" if revenue_growth is not None or eps_growth is not None else None

    latest_period = payload.get("fiscal_quarter") or latest.get("period")
    cash_flow = _latest_cash_flow(payload, latest_period)
    debt_ratio = _number((payload.get("health") or {}).get("debt_ratio"))
    revenue = _number(latest.get("revenue"))
    cash_flow_margin = None
    if cash_flow is not None and revenue not in (None, 0):
        cash_flow_margin = cash_flow / revenue
    gross_margin = _number(latest.get("gross_margin"))
    operating_margin = _number(latest.get("operating_margin"))
    net_margin = _number(latest.get("net_margin"))
    return {
        "score": None,
        "fiscal_quarter": latest_period,
        "comparison_basis": basis,
        "revenue_growth": _round_half_up(revenue_growth, 2) if revenue_growth is not None else None,
        "revenue_direction": _direction(revenue_growth),
        "eps_growth": _round_half_up(eps_growth, 2) if eps_growth is not None else None,
        "eps_direction": _direction(eps_growth),
        "gross_margin": gross_margin,
        "operating_margin": operating_margin,
        "operating_cash_flow": cash_flow,
        "operating_cash_flow_margin": _round_half_up(cash_flow_margin, 4) if cash_flow_margin is not None else None,
        "debt_ratio": debt_ratio,
        "_metrics": {
            "revenue_growth": revenue_growth,
            "eps_growth": eps_growth,
            "gross_margin": gross_margin,
            "operating_margin": operating_margin,
            "net_margin": net_margin,
            "operating_cash_flow_margin": cash_flow_margin,
            "inverse_debt_ratio": -debt_ratio if debt_ratio is not None else None,
        },
    }


def _available_average(values: list[float | int | None]) -> float | None:
    available = [float(value) for value in values if value is not None]
    return sum(available) / len(available) if available else None


def _available_weighted(values: Mapping[str, float | None], weights: Mapping[str, float]) -> float | None:
    available_weight = sum(weights[key] for key, value in values.items() if value is not None)
    if available_weight <= 0:
        return None
    return sum(
        float(value) * weights[key] / available_weight
        for key, value in values.items()
        if value is not None
    )


def _fundamental_scores(
    fundamentals: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, float | None]]:
    metric_names = (
        "revenue_growth",
        "eps_growth",
        "gross_margin",
        "operating_margin",
        "net_margin",
        "operating_cash_flow_margin",
        "inverse_debt_ratio",
    )
    percentiles = {
        metric: average_rank_percentiles(
            {
                instrument_id: row["_metrics"].get(metric)
                for instrument_id, row in fundamentals.items()
            }
        )
        for metric in metric_names
    }
    scores: dict[str, dict[str, float | None]] = {}
    for instrument_id in fundamentals:
        growth = _available_average(
            [
                percentiles["revenue_growth"].get(instrument_id),
                percentiles["eps_growth"].get(instrument_id),
            ]
        )
        profitability = _available_average(
            [
                percentiles["gross_margin"].get(instrument_id),
                percentiles["operating_margin"].get(instrument_id),
                percentiles["net_margin"].get(instrument_id),
            ]
        )
        structure = _available_average(
            [
                percentiles["operating_cash_flow_margin"].get(instrument_id),
                percentiles["inverse_debt_ratio"].get(instrument_id),
            ]
        )
        quality = _available_weighted(
            {"growth": growth, "profitability": profitability, "structure": structure},
            {"growth": 0.40, "profitability": 0.35, "structure": 0.25},
        )
        scores[instrument_id] = {
            "growth": growth,
            "profitability": profitability,
            "structure": structure,
            "fundamental_quality": quality,
            "fundamental_defense": _available_average([profitability, structure]),
        }
    return scores


def _trading_activity(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        payload = {}
    ratio = _number(payload.get("day_trading_volume_ratio"))
    if ratio is not None and not 0 <= ratio <= 1:
        ratio = None
    overnight = payload.get("overnight_risk")
    return {
        "as_of": payload.get("as_of"),
        "day_trading_volume": payload.get("day_trading_volume"),
        "total_volume": payload.get("total_volume"),
        "day_trading_volume_ratio": ratio,
        "overnight_risk": overnight if overnight is not None else None,
        "overnight_missing_reason": (
            payload.get("overnight_missing_reason")
            or payload.get("missing_reason")
            or ("no reliable overnight source" if overnight is None else None)
        ),
    }


def _component(raw: float | None, normalized: float | None, base_weight: float) -> dict[str, Any]:
    available = raw is not None and normalized is not None
    return {
        "raw": _round_half_up(raw, 4) if raw is not None else None,
        "normalized": normalized,
        "base_weight": base_weight,
        "effective_weight": 0.0,
        "available": available,
    }


def _score(components: dict[str, dict[str, Any]]) -> float:
    available_weight = sum(component["base_weight"] for component in components.values() if component["available"])
    if available_weight <= 0:
        return 0
    total = 0.0
    for component in components.values():
        if component["available"]:
            component["effective_weight"] = component["base_weight"] / available_weight
            total += component["normalized"] * component["effective_weight"]
        else:
            component["effective_weight"] = 0.0
    return int(_round_half_up(max(0.0, min(100.0, total)), 0))


def _flags(row: Mapping[str, Any]) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    primary = row["themes"][0] if row["themes"] else {}
    institutional = row["institutional"]
    fundamentals = row["fundamentals"]
    trading = row["trading_activity"]
    heat_change = primary.get("heat_change_24h")
    if heat_change is not None and float(heat_change) >= 5:
        flags.append({"key": "heat_rising", "type": "positive"})
    if len(row["themes"]) >= 2:
        flags.append({"key": "multi_theme", "type": "info"})
    if institutional["direction"] == "positive":
        flags.append({"key": "institutional_positive", "type": "positive"})
    if fundamentals["revenue_direction"] == "up" and fundamentals["eps_direction"] == "up":
        flags.append({"key": "fundamentals_improving", "type": "positive"})
    ratio = trading.get("day_trading_volume_ratio")
    if ratio is not None and float(ratio) >= 0.30:
        flags.append({"key": "high_daytrade", "type": "risk"})
    overnight = trading.get("overnight_risk")
    if overnight is not None and float(overnight) >= 70:
        flags.append({"key": "overnight_risk", "type": "risk"})
    cash_flow = fundamentals.get("operating_cash_flow")
    if cash_flow is not None and float(cash_flow) <= 0:
        flags.append({"key": "cashflow_weak", "type": "risk"})
    debt = fundamentals.get("debt_ratio")
    if debt is not None and float(debt) >= 0.60:
        flags.append({"key": "high_leverage", "type": "risk"})
    if row["coverage"]["short_ratio"] < 0.50 or row["coverage"]["long_ratio"] < 0.50:
        flags.append({"key": "data_sparse", "type": "info"})
    order = {"risk": 0, "positive": 1, "info": 2}
    return sorted(flags, key=lambda flag: (order[flag["type"]], flag["key"]))


def _assign_ranks(items: list[dict[str, Any]], horizon: str) -> list[dict[str, Any]]:
    sorted_items = sorted(
        items,
        key=lambda item: (
            -item[horizon]["score"],
            item["short"]["components"]["theme_attention"]["raw"] is None,
            -float(item["short"]["components"]["theme_attention"]["raw"] or 0),
            item["instrument"]["instrument_id"],
        ),
    )
    for rank, item in enumerate(sorted_items, start=1):
        item[horizon]["rank"] = rank
    return sorted_items


def build_stock_watchlist(
    *,
    momentum_payload: Mapping[str, Any],
    fundamentals_by_instrument: Mapping[str, Mapping[str, Any]],
    institutional_flows: Mapping[str, Mapping[str, Any]],
    day_trading_activity: Mapping[str, Mapping[str, Any]],
    generated_at: str,
    candidate_as_of: str,
    top_n: int = 50,
) -> dict[str, Any]:
    candidates = _candidate_index(momentum_payload)
    ids = sorted(candidates)
    fundamentals = {key: _fundamentals(fundamentals_by_instrument.get(key)) for key in ids}
    fundamental_scores = _fundamental_scores(fundamentals)
    for instrument_id, row in fundamentals.items():
        quality = fundamental_scores[instrument_id]["fundamental_quality"]
        row["score"] = int(_round_half_up(quality, 0)) if quality is not None else None
        row.pop("_metrics", None)
    institutional = {key: _institutional(institutional_flows.get(key)) for key in ids}
    activity_symbols = day_trading_activity.get("symbols") if isinstance(day_trading_activity, Mapping) else None
    if not isinstance(activity_symbols, Mapping):
        activity_symbols = day_trading_activity
    trading = {key: _trading_activity(activity_symbols.get(key)) for key in ids}

    raw = {
        "theme_attention": {key: candidates[key]["theme_attention_raw"] for key in ids},
        "institutional_short_activity": {
            key: institutional[key]["five_day_net"] for key in ids
        },
        "daytrade_activity": {
            key: trading[key]["day_trading_volume_ratio"]
            for key in ids
        },
        "fundamental_defense": {
            key: fundamental_scores[key]["fundamental_defense"] for key in ids
        },
        "fundamental_quality": {
            key: fundamental_scores[key]["fundamental_quality"] for key in ids
        },
        "institutional_support": {key: institutional[key]["five_day_net"] for key in ids},
        "theme_persistence": {
            key: max(
                (
                    theme["momentum_score"] * (1 if theme["relation"] == "direct" else 0.85)
                    for theme in candidates[key]["themes"]
                    if theme["momentum_score"] is not None
                ),
                default=None,
            )
            for key in ids
        },
        "trading_stability": {
            key: trading[key]["day_trading_volume_ratio"]
            for key in ids
        },
    }
    institutional_percentiles = average_rank_percentiles(raw["institutional_short_activity"])
    normalized = {
        "theme_attention": raw["theme_attention"],
        "institutional_short_activity": institutional_percentiles,
        "daytrade_activity": {
            key: min(100.0, max(0.0, value / 0.50 * 100)) if value is not None else None
            for key, value in raw["daytrade_activity"].items()
        },
        "fundamental_defense": raw["fundamental_defense"],
        "fundamental_quality": raw["fundamental_quality"],
        "institutional_support": institutional_percentiles,
        "theme_persistence": raw["theme_persistence"],
        "trading_stability": {
            key: (
                100 - min(100.0, max(0.0, value / 0.50 * 100))
                if value is not None
                else None
            )
            for key, value in raw["trading_stability"].items()
        },
    }

    items: list[dict[str, Any]] = []
    for instrument_id in ids:
        short_components = {
            key: _component(raw[key][instrument_id], normalized[key].get(instrument_id), weight)
            for key, weight in SHORT_WEIGHTS.items()
        }
        long_components = {
            key: _component(raw[key][instrument_id], normalized[key].get(instrument_id), weight)
            for key, weight in LONG_WEIGHTS.items()
        }
        missing = [
            key
            for key, component in {**short_components, **long_components}.items()
            if not component["available"]
        ]
        overnight = trading[instrument_id]["overnight_risk"]
        adjustment = min(10.0, max(0.0, float(overnight) / 10)) if overnight is not None else 0.0
        short_score = int(_round_half_up(max(0.0, _score(short_components) - adjustment), 0))
        row: dict[str, Any] = {
            "instrument": candidates[instrument_id]["instrument"],
            "themes": candidates[instrument_id]["themes"],
            "short": {
                "rank": None,
                "score": short_score,
                "components": short_components,
                "risk_adjustment": {
                    "overnight_risk_adjustment": {
                        "value": overnight,
                        "applied": _round_half_up(adjustment, 2),
                        "missing_reason": (
                            trading[instrument_id]["overnight_missing_reason"]
                            if overnight is None
                            else None
                        ),
                    }
                },
            },
            "long": {
                "rank": None,
                "score": _score(long_components),
                "components": long_components,
            },
            "institutional": institutional[instrument_id],
            "trading_activity": trading[instrument_id],
            "fundamentals": fundamentals[instrument_id],
            "flags": [],
            "coverage": {
                "short_ratio": sum(c["base_weight"] for c in short_components.values() if c["available"]),
                "long_ratio": sum(c["base_weight"] for c in long_components.values() if c["available"]),
                "missing": sorted(set(missing)),
            },
        }
        row["flags"] = _flags(row)
        items.append(row)

    mother_set = sorted(
        items,
        key=lambda item: (
            item["short"]["components"]["theme_attention"]["raw"] is None,
            -float(item["short"]["components"]["theme_attention"]["raw"] or 0),
            item["instrument"]["instrument_id"],
        ),
    )[: max(top_n, 0)]
    selected_ids = {item["instrument"]["instrument_id"] for item in mother_set}
    selected_items = [item for item in items if item["instrument"]["instrument_id"] in selected_ids]
    short_items = _assign_ranks(selected_items, "short")
    long_items = _assign_ranks(selected_items, "long")
    searchable = []
    short_rank_by_id = {
        item["instrument"]["instrument_id"]: item["short"]["rank"] for item in short_items
    }
    long_rank_by_id = {
        item["instrument"]["instrument_id"]: item["long"]["rank"] for item in long_items
    }
    for item in sorted(items, key=lambda row: row["instrument"]["instrument_id"]):
        instrument_id = item["instrument"]["instrument_id"]
        searchable.append(
            {
                "instrument": item["instrument"],
                "themes": item["themes"],
                "selected_top50": instrument_id in selected_ids,
                "short_rank": short_rank_by_id.get(instrument_id),
                "long_rank": long_rank_by_id.get(instrument_id),
                "flags": item["flags"],
            }
        )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "methodology_version": METHODOLOGY_VERSION,
        "generated_at": generated_at,
        "candidate_as_of": candidate_as_of,
        "sources": {
            "momentum": {
                "generated_at": momentum_payload.get("generated_at"),
                "observed_hour": momentum_payload.get("observed_hour"),
            },
            "institutional": {
                "as_of": sorted(
                    {row["as_of"] for row in institutional.values() if row.get("as_of")}
                )
            },
            "fundamentals": {
                "fiscal_quarters": sorted(
                    {row["fiscal_quarter"] for row in fundamentals.values() if row.get("fiscal_quarter")}
                )
            },
            "day_trading_activity": (
                day_trading_activity.get("sources")
                if isinstance(day_trading_activity.get("sources"), Mapping)
                else {"as_of": sorted(
                {
                    value.get("as_of")
                    for value in activity_symbols.values()
                    if isinstance(value, Mapping) and value.get("as_of")
                }
                )}
            ),
        },
        "methodology": {
            "missing_values": "available components are reweighted; missing values are never filled with zero",
            "top50": "theme-attention mother set shared by short and long",
            "short_weights": SHORT_WEIGHTS,
            "long_weights": LONG_WEIGHTS,
            "fundamental_quality_weights": {"growth": 0.40, "profitability": 0.35, "structure": 0.25},
        },
        "coverage": {
            "eligible_count": len(items),
            "selected_count": len(selected_ids),
            "metrics": sorted(raw),
            "missing_reasons": sorted({reason for item in items for reason in item["coverage"]["missing"]}),
        },
        "short": {"count": len(short_items), "items": short_items},
        "long": {"count": len(long_items), "items": long_items},
        "searchable": searchable,
    }
    validate_stock_watchlist_payload(payload)
    return payload


def validate_stock_watchlist_payload(payload: Mapping[str, Any]) -> None:
    if set(payload) != TOP_KEYS:
        raise ValueError(f"unexpected keys: {sorted(set(payload) ^ TOP_KEYS)}")
    if set(payload["short"]) != LIST_KEYS or set(payload["long"]) != LIST_KEYS:
        raise ValueError("unexpected watchlist section keys")
    if set(payload["coverage"]) != TOP_COVERAGE_KEYS:
        raise ValueError("unexpected top-level coverage keys")
    if set(payload["sources"]) != SOURCES_KEYS:
        raise ValueError("unexpected source keys")
    if set(payload["sources"]["momentum"]) != MOMENTUM_SOURCE_KEYS:
        raise ValueError("unexpected momentum source keys")
    if set(payload["sources"]["institutional"]) != INSTITUTIONAL_SOURCE_KEYS:
        raise ValueError("unexpected institutional source keys")
    if set(payload["sources"]["fundamentals"]) != FUNDAMENTALS_SOURCE_KEYS:
        raise ValueError("unexpected fundamentals source keys")
    day_trading_source = payload["sources"]["day_trading_activity"]
    if set(day_trading_source) == {"TWSE", "TPEX"}:
        if any(set(source) != DAY_TRADING_SOURCE_KEYS for source in day_trading_source.values()):
            raise ValueError("unexpected day-trading source keys")
    elif set(day_trading_source) != {"as_of"}:
        raise ValueError("unexpected day-trading source keys")
    if set(payload["methodology"]) != METHODOLOGY_KEYS:
        raise ValueError("unexpected methodology keys")
    if payload["methodology"]["short_weights"] != SHORT_WEIGHTS:
        raise ValueError("unexpected short methodology weights")
    if payload["methodology"]["long_weights"] != LONG_WEIGHTS:
        raise ValueError("unexpected long methodology weights")
    short_items = payload["short"]["items"]
    long_items = payload["long"]["items"]
    for item in [*short_items, *long_items]:
        if set(item) != ITEM_KEYS:
            raise ValueError(f"unexpected keys: {sorted(set(item) ^ ITEM_KEYS)}")
        if set(item["instrument"]) != INSTRUMENT_KEYS:
            raise ValueError("unexpected instrument keys")
        for theme in item["themes"]:
            if set(theme) != THEME_KEYS:
                raise ValueError("unexpected theme keys")
        if set(item["short"]) != SHORT_SCORE_KEYS or set(item["long"]) != SCORE_KEYS:
            raise ValueError("unexpected score summary keys")
        adjustment = item["short"]["risk_adjustment"]
        if set(adjustment) != {"overnight_risk_adjustment"} or set(
            adjustment["overnight_risk_adjustment"]
        ) != {"value", "applied", "missing_reason"}:
            raise ValueError("unexpected risk adjustment keys")
        if set(item["institutional"]) != INSTITUTIONAL_KEYS:
            raise ValueError("unexpected institutional keys")
        if set(item["trading_activity"]) != TRADING_ACTIVITY_KEYS:
            raise ValueError("unexpected trading activity keys")
        if set(item["fundamentals"]) != FUNDAMENTALS_KEYS:
            raise ValueError("unexpected fundamentals keys")
        if set(item["coverage"]) != COVERAGE_KEYS:
            raise ValueError("unexpected coverage keys")
        for flag in item["flags"]:
            if set(flag) != FLAG_KEYS:
                raise ValueError("unexpected flag keys")
        for horizon in ("short", "long"):
            summary = item[horizon]
            expected_components = SHORT_WEIGHTS if horizon == "short" else LONG_WEIGHTS
            if set(summary["components"]) != set(expected_components):
                raise ValueError(f"unexpected {horizon} component keys")
            if not isinstance(summary["score"], int) or not 0 <= summary["score"] <= 100:
                raise ValueError(f"invalid {horizon} score")
            available_weights = []
            for key, component in summary["components"].items():
                if set(component) != COMPONENT_KEYS:
                    raise ValueError("unexpected component keys")
                if not math.isclose(component["base_weight"], expected_components[key], abs_tol=1e-12):
                    raise ValueError("unexpected component base weight")
                normalized = component["normalized"]
                if normalized is not None and not 0 <= normalized <= 100:
                    raise ValueError("normalized score outside 0..100")
                if component["available"]:
                    if component["raw"] is None or normalized is None:
                        raise ValueError("available component is missing a value")
                    available_weights.append(component["effective_weight"])
                elif component["raw"] is not None or normalized is not None:
                    raise ValueError("missing component contains a metric value")
            if available_weights and not math.isclose(sum(available_weights), 1.0, abs_tol=1e-9):
                raise ValueError("effective weights do not sum to one")
            recomputed = sum(
                component["normalized"] * component["effective_weight"]
                for component in summary["components"].values()
                if component["available"]
            )
            if horizon == "short":
                recomputed -= summary["risk_adjustment"]["overnight_risk_adjustment"]["applied"]
            expected_score = int(_round_half_up(max(0.0, min(100.0, recomputed)), 0))
            if expected_score != summary["score"]:
                raise ValueError(f"invalid {horizon} composite score")
        expected_missing = sorted(
            key
            for horizon in ("short", "long")
            for key, component in item[horizon]["components"].items()
            if not component["available"]
        )
        if item["coverage"]["missing"] != sorted(set(expected_missing)):
            raise ValueError("coverage missing reasons mismatch")
        for horizon in ("short", "long"):
            expected_coverage = sum(
                component["base_weight"]
                for component in item[horizon]["components"].values()
                if component["available"]
            )
            if not math.isclose(item["coverage"][f"{horizon}_ratio"], expected_coverage, abs_tol=1e-12):
                raise ValueError("coverage ratio mismatch")
        if item["flags"] != _flags(item):
            raise ValueError("pipeline flags mismatch")
    short_ids = [item["instrument"]["instrument_id"] for item in short_items]
    long_ids = [item["instrument"]["instrument_id"] for item in long_items]
    if len(short_ids) != len(set(short_ids)) or len(long_ids) != len(set(long_ids)):
        raise ValueError("duplicate selected instrument")
    if set(short_ids) != set(long_ids):
        raise ValueError("short and long must contain same instrument set")
    long_by_id = {item["instrument"]["instrument_id"]: item for item in long_items}
    if any(item != long_by_id[item["instrument"]["instrument_id"]] for item in short_items):
        raise ValueError("short and long item payloads must match")
    for horizon, items in (("short", short_items), ("long", long_items)):
        ranks = [item[horizon]["rank"] for item in items]
        if ranks != list(range(1, len(items) + 1)):
            raise ValueError(f"{horizon} rank continuity failed")
        expected_order = sorted(
            items,
            key=lambda item: (
                -item[horizon]["score"],
                item["short"]["components"]["theme_attention"]["raw"] is None,
                -float(item["short"]["components"]["theme_attention"]["raw"] or 0),
                item["instrument"]["instrument_id"],
            ),
        )
        if items != expected_order:
            raise ValueError(f"{horizon} score order mismatch")
    if payload["short"]["count"] != len(short_items) or payload["long"]["count"] != len(long_items):
        raise ValueError("watchlist count mismatch")
    short_rank_by_id = {
        item["instrument"]["instrument_id"]: item["short"]["rank"] for item in short_items
    }
    long_rank_by_id = {
        item["instrument"]["instrument_id"]: item["long"]["rank"] for item in long_items
    }
    selected_by_id = {
        item["instrument"]["instrument_id"]: item for item in short_items
    }
    searchable_ids: set[str] = set()
    for row in payload["searchable"]:
        if set(row) != SEARCHABLE_KEYS:
            raise ValueError(f"unexpected searchable keys: {sorted(set(row) ^ SEARCHABLE_KEYS)}")
        instrument_id = row["instrument"]["instrument_id"]
        if set(row["instrument"]) != INSTRUMENT_KEYS:
            raise ValueError("unexpected searchable instrument keys")
        if any(set(theme) != THEME_KEYS for theme in row["themes"]):
            raise ValueError("unexpected searchable theme keys")
        if any(set(flag) != FLAG_KEYS for flag in row["flags"]):
            raise ValueError("unexpected searchable flag keys")
        if instrument_id in searchable_ids:
            raise ValueError("duplicate searchable instrument")
        searchable_ids.add(instrument_id)
        expected_selected = instrument_id in short_rank_by_id
        if row["selected_top50"] != expected_selected:
            raise ValueError("searchable selected_top50 mismatch")
        if row["short_rank"] != short_rank_by_id.get(instrument_id):
            raise ValueError("searchable rank mismatch")
        if row["long_rank"] != long_rank_by_id.get(instrument_id):
            raise ValueError("searchable rank mismatch")
        if expected_selected:
            selected = selected_by_id[instrument_id]
            if (
                row["instrument"] != selected["instrument"]
                or row["themes"] != selected["themes"]
                or row["flags"] != selected["flags"]
            ):
                raise ValueError("selected searchable payload mismatch")
    if not set(short_ids).issubset(searchable_ids):
        raise ValueError("selected instruments missing from searchable")
    if len(searchable_ids) != payload["coverage"]["eligible_count"]:
        raise ValueError("searchable eligible count mismatch")
    if payload["coverage"]["selected_count"] != len(short_ids):
        raise ValueError("selected count mismatch")


def write_stock_watchlist(output_dir: Path, payload: Mapping[str, Any]) -> None:
    validate_stock_watchlist_payload(payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / PUBLIC_STOCK_WATCHLIST_FILENAME
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_dir,
            prefix=f".{PUBLIC_STOCK_WATCHLIST_FILENAME}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(serialized)
            temporary.flush()
        validate_stock_watchlist_payload(json.loads(temporary_path.read_text(encoding="utf-8")))
        temporary_path.replace(destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
