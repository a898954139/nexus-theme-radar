"""Nexus core technical read for every stock on the radar (job/mac/jobs.conf: nexus-structure).

The stock page used to show Nexus structure only for the handful of names in
the 07:30 daily report. This job runs the same pinned Nexus structure detector
(``analyze_stock_audit_technical._run_detector``: private npm package
``nexus-structure-detector``, sha256-pinned, never vendored here) over every
instrument the stock watchlist can show (``searchable``), on D1 and on
completed W1 bars, plus the local PVA runtime when it is installed.

Per stock it keeps a mechanical read, not a trade call:

* bias per timeframe from the latest non-internal structure break (BOS/CHoCH),
  same rule as the stock audit's ``_structure_read``;
* active FVG / order-block zones (the audit's ``_zone_validation``: an FVG is
  dead once wicked through, an OB once a later body closes through it) and the
  nearest unbroken swing high / low, as resistance / support around the close;
* the last few structure breaks;
* PVA P / V / A on D1 when the runtime is present (else ``pva_status`` says why).

Candles: Yahoo Finance daily bars (``.TW`` / ``.TWO``, 5y), completed sessions
only (today's bar is dropped before 14:35 Taipei). Writes
``data/nexus-structure.json``; ``radar_publish.py --dataset nexus-structure``
upserts one current row per instrument (radar.nexus_structure).

The detector is required: if it is missing or its hash drifted the job writes
nothing and exits 1, so the scheduler alert fires instead of the page showing
an empty read. A single stock that fails (no candles, too few bars) is listed
in ``unavailable`` and keeps its previous published row.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time as dtime, timedelta, timezone
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

try:
    from scripts import analyze_stock_audit_technical as tech
except ModuleNotFoundError:
    import analyze_stock_audit_technical as tech

LOGGER = logging.getLogger("nexus_structure")
TZ = ZoneInfo("Asia/Taipei")
OUTPUT_FILENAME = "nexus-structure.json"
WATCHLIST_FILENAME = "public-stock-watchlist-v1.json"
METHOD_VERSION = "nexus_structure_v1"
MIN_D1_BARS = 120
MIN_W1_BARS = 30
SESSION_CLOSE = dtime(14, 35)
ZONE_AGE_DAYS = {"D1": 180, "W1": 730}
PIVOT_LOOKBACK = {"D1": 250, "W1": 156}
MAX_LEVELS_PER_SIDE = 3
MAX_BREAKS = 4
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5y&interval=1d"

Detector = Callable[..., Mapping[str, Any]]


# ------------------------------------------------------------------ candles


def yahoo_symbol(symbol: str, exchange: str) -> str | None:
    suffix = {"TWSE": "TW", "TPEX": "TWO"}.get(exchange)
    return f"{symbol}.{suffix}" if suffix and symbol.isalnum() else None


def shape_candles(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Yahoo chart payload -> oldest-first daily OHLCV with Taipei dates (mirrors backend shapeCandles)."""
    result = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
    times = result.get("timestamp") or []
    quotes = ((result.get("indicators") or {}).get("quote") or [{}])[0] or {}
    offset = result.get("meta", {}).get("gmtoffset", 8 * 3600)
    rows: dict[str, dict[str, Any]] = {}
    for index, stamp in enumerate(times):
        values = {}
        for key in ("open", "high", "low", "close"):
            series = quotes.get(key) or []
            value = series[index] if index < len(series) else None
            if not isinstance(value, (int, float)) or value != value or value <= 0:
                break
            values[key] = round(float(value), 2)
        else:
            volume_series = quotes.get("volume") or []
            volume = volume_series[index] if index < len(volume_series) else None
            day = datetime.fromtimestamp(int(stamp) + int(offset), tz=timezone.utc).date().isoformat()
            low = min(values["low"], values["open"], values["close"])
            high = max(values["high"], values["open"], values["close"])
            rows[day] = {"date": day, **values, "low": low, "high": high,
                         "volume": float(volume) if isinstance(volume, (int, float)) and volume >= 0 else 0.0}
    return [rows[day] for day in sorted(rows)]


