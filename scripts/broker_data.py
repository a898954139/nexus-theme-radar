"""Parse and project public Fubon broker-branch pages for the broker UI.

The source page exposes the leading buy and sell branches for one symbol. The
updater calls it once per symbol, records every response outcome, and projects
the successful rows into the two shapes described by ``BROKER_SPEC.md``.

The source does not publish a genuine day-trade ratio or an overnight index.
Those fields remain null until a source-backed formula exists; a volume share
must not be presented as a day-trade measurement.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup


FUBON_BROKER_URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco_{code}.djhtm"
BROKER_DATA_SCHEMA_VERSION = 1
_DATE_RE = re.compile(r"(?:最後更新日|更新日)\s*[：:]?\s*(\d{4})/(\d{1,2})/(\d{1,2})")
_BROKER_ID_RE = re.compile(r"(?:^|[?&])b=([^&]+)")
_SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9]{1,10}$")


def _parse_int(value: str) -> int:
    text = value.strip().replace(",", "").replace(" ", "")
    if not text or text in {"-", "--"}:
        return 0
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    try:
        return int(float(text))
    except ValueError:
        return 0


def _parse_float(value: str) -> float:
    text = value.strip().replace(",", "").replace("%", "")
    if not text or text in {"-", "--"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _broker_identity(cell: Any) -> tuple[str, str]:
    link = cell.find("a")
    name = (link or cell).get_text(" ", strip=True)
    href = link.get("href", "") if link else ""
    match = _BROKER_ID_RE.search(href)
    if match:
        broker_id = match.group(1)
    else:
        broker_id = parse_qs(urlparse(href).query).get("b", [""])[0]
    return broker_id, name


def _normalize_date(html_text: str) -> str:
    match = _DATE_RE.search(html_text)
    if not match:
        return ""
    year, month, day = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _side_record(
    cells: list[Any],
    *,
    stock_code: str,
    stock_name: str,
    offset: int,
    sign: int,
) -> dict[str, Any] | None:
    broker_id, broker_name = _broker_identity(cells[offset])
    if not broker_name or broker_name in {"買超券商", "賣超券商"}:
        return None

    buy = _parse_int(cells[offset + 1].get_text(" ", strip=True))
    sell = _parse_int(cells[offset + 2].get_text(" ", strip=True))
    net = sign * abs(_parse_int(cells[offset + 3].get_text(" ", strip=True)))
    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "broker_id": broker_id,
        "broker_name": broker_name,
        "buy": buy,
        "sell": sell,
        "net": net,
        "source_ratio": _parse_float(cells[offset + 4].get_text(" ", strip=True)),
    }


def parse_fubon_page(html: str, stock_code: str, stock_name: str = "") -> dict[str, Any]:
    """Parse one Fubon broker page into a response outcome and normalized rows."""
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True)
    trade_date = _normalize_date(page_text)

    table = soup.select_one("table.t01")
    if table is None:
        return {"status": "no_data", "stock_code": stock_code, "records": [], "trade_date": trade_date}

    rows = table.select("tr")
    if len(rows) <= 1:
        return {"status": "no_data", "stock_code": stock_code, "records": [], "trade_date": trade_date}

    header_index = None
    for index, row in enumerate(rows):
        cells = row.select("td, th")
        texts = [cell.get_text(" ", strip=True) for cell in cells]
        if len(texts) >= 10 and texts[0] == "買超券商" and texts[5] == "賣超券商":
            header_index = index
            break

    if header_index is None:
        return {
            "status": "error",
            "stock_code": stock_code,
            "records": [],
            "trade_date": trade_date,
            "error": "Fubon broker table header not found",
        }

    records: list[dict[str, Any]] = []
    for row in rows[header_index + 1 :]:
        cells = row.select("td, th")
        if len(cells) < 10:
            continue
        buy = _side_record(
            cells, stock_code=stock_code, stock_name=stock_name, offset=0, sign=1,
        )
        sell = _side_record(
            cells, stock_code=stock_code, stock_name=stock_name, offset=5, sign=-1,
        )
        if buy is not None:
            records.append(buy)
        if sell is not None:
            records.append(sell)

    return {
        "status": "ok" if records else "no_data",
        "stock_code": stock_code,
        "trade_date": trade_date,
        "records": records,
    }


def _record_key(record: Mapping[str, Any]) -> str:
    return str(record.get("broker_id") or record.get("broker_name") or "")


def _valid_records(records: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        record
        for record in records
        if str(record.get("stock_code", ""))
        and str(record.get("broker_name", ""))
    ]


def build_broker_stats(
    records: Iterable[Mapping[str, Any]], *, top_n: int = 5,
) -> list[dict[str, Any]]:
    """Build the ``brokerStats`` list required by the flows page."""
    grouped: dict[str, dict[str, Any]] = {}
    stock_totals: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)

    for record in _valid_records(records):
        key = _record_key(record)
        if not key:
            continue
        entry = grouped.setdefault(key, {
            "name": str(record["broker_name"]),
            "buy": 0,
            "sell": 0,
            "dt": None,
            "ov": None,
            "top": [],
        })
        entry["buy"] += int(record.get("buy", 0) or 0)
        entry["sell"] += int(record.get("sell", 0) or 0)

        stock_code = str(record["stock_code"])
        stock = stock_totals[key].setdefault(stock_code, {
            "name": str(record.get("stock_name", "")),
            "net": 0,
        })
        stock["net"] += int(record.get("net", 0) or 0)

    for key, entry in grouped.items():
        ranked = sorted(
            stock_totals[key].items(),
            key=lambda item: (-abs(item[1]["net"]), item[0]),
        )
        entry["top"] = [
            [code, str(info["name"])]
            for code, info in ranked[:top_n]
        ]

    return sorted(
        grouped.values(),
        key=lambda item: (-abs(item["buy"] - item["sell"]), item["name"]),
    )


def build_broker_maps(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Build ``brokerData[stockCode]`` for the stock relationship graph."""
    valid = _valid_records(records)
    by_stock: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    broker_stocks: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)

    for record in valid:
        broker_key = _record_key(record)
        stock_code = str(record["stock_code"])
        branch = by_stock[stock_code].setdefault(broker_key, {
            "id": str(record.get("broker_id") or broker_key),
            "name": str(record["broker_name"]),
            "buy": 0,
            "sell": 0,
            "ratio": 0.0,
        })
        branch["buy"] += int(record.get("buy", 0) or 0)
        branch["sell"] += int(record.get("sell", 0) or 0)
        branch["ratio"] += float(record.get("source_ratio", 0) or 0)

        stock = broker_stocks[broker_key].setdefault(stock_code, {
            "name": str(record.get("stock_name", "")),
            "net": 0,
        })
        stock["net"] += int(record.get("net", 0) or 0)

    maps: dict[str, list[dict[str, Any]]] = {}
    for stock_code, branches in by_stock.items():
        projected: list[dict[str, Any]] = []
        for broker_key, branch in branches.items():
            net = branch["buy"] - branch["sell"]
            # Fubon provides the branch's share of the stock turnover. Keep
            # that source-backed ratio instead of normalizing only the top
            # rows returned by the page.
            ratio = round(branch["ratio"], 2)
            children = [
                [code, str(info["name"]), int(info["net"])]
                for code, info in broker_stocks[broker_key].items()
                if code != stock_code
            ]
            children.sort(key=lambda item: (-abs(item[2]), item[0]))
            projected.append({
                "id": branch["id"],
                "name": branch["name"],
                "net": net,
                "ratio": ratio,
                "stocks": children,
            })
        projected.sort(key=lambda item: (-abs(item["net"]), item["name"]))
        maps[stock_code] = projected

    return maps


