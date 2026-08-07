"""Attaching quarterly fundamentals to published theme symbol entries.

Adds a ``fundamentals`` object onto the ``direct_symbols`` / ``related_symbols``
entries already present in the public momentum payload, and gates how often
each symbol's quarterly statements need to be re-scraped from Goodinfo.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

# TWSE/TPEX filing deadlines, as (month, day) -> the quarter that becomes
# available on that date. Q4 arrives inside the annual report (31 March).
_FILING_DEADLINES = (
    ((3, 31), 4),
    ((5, 15), 1),
    ((8, 14), 2),
    ((11, 14), 3),
)


def latest_expected_quarter(as_of: datetime) -> str:
    """Return the newest quarterly statement period expected to be published.

    Taiwan filings land in arrears, but by a statutory deadline rather than a
    fixed offset: Q2 numbers appear on 14 August, not "two quarters after Q2".
    A flat lag stays a full quarter stale for months after each deadline and
    would refuse to refresh statements that are already public.
    """
    passed = [
        (as_of.year, quarter)
        for (month, day), quarter in _FILING_DEADLINES
        if (as_of.month, as_of.day) >= (month, day)
    ]
    if passed:
        year, quarter = passed[-1]
        # The annual report published in March carries the *previous* year's Q4.
        return f"{year - 1}Q4" if quarter == 4 else f"{year}Q{quarter}"

    # Before this year's first deadline the newest filing is last year's Q3,
    # published the preceding 14 November.
    return f"{as_of.year - 1}Q3"


def _iter_symbol_lists(payload: Mapping) -> list[list]:
    return [
        theme[key]
        for theme in payload.get("themes", [])
        for key in ("direct_symbols", "related_symbols")
        if key in theme
    ]


def symbols_due_for_refresh(
    payload: Mapping, *, cache: Mapping[str, Mapping], as_of: datetime
) -> list[str]:
    """Instrument ids whose cached fundamentals are missing or stale.

    This is the quarterly throttle: it stops an hourly pipeline from
    refetching a scraped third party 24x a day for data that only changes
    four times a year.
    """
    expected = latest_expected_quarter(as_of)
    instrument_ids = {
        symbol["instrument_id"]
        for symbol_list in _iter_symbol_lists(payload)
        for symbol in symbol_list
    }

    due = set()
    for instrument_id in instrument_ids:
        context = cache.get(instrument_id)
        if context is None:
            due.add(instrument_id)
            continue
        # A missing or non-string fiscal_quarter reads as stale. Comparing it
        # to the expected quarter directly is a TypeError, which would end the
        # whole radar publish over one damaged cache entry.
        quarter = context.get("fiscal_quarter")
        if not isinstance(quarter, str) or quarter < expected:
            due.add(instrument_id)

    return sorted(due)


def attach_symbol_fundamentals(payload: Mapping, contexts: Mapping[str, Mapping]) -> dict:
    """Return a new payload with ``fundamentals`` attached where available.

    Strictly additive: no existing key on the payload, a theme, or a symbol
    is removed, renamed, or altered. Symbols without a matching context are
    left exactly as-is, with no ``fundamentals`` key at all.
    """
    new_themes = []
    for theme in payload.get("themes", []):
        new_theme = dict(theme)
        for key in ("direct_symbols", "related_symbols"):
            if key not in theme:
                continue
            new_theme[key] = [
                {**symbol, "fundamentals": contexts[symbol["instrument_id"]]}
                if symbol["instrument_id"] in contexts
                else symbol
                for symbol in theme[key]
            ]
        new_themes.append(new_theme)

    return {**payload, "themes": new_themes}
