"""Whole-market daily institutional flows, stored one file per symbol.

The leaderboards only reach the ~293 symbols that ranked. Looking up an
arbitrary stock needs the whole market -- about 2,220 symbols a day -- and the
size of that decides the layout rather than taste.

Measured 2026-08-07: sixty days of the whole market in one file is 7.1MB, which
every visitor would download in order to read one symbol. Split per symbol it
is 2.9KB each and the page fetches exactly the one it was asked for. Rows are
arrays rather than objects because repeating five key names across ~133,000
rows costs 2.1x the bytes and adds nothing a documented field order does not.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

LOGGER = logging.getLogger(__name__)

FLOWS_DIR = "flows"
FLOWS_INDEX_FILE = "index.json"
SCHEMA_VERSION = 1

# The row layout, published so the page reads by index instead of guessing.
SERIES_FIELDS = ("date", "foreign_net", "trust_net", "dealer_net", "total_net")

DEFAULT_HISTORY_DAYS = 60

# Taiwan codes are 4-6 alphanumerics; ETFs carry a trailing letter. Anchored so
# a crafted code cannot escape the directory -- the page passes this straight
# from a URL query parameter.
_SAFE_CODE = re.compile(r"^[A-Za-z0-9]{1,10}$")
_SAFE_EXCHANGE = re.compile(r"^[A-Z]{2,8}$")


def flow_filename(instrument_id: str) -> str:
    """Return the per-symbol filename, or raise if either half is unsafe.

    The exchange is part of the name because codes are not unique across
    exchanges: one filename for both would silently serve the wrong company.
    """
    exchange, _, code = str(instrument_id).partition(":")
    if not _SAFE_EXCHANGE.match(exchange) or not _SAFE_CODE.match(code):
        raise ValueError(f"unsafe instrument id for a filename: {instrument_id!r}")
    return f"{exchange}-{code}.json"


def split_by_symbol(flows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Turn one day of whole-market rows into per-symbol entries."""
    by_symbol: dict[str, dict[str, Any]] = {}
    for flow in flows:
        instrument_id = flow["instrument_id"]
        entry = by_symbol.setdefault(instrument_id, {
            "instrument_id": instrument_id,
            "symbol": flow.get("symbol", ""),
            "name": flow.get("name", ""),
            "exchange": flow.get("exchange", ""),
            "series": [],
        })
        entry["series"].append([flow[field] for field in SERIES_FIELDS])
    return by_symbol


def merge_symbol_series(
    existing: Mapping[str, Any] | None,
    new_rows: Sequence[Sequence[Any]],
    *,
    history_days: int = DEFAULT_HISTORY_DAYS,
) -> list[list[Any]]:
    """Fold new rows into a stored series, newest first and without duplicates.

    A stored series that is missing or malformed is replaced rather than
    propagated: one truncated write should not make every later run fail.
    """
    prior = existing.get("series") if isinstance(existing, Mapping) else None
    if not isinstance(prior, list):
        prior = []

    incoming_dates = {row[0] for row in new_rows}
    kept = [
        row for row in prior
        if isinstance(row, list) and row and row[0] not in incoming_dates
    ]
    kept.extend(list(row) for row in new_rows)
    kept.sort(key=lambda row: row[0], reverse=True)
    return kept[:history_days]


def build_index(entries: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Build the lookup the page needs to turn a typed code into a filename.

    Without it the page would have to guess an exchange and 404 half the time.
    Codes are not globally unique, so a collision keeps both rather than
    dropping one -- a dropped symbol is permanently unsearchable.
    """
    symbols: dict[str, Any] = {}
    for instrument_id in sorted(entries):
        entry = entries[instrument_id]
        exchange, _, code = instrument_id.partition(":")
        record = {
            "file": flow_filename(instrument_id),
            "name": entry.get("name", ""),
            "exchange": exchange,
        }
        if code in symbols:
            symbols[code].setdefault("alternates", []).append(record)
        else:
            symbols[code] = record

    return {"schema_version": SCHEMA_VERSION, "symbols": symbols}


def write_symbol_files(
    directory: Path,
    by_symbol: Mapping[str, Mapping[str, Any]],
    *,
    history_days: int = DEFAULT_HISTORY_DAYS,
) -> int:
    """Merge each symbol's new rows into its file. Returns files written."""
    directory.mkdir(parents=True, exist_ok=True)
    written = 0

    for instrument_id, entry in by_symbol.items():
        try:
            filename = flow_filename(instrument_id)
        except ValueError as error:
            LOGGER.warning("flows_symbol_skipped id=%s error=%s", instrument_id, error)
            continue

        path = directory / filename
        existing: Mapping[str, Any] | None = None
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                LOGGER.warning("flows_file_unreadable path=%s error=%s", path, error)

        series = merge_symbol_series(existing, entry["series"], history_days=history_days)
        body = {
            "schema_version": SCHEMA_VERSION,
            "instrument_id": instrument_id,
            "symbol": entry.get("symbol", ""),
            "name": entry.get("name", ""),
            "exchange": entry.get("exchange", ""),
            "unit": "shares",
            "fields": list(SERIES_FIELDS),
            "series": series,
        }
        path.write_text(json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n",
                        encoding="utf-8")
        written += 1

    return written


def write_index(directory: Path, entries: Mapping[str, Mapping[str, Any]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    index = build_index(entries)
    (directory / FLOWS_INDEX_FILE).write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def load_existing_index(directory: Path) -> dict[str, Mapping[str, Any]]:
    """Read back the symbols already on disk, so a single day's run does not
    shrink the index to just the symbols that traded today."""
    path = directory / FLOWS_INDEX_FILE
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    known: dict[str, Mapping[str, Any]] = {}
    for code, record in (payload.get("symbols") or {}).items():
        for item in [record, *(record.get("alternates") or [])]:
            exchange = item.get("exchange")
            if exchange:
                known[f"{exchange}:{code}"] = {"name": item.get("name", ""), "exchange": exchange}
    return known
