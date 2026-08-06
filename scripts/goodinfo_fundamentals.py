"""Goodinfo.tw quarterly fundamentals adapter.

Fetches and parses the three quarterly statement reports Goodinfo publishes
per symbol (income statement, balance sheet, cash flow) and reshapes them
into ``fundamental_context`` — the payload consumed verbatim by the
downstream Hermes producer / nexus-market-analysis-v2 skill.
"""

from __future__ import annotations

import html
import re
import time
from datetime import datetime
from typing import Any

import requests

REPORTS = ("IS_QUAR", "BS_QUAR", "CF_QUAR")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
BASE_URL = "https://goodinfo.tw/tw/StockFinDetail.asp"
REQUEST_TIMEOUT_SECONDS = 25.0
# Captured statement pages run ~100KB; this is a runaway guard, not a tight fit.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

# Row labels we pull out of the parsed tables, by report.
_INCOME_REVENUE = "營業收入"
_INCOME_GROSS_MARGIN = "營業毛利"
_INCOME_OPERATING_MARGIN = "營業利益"
_INCOME_NET_MARGIN = "稅後淨利"  # parent-only; NOT 合併稅後淨利 (consolidated)
_INCOME_EPS = "每股稅後盈餘(元)"
_BALANCE_CASH = "現金及約當現金"
_BALANCE_CURRENT_ASSETS = "流動資產合計"
_BALANCE_CURRENT_LIABILITIES = "流動負債合計"
_BALANCE_DEBT_RATIO = "負債總額"
_CASH_FLOW_OPERATING = "營業活動之淨現金流入(出)"