def completed_sessions(candles: Sequence[Mapping[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Drop today's bar while the session is still open (partial bar would fake a break)."""
    local = now.astimezone(TZ)
    today = local.date().isoformat()
    out = [dict(c) for c in candles if c["date"] <= today]
    if out and out[-1]["date"] == today and local.time() < SESSION_CLOSE:
        out.pop()
    return out


def fetch_candles(session: requests.Session, symbol: str, exchange: str) -> list[dict[str, Any]]:
    ticker = yahoo_symbol(symbol, exchange)
    if ticker is None:
        raise tech.TechnicalInputError(f"no Yahoo ticker for {exchange}:{symbol}")
    response = session.get(YAHOO_URL.format(symbol=quote(ticker)), timeout=20)
    if response.status_code != 200:
        raise tech.TechnicalInputError(f"Yahoo answered {response.status_code} for {ticker}")
    return shape_candles(response.json())


# --------------------------------------------------------------- analysis


def completed_weeks(candles: Sequence[Mapping[str, Any]], today: date) -> list[dict[str, Any]]:
    """W1 bars of finished weeks only.

    The last week counts as finished once its Friday session is in, or once
    ``today`` is in a later week (a holiday Friday). aggregate_completed_weekly
    drops the week of the date it is given, so hand it the Monday after.
    """
    as_of = tech._date(candles[-1]["date"])
    week_start = as_of - timedelta(days=as_of.weekday())
    finished = as_of.weekday() >= 4 or today - timedelta(days=today.weekday()) > week_start
    report = week_start + timedelta(days=7) if finished else as_of
    weekly, _meta = tech.aggregate_completed_weekly(candles, report)
    return weekly


def _bias(direction: int | None) -> str:
    return {1: "偏多", -1: "偏空"}.get(direction or 0, "中性")


def overall_bias(d1: str, w1: str) -> str:
    if d1 == w1:
        return d1
    if "中性" in (d1, w1):
        return d1 if w1 == "中性" else w1
    return "分歧"


def _md(iso: str | None) -> str:
    return f"{int(iso[5:7])}/{int(iso[8:10])}" if iso else "—"


def _px(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def read_timeframe(
    candles: Sequence[Mapping[str, Any]],
    *,
    timeframe: str,
    detector: Detector,
    mintick: float,
) -> dict[str, Any]:
    engine = detector(candles, timeframe=timeframe, mintick=mintick)
    current = engine.get("current") or {}
    breaks = tech._normalize_breaks(current.get("structureBreaks", []), candles, timeframe)
    external = [b for b in breaks if not b.get("internal")]
    latest = external[-1] if external else None
    as_of = tech._date(candles[-1]["date"])
    raw_zones = list(current.get("fvgZones", [])) + list(current.get("obZones", []))
    ids = {str(z.get("id")) for z in raw_zones}
    zones = [
        tech._zone_validation(raw, candles, timeframe, current_engine_ids=ids, as_of=as_of,
                              age_window_days=ZONE_AGE_DAYS[timeframe])
        for raw in raw_zones
    ]
    live = [z for z in zones if z["state"] in ("active", "candidate")]
    pivots = tech._pivot_candidates(engine.get("pivots") or {}, candles, timeframe=timeframe)
    close = float(candles[-1]["close"])
    return {
        "timeframe": timeframe,
        "as_of": candles[-1]["date"],
        "bar_count": len(candles),
        "bias": _bias(latest["dir"] if latest else None),
        "last_event": (latest.get("label") or latest.get("base")) if latest else None,
        "last_event_dir": latest["dir"] if latest else None,
        "last_event_price": latest["price"] if latest else None,
        "last_event_date": latest["confirmation_date"] if latest else None,
        "inside_zone": any(z["low"] <= close <= z["high"] for z in live),
        "breaks": [
            {"timeframe": timeframe, "label": b.get("label") or b.get("base"), "dir": b["dir"], "price": b["price"],
             "strong": bool(b.get("strong")), "confirmed_on": b["confirmation_date"]}
            for b in external[-MAX_BREAKS:]
        ][::-1],
        "zones": live,
        "pivots": pivots,
    }


def key_levels(close: float, reads: Sequence[Mapping[str, Any]], candles_by_tf: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    """Nearest resistance above / support below the close: live zones plus unbroken swing pivots."""
    found: list[dict[str, Any]] = []
    for read in reads:
        timeframe = read["timeframe"]
        for zone in read["zones"]:
            side = "inside" if zone["low"] <= close <= zone["high"] else ("support" if zone["high"] < close else "resistance")
            found.append({"timeframe": timeframe, "kind": zone["kind"], "side": side, "dir": zone["dir"],
                          "low": zone["low"], "high": zone["high"], "formed_on": zone["origin"]["formation_date"],
                          "state": zone["state"]})
        candles = candles_by_tf[timeframe]
        last = len(candles) - 1
        for pivot in read["pivots"]:
            if pivot["index"] < last - PIVOT_LOOKBACK[timeframe]:
                continue
            after = candles[pivot["index"] + 1:]
            price = float(pivot["price"])
            if pivot["kind"] == "swing_high" and price > close and all(float(c["high"]) <= price for c in after):
                side = "resistance"
            elif pivot["kind"] == "swing_low" and price < close and all(float(c["low"]) >= price for c in after):
                side = "support"
            else:
                continue
            found.append({"timeframe": timeframe, "kind": pivot["kind"], "side": side, "dir": 1 if side == "support" else -1,
                          "low": price, "high": price, "formed_on": pivot["date"], "state": "active"})

    def distance(level: Mapping[str, Any]) -> float:
        if level["side"] == "support":
            return close - level["high"]
        if level["side"] == "resistance":
            return level["low"] - close
        return 0.0

    out: list[dict[str, Any]] = [lvl for lvl in found if lvl["side"] == "inside"]
    for side in ("resistance", "support"):
        seen: set[tuple[float, float]] = set()
        for level in sorted((l for l in found if l["side"] == side), key=distance):
            key = (level["low"], level["high"])
            if key in seen:
                continue
            seen.add(key)
            out.append(level)
            if sum(1 for l in out if l["side"] == side) >= MAX_LEVELS_PER_SIDE:
                break
    return out


_KIND_ZH = {"fvg": "FVG", "ob": "OB", "swing_high": "前高", "swing_low": "前低"}


def _level_text(level: Mapping[str, Any]) -> str:
    span = _px(level["low"]) if level["low"] == level["high"] else f"{_px(level['low'])}–{_px(level['high'])}"
    tf = "週線" if level["timeframe"] == "W1" else "日線"
    return f"{tf} {_KIND_ZH.get(level['kind'], level['kind'])} {span}"


def summary_text(close: float, d1: Mapping[str, Any], w1: Mapping[str, Any] | None, levels: Sequence[Mapping[str, Any]]) -> str:
    parts = []
    for read, name in ((w1, "週線"), (d1, "日線")):
        if read is None:
            parts.append(f"{name}資料不足")
        elif read["last_event"]:
            parts.append(f"{name}{read['bias']}（{_md(read['last_event_date'])} {read['last_event']} @{_px(read['last_event_price'])}）")
        else:
            parts.append(f"{name}尚無外部結構突破")
    text = "，".join(parts) + "。"
    inside = [l for l in levels if l["side"] == "inside"]
    support = next((l for l in levels if l["side"] == "support"), None)
    resistance = next((l for l in levels if l["side"] == "resistance"), None)
    loc = [f"收盤 {_px(close)}"]
    if inside:
        loc.append(f"位於 {_level_text(inside[0])} 區內")
    if support:
        loc.append(f"下方支撐 {_level_text(support)}")
    if resistance:
        loc.append(f"上方壓力 {_level_text(resistance)}")
    return text + "，".join(loc) + "。"


def pva_read(candles: Sequence[Mapping[str, Any]], symbol: str, pva_path: Path | None) -> dict[str, Any]:
    if pva_path is None or not pva_path.exists():
        return {"status": "unavailable", "reason": "PVA runtime not installed on this host"}
    if len(candles) - tech.PVA_EMA_SEED < tech.MIN_POST_SEED_BARS:
        return {"status": "unavailable", "reason": f"only {len(candles)} bars; PVA needs {tech.MIN_TECHNICAL_BARS}"}
    try:
        pva, _series = tech._pva_analysis(candles, symbol, pva_path)
    except Exception as exc:  # external runtime: one bad stock must not kill the batch
        return {"status": "unavailable", "reason": f"PVA failed: {exc}"[:200]}
    latest = pva.get("latest") or {}
    return {"status": pva.get("status", "unready"), "reason": None,
            **{k: latest.get(k) for k in ("P", "V", "A", "anchor", "ATR")}}


def analyze_instrument(
    instrument: Mapping[str, Any],
    candles: Sequence[Mapping[str, Any]],
    *,
    detector: Detector,
    pva_path: Path | None,
    today: date | None = None,
) -> dict[str, Any]:
    symbol = str(instrument["symbol"])
    if len(candles) < MIN_D1_BARS:
        raise tech.TechnicalInputError(f"only {len(candles)} daily bars; need {MIN_D1_BARS}")
    as_of = tech._date(candles[-1]["date"])
    close = float(candles[-1]["close"])
    mintick = float(tech._tick(close))
    d1 = read_timeframe(candles, timeframe="D1", detector=detector, mintick=mintick)
    weekly = completed_weeks(candles, today or as_of)
    w1 = read_timeframe(weekly, timeframe="W1", detector=detector, mintick=mintick) if len(weekly) >= MIN_W1_BARS else None
    reads = [d1] + ([w1] if w1 else [])
    levels = key_levels(close, reads, {"D1": candles, "W1": weekly})
    pva = pva_read(candles, symbol, pva_path)
    tf_out = {}
    for read in reads:
        tf_out[read["timeframe"]] = {k: read[k] for k in (
            "as_of", "bar_count", "bias", "last_event", "last_event_dir", "last_event_price", "last_event_date", "inside_zone")}
    return {
        "instrument": {k: instrument.get(k) for k in ("instrument_id", "symbol", "exchange", "name_zh")},
        "as_of": as_of.isoformat(),
        "close": close,
        "bias": overall_bias(d1["bias"], w1["bias"] if w1 else "中性"),
        "timeframes": tf_out,
        "pva": pva,
        "levels": levels,
        "breaks": d1["breaks"] + (w1["breaks"] if w1 else []),
        "summary": summary_text(close, d1, w1, levels),
    }


# ------------------------------------------------------------------ batch


def watchlist_instruments(data_dir: Path) -> list[dict[str, Any]]:
    payload = json.loads((data_dir / WATCHLIST_FILENAME).read_text(encoding="utf-8"))
    seen: dict[str, dict[str, Any]] = {}
    rows = list(payload.get("searchable") or [])
    for key in ("short", "long"):
        rows.extend((payload.get(key) or {}).get("items") or [])
    for row in rows:
        inst = row.get("instrument") or {}
        iid = inst.get("instrument_id")
        if iid and inst.get("exchange") in ("TWSE", "TPEX") and iid not in seen:
            seen[iid] = {k: inst.get(k) for k in ("instrument_id", "symbol", "exchange", "name_zh")}
    return list(seen.values())


def pinned_detector(detector_path: Path) -> tuple[Detector, dict[str, Any]]:
    """The audit's pinned Node bridge, current state only (no prefix replay: one run per timeframe)."""
    sha = tech._assert_source_pin(detector_path, "nexus-structure")

    def run(candles: Sequence[Mapping[str, Any]], *, timeframe: str, mintick: float) -> Mapping[str, Any]:
        return tech._run_detector(candles, timeframe=timeframe, detector_path=detector_path, mintick=mintick, replay=False)

    return run, {"detector_sha256": sha, "detector_revision": tech._git_revision(detector_path, sha)}


def build(
    data_dir: Path,
    *,
    detector: Detector,
    method: Mapping[str, Any],
    pva_path: Path | None,
    candles_for: Callable[[Mapping[str, Any]], Sequence[Mapping[str, Any]]],
    now: datetime,
    limit: int | None = None,
) -> dict[str, Any]:
    instruments = watchlist_instruments(data_dir)[:limit] if limit else watchlist_instruments(data_dir)
    items: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    for instrument in instruments:
        try:
            candles = completed_sessions(candles_for(instrument), now)
            items.append(analyze_instrument(instrument, candles, detector=detector, pva_path=pva_path,
                                            today=now.astimezone(TZ).date()))
        except (tech.TechnicalInputError, requests.RequestException, ValueError, KeyError) as exc:
            LOGGER.warning("nexus_structure_skip instrument=%s error=%s", instrument["instrument_id"], exc)
            unavailable.append({"instrument_id": instrument["instrument_id"], "reason": str(exc)[:200]})
    return {
        "schema_version": "nexus-structure-v1",
        "method_version": METHOD_VERSION,
        "generated_at": now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "method": {**method, "pva_available": bool(pva_path and pva_path.exists()),
                   "candle_source": "Yahoo Finance daily (completed sessions)"},
        "universe_count": len(instruments),
        "items": items,
        "unavailable": unavailable,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--detector-path", type=Path, default=tech.DEFAULT_DETECTOR_PATH)
    parser.add_argument("--pva-path", type=Path, default=tech.DEFAULT_PVA_PATH)
    parser.add_argument("--limit", type=int, default=None, help="analyze only the first N instruments (debug)")
    parser.add_argument("--delay", type=float, default=0.25, help="seconds between Yahoo requests")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        detector, method = pinned_detector(args.detector_path)
    except tech.TechnicalInputError as exc:
        LOGGER.error("nexus_detector_unavailable error=%s (install: docs/STOCK_AUDIT.md)", exc)
        return 1

    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; nexus-theme-radar)"

    def candles_for(instrument: Mapping[str, Any]) -> list[dict[str, Any]]:
        time.sleep(args.delay)
        return fetch_candles(session, str(instrument["symbol"]), str(instrument["exchange"]))

    result = build(args.data_dir, detector=detector, method=method, pva_path=args.pva_path,
                   candles_for=candles_for, now=datetime.now(timezone.utc), limit=args.limit)
    if not result["items"]:
        LOGGER.error("nexus_structure_empty universe=%d unavailable=%d", result["universe_count"], len(result["unavailable"]))
        return 1
    path = args.data_dir / OUTPUT_FILENAME
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    LOGGER.info("nexus_structure_written items=%d unavailable=%d universe=%d pva=%s path=%s",
                len(result["items"]), len(result["unavailable"]), result["universe_count"],
                result["method"]["pva_available"], path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
