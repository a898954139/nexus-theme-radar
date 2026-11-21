"""Bounded TWSE/TPEX official day-trading activity cache."""

from __future__ import annotations

import json
import math
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import requests

DAY_TRADING_CACHE_FILENAME = "day-trading-activity-v1.json"
SCHEMA_VERSION = "nexus_day_trading_activity.v1"

TWSE_TWTB4U_URL = "https://www.twse.com.tw/rwd/zh/dayTrading/TWTB4U"
TWSE_MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TPEX_INTRADAY_URL = "https://www.tpex.org.tw/www/zh-tw/intraday/stat"
TPEX_DAILY_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"

DAY_TRADING_COLUMNS = (
    "證券代號",
    "證券名稱",
    "暫停現股賣出後現款買進當沖註記",
    "當日沖銷交易成交股數",
    "當日沖銷交易買進成交金額",
    "當日沖銷交易賣出成交金額",
)
TWSE_TOTAL_VOLUME_COLUMNS = (
    "證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額", "開盤價", "最高價", "最低價",
    "收盤價", "漲跌(+/-)", "漲跌價差", "最後揭示買價", "最後揭示買量", "最後揭示賣價", "最後揭示賣量", "本益比",
)
TPEX_TOTAL_VOLUME_COLUMNS = (
    "代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低", "均價", "成交股數", "成交金額(元)",
    "成交筆數", "最後買價", "最後買量(張數)", "最後賣價", "最後賣量(張數)", "發行股數",
    "次日參考價", "次日漲停價", "次日跌停價",
)

SOURCE_KEYS = {
    "as_of",
    "finality",
    "numerator_url",
    "denominator_url",
    "status",
    "error",
}
SYMBOL_KEYS = {
    "exchange",
    "as_of",
    "day_trading_volume",
    "total_volume",
    "day_trading_volume_ratio",
    "status",
    "stale",
    "missing_reason",
}


class DayTradingDataError(ValueError):
    """Raised when an official response is unavailable or changes shape."""


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        raise DayTradingDataError("boolean volume is invalid")
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError) as error:
        raise DayTradingDataError(f"invalid volume: {value!r}") from error


