"""Extract auditable direct Taiwan stock mentions from normalized news items."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SYMBOL_ALIASES_PATH = ROOT / "config" / "symbol_aliases.tw.json"
DEFAULT_SYMBOL_REGISTRY_PATH = ROOT / "config" / "symbol_registry.tw.json"
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


def load_symbol_registry(
    path: str | Path = DEFAULT_SYMBOL_REGISTRY_PATH,
) -> dict[str, Any]:
    """Load the current official Taiwan-company registry.

    The registry is deliberately separate from the compact alias seed: its
    names resolve taxonomy-derived symbols, but they are not used for broad
    substring matching in news text.
    """

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("symbols")
    if not isinstance(rows, list) or not rows:
        raise ValueError("symbol registry must contain a non-empty symbols array")

    symbols: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("symbol registry entries must be JSON objects")
        symbol = str(row.get("symbol") or "")
        exchange = str(row.get("exchange") or "")
        name_zh = str(row.get("name_zh") or "").strip()
        if not re.fullmatch(r"\d{4}", symbol):
            raise ValueError("symbol registry symbols must use four-digit keys")
        if exchange not in {"TWSE", "TPEX", "ESB"}:
            raise ValueError(f"{symbol}.exchange must be TWSE, TPEX, or ESB")
        if not name_zh:
            raise ValueError(f"{symbol}.name_zh must be non-empty")
        if symbol in symbols:
            raise ValueError(f"symbol registry contains duplicate symbol {symbol}")
        symbols[symbol] = {
            "name_zh": name_zh,
            "exchange": exchange,
        }

    normalized = dict(payload)
    normalized["symbols_by_symbol"] = symbols
    return normalized


def load_symbol_universe(
    aliases_path: str | Path = DEFAULT_SYMBOL_ALIASES_PATH,
    registry_path: str | Path = DEFAULT_SYMBOL_REGISTRY_PATH,
) -> dict[str, Any]:
    """Combine direct-mention aliases with official metadata for taxonomy seeds.

    Registry-only entries receive an empty alias list, so their company names
    never become unrestricted substring matches. Exact four-digit code mentions
    remain resolvable because they are in the merged symbol map.
    """

    aliases = load_symbol_aliases(aliases_path)
    registry = load_symbol_registry(registry_path)
    return augment_symbol_aliases_with_registry(aliases, registry)


def augment_symbol_aliases_with_registry(
    aliases: dict[str, Any],
    registry: dict[str, Any] | None = None,
    registry_path: str | Path = DEFAULT_SYMBOL_REGISTRY_PATH,
) -> dict[str, Any]:
    """Add official metadata without adding company-name substring aliases."""

    active_registry = registry if registry is not None else load_symbol_registry(registry_path)
    merged = dict(aliases)
    merged_symbols = {
        symbol: dict(metadata)
        for symbol, metadata in aliases["symbols"].items()
    }
    for symbol, metadata in active_registry["symbols_by_symbol"].items():
        if metadata["exchange"] not in {"TWSE", "TPEX"}:
            continue
        existing = merged_symbols.get(symbol)
        if existing is None:
            merged_symbols[symbol] = {
                "name_zh": metadata["name_zh"],
                "exchange": metadata["exchange"],
                "aliases": [],
            }
            continue
        # Keep the curated display name/aliases, but repair stale exchange
        # metadata from the authoritative current registry when available.
        existing["exchange"] = metadata["exchange"]
        if not str(existing.get("name_zh") or "").strip():
            existing["name_zh"] = metadata["name_zh"]

    merged["symbols"] = merged_symbols
    merged["symbol_registry_count"] = len(active_registry["symbols_by_symbol"])
    merged["direct_alias_symbol_count"] = len(aliases["symbols"])
    return merged


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
