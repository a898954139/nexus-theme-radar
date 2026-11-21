#!/usr/bin/env python3
"""Market temperature: real market anchors for the pre-market board (issue #10).

News tone alone misled the board: on a day the US chip index closed sharply up,
the focus list still read bearish. This module puts five market facts on top of
the page and compares them with the net direction of the news:

  加權指數        TWSE FMTQIK, latest completed session
  台指期夜盤      TAIFEX open data, TX near month, 盤後 session
  費半 / TSM ADR  Finnhub quote API (documented, free key in FINNHUB_API_KEY);
                 SOX itself is not on the free tier, so SOXX (iShares
                 Semiconductor ETF) stands in and is labelled as a proxy
  外資買賣超      TWSE BFI82U, latest completed session

Rules (from the issue):

* Every indicator carries its own as-of time. A missing source yields a
  ``missing`` row with the reason -- never a carried-over or invented value.
* Each market is read on its own latest completed session; US and Taiwan
  holidays are not assumed to coincide.
* The news net direction is empty until directions exist; without it no
  divergence hint is shown.

The sector board also moves to TWSE MI_INDEX (official sector indices): the
previous third-party quote feed has been refusing GitHub runners, and the page
kept showing the last good August values as if they were current.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping

LOGGER = logging.getLogger(__name__)

TAIPEI = timezone(timedelta(hours=8))
TWSE_FMTQIK = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
TWSE_BFI82U = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
TWSE_MI_INDEX = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TAIFEX_FUT = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
FINNHUB_QUOTE = "https://finnhub.io/api/v1/quote"
USER_AGENT = "nexus-theme-radar/1.0 (+https://github.com/a898954139/nexus-theme-radar)"

# A news net or a market move inside these bands is "no clear lean".
NEWS_BAND = 0.5
MARKET_BAND_PCT = 0.3
NEWS_WINDOW_HOURS = 24

INDICATORS = (
    ("taiex", "加權指數"),
    ("tx_night", "台指期夜盤"),
    ("sox", "費城半導體"),
    ("tsm_adr", "TSM ADR"),
    ("foreign_net", "外資買賣超"),
)


# --- small parsing helpers ---------------------------------------------------

def _num(text: Any) -> float | None:
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    cleaned = re.sub(r"<[^>]+>", "", str(text or "")).replace(",", "").replace("%", "").strip()
    if cleaned in {"", "-", "--", "NULL", "X"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def roc_to_iso(text: str) -> str | None:
    found = re.match(r"^\s*(\d{2,3})/(\d{1,2})/(\d{1,2})\s*$", str(text or ""))
    if not found:
        return None
    year, month, day = (int(part) for part in found.groups())
    return date(year + 1911, month, day).isoformat()


def _missing(indicator_id: str, label: str, reason: str) -> dict[str, Any]:
    return {"id": indicator_id, "label": label, "missing": True, "reason": reason}


def _row(indicator_id: str, label: str, *, value: float, change: float | None,
         change_pct: float | None, as_of: str, session: str, source: str,
         unit: str = "") -> dict[str, Any]:
    return {
        "id": indicator_id, "label": label, "missing": False,
        "value": round(value, 2), "change": None if change is None else round(change, 2),
        "change_pct": None if change_pct is None else round(change_pct, 2),
        "unit": unit, "as_of": as_of, "session": session, "source": source,
    }


# --- TWSE: TAIEX --------------------------------------------------------------

def parse_fmtqik(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Latest row of FMTQIK -> TAIEX close, change and percent."""
    if payload.get("stat") != "OK":
        return None
    fields = list(payload.get("fields") or [])
    try:
        i_date = fields.index("日期")
        i_close = next(i for i, f in enumerate(fields) if "加權" in f)
        i_change = fields.index("漲跌點數")
    except (ValueError, StopIteration):
        return None
    rows = [r for r in payload.get("data") or [] if isinstance(r, list) and len(r) > max(i_date, i_close, i_change)]
    if not rows:
        return None
    last = rows[-1]
    close, change, day = _num(last[i_close]), _num(last[i_change]), roc_to_iso(last[i_date])
    if close is None or change is None or day is None:
        return None
    base = close - change
    return {"date": day, "close": close, "change": change,
            "pct": round(change / base * 100, 2) if base else None}