def _tables(payload: Any) -> list[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        raise DayTradingDataError("official response is not a JSON object")
    if str(payload.get("stat") or "").lower() != "ok":
        raise DayTradingDataError(f"official response status is not ok: {payload.get('stat')!r}")
    tables = payload.get("tables")
    if not isinstance(tables, list) or not tables:
        raise DayTradingDataError("official response has no tables")
    return [table for table in tables if isinstance(table, Mapping)]


def _rows_by_columns(
    payload: Any,
    *,
    code_column: str,
    value_column: str,
    required_columns: Sequence[str],
) -> dict[str, int]:
    result: dict[str, int] = {}
    matched = False
    drifted = False
    for table in _tables(payload):
        fields = table.get("fields")
        data = table.get("data")
        if not isinstance(fields, list):
            continue
        normalized_fields = ["".join(str(field).split()) for field in fields]
        normalized_code = "".join(code_column.split())
        normalized_value = "".join(value_column.split())
        if normalized_code not in normalized_fields or normalized_value not in normalized_fields:
            continue
        matched = True
        normalized_required = {"".join(column.split()) for column in required_columns}
        if not normalized_required.issubset(normalized_fields):
            drifted = True
            continue
        if not isinstance(data, list):
            raise DayTradingDataError(f"official table {value_column} data is not a list")
        code_index = normalized_fields.index(normalized_code)
        value_index = normalized_fields.index(normalized_value)
        for row in data:
            if not isinstance(row, list) or max(code_index, value_index) >= len(row):
                raise DayTradingDataError(f"official table {value_column} row shape changed")
            code = str(row[code_index]).strip()
            if code:
                result[code] = _integer(row[value_index])
    if result:
        return result
    if drifted:
        raise DayTradingDataError(f"official table is missing required columns for {value_column}")
    if matched:
        raise DayTradingDataError(f"official table {value_column} has no instruments")
    raise DayTradingDataError(f"official table is missing columns: {code_column}, {value_column}")


def parse_twse_day_trading(payload: Any) -> dict[str, int]:
    return _rows_by_columns(
        payload,
        code_column="證券代號",
        value_column="當日沖銷交易成交股數",
        required_columns=DAY_TRADING_COLUMNS,
    )


def parse_twse_total_volume(payload: Any) -> dict[str, int]:
    return _rows_by_columns(
        payload,
        code_column="證券代號",
        value_column="成交股數",
        required_columns=TWSE_TOTAL_VOLUME_COLUMNS,
    )


def parse_tpex_day_trading(payload: Any) -> dict[str, int]:
    return _rows_by_columns(
        payload,
        code_column="證券代號",
        value_column="當日沖銷交易成交股數",
        required_columns=DAY_TRADING_COLUMNS,
    )


def parse_tpex_total_volume(payload: Any) -> dict[str, int]:
    return _rows_by_columns(
        payload,
        code_column="代號",
        value_column="成交股數",
        required_columns=TPEX_TOTAL_VOLUME_COLUMNS,
    )


def build_market_rows(
    exchange: str,
    as_of: str,
    numerators: Mapping[str, int],
    denominators: Mapping[str, int],
) -> dict[str, dict[str, Any]]:
    if exchange not in {"TWSE", "TPEX"}:
        raise ValueError(f"unsupported exchange: {exchange}")
    rows: dict[str, dict[str, Any]] = {}
    for code, numerator in numerators.items():
        denominator = denominators.get(code)
        reason: str | None = None
        if denominator is None:
            reason = "total_volume_missing"
        elif numerator < 0 or denominator < 0:
            reason = "negative_volume"
        elif denominator <= 0:
            reason = "total_volume_not_positive"
        elif numerator > denominator:
            reason = "day_trading_volume_exceeds_total"
        ratio = None if reason else numerator / denominator
        rows[f"{exchange}:{code}"] = {
            "exchange": exchange,
            "as_of": as_of,
            "day_trading_volume": numerator,
            "total_volume": denominator,
            "day_trading_volume_ratio": ratio,
            "status": "missing" if reason else "fresh",
            "stale": False,
            "missing_reason": reason,
        }
    return rows


def select_settled_target(
    latest_date: date,
    completed_trading_dates: Sequence[str],
    *,
    lag: int = 2,
) -> str:
    eligible = sorted(
        {
            value
            for value in completed_trading_dates
            if isinstance(value, str) and value <= latest_date.isoformat()
        },
        reverse=True,
    )
    if len(eligible) <= lag:
        raise DayTradingDataError("not enough official trading dates for settled target")
    return eligible[lag]


def _source_metadata(exchange: str, *, as_of: str | None, status: str, error: str | None) -> dict[str, Any]:
    if exchange == "TWSE":
        numerator_url, denominator_url = TWSE_TWTB4U_URL, TWSE_MI_INDEX_URL
    else:
        numerator_url, denominator_url = TPEX_INTRADAY_URL, TPEX_DAILY_URL
    return {
        "as_of": as_of,
        "finality": "settled_t_plus_2",
        "numerator_url": numerator_url,
        "denominator_url": denominator_url,
        "status": status,
        "error": error,
    }


def _payload_date(payload: Any) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    value = str(payload.get("date") or "").replace("/", "").replace("-", "")
    if len(value) != 8 or not value.isdigit():
        return None
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def _market_rows(exchange: str, target_date: str, numerator_payload: Any, denominator_payload: Any):
    if _payload_date(numerator_payload) != target_date or _payload_date(denominator_payload) != target_date:
        raise DayTradingDataError("official response date does not match target date")
    if exchange == "TWSE":
        numerators = parse_twse_day_trading(numerator_payload)
        denominators = parse_twse_total_volume(denominator_payload)
    else:
        numerators = parse_tpex_day_trading(numerator_payload)
        denominators = parse_tpex_total_volume(denominator_payload)
    if any(value < 0 for value in [*numerators.values(), *denominators.values()]):
        raise DayTradingDataError(f"{exchange} official rows contain negative volume")
    if any(
        code in denominators and denominators[code] > 0 and numerator > denominators[code]
        for code, numerator in numerators.items()
    ):
        raise DayTradingDataError(f"{exchange} day-trading volume exceeds total volume")
    rows = build_market_rows(exchange, target_date, numerators, denominators)
    if not any(row["day_trading_volume_ratio"] is not None for row in rows.values()):
        raise DayTradingDataError(f"{exchange} official rows have no valid numerator/denominator join")
    return rows


def fetch_official_market_payloads(
    exchange: str,
    target_date: str,
    *,
    session: requests.Session | None = None,
    timeout: float = 15.0,
) -> tuple[Any, Any]:
    client = session or requests.Session()
    if exchange == "TWSE":
        compact_date = target_date.replace("-", "")
        numerator = client.get(
            TWSE_TWTB4U_URL,
            params={"date": compact_date, "selectType": "All", "response": "json"},
            timeout=timeout,
        )
        denominator = client.get(
            TWSE_MI_INDEX_URL,
            params={"date": compact_date, "type": "ALLBUT0999NOTIND", "response": "json"},
            timeout=timeout,
        )
    elif exchange == "TPEX":
        slash_date = target_date.replace("-", "/")
        numerator = client.get(
            TPEX_INTRADAY_URL,
            params={"date": slash_date, "type": "Daily"},
            timeout=timeout,
        )
        denominator = client.get(
            TPEX_DAILY_URL,
            params={"date": slash_date},
            timeout=timeout,
        )
    else:
        raise ValueError(f"unsupported exchange: {exchange}")
    numerator.raise_for_status()
    denominator.raise_for_status()
    return numerator.json(), denominator.json()


def _load_prior(cache_path: Path, *, enabled: bool) -> dict[str, Any] | None:
    if not enabled or not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        validate_day_trading_cache(payload)
        return payload
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _atomic_write(cache_path: Path, payload: Mapping[str, Any]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=cache_path.parent,
            prefix=f".{cache_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
        temporary_path.replace(cache_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def refresh_day_trading_cache(
    cache_path: Path,
    *,
    target_date: str,
    generated_at: str,
    fetch_market: Callable[[str, str], tuple[Any, Any]] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    prior = _load_prior(cache_path, enabled=write)
    if prior and prior["target_date"] == target_date and all(
        source["status"] == "fresh" for source in prior["sources"].values()
    ):
        return prior

    fetch = fetch_market or (lambda exchange, target: fetch_official_market_payloads(exchange, target))
    sources: dict[str, dict[str, Any]] = {}
    symbols: dict[str, dict[str, Any]] = {}
    for exchange in ("TWSE", "TPEX"):
        try:
            numerator_payload, denominator_payload = fetch(exchange, target_date)
            market_rows = _market_rows(exchange, target_date, numerator_payload, denominator_payload)
            symbols.update(market_rows)
            sources[exchange] = _source_metadata(
                exchange,
                as_of=target_date,
                status="fresh",
                error=None,
            )
        except Exception as error:  # noqa: BLE001 - one exchange must not abort the cache
            message = f"{type(error).__name__}: {error}"
            prior_rows = {
                key: value
                for key, value in (prior or {}).get("symbols", {}).items()
                if key.startswith(f"{exchange}:")
            }
            if prior_rows:
                for key, row in prior_rows.items():
                    symbols[key] = {
                        **row,
                        "status": "stale",
                        "stale": True,
                        "missing_reason": f"stale_official_cache: {message}",
                    }
                prior_source = prior["sources"][exchange]
                sources[exchange] = _source_metadata(
                    exchange,
                    as_of=prior_source["as_of"],
                    status="stale",
                    error=message,
                )
            else:
                sources[exchange] = _source_metadata(
                    exchange,
                    as_of=None,
                    status="missing",
                    error=message,
                )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "target_date": target_date,
        "sources": sources,
        "symbols": symbols,
    }
    validate_day_trading_cache(payload)
    if write:
        _atomic_write(cache_path, payload)
    return payload


def validate_day_trading_cache(payload: Mapping[str, Any]) -> None:
    expected_top = {"schema_version", "generated_at", "target_date", "sources", "symbols"}
    if set(payload) != expected_top:
        raise ValueError(f"unexpected cache keys: {sorted(set(payload) ^ expected_top)}")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unexpected day-trading schema version")
    target_date = payload["target_date"]
    if not isinstance(target_date, str) or len(target_date) != 10:
        raise ValueError("invalid day-trading target date")
    if set(payload["sources"]) != {"TWSE", "TPEX"}:
        raise ValueError("day-trading cache requires TWSE and TPEX sources")
    for exchange, source in payload["sources"].items():
        if set(source) != SOURCE_KEYS:
            raise ValueError(f"unexpected source keys for {exchange}: {sorted(set(source) ^ SOURCE_KEYS)}")
        if source["status"] not in {"fresh", "stale", "missing"}:
            raise ValueError(f"invalid source status for {exchange}")
        expected = _source_metadata(exchange, as_of=source["as_of"], status=source["status"], error=source["error"])
        if source != expected:
            raise ValueError(f"invalid source attribution for {exchange}")
        if source["status"] == "fresh" and source["as_of"] != target_date:
            raise ValueError(f"fresh source date mismatch for {exchange}")
        if source["status"] == "missing" and source["as_of"] is not None:
            raise ValueError(f"missing source date mismatch for {exchange}")
    valid_joins = {"TWSE": 0, "TPEX": 0}
    for instrument_id, row in payload["symbols"].items():
        if set(row) != SYMBOL_KEYS:
            raise ValueError(f"unexpected symbol keys for {instrument_id}: {sorted(set(row) ^ SYMBOL_KEYS)}")
        exchange, separator, _ = instrument_id.partition(":")
        if not separator or exchange != row["exchange"] or exchange not in {"TWSE", "TPEX"}:
            raise ValueError(f"invalid exchange-qualified instrument id: {instrument_id}")
        source = payload["sources"][exchange]
        if row["as_of"] != source["as_of"]:
            raise ValueError(f"source date mismatch for {instrument_id}")
        if source["status"] == "missing":
            raise ValueError(f"missing source contains rows for {instrument_id}")
        if source["status"] == "stale" and (row["status"] != "stale" or row["stale"] is not True):
            raise ValueError(f"stale source row mismatch for {instrument_id}")
        if source["status"] == "fresh" and row["status"] not in {"fresh", "missing"}:
            raise ValueError(f"fresh source row mismatch for {instrument_id}")
        if source["status"] == "fresh" and row["stale"] is not False:
            raise ValueError(f"fresh source stale marker mismatch for {instrument_id}")
        numerator = row["day_trading_volume"]
        denominator = row["total_volume"]
        if isinstance(numerator, bool) or not isinstance(numerator, int) or numerator < 0:
            raise ValueError(f"invalid day-trading volume for {instrument_id}")
        if denominator is not None and (
            isinstance(denominator, bool) or not isinstance(denominator, int) or denominator < 0
        ):
            raise ValueError(f"invalid total volume for {instrument_id}")
        if denominator is not None and denominator > 0 and numerator > denominator:
            raise ValueError(f"day-trading volume exceeds total for {instrument_id}")
        ratio = row["day_trading_volume_ratio"]
        if ratio is not None:
            if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not (0 <= ratio <= 1):
                raise ValueError(f"invalid day-trading ratio for {instrument_id}")
            if denominator is None or denominator <= 0:
                raise ValueError(f"ratio has invalid denominator for {instrument_id}")
            if not math.isclose(ratio, numerator / denominator, rel_tol=0, abs_tol=1e-12):
                raise ValueError(f"ratio does not match volumes for {instrument_id}")
            if row["status"] == "missing":
                raise ValueError(f"available ratio marked missing for {instrument_id}")
            valid_joins[exchange] += 1
        elif not isinstance(row["missing_reason"], str) or not row["missing_reason"]:
            raise ValueError(f"missing ratio has no reason for {instrument_id}")
    for exchange, source in payload["sources"].items():
        if source["status"] == "fresh" and valid_joins[exchange] == 0:
            raise ValueError(f"fresh source has no valid join for {exchange}")
