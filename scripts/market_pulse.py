#!/usr/bin/env python3
"""Fetch Taiwan sector indices and build the homepage sector-change list.

One request returns every quoted instrument, indices included, so the whole
sector board costs a single call rather than one per sector.

Sector names are pinned in SECTOR_NAMES rather than read from the response:
the quote feed carries codes only, and the code ranges are not guessable --
^033 is 航運, not 半導體, and a chart mislabelled that way looks correct while
being wrong. Composite indices (不含金融, 電子類) are excluded from the board so
a whole-market aggregate cannot outrank a single industry.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Mapping

import requests

LOGGER = logging.getLogger(__name__)

QUOTE_URL = "https://www.wantgoo.com/investrue/all-quote-info"
REFERER = "https://www.wantgoo.com/index/listed/industry"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# 上市 (TWSE)
LISTED: dict[str, str] = {
    "^011": "水泥", "^012": "食品", "^013": "塑膠", "^014": "紡織",
    "^015": "電機機械", "^016": "電器電纜", "^017": "化學工業", "^018": "生技醫療",
    "^019": "玻璃陶瓷", "^020": "造紙", "^021": "鋼鐵", "^022": "橡膠",
    "^023": "汽車", "^024": "半導體", "^025": "電腦及週邊", "^026": "光電",
    "^027": "通信網路", "^028": "電子零組件", "^029": "電子通路", "^030": "資訊服務",
    "^031": "其他電子", "^032": "營建", "^033": "航運", "^034": "觀光餐旅",
    "^035": "金融", "^036": "百貨貿易", "^037": "油電燃氣", "^038": "其他",
    "^263": "化生類", "^264": "電子類", "^658": "不含金融", "^659": "水泥窯類",
    "^660": "塑化類", "^661": "機電類", "^663": "非電指", "^664": "未金電",
    "^665": "綠能環保", "^666": "數位雲端", "^667": "運動休閒", "^668": "居家生活",
}

# 上櫃 (TPEx)
OTC: dict[str, str] = {
    "^044": "櫃紡織纖維", "^045": "櫃電機機械", "^047": "櫃化學工業", "^048": "櫃生技醫療",
    "^050": "櫃鋼鐵工業", "^052": "櫃半導體", "^053": "櫃電腦及週邊", "^054": "櫃光電",
    "^055": "櫃通訊網路", "^056": "櫃電子零組件", "^057": "櫃電子通路", "^058": "櫃資訊服務",
    "^059": "櫃其他電子", "^060": "櫃建材營造", "^061": "櫃航運", "^062": "櫃觀光餐旅",
    "^066": "櫃其他", "^260": "櫃文創", "^669": "櫃電子工業", "^670": "櫃綠能環保",
    "^671": "櫃數位雲端", "^673": "櫃居家生活",
}

SECTOR_NAMES: dict[str, str] = {**LISTED, **OTC}

# Whole-market aggregates, not industries -- kept out of the sector board.
COMPOSITE = frozenset({"^263", "^264", "^658", "^663", "^664", "^669"})

# The homepage board: single-industry TWSE groups only.
BOARD_CODES = tuple(code for code in LISTED if code not in COMPOSITE)


def fetch_quotes(session: requests.Session | None = None, timeout: int = 25) -> list[dict[str, Any]]:
    """Return every quoted instrument from the upstream feed."""
    sess = session or requests.Session()
    response = sess.get(
        QUOTE_URL,
        headers={"User-Agent": USER_AGENT, "Referer": REFERER, "Accept": "application/json"},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError(f"expected a list of quotes, got {type(payload).__name__}")
    return payload


def _pct_change(quote: Mapping[str, Any]) -> float | None:
    """Percent change vs previous close, or None when the base is unusable."""
    previous = quote.get("previousClose")
    close = quote.get("close")
    if not isinstance(previous, (int, float)) or not isinstance(close, (int, float)):
        return None
    if not previous:
        return None
    return round((close - previous) / previous * 100, 2)


def build_sector_board(
    quotes: Iterable[Mapping[str, Any]],
    codes: Iterable[str] = BOARD_CODES,
) -> list[dict[str, Any]]:
    """Sector rows sorted by percent change, descending.

    Sorted here so the page can draw the bars in array order without
    re-deriving business rules in the browser.
    """
    by_id = {q.get("id"): q for q in quotes if isinstance(q, Mapping)}
    rows: list[dict[str, Any]] = []
    for code in codes:
        quote = by_id.get(code)
        if quote is None:
            LOGGER.warning("sector %s missing from quote feed", code)
            continue
        change = _pct_change(quote)
        if change is None:
            LOGGER.warning("sector %s has no usable previous close", code)
            continue
        rows.append({"name": SECTOR_NAMES[code], "chg": change})
    rows.sort(key=lambda row: row["chg"], reverse=True)
    return rows


def main() -> int:  # pragma: no cover - manual smoke entrypoint
    logging.basicConfig(level=logging.INFO)
    board = build_sector_board(fetch_quotes())
    print(json.dumps(board, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
