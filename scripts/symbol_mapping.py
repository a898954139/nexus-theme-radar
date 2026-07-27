"""Extract auditable direct Taiwan stock mentions from normalized news items."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SYMBOL_ALIASES_PATH = ROOT / "config" / "symbol_aliases.tw.json"
DEFAULT_MARKET_ID = "TW_EQUITY"
DEFAULT_EXCHANGE = "TWSE"
ASSET_CLASS = "equity"
TEXT_FIELDS = ("title", "title_zh", "summary", "content")
STOCK_CODE_PATTERN = re.compile(
    r"(?<![0-9A-Za-z])(?P<symbol>\d{4})(?:\.TW)?"
    r"(?![0-9A-Za-z])(?!\.[A-Za-z])",
    re.IGNORECASE,
)


def load_symbol_aliases(
    path: str | Path = DEFAULT_SYMBOL_ALIASES_PATH,
) -> dict[str, Any]:
    """Load and validate the compact Taiwan symbol alias seed."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    symbols = payload.get("symbols")
    if not isinstance(symbols, dict) or not symbols:
        raise ValueError("symbol aliases must contain a non-empty symbols object")
    if payload.get("market_id") != DEFAULT_MARKET_ID:
        raise ValueError(f"symbol aliases market_id must be {DEFAULT_MARKET_ID}")
    if payload.get("market_scope") != [DEFAULT_MARKET_ID]:
        raise ValueError(f"symbol aliases market_scope must be [{DEFAULT_MARKET_ID}]")

    for symbol, metadata in symbols.items():
        if not re.fullmatch(r"\d{4}", symbol) or not isinstance(metadata, dict):
            raise ValueError("symbol aliases must use four-digit symbol keys")
        name_zh = metadata.get("name_zh")
        aliases = metadata.get("aliases")
        if not isinstance(name_zh, str) or not name_zh.strip():
            raise ValueError(f"{symbol}.name_zh must be a non-empty string")
        if not isinstance(aliases, list) or not aliases:
            raise ValueError(f"{symbol}.aliases must be a non-empty array")
        if any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
            raise ValueError(f"{symbol}.aliases must contain non-empty strings")
        if metadata.get("exchange") not in {"TWSE", "TPEX"}:
            raise ValueError(f"{symbol}.exchange must be TWSE or TPEX")
    return payload


def instrument_for_symbol(
    symbol: str,
    aliases: dict[str, Any],
    *,
    evidence: str,
    reason: str,
) -> dict[str, str]:
    metadata = aliases["symbols"].get(symbol, {})
    exchange = str(metadata.get("exchange") or DEFAULT_EXCHANGE)
    market_id = str(aliases.get("market_id") or DEFAULT_MARKET_ID)
    return {
        "instrument_id": f"{exchange}:{symbol}",
        "market_id": market_id,
        "asset_class": ASSET_CLASS,
        "symbol": symbol,
        "exchange": exchange,
        "name_zh": str(metadata.get("name_zh") or ""),
        "evidence": evidence,
        "reason": reason,
    }


def extract_direct_symbols(
    item: dict[str, Any],
    aliases: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Return direct symbol mentions in stable field and mention order."""

    active_aliases = aliases if aliases is not None else load_symbol_aliases()
    symbols = active_aliases["symbols"]
    found: dict[str, dict[str, str]] = {}

    for field in TEXT_FIELDS:
        text = str(item.get(field) or "")
        if not text:
            continue

        for match in STOCK_CODE_PATTERN.finditer(text):
            symbol = match.group("symbol")
            has_tw_suffix = match.group(0).upper().endswith(".TW")
            if (symbol in symbols or has_tw_suffix) and symbol not in found:
                found[symbol] = instrument_for_symbol(
                    symbol,
                    active_aliases,
                    evidence=f"{field}: {match.group(0)}",
                    reason="direct stock code mention",
                )

        normalized_text = text.casefold()
        for symbol, metadata in symbols.items():
            if symbol in found:
                continue
            for alias_value in metadata["aliases"]:
                alias = str(alias_value)
                index = normalized_text.find(alias.casefold())
                if index < 0:
                    continue
                found[symbol] = instrument_for_symbol(
                    symbol,
                    active_aliases,
                    evidence=f"{field}: {text[index:index + len(alias)]}",
                    reason="direct company alias mention",
                )
                break

    return list(found.values())