_TABLE_RE = re.compile(r"<table.*?</table>", re.DOTALL | re.IGNORECASE)
_ROW_RE = re.compile(r"<tr.*?</tr>", re.DOTALL | re.IGNORECASE)
_CELL_RE = re.compile(r"<t[dh]([^>]*)>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_COLSPAN_RE = re.compile(r"colspan\s*=\s*['\"]?(\d+)")
_NUMBER_RE = re.compile(r"^-?[\d,]+(?:\.\d+)?$")

DATA_TABLE_INDEX = 6


class GoodinfoUnavailable(Exception):
    """Raised when a Goodinfo report cannot be fetched or parsed."""


def client_key_for(now: datetime) -> str:
    """Build the CLIENT_KEY cookie value Goodinfo requires to serve pages."""

    tz_offset = -480
    now_ms = now.timestamp() * 1000
    days_adjusted = now_ms / 86400000 - tz_offset / 1440
    return f"2.8|38057.1435627105|46946.0324515993|{tz_offset}|{days_adjusted}|{days_adjusted}"


def _strip_cell_text(raw: str) -> str:
    return html.unescape(_TAG_RE.sub("", raw)).strip()


def _parse_number(text: str) -> float | None:
    cleaned = text.replace(",", "").strip()
    if not _NUMBER_RE.match(cleaned):
        return None
    return float(cleaned)


def _parse_row(row_html: str) -> tuple[list[str], list[int]]:
    """Return (cell texts, colspans) for a single <tr>."""

    texts: list[str] = []
    spans: list[int] = []
    for attrs, body in _CELL_RE.findall(row_html):
        span_match = _COLSPAN_RE.search(attrs)
        spans.append(int(span_match.group(1)) if span_match else 1)
        texts.append(_strip_cell_text(body))
    return texts, spans


def parse_financial_table(html_text: str) -> dict[str, Any]:
    """Parse one Goodinfo quarterly report page into periods + metric rows.

    The stride (columns per period) varies by report: IS_QUAR/BS_QUAR pair
    each period with a following ％ column (colspan='2' on the header cell);
    CF_QUAR lists one column per period. The stride is read from the header
    row's colspan rather than assumed, since Goodinfo does not apply it
    consistently across report types.
    """

    tables = _TABLE_RE.findall(html_text)
    if len(tables) <= DATA_TABLE_INDEX:
        raise GoodinfoUnavailable("no parseable financial table found in Goodinfo response")

    table = tables[DATA_TABLE_INDEX]
    rows = _ROW_RE.findall(table)
    if not rows:
        raise GoodinfoUnavailable("financial table has no rows")

    header_cells, header_spans = _parse_row(rows[0])
    periods = header_cells[1:]
    if not periods:
        raise GoodinfoUnavailable("financial table header has no period columns")
    stride = header_spans[1] if len(header_spans) > 1 else 1

    metrics: dict[str, dict[str, float | None]] = {}
    metrics_pct: dict[str, dict[str, float | None]] = {}
    for row_html in rows[1:]:
        cells, _spans = _parse_row(row_html)
        if not cells:
            continue
        label = cells[0]
        if not label:
            continue
        values = cells[1:]
        by_period: dict[str, float | None] = {}
        by_period_pct: dict[str, float | None] = {}
        for index, period in enumerate(periods):
            column = index * stride
            by_period[period] = _parse_number(values[column]) if column < len(values) else None
            if stride > 1:
                pct_column = column + 1
                by_period_pct[period] = (
                    _parse_number(values[pct_column]) if pct_column < len(values) else None
                )
        metrics[label] = by_period
        if stride > 1:
            metrics_pct[label] = by_period_pct

    return {"periods": periods, "metrics": metrics, "metrics_pct": metrics_pct}


def _metric_value(table: dict[str, Any], label: str, period: str) -> float | None:
    return table["metrics"].get(label, {}).get(period)


def _metric_pct(table: dict[str, Any], label: str, period: str) -> float | None:
    return table.get("metrics_pct", {}).get(label, {}).get(period)


def _fraction(value: float | None) -> float | None:
    return None if value is None else value / 100.0


def _margin(numerator: float | None, revenue: float | None) -> float | None:
    # metrics store the 金額 (amount) column, not the adjacent ％ column, so
    # margins are derived from the amount ratio rather than read directly.
    if numerator is None or revenue is None or revenue == 0:
        return None
    return numerator / revenue


def build_fundamental_context(
    *,
    symbol: str,
    income: dict[str, Any],
    balance: dict[str, Any],
    cash_flow: dict[str, Any],
    fetched_at: datetime,
) -> dict[str, Any]:
    periods = income["periods"][:6]
    missing: list[str] = []

    quarters: list[dict[str, Any]] = []
    for period in periods:
        entry: dict[str, Any] = {"period": period}
        revenue = _metric_value(income, _INCOME_REVENUE, period)
        field_sources = (
            ("revenue", revenue),
            ("gross_margin", _margin(_metric_value(income, _INCOME_GROSS_MARGIN, period), revenue)),
            ("operating_margin", _margin(_metric_value(income, _INCOME_OPERATING_MARGIN, period), revenue)),
            ("net_margin", _margin(_metric_value(income, _INCOME_NET_MARGIN, period), revenue)),
            ("eps", _metric_value(income, _INCOME_EPS, period)),
        )
        for field, value in field_sources:
            if value is None:
                missing.append(f"{field} unavailable for {period}")
                continue
            entry[field] = value
        quarters.append(entry)

    newest_period = periods[0]
    health: dict[str, Any] = {}

    cash = _metric_value(balance, _BALANCE_CASH, newest_period)
    if cash is None:
        missing.append(f"cash unavailable for {newest_period}")
    else:
        health["cash"] = cash

    current_assets = _metric_value(balance, _BALANCE_CURRENT_ASSETS, newest_period)
    current_liabilities = _metric_value(balance, _BALANCE_CURRENT_LIABILITIES, newest_period)
    if current_assets is None or current_liabilities is None or current_liabilities == 0:
        missing.append(f"current_ratio unavailable for {newest_period}")
    else:
        health["current_ratio"] = current_assets / current_liabilities

    debt_ratio = _fraction(_metric_pct(balance, _BALANCE_DEBT_RATIO, newest_period))
    if debt_ratio is None:
        missing.append(f"debt_ratio unavailable for {newest_period}")
    else:
        health["debt_ratio"] = debt_ratio

    # net_income / operating_cash_flow carry a quarter suffix: health is a
    # single point-in-time snapshot and the v2 prompt strips the suffix
    # itself, so the bare key would be ambiguous about which quarter it is.
    net_income = _metric_value(income, _INCOME_NET_MARGIN, newest_period)
    if net_income is None:
        missing.append(f"net_income unavailable for {newest_period}")
    else:
        health[f"net_income_{newest_period}"] = net_income

    operating_cash_flow = _metric_value(cash_flow, _CASH_FLOW_OPERATING, newest_period)
    if operating_cash_flow is None:
        missing.append(f"operating_cash_flow unavailable for {newest_period}")
    else:
        health[f"operating_cash_flow_{newest_period}"] = operating_cash_flow

    eps_values = [q["eps"] for q in quarters[:4] if "eps" in q]
    valuation: dict[str, Any] = {}
    if len(eps_values) == 4:
        valuation["ttm_eps"] = sum(eps_values)
    else:
        missing.append("ttm_eps unavailable: fewer than four quarters of EPS")

    return {
        "quarters": quarters,
        "health": health,
        "valuation": valuation,
        # Goodinfo lists both parent-only (稅後淨利) and consolidated
        # (合併稅後淨利) net income; parent-only matches the basis used when
        # the v2 skill's prompt was hand-validated.
        "basis": "parent_only",
        "currency": "TWD 億元",
        "source": "Goodinfo.tw quarterly statements",
        "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
        "fiscal_quarter": newest_period,
        "missing": missing,
    }


_MARGIN_FIELDS = ("gross_margin", "operating_margin", "net_margin")


def _check_fields(source: dict[str, Any], label: str) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []

    for field in _MARGIN_FIELDS:
        value = source.get(field)
        if value is not None and abs(value) > 1.0:
            warnings.append(
                {
                    "level": "error",
                    "field": f"{field}[{label}]",
                    "msg": f"{field} {value} is outside [-1.0, 1.0] for {label}",
                }
            )

    debt_ratio = source.get("debt_ratio")
    if debt_ratio is not None and debt_ratio > 1.0:
        warnings.append(
            {
                "level": "error",
                "field": f"debt_ratio[{label}]",
                "msg": f"debt_ratio {debt_ratio} exceeds 1.0 for {label}",
            }
        )

    current_ratio = source.get("current_ratio")
    if current_ratio is not None and current_ratio < 0:
        warnings.append(
            {
                "level": "error",
                "field": f"current_ratio[{label}]",
                "msg": f"current_ratio {current_ratio} is negative for {label}",
            }
        )

    return warnings


def sanity_check(context: dict[str, Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []

    for quarter in context.get("quarters", []):
        warnings.extend(_check_fields(quarter, quarter.get("period", "?")))

    warnings.extend(_check_fields(context.get("health", {}), "health"))

    return warnings


def _fetch_report(
    session: Any,
    symbol: str,
    report: str,
    *,
    client_key: str,
    days_adjusted: float,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> str:
    url = f"{BASE_URL}?RPT_CAT={report}&STOCK_ID={symbol}&REINIT={days_adjusted:.10f}"
    headers = {"User-Agent": USER_AGENT, "Referer": "https://goodinfo.tw/"}
    try:
        response = session.get(
            url, headers=headers, cookies={"CLIENT_KEY": client_key}, timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise GoodinfoUnavailable(f"failed to fetch {report} for {symbol}: {exc}") from exc

    declared = getattr(response, "headers", {}).get("Content-Length")
    if declared:
        try:
            declared_length = int(declared)
        except (TypeError, ValueError):
            declared_length = 0
        if declared_length > MAX_RESPONSE_BYTES:
            raise GoodinfoUnavailable(
                f"{report} for {symbol} exceeds {MAX_RESPONSE_BYTES} bytes"
            )

    response.encoding = "utf-8"
    text = response.text
    if len(text) > MAX_RESPONSE_BYTES:
        raise GoodinfoUnavailable(f"{report} for {symbol} exceeds {MAX_RESPONSE_BYTES} bytes")
    return text


def fetch_symbol_fundamentals(
    session: Any,
    symbol: str,
    *,
    fetched_at: datetime,
    pause_seconds: float = 3.0,
) -> dict[str, Any]:
    tz_offset = -480
    now_ms = fetched_at.timestamp() * 1000
    days_adjusted = now_ms / 86400000 - tz_offset / 1440
    client_key = client_key_for(fetched_at)

    tables: dict[str, dict[str, Any]] = {}
    for index, report in enumerate(REPORTS):
        if index > 0 and pause_seconds > 0:
            time.sleep(pause_seconds)
        page = _fetch_report(session, symbol, report, client_key=client_key, days_adjusted=days_adjusted)
        tables[report] = parse_financial_table(page)

    return build_fundamental_context(
        symbol=symbol,
        income=tables["IS_QUAR"],
        balance=tables["BS_QUAR"],
        cash_flow=tables["CF_QUAR"],
        fetched_at=fetched_at,
    )