def parse_fmtqik_history(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every row of one FMTQIK month, oldest first."""
    if payload.get("stat") != "OK":
        return []
    fields = list(payload.get("fields") or [])
    try:
        i_date = fields.index("日期")
        i_close = next(i for i, f in enumerate(fields) if "加權" in f)
        i_change = fields.index("漲跌點數")
    except (ValueError, StopIteration):
        return []
    out = []
    for raw in payload.get("data") or []:
        close, change, day = _num(raw[i_close]), _num(raw[i_change]), roc_to_iso(raw[i_date])
        if close is None or change is None or day is None:
            continue
        base = close - change
        out.append({"date": day, "close": close, "change": change,
                    "pct": round(change / base * 100, 2) if base else None})
    return out


# --- TWSE: foreign net (BFI82U) ----------------------------------------------

def parse_bfi82u(payload: Mapping[str, Any]) -> float | None:
    """外資及陸資(不含外資自營商) net, NT$ 100 million (億元)."""
    if payload.get("stat") != "OK":
        return None
    for row in payload.get("data") or []:
        if isinstance(row, list) and row and str(row[0]).startswith("外資及陸資") and "不含" in str(row[0]):
            net = _num(row[-1])
            return None if net is None else round(net / 1e8, 1)
    return None


# --- TWSE: sector indices (MI_INDEX) -----------------------------------------

# MI_INDEX names (minus "類指數") -> the board's existing sector names.
SECTOR_ALIASES = {
    "紡織纖維": "紡織", "電腦及週邊設備": "電腦及週邊", "化學": "化學工業",
    "建材營造": "營建", "金融保險": "金融", "貿易百貨": "百貨貿易", "塑膠": "塑膠",
    "通信網路": "通信網路", "觀光餐旅": "觀光餐旅",
}
# Aggregates of several industries; an aggregate must not outrank an industry.
SECTOR_COMPOSITES = frozenset({"電子工業", "化學生技醫療", "水泥窯製", "塑膠化工", "機電"})


def _signed(raw_sign: Any, magnitude: float | None) -> float | None:
    if magnitude is None:
        return None
    text = str(raw_sign or "")
    if "green" in text or "-" in re.sub(r"<[^>]+>", "", text):
        return -abs(magnitude)
    return abs(magnitude)


def parse_sector_board(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Single-industry TWSE sector indices, sorted by percent change, descending."""
    if payload.get("stat") != "OK":
        return []
    rows: list[dict[str, Any]] = []
    for table in payload.get("tables") or []:
        fields = list(table.get("fields") or [])
        if not fields or "漲跌百分比(%)" not in fields:
            continue
        i_name, i_sign, i_pct = 0, fields.index("漲跌(+/-)") if "漲跌(+/-)" in fields else None, fields.index("漲跌百分比(%)")
        for raw in table.get("data") or []:
            name = str(raw[i_name]).strip()
            if not name.endswith("類指數"):
                continue
            short = name[: -len("類指數")]
            if short in SECTOR_COMPOSITES:
                continue
            pct = _num(raw[i_pct])
            if i_sign is not None and pct is not None and pct >= 0:
                pct = _signed(raw[i_sign], pct)
            if pct is None:
                continue
            rows.append({"name": SECTOR_ALIASES.get(short, short), "chg": round(pct, 2)})
        if rows:
            break  # table 0 (TWSE price indices) is the one the board uses
    seen: set[str] = set()
    unique = [r for r in rows if not (r["name"] in seen or seen.add(r["name"]))]
    unique.sort(key=lambda r: r["chg"], reverse=True)
    return unique


# --- TAIFEX: TX night session -------------------------------------------------

def parse_tx_night(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Near-month TX in the 盤後 (after-hours) session."""
    candidates = []
    for row in rows:
        if str(row.get("Contract", "")).strip() != "TX":
            continue
        if "盤後" not in str(row.get("TradingSession", "")):
            continue
        month = str(row.get("ContractMonth(Week)", "")).strip()
        if not re.fullmatch(r"\d{6}", month):
            continue  # spreads ("202611/202612") and weeklies
        last = _num(row.get("Last"))
        if last is None:
            continue
        candidates.append((month, row, last))
    if not candidates:
        return None
    month, row, last = min(candidates, key=lambda item: item[0])
    day = str(row.get("Date", ""))
    iso = f"{day[:4]}-{day[4:6]}-{day[6:8]}" if re.fullmatch(r"\d{8}", day) else day
    return {"date": iso, "month": month, "last": last,
            "change": _num(row.get("Change")), "pct": _num(row.get("%"))}


# --- Finnhub: US quotes --------------------------------------------------------

def parse_finnhub(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """{c, d, dp, t} -> last, change, pct, as-of (US/Eastern session date)."""
    last = _num(payload.get("c"))
    stamp = payload.get("t")
    if not last or not isinstance(stamp, (int, float)) or stamp <= 0:
        return None  # Finnhub answers unknown symbols with zeros
    moment = datetime.fromtimestamp(stamp, tz=timezone(timedelta(hours=-5)))
    return {"last": last, "change": _num(payload.get("d")), "pct": _num(payload.get("dp")),
            "time": moment.date().isoformat()}


# --- fetch orchestration ------------------------------------------------------

Getter = Callable[[str, Mapping[str, Any]], Any]


def requests_getter(session: Any, timeout: int = 20) -> Getter:
    def get(url: str, params: Mapping[str, Any]) -> Any:
        response = session.get(url, params=dict(params), timeout=timeout,
                               headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        response.raise_for_status()
        return response.json()
    return get


def _recent_days(today: date, count: int = 7) -> list[date]:
    return [today - timedelta(days=offset) for offset in range(count)
            if (today - timedelta(days=offset)).weekday() < 5]


def fetch_taiex(get: Getter, today: date) -> dict[str, Any] | None:
    for month_start in (today.replace(day=1), (today.replace(day=1) - timedelta(days=1)).replace(day=1)):
        parsed = parse_fmtqik(get(TWSE_FMTQIK, {"response": "json", "date": month_start.strftime("%Y%m%d")}))
        if parsed:
            return parsed
    return None


def fetch_taiex_history(get: Getter, today: date) -> list[dict[str, Any]]:
    """This month's TAIEX rows (plus last month's in the first days of a month)."""
    months = [today.replace(day=1)]
    if today.day <= 5:
        months.insert(0, (today.replace(day=1) - timedelta(days=1)).replace(day=1))
    rows: list[dict[str, Any]] = []
    for month_start in months:
        rows.extend(parse_fmtqik_history(get(TWSE_FMTQIK, {"response": "json", "date": month_start.strftime("%Y%m%d")})))
    return rows


def merge_taiex_history(history: Mapping[str, Any], rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Return ``history`` itself when nothing changed, else a new dict with rows merged by date."""
    by_date = {row["date"]: dict(row) for row in history.get("rows") or [] if isinstance(row, Mapping)}
    changed = False
    for row in rows:
        if by_date.get(row["date"]) != dict(row):
            by_date[row["date"]] = dict(row)
            changed = True
    if not changed:
        return history
    return {**history, "rows": [by_date[key] for key in sorted(by_date)]}


def fetch_foreign_net(get: Getter, today: date) -> tuple[str, float] | None:
    for day in _recent_days(today):
        net = parse_bfi82u(get(TWSE_BFI82U, {"response": "json", "dayDate": day.strftime("%Y%m%d"), "type": "day"}))
        if net is not None:
            return day.isoformat(), net
    return None


def fetch_sector_board(get: Getter, today: date) -> tuple[str, list[dict[str, Any]]] | None:
    for day in _recent_days(today):
        board = parse_sector_board(get(TWSE_MI_INDEX, {"response": "json", "date": day.strftime("%Y%m%d"), "type": "IND"}))
        if board:
            return day.isoformat(), board
    return None


US_SYMBOLS = {"sox": ("SOXX", "SOXX ETF 代理・美股最近收盤"), "tsm_adr": ("TSM", "美股最近收盤")}


def build_indicators(get: Getter, now: datetime, finnhub_key: str = "") -> list[dict[str, Any]]:
    today = now.astimezone(TAIPEI).date()
    labels = dict(INDICATORS)
    out: dict[str, dict[str, Any]] = {}

    def attempt(key: str, fn: Callable[[], dict[str, Any] | None], reason: str) -> None:
        try:
            row = fn()
        except LookupError:
            row = None  # source not configured; the reason says so
        except Exception as error:  # noqa: BLE001 - one source must not blank the bar
            LOGGER.warning("market_temperature_fetch_failed id=%s error=%s", key, type(error).__name__)
            row = None
        out[key] = row or _missing(key, labels[key], reason)

    def taiex() -> dict[str, Any] | None:
        parsed = fetch_taiex(get, today)
        if not parsed:
            return None
        return _row("taiex", labels["taiex"], value=parsed["close"], change=parsed["change"],
                    change_pct=parsed["pct"], as_of=parsed["date"], session="台股收盤", source="TWSE")

    def tx_night() -> dict[str, Any] | None:
        parsed = parse_tx_night(get(TAIFEX_FUT, {}))
        if not parsed:
            return None
        return _row("tx_night", labels["tx_night"], value=parsed["last"], change=parsed["change"],
                    change_pct=parsed["pct"], as_of=parsed["date"],
                    session=f"TX {parsed['month']} 盤後", source="TAIFEX")

    def us(key: str) -> dict[str, Any] | None:
        if not finnhub_key:
            raise LookupError("no key")
        symbol, session = US_SYMBOLS[key]
        quote = parse_finnhub(get(FINNHUB_QUOTE, {"symbol": symbol, "token": finnhub_key}))
        if not quote:
            return None
        return _row(key, labels[key], value=quote["last"], change=quote["change"],
                    change_pct=quote["pct"], as_of=quote["time"], session=session, source="Finnhub")

    def foreign() -> dict[str, Any] | None:
        parsed = fetch_foreign_net(get, today)
        if not parsed:
            return None
        day, net = parsed
        return _row("foreign_net", labels["foreign_net"], value=net, change=None, change_pct=None,
                    as_of=day, session="前一交易日", source="TWSE", unit="億")

    attempt("taiex", taiex, "TWSE 無回應或無資料")
    attempt("tx_night", tx_night, "TAIFEX 無夜盤資料")
    us_reason = "美股報價無回應" if finnhub_key else "未設定 FINNHUB_API_KEY"
    attempt("sox", lambda: us("sox"), us_reason)
    attempt("tsm_adr", lambda: us("tsm_adr"), us_reason)
    attempt("foreign_net", foreign, "TWSE 無回應或無資料")
    return [out[key] for key, _ in INDICATORS]


# --- news vs market -----------------------------------------------------------

def news_net(events: Iterable[Mapping[str, Any]], now: datetime,
             window_hours: int = NEWS_WINDOW_HOURS) -> dict[str, Any] | None:
    """Score-weighted bull minus bear over the window. None before directions exist."""
    cutoff = now - timedelta(hours=window_hours)
    bull = bear = 0
    net = 0.0
    directed = False
    for event in events:
        if "direction" not in event:
            continue
        directed = True
        try:
            published = datetime.fromisoformat(str(event.get("publishedAt")))
        except ValueError:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        if published < cutoff:
            continue
        direction = event.get("direction")
        score = event.get("score") if isinstance(event.get("score"), (int, float)) else 0.0
        if direction == 1:
            bull += 1
            net += float(score)
        elif direction == -1:
            bear += 1
            net -= float(score)
    if not directed:
        return None
    lean = "偏多" if net >= NEWS_BAND else "偏空" if net <= -NEWS_BAND else "中性"
    return {"net": round(net, 2), "bull": bull, "bear": bear, "lean": lean, "window_hours": window_hours}


def market_lean(indicators: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Lean of the anchors that trade after the Taiwan close (TX night, SOX, TSM ADR).

    Falls back to the TAIEX close when none of them is available.
    """
    by_id = {row["id"]: row for row in indicators if not row.get("missing")}
    overnight = [by_id[key]["change_pct"] for key in ("tx_night", "sox", "tsm_adr")
                 if key in by_id and isinstance(by_id[key].get("change_pct"), (int, float))]
    basis = "夜盤/美股"
    moves = overnight
    if not moves and isinstance(by_id.get("taiex", {}).get("change_pct"), (int, float)):
        moves, basis = [by_id["taiex"]["change_pct"]], "加權指數"
    if not moves:
        return {"lean": None, "avg_pct": None, "basis": None}
    avg = sum(moves) / len(moves)
    lean = "偏多" if avg >= MARKET_BAND_PCT else "偏空" if avg <= -MARKET_BAND_PCT else "中性"
    return {"lean": lean, "avg_pct": round(avg, 2), "basis": basis}


def divergence(news: Mapping[str, Any] | None, market: Mapping[str, Any]) -> dict[str, Any] | None:
    if not news or market.get("lean") not in {"偏多", "偏空"} or news.get("lean") not in {"偏多", "偏空"}:
        return None
    if news["lean"] == market["lean"]:
        return None
    return {"message": f"新聞{news['lean']}，市場{market['lean']}",
            "news_lean": news["lean"], "market_lean": market["lean"]}


def build_market(get: Getter, now: datetime, events: Iterable[Mapping[str, Any]],
                 finnhub_key: str = "") -> dict[str, Any]:
    indicators = build_indicators(get, now, finnhub_key)
    news = news_net(list(events), now)
    lean = market_lean(indicators)
    return {
        "generated_at": now.isoformat(),
        "indicators": indicators,
        "news": news,
        "market": lean,
        "divergence": divergence(news, lean),
    }