def build_coverage(
    requested_symbols: Iterable[str],
    results: Mapping[str, Mapping[str, Any]],
    *,
    source_updated: str | None,
) -> dict[str, Any]:
    """Summarize attempts separately from symbols that happened to have rows."""
    requested = sorted({str(symbol) for symbol in requested_symbols})
    attempted = [symbol for symbol in requested if symbol in results]
    failed = sorted(
        symbol for symbol in requested
        if results.get(symbol, {}).get("status") == "error"
    )
    with_data = sorted(
        symbol for symbol in requested
        if results.get(symbol, {}).get("records")
    )
    no_data = sorted(
        symbol for symbol in requested
        if results.get(symbol, {}).get("status") == "no_data"
    )
    not_attempted = sorted(set(requested) - set(attempted))
    return {
        "schema_version": BROKER_DATA_SCHEMA_VERSION,
        "source_updated": source_updated,
        "requested_symbols": len(requested),
        "attempted_symbols": len(attempted),
        "failed_symbols": len(failed),
        "successful_symbols": len(attempted) - len(failed),
        "symbols_with_data": len(with_data),
        "attempt_coverage": round(len(attempted) / len(requested), 6) if requested else 1.0,
        "data_coverage": round(len(with_data) / len(requested), 6) if requested else 1.0,
        "data_coverage_denominator": "requested_symbols",
        "failed_symbol_codes": failed,
        "no_data_symbol_codes": no_data,
        "status": "complete" if len(attempted) == len(requested) and not failed else "incomplete",
        "not_attempted_symbol_codes": not_attempted,
    }


def broker_map_filename(stock_code: str) -> str:
    if not _SAFE_CODE_RE.fullmatch(stock_code):
        raise ValueError(f"unsafe broker map code: {stock_code!r}")
    return f"{stock_code}.json"
