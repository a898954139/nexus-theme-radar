"""Per-stock institutional net buy/sell from the official exchange APIs.

TWSE and TPEX each publish the whole market for one trading day in a single
response, so covering every symbol in the universe costs two requests per day
rather than one per symbol. Nothing here is scraped.

Both feeds report the dealer figure three times -- the total, the proprietary
component and the hedging component -- under labels differing only by a
parenthetical. Matching on a keyword lands on a component, and the result stays
individually plausible while being wrong: measured against the real 2026-08-05
market, reading TWSE column 14 instead of 11 corrupts 750 of 1,332 symbols.

So the columns are addressed by index, and every row is checked against the
total the exchange itself publishes. A row that fails is dropped rather than
published, because on a page about where money is moving a wrong number is
worse than a missing one.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date
from typing import Any, Mapping, Sequence

LOGGER = logging.getLogger(__name__)

FLOWS_FILE = "institutional-flows.json"
SCHEMA_VERSION = 1

TWSE_URL = "https://www.twse.com.tw/fund/T86"
TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"

# TWSE serves this endpoint as Big5/cp950, not UTF-8.
TWSE_ENCODING = "cp950"

ROC_DATE_FORMAT_EXAMPLE = "115/08/05"
ROC_YEAR_OFFSET = 1911

# TWSE T86 column indices. Verified against the live 2026-08-05 response.
#   [11] is the dealer TOTAL; [14] (自行買賣) and [17] (避險) are its components.
_TWSE_CODE = 0
_TWSE_NAME = 1
_TWSE_FOREIGN_NET = 4      # 外陸資買賣超股數(不含外資自營商)
_TWSE_TRUST_NET = 10       # 投信買賣超股數
_TWSE_DEALER_NET = 11      # 自營商買賣超股數  <- total, not [14]
_TWSE_TOTAL_NET = 18       # 三大法人買賣超股數
_TWSE_MIN_COLUMNS = 19

# TPEX dailyTrade column indices. The API repeats the field name
# "買賣超股數" for every institution group, so names cannot disambiguate these.
_TPEX_CODE = 0
_TPEX_NAME = 1
_TPEX_FOREIGN_EXCL_DEALER_NET = 4   # matches the TWSE [4] concept
_TPEX_FOREIGN_TOTAL_NET = 10        # foreign incl. foreign-dealer
_TPEX_TRUST_NET = 13
_TPEX_DEALER_NET = 22               # dealer total
_TPEX_TOTAL_NET = 23
_TPEX_MIN_COLUMNS = 24


def roc_date(day: date) -> str:
    """Format a date the way TPEX wants it: ROC year, zero-padded."""
    return f"{day.year - ROC_YEAR_OFFSET}/{day.month:02d}/{day.day:02d}"


def twse_date(day: date) -> str:
    return day.strftime("%Y%m%d")


def to_instrument_id(exchange: str, symbol: str) -> str:
    return f"{exchange}:{symbol}"


def _clean_code(raw: str) -> str:
    # TWSE wraps codes as ="2330" so spreadsheets keep the leading zeros.
    return raw.replace('="', "").replace('"', "").strip()


def _to_int(raw: Any) -> int | None:
    text = str(raw).replace(",", "").replace('="', "").replace('"', "").strip()
    if not text or text in {"-", "--"}:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _row_to_flow(
    *,
    symbol: str,
    name: str,
    exchange: str,
    foreign_net: int | None,
    trust_net: int | None,
    dealer_net: int | None,
    total_net: int | None,
    reconcile_foreign: int | None,
    as_of: date,
) -> dict[str, Any] | None:
    """Build one flow record, or None if it fails reconciliation.

    ``reconcile_foreign`` is the foreign figure the exchange used when it
    computed ``total_net``; ``foreign_net`` is the one we publish. On TWSE they
    are the same column. On TPEX the published total is built from the foreign
    *total* while the comparable per-stock figure excludes the foreign dealer,
    so the two differ on any day with foreign-dealer activity.
    """
    values = (foreign_net, trust_net, dealer_net, total_net, reconcile_foreign)
    if any(value is None for value in values):
        return None

    if reconcile_foreign + trust_net + dealer_net != total_net:
        LOGGER.warning(
            "institutional_row_rejected symbol=%s foreign=%s trust=%s dealer=%s total=%s",
            symbol, reconcile_foreign, trust_net, dealer_net, total_net,
        )
        return None

    return {
        "instrument_id": to_instrument_id(exchange, symbol),
        "symbol": symbol,
        "name": name,
        "exchange": exchange,
        "date": as_of.isoformat(),
        "foreign_net": foreign_net,
        "trust_net": trust_net,
        "dealer_net": dealer_net,
        "total_net": total_net,
        # The rankings feed publishes 張 (1,000 shares); these are 股.
        "unit": "shares",
    }


def parse_twse_csv(text: str, *, as_of: date) -> list[dict[str, Any]]:
    """Parse the TWSE T86 CSV into flow records, dropping unreconciled rows."""
    flows: list[dict[str, Any]] = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < _TWSE_MIN_COLUMNS:
            continue
        symbol = _clean_code(row[_TWSE_CODE])
        if not symbol or not symbol[0].isdigit():
            # Skips the title line and the header row without matching on their
            # text, which is localised and has changed before.
            continue

        foreign = _to_int(row[_TWSE_FOREIGN_NET])
        flow = _row_to_flow(
            symbol=symbol,
            name=row[_TWSE_NAME].strip(),
            exchange="TWSE",
            foreign_net=foreign,
            trust_net=_to_int(row[_TWSE_TRUST_NET]),
            dealer_net=_to_int(row[_TWSE_DEALER_NET]),
            total_net=_to_int(row[_TWSE_TOTAL_NET]),
            reconcile_foreign=foreign,
            as_of=as_of,
        )
        if flow is not None:
            flows.append(flow)
    return flows


def parse_tpex_payload(payload: Mapping[str, Any], *, as_of: date) -> list[dict[str, Any]]:
    """Parse the TPEX dailyTrade JSON into flow records."""
    tables = payload.get("tables") if isinstance(payload, Mapping) else None
    if not isinstance(tables, Sequence) or not tables:
        return []

    rows = tables[0].get("data") if isinstance(tables[0], Mapping) else None
    if not isinstance(rows, Sequence):
        return []

    flows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Sequence) or len(row) < _TPEX_MIN_COLUMNS:
            continue
        symbol = _clean_code(str(row[_TPEX_CODE]))
        if not symbol or not symbol[0].isdigit():
            continue

        flow = _row_to_flow(
            symbol=symbol,
            name=str(row[_TPEX_NAME]).strip(),
            exchange="TPEX",
            foreign_net=_to_int(row[_TPEX_FOREIGN_EXCL_DEALER_NET]),
            trust_net=_to_int(row[_TPEX_TRUST_NET]),
            dealer_net=_to_int(row[_TPEX_DEALER_NET]),
            total_net=_to_int(row[_TPEX_TOTAL_NET]),
            reconcile_foreign=_to_int(row[_TPEX_FOREIGN_TOTAL_NET]),
            as_of=as_of,
        )
        if flow is not None:
            flows.append(flow)
    return flows


def fetch_twse_flows(session: Any, day: date, *, timeout: float = 30.0) -> list[dict[str, Any]]:
    response = session.get(
        TWSE_URL,
        params={"response": "csv", "date": twse_date(day), "selectType": "ALLBUT0999"},
        timeout=timeout,
    )
    response.raise_for_status()
    return parse_twse_csv(response.content.decode(TWSE_ENCODING, errors="replace"), as_of=day)


def fetch_tpex_flows(session: Any, day: date, *, timeout: float = 30.0) -> list[dict[str, Any]]:
    response = session.get(
        TPEX_URL,
        params={"type": "Daily", "sect": "EW", "date": roc_date(day), "response": "json"},
        timeout=timeout,
    )
    response.raise_for_status()
    return parse_tpex_payload(response.json(), as_of=day)
