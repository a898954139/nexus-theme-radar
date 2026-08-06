"""Fetch-and-attach step joining quarterly fundamentals to the public payload.

Sits between ``symbols_due_for_refresh`` and ``attach_symbol_fundamentals``,
and owns the containment rules for putting a scraped source inside an hourly
pipeline: fetch only what the quarterly throttle says is due, cap how much one
run may fetch, and treat every scraper failure as "no fundamentals for this
symbol" rather than an error the radar run has to handle.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.theme_symbol_fundamentals import (
    attach_symbol_fundamentals,
    symbols_due_for_refresh,
)

LOGGER = logging.getLogger(__name__)

# One quarter's worth of the radar pool, with headroom. Guards against a pool
# that suddenly grows turning a single hourly run into hundreds of scrapes.
DEFAULT_MAX_FETCHES = 40

FUNDAMENTALS_CACHE_FILE = "theme-symbol-fundamentals.json"


def load_fundamentals_cache(path: Path) -> dict[str, Mapping[str, Any]]:
    """Read the quarterly cache, degrading to empty on anything unreadable.

    A damaged cache should cost one refetch, never an aborted radar run.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    symbols = payload.get("symbols")
    if not isinstance(symbols, dict):
        return {}
    return {
        key: value for key, value in symbols.items() if isinstance(value, Mapping)
    }


def write_fundamentals_cache(path: Path, cache: Mapping[str, Mapping[str, Any]]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"schema_version": 1, "symbols": dict(cache)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(destination)


def _bare_ticker(instrument_id: str) -> str:
    """Goodinfo is queried by 4-digit ticker; ``TWSE:``/``TPEX:`` is Nexus
    canonical identity and 404s there."""
    return instrument_id.split(":", 1)[-1]


def enrich_with_fundamentals(
    payload: Mapping[str, Any],
    *,
    cache: Mapping[str, Mapping[str, Any]],
    as_of: datetime,
    fetch: Callable[[str], Mapping[str, Any]],
    max_fetches: int = DEFAULT_MAX_FETCHES,
) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
    """Return the payload with fundamentals attached, plus the updated cache.

    ``fetch`` takes a bare ticker and returns one ``fundamental_context``. It
    may raise; a raising symbol simply ends up without fundamentals.
    """
    contexts: dict[str, Mapping[str, Any]] = dict(cache)
    due = symbols_due_for_refresh(payload, cache=cache, as_of=as_of)

    if len(due) > max_fetches:
        LOGGER.warning(
            "fundamentals_fetch_budget_exceeded due=%d budget=%d deferred=%s",
            len(due), max_fetches, due[max_fetches:],
        )
        due = due[:max_fetches]

    for instrument_id in due:
        try:
            contexts[instrument_id] = fetch(_bare_ticker(instrument_id))
        except Exception as error:  # noqa: BLE001 - a scraped source must never
            # take down the hourly theme-momentum publish, which is this
            # pipeline's actual job.
            LOGGER.warning(
                "fundamentals_fetch_failed symbol=%s error=%s", instrument_id, error,
            )

    return attach_symbol_fundamentals(payload, contexts), contexts
