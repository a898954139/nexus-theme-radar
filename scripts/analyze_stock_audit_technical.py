"""Build source-linked technical research for the dated Stock Audit snapshot.

This module is deliberately offline and data-only.  It reads a precomputed
snapshot, runs the pinned PVA implementation and the exact NexusDashboard
structure detector in a read-only Node subprocess, then emits technical
analysis plus conditional/no-trade plans.  It never changes the public report.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

try:
    from scripts.stock_audit_technical_contract import validate_week_completion
except ModuleNotFoundError:
    from stock_audit_technical_contract import validate_week_completion


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "reports/stock-audit-2026-10-21.json"
DEFAULT_OUTPUT = ROOT / ".omx/reviews/stock-audit-technical-v2/computed.json"
DEFAULT_PVA_PATH = Path.home() / "Dev/algoTrade/nexus_bridge/pva_reclaim_runtime.py"
DEFAULT_DETECTOR_PATH = (Path.home() / "Dev/iCloud-dev/NexusDashboard/src/lib/indicators/nexusStructureDetector.js")
# Release/source pins.  A changed upstream implementation is unavailable until
# its hash is explicitly re-pinned; never silently run drifted code.
PINNED_SOURCE_SHA256 = {
    "pva": "d3da82708a9034de6536d0d73d4a3f42aa689e01c0672dc17f3c0629988a0857",
    "nexus-structure": "154e66ad866d782efbca59bd9c7a424ba29fa6228c27a1d2a33bfb609ae98929",
}
TZ = ZoneInfo("Asia/Taipei")
MIN_TECHNICAL_BARS = 600
MIN_POST_SEED_BARS = 400
PVA_EMA_SEED = 200
REPORT_DATE = date(2026, 10, 21)


class TechnicalInputError(ValueError):
    """Raised when the extended technical source cannot support a claim."""


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _json_value(value: Any) -> float | None:
    return float(value) if _finite(value) else None


def _date(value: str) -> date:
    return date.fromisoformat(str(value)[:10])


def _bar_time(value: str) -> datetime:
    return datetime.combine(_date(value), datetime.min.time(), tzinfo=TZ)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_source_pin(path: Path, method_id: str, expected_sha256: str | None = None) -> str:
    if not path.exists():
        raise TechnicalInputError(f"{method_id} source unavailable: {path.name}")
    actual_sha256 = _sha256(path)
    expected = expected_sha256 or PINNED_SOURCE_SHA256.get(method_id)
    if expected and actual_sha256 != expected:
        raise TechnicalInputError(
            f"{method_id} source hash drift for {path.name}: expected {expected}, got {actual_sha256}"
        )
    return actual_sha256


def _git_revision(path: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(path.parent), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() or "unavailable"
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "unavailable"


def _source_receipt(
    path: Path,
    *,
    method_id: str,
    params: Mapping[str, Any],
    expected_sha256: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    actual_sha256 = _assert_source_pin(path, method_id, expected_sha256)
    return {
        "id": method_id,
        # Public output carries only a stable basename; private absolute paths
        # stay in the local evidence environment, not in the report contract.
        "source_path": path.name,
        "source_sha256": actual_sha256,
        "revision": _git_revision(path),
        "params": dict(params),
        **extra,
    }


def _tick(value: float) -> Decimal:
    """TWSE board tick schedule shared by the existing renderer."""
    for ceiling, size in ((10, ".01"), (50, ".05"), (100, ".1"), (500, ".5"), (1000, "1")):
        if value < ceiling:
            return Decimal(size)
    return Decimal("5")


def next_tick(value: float) -> float:
    decimal = Decimal(str(value))
    step = _tick(value)
    return float((decimal / step).to_integral_value(rounding=ROUND_FLOOR) * step + step)


def previous_tick(value: float) -> float:
    decimal = Decimal(str(value))
    step = _tick(float(decimal - Decimal(".000001")))
    return float((decimal / step).to_integral_value(rounding=ROUND_CEILING) * step - step)


def _validate_candles(candles: Sequence[Mapping[str, Any]], *, as_of: date, minimum: int) -> list[dict[str, Any]]:
    if not isinstance(candles, Sequence) or isinstance(candles, (str, bytes)):
        raise TechnicalInputError("technical_candles is not a sequence")
    if len(candles) < minimum:
        raise TechnicalInputError(f"technical_candles has {len(candles)} bars; need >= {minimum}")
    out: list[dict[str, Any]] = []
    previous: str | None = None
    for raw in candles:
        try:
            day = _date(raw["date"])
            values = {key: float(raw[key]) for key in ("open", "high", "low", "close", "volume")}
        except (KeyError, TypeError, ValueError) as exc:
            raise TechnicalInputError(f"invalid technical candle: {exc}") from exc
        iso = day.isoformat()
        if previous is not None and iso <= previous:
            raise TechnicalInputError("technical_candles must be strictly date-sorted and unique")
        if day > as_of:
            raise TechnicalInputError(f"technical candle {iso} is after report date {as_of}")
        if not all(_finite(value) for value in values.values()):
            raise TechnicalInputError(f"non-finite technical candle {iso}")
        if min(values["open"], values["close"]) < values["low"] or max(values["open"], values["close"]) > values["high"]:
            raise TechnicalInputError(f"impossible OHLC candle {iso}")
        if values["low"] <= 0 or values["volume"] < 0:
            raise TechnicalInputError(f"non-positive OHLC or negative volume {iso}")
        out.append({"date": iso, **values})
        previous = iso
    if _date(out[-1]["date"]) != as_of:
        raise TechnicalInputError(f"latest technical candle {out[-1]['date']} is not report date {as_of}")
    return out


def _load_pva_module(path: Path):
    spec = importlib.util.spec_from_file_location("nexus_pva_reclaim_runtime", path)
    if spec is None or spec.loader is None:
        raise TechnicalInputError(f"cannot load PVA module: {path}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves forward annotations through sys.modules while the
    # external module is executing; register before exec without mutating it.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _pva_settings(module: Any, symbol: str) -> Any:
    return module.PvaReclaimSettings(
        symbol=symbol,
        timeframe="D1",
        pva_source="hlc3",
        anchor_mode="EMA",
        anchor_ema_length=200,
        atr_period=14,
        velocity_smooth=3,
    )


def _series_start(values: Sequence[float | None], dates: Sequence[str]) -> str | None:
    for value, day in zip(values, dates):
        if value is not None:
            return day
    return None


def _pva_analysis(candles: Sequence[Mapping[str, Any]], symbol: str, pva_path: Path) -> tuple[dict[str, Any], Any]:
    _assert_source_pin(pva_path, "pva")
    module = _load_pva_module(pva_path)
    bars = tuple(
        module.PvaReclaimBar(
            time=_bar_time(candle["date"]),
            open=float(candle["open"]),
            high=float(candle["high"]),
            low=float(candle["low"]),
            close=float(candle["close"]),
            volume=float(candle["volume"]),
        )
        for candle in candles
    )
    snapshot = module.PvaReclaimSnapshot(symbol=symbol, timeframe="D1", bars=bars)
    settings = _pva_settings(module, symbol)
    series = module.compute_pva_series(snapshot, settings=settings)
    dates = [str(candle["date"]) for candle in candles]

    anchor = [_json_value(value) for value in series.anchor]
    atr = [_json_value(value) if _json_value(value) is not None and _json_value(value) > 0 else None for value in series.atr]
    p_values: list[float | None] = []
    v_values: list[float | None] = []
    a_values: list[float | None] = []
    timeline: list[dict[str, Any]] = []
    first_p_index: int | None = None
    first_v_index: int | None = None
    for index, day in enumerate(dates):
        p_ready = anchor[index] is not None and atr[index] is not None
        p = _json_value(series.pva_position[index]) if p_ready else None
        if p_ready and first_p_index is None:
            first_p_index = index
        # The runtime's EMA can be numerically finite while its input is still
        # the pre-anchor literal zero.  Require a complete P window before
        # exposing V, then a complete V pair before exposing A.
        v_ready = (
            p_ready
            and first_p_index is not None
            and index - first_p_index + 1 >= 3
            and all(item is not None for item in p_values[-2:])
        )
        if v_ready and first_v_index is None:
            first_v_index = index
        a_ready = v_ready and first_v_index is not None and index > first_v_index and v_values[-1] is not None
        v = _json_value(series.pva_velocity[index]) if v_ready else None
        a = _json_value(series.pva_acceleration[index]) if a_ready else None
        p_values.append(p)
        v_values.append(v)
        a_values.append(a)
        timeline.append({
            "date": day,
            "P": p,
            "V": v,
            "A": a,
            "anchor": anchor[index],
            "ATR": atr[index],
            "ready": all(value is not None for value in (p, v, a, anchor[index], atr[index])),
        })

    readiness = {
        "anchor_finite_from": _series_start(anchor, dates),
        "ATR_finite_from": _series_start(atr, dates),
        "P_finite_from": _series_start(p_values, dates),
        "V_finite_from": _series_start(v_values, dates),
        "A_finite_from": _series_start(a_values, dates),
        "ema200_seed_index": PVA_EMA_SEED - 1,
        "ema200_seed_date": dates[PVA_EMA_SEED - 1] if len(dates) >= PVA_EMA_SEED else None,
        "preseed_zero_excluded": True,
    }
    latest = timeline[-1]
    ready_tail = [row for row in timeline if row["date"] >= (readiness["A_finite_from"] or dates[-1])]
    post_seed_bars = len(timeline) - PVA_EMA_SEED
    status = "ready" if latest["ready"] and post_seed_bars >= MIN_POST_SEED_BARS else "unready"
    pva = {
        "timeframe": "D1",
        "status": status,
        "latest": {
            "date": latest["date"],
            "P": latest["P"],
            "V": latest["V"],
            "A": latest["A"],
            "anchor": latest["anchor"],
            "ATR": latest["ATR"],
        },
        "settings": asdict(settings),
        "readiness": readiness,
        "full_finite": {
            "P": all(row["P"] is not None for row in ready_tail),
            "V": all(row["V"] is not None for row in ready_tail),
            "A": all(row["A"] is not None for row in ready_tail),
            "anchor": all(row["anchor"] is not None for row in ready_tail),
            "ATR": all(row["ATR"] is not None for row in ready_tail),
        },
        "post_seed_bar_count": post_seed_bars,
        "nullable_timeline": timeline,
        "gap_policy": "Use observed exchange bars only; no synthetic weekend rows or gap fills.",
    }
    return pva, series


def aggregate_completed_weekly(
    candles: Sequence[Mapping[str, Any]],
    report_date: date,
    week_completion: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Aggregate completed weeks, optionally closing the current week via calendar evidence."""
    current_week_start = report_date - timedelta(days=report_date.weekday())
    if week_completion is not None:
        if not validate_week_completion(week_completion, report_date.isoformat()):
            raise TechnicalInputError("invalid week_completion calendar evidence")
    include_current_week = week_completion is not None
    groups: dict[date, list[tuple[int, Mapping[str, Any]]]] = {}
    dropped: list[dict[str, Any]] = []
    for index, candle in enumerate(candles):
        day = _date(candle["date"])
        week_start = day - timedelta(days=day.weekday())
        if week_start > current_week_start or (week_start == current_week_start and not include_current_week):
            dropped.append({"index": index, "date": day.isoformat(), "week_start": week_start.isoformat()})
            continue
        groups.setdefault(week_start, []).append((index, candle))

    weekly: list[dict[str, Any]] = []
    for week_start, items in sorted(groups.items()):
        first_index, first = items[0]
        last_index, last = items[-1]
        weekly.append({
            "date": str(last["date"]),
            "week_start": week_start.isoformat(),
            "open": float(first["open"]),
            "high": max(float(item["high"]) for _, item in items),
            "low": min(float(item["low"]) for _, item in items),
            "close": float(last["close"]),
            "volume": sum(float(item["volume"]) for _, item in items),
            "source_indices": [index for index, _ in items],
            "source_dates": [str(item["date"]) for _, item in items],
            "source_index_range": [first_index, last_index],
        })
    metadata = {
        "timeframe": "W1",
        "bar_count": len(weekly),
        "as_of": weekly[-1]["date"] if weekly else None,
        "dropped_current_week": {
            "week_start": current_week_start.isoformat(),
            "report_date": report_date.isoformat(),
            "dropped_dates": [item["date"] for item in dropped],
            "reason": "current report week is incomplete; W1 uses completed weeks only" if not include_current_week else "calendar evidence closes current week through last observed session",
        },
        "gap_policy": "Weeks are exchange-date groups; no synthetic bars are inserted.",
    }
    if week_completion is not None:
        metadata["week_completion"] = dict(week_completion)
        metadata["completion_verified"] = True
    return weekly, metadata


_NODE_BRIDGE = r"""
import fs from 'node:fs'

const detectorPath = process.argv[1]
const input = JSON.parse(fs.readFileSync(0, 'utf8'))
const source = fs.readFileSync(detectorPath, 'utf8') + '\nexport { detectPivots };'
const moduleUrl = 'data:text/javascript;base64,' + Buffer.from(source).toString('base64')
const detector = await import(moduleUrl)

const current = detector.detectNexusStructure(input.candles, input.options)
const pivotSets = detector.detectPivots(input.candles, Math.max(3, input.options.fractalLen ?? 5))
const pivots = {
  swingHighs: [...pivotSets.swingHighs].sort((a, b) => a - b),
  swingLows: [...pivotSets.swingLows].sort((a, b) => a - b),
}

const replay = { fvgZones: [], obZones: [] }
if (input.replay) {
  const seen = { fvg: new Map(), ob: new Map() }
  for (let end = 4; end < input.candles.length; end += 1) {
    const prefix = input.candles.slice(0, end + 1)
    const result = detector.detectNexusStructure(prefix, input.options)
    for (const kind of ['fvg', 'ob']) {
      const key = kind === 'fvg' ? 'fvgZones' : 'obZones'
      for (const zone of result[key] ?? []) {
        const previous = seen[kind].get(zone.id)
        seen[kind].set(zone.id, {
          ...(previous ?? {}),
          ...zone,
          firstSeenPrefixIndex: previous?.firstSeenPrefixIndex ?? end,
          lastSeenPrefixIndex: end,
        })
      }
    }
  }
  replay.fvgZones = [...seen.fvg.values()]
  replay.obZones = [...seen.ob.values()]
}

process.stdout.write(JSON.stringify({ current, pivots, replay }))
"""


def _run_detector(
    candles: Sequence[Mapping[str, Any]],
    *,
    timeframe: str,
    detector_path: Path,
    mintick: float,
    replay: bool = True,
) -> dict[str, Any]:
    _assert_source_pin(detector_path, "nexus-structure")
    options = {
        "minFvgAmount": 0.1,
        "fvgSizeUnit": "Price",
        "mintick": mintick,
        "maxTrackedZones": 120,
        "clearFvgWhenFilled": True,
        "zoneWindowBars": None,
        "timeframe": timeframe,
        "fractalLen": 5,
        "internalPivotBars": 1,
        "minRelevantBars": 6,
        "minBosAtr": 0.15,
        "minChochAtr": 0.15,
        "strongBreakAtr": 0.25,
        "minBodyToRange": 0.55,
        "strongBodyToRange": 0.65,
    }
    payload = {
        "candles": [
            {**dict(candle), "time": f"{candle['date']}T00:00:00+08:00"}
            for candle in candles
        ],
        "options": options,
        "replay": replay,
    }
    try:
        process = subprocess.run(
            ["node", "--input-type=module", "-e", _NODE_BRIDGE, str(detector_path)],
            input=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            capture_output=True,
            text=True,
            check=True,
            timeout=180,
        )
        return {"options": options, **json.loads(process.stdout)}
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        stderr = getattr(exc, "stderr", "")
        raise TechnicalInputError(f"Nexus detector failed: {exc}; stderr={stderr}") from exc


def _simple_atr(candles: Sequence[Mapping[str, Any]], period: int = 14) -> list[float | None]:
    values: list[float | None] = []
    tr: list[float] = []
    for index, candle in enumerate(candles):
        if index == 0:
            tr.append(float(candle["high"]) - float(candle["low"]))
        else:
            previous = float(candles[index - 1]["close"])
            tr.append(max(float(candle["high"]) - float(candle["low"]), abs(float(candle["high"]) - previous), abs(float(candle["low"]) - previous)))
        values.append(sum(tr[-period:]) / period if len(tr) >= period else None)
    return values


def _pivot_candidates(
    pivot_data: Mapping[str, Any],
    candles: Sequence[Mapping[str, Any]],
    *,
    timeframe: str,
    fractal_len: int = 5,
) -> list[dict[str, Any]]:
    right = max(1, fractal_len // 2)
    atr = _simple_atr(candles)
    candidates: list[dict[str, Any]] = []
    for kind, indexes in (("high", pivot_data.get("swingHighs", [])), ("low", pivot_data.get("swingLows", []))):
        for raw_index in indexes:
            index = int(raw_index)
            if index < 0 or index >= len(candles):
                continue
            confirmation_index = index + right
            if confirmation_index >= len(candles):
                continue
            price = float(candles[index]["high"] if kind == "high" else candles[index]["low"])
            horizon_end = min(len(candles), confirmation_index + 6)
            if kind == "high":
                excursion = price - min(float(candles[j]["low"]) for j in range(confirmation_index, horizon_end))
            else:
                excursion = max(float(candles[j]["high"]) for j in range(confirmation_index, horizon_end)) - price
            atr_ref = atr[confirmation_index] or 0.0
            strength_ratio = excursion / atr_ref if atr_ref > 0 else 0.0
            source_id = f"{timeframe}:pivot-{kind}-{index}-{candles[index]['date']}"
            candidates.append({
                "source_id": source_id,
                "kind": f"swing_{kind}",
                "index": index,
                "date": str(candles[index]["date"]),
                "price": price,
                "confirmed_at_index": confirmation_index,
                "confirmed_at": str(candles[confirmation_index]["date"]),
                "source_candle_id": f"{timeframe}:candle-{index}-{candles[index]['date']}",
                "classification": "strong" if strength_ratio >= 0.75 else "ambiguous",
                "manual_review_needed": True,
                "canonical_true_swing": False,
                "reaction": {
                    "bars_observed": horizon_end - confirmation_index,
                    "excursion": excursion,
                    "ATR": atr_ref,
                    "ratio": strength_ratio,
                    "review_end_index": horizon_end - 1,
                    "review_end_date": str(candles[horizon_end - 1]["date"]),
                    "review_source_candle_ids": [
                        f"{timeframe}:candle-{idx}-{candles[idx]['date']}"
                        for idx in range(confirmation_index, horizon_end)
                    ],
                },
            })
    return sorted(candidates, key=lambda item: (item["index"], item["kind"]))


def _normalize_breaks(raw_breaks: Sequence[Mapping[str, Any]], candles: Sequence[Mapping[str, Any]], timeframe: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in raw_breaks:
        start = int(raw["startIndex"])
        end = int(raw["endIndex"])
        if not (0 <= start < len(candles) and 0 <= end < len(candles)):
            continue
        raw_id = str(raw.get("id", f"break-{end}-{start}"))
        output.append({
            "source_id": f"{timeframe}:{raw_id}",
            "raw_engine_id": raw_id,
            "kind": "structure_break",
            "dir": int(raw["dir"]),
            "base": str(raw.get("base", "")),
            "label": str(raw.get("label", "")),
            "internal": bool(raw.get("internal", False)),
            "strong": bool(raw.get("strong", False)),
            "displacement": bool(raw.get("strong", False)),
            "price": float(raw["price"]),
            "start_index": start,
            "end_index": end,
            "start_date": str(candles[start]["date"]),
            "confirmation_date": str(candles[end]["date"]),
            "source_candle_ids": [
                f"{timeframe}:candle-{start}-{candles[start]['date']}",
                f"{timeframe}:candle-{end}-{candles[end]['date']}",
            ],
        })
    return output


def _zone_validation(
    raw: Mapping[str, Any],
    candles: Sequence[Mapping[str, Any]],
    timeframe: str,
    *,
    current_engine_ids: set[str] | None = None,
    as_of: date | None = None,
    age_window_days: int = 180,
) -> dict[str, Any]:
    kind = str(raw.get("kind", ""))
    direction = int(raw.get("dir", 0))
    low = float(raw["low"])
    high = float(raw["high"])
    born = int(raw.get("bornIndex", raw.get("startIndex", 0)))
    start = int(raw.get("startIndex", born))
    invalidation: dict[str, Any] | None = None
    exhausted = bool(raw.get("exhausted", False)) or int(raw.get("taps", 0) or 0) >= 3
    reaction: dict[str, Any] | None = None
    for index in range(max(0, born + 1), len(candles)):
        candle = candles[index]
        if kind == "ob":
            body_break = (direction == 1 and float(candle["close"]) < low) or (direction == -1 and float(candle["close"]) > high)
            if body_break:
                invalidation = {"index": index, "date": str(candle["date"]), "reason": "strict_later_body_close_invalidates_ob"}
                break
            touched = float(candle["high"]) >= low and float(candle["low"]) <= high
            directional_reaction = (
                direction == 1
                and touched
                and float(candle["close"]) > float(raw.get("mid", (low + high) / 2))
                and float(candle["close"]) > float(candle["open"])
            ) or (
                direction == -1
                and touched
                and float(candle["close"]) < float(raw.get("mid", (low + high) / 2))
                and float(candle["close"]) < float(candle["open"])
            )
            if directional_reaction and reaction is None:
                reaction = {
                    "index": index,
                    "date": str(candle["date"]),
                    "source_candle_id": f"{timeframe}:candle-{index}-{candle['date']}",
                    "reason": "directional_body_reaction_after_ob_touch",
                }
        elif kind == "fvg":
            wick_fill = (direction == 1 and float(candle["low"]) <= low) or (direction == -1 and float(candle["high"]) >= high)
            if wick_fill:
                invalidation = {"index": index, "date": str(candle["date"]), "reason": "later_wick_fill_invalidates_fvg"}
                break
    if invalidation:
        state = "invalidated"
        reviewed_valid = False
        reason = invalidation["reason"]
    elif exhausted:
        state = "exhausted"
        reviewed_valid = False
        reason = "engine_taps_or_exhausted_flag"
    elif kind == "ob" and reaction is None:
        # An untouched order-block candidate is not a reviewed defense source.
        state = "candidate"
        reviewed_valid = False
        reason = "untested_ob_requires_directional_reaction_review"
    else:
        state = "active"
        reviewed_valid = True
        reason = "no_later_invalidation_or_exhaustion_observed"
    raw_id = str(raw.get("id", f"{kind}-{direction}-{born}"))
    formation_date = _date(candles[born]["date"]) if 0 <= born < len(candles) else None
    age_expired = bool(as_of and formation_date and formation_date < as_of - timedelta(days=age_window_days))
    current_candidate = current_engine_ids is None or raw_id in current_engine_ids
    expired = age_expired or not current_candidate
    if expired:
        # Keep an independently observed invalidation/exhaustion as the
        # lifecycle state and carry expiry separately.  Historical evidence
        # must never be rewritten as "no later invalidation" merely because it
        # is outside the current chart window.
        reviewed_valid = False
        if invalidation:
            state = "invalidated"
        elif exhausted:
            state = "exhausted"
        else:
            state = "expired"
            reason = "not_in_current_engine_or_outside_180d_window"
    return {
        "id": f"{timeframe}:{raw_id}",
        "raw_engine_id": raw_id,
        "type": kind,
        "kind": kind,
        "dir": direction,
        "low": low,
        "high": high,
        "mid": float(raw.get("mid", (low + high) / 2)),
        "timeframe": timeframe,
        "origin": {
            "start_index": start,
            "born_index": born,
            "start_date": str(candles[start]["date"]) if 0 <= start < len(candles) else None,
            "formation_date": str(candles[born]["date"]) if 0 <= born < len(candles) else None,
            "source_candle_ids": [
                f"{timeframe}:candle-{idx}-{candles[idx]['date']}"
                for idx in sorted({start, born})
                if 0 <= idx < len(candles)
            ],
        },
        "engine_candidate": True,
        "current_engine_candidate": current_candidate,
        "age_window_days": age_window_days,
        "expired": expired,
        "expiry_reason": "not_in_current_engine_or_outside_180d_window" if expired else None,
        "engine_state": raw.get("state"),
        "reviewed_valid": reviewed_valid,
        "state": state,
        "chart_only_active": reviewed_valid,
        "validation_reason": reason,
        "invalidation": invalidation,
        "invalidation_at_as_of": bool(invalidation and invalidation["index"] == len(candles) - 1),
        "exhausted": exhausted,
        "reaction": reaction,
        "review_source_ids": [reaction["source_candle_id"]] if reaction else [],
        "raw_engine": dict(raw),
    }


def _structure_read(candles: Sequence[Mapping[str, Any]], d1: Mapping[str, Any], pva: Mapping[str, Any]) -> dict[str, Any]:
    breaks = [item for item in d1.get("breaks", []) if not item.get("internal")]
    latest_break = breaks[-1] if breaks else None
    if latest_break is None:
        bias, last_event = "中性", None
    elif latest_break["dir"] == 1:
        bias, last_event = "偏多", latest_break.get("label") or latest_break.get("base")
    else:
        bias, last_event = "偏空", latest_break.get("label") or latest_break.get("base")
    price = float(candles[-1]["close"])
    active = [zone for zone in d1.get("zones", []) if zone.get("chart_only_active")]
    return {
        "bias": bias,
        "bias_source": "Nexus detector structureBreaks; mechanical read only",
        "phase": "unassessed",
        "last_event": last_event,
        "location": {
            "price": price,
            "active_zone_ids": [zone["id"] for zone in active],
            "inside_active_zone": any(zone["low"] <= price <= zone["high"] for zone in active),
        },
        "confluence": {
            "pva_status": pva.get("status"),
            "pva_positive": bool((pva.get("latest") or {}).get("P") is not None and (pva.get("latest") or {}).get("P") > 0),
            "active_zone_count": len(active),
            "latest_break_source": latest_break["source_id"] if latest_break else None,
        },
        "actionability": "等待來源連結的 D1 結構確認，不以最新 K、OB/FVG 或 PVA 單獨進場。",
        "scenarios": {
            "long": "先有已確認結構高點的日收盤突破，再等後續收盤跟隨與 PVA 支持；否則 no-trade。",
            "short": "本卡只生成多方條件計畫；空方結構只作風險／失效資訊，不反向發出交易指令。",
        },
    }


def _valid_pivot_highs(candidates: Sequence[Mapping[str, Any]], candles: Sequence[Mapping[str, Any]], current_index: int) -> list[dict[str, Any]]:
    valid: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.get("kind") != "swing_high" or int(candidate["confirmed_at_index"]) >= current_index:
            continue
        price = float(candidate["price"])
        if any(float(candles[index]["close"]) > price for index in range(int(candidate["confirmed_at_index"]) + 1, current_index + 1)):
            continue
        valid.append(dict(candidate))
    return valid


def _valid_pivot_lows(candidates: Sequence[Mapping[str, Any]], candles: Sequence[Mapping[str, Any]], current_index: int) -> list[dict[str, Any]]:
    valid: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.get("kind") != "swing_low" or int(candidate["confirmed_at_index"]) >= current_index:
            continue
        price = float(candidate["price"])
        if any(float(candles[index]["close"]) < price for index in range(int(candidate["confirmed_at_index"]) + 1, current_index + 1)):
            continue
        valid.append(dict(candidate))
    return valid


def _no_trade(
    reason: str,
    *,
    as_of: str,
    current_price: float | None = None,
    details: Mapping[str, Any] | None = None,
    wait_condition: str | None = None,
    watch_levels: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": "no_trade",
        "timeframe": "D1",
        "entry": None,
        "add": None,
        "stop": None,
        "targets": [],
        "trigger_source": None,
        "defense_source": None,
        "target_sources": [],
        "zone_low": None,
        "zone_high": None,
        "reason": reason,
        "wait_condition": wait_condition or "目前條件不足；等待結構、PVA 或來源位階改善後重評，不執行。",
        "confirmation": {"latest_bar_not_trigger": True, "future_body_close_required": True, "follow_through_required": True},
        "as_of": as_of,
        "current_price": current_price,
        "details": dict(details or {}),
        "watch_levels": dict(watch_levels or {}),
    }


def _derive_plan(
    candles: Sequence[Mapping[str, Any]],
    pva: Mapping[str, Any],
    d1: Mapping[str, Any],
    *,
    as_of: date,
    w1_read: Mapping[str, Any] | None = None,
    w1_zones: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    current = float(candles[-1]["close"])
    current_index = len(candles) - 1
    htf_bias = str((w1_read or {}).get("bias", "中性"))
    if pva.get("status") != "ready":
        return _no_trade("PVA 未完成 EMA200 seed 與 post-seed 可用長度檢查。", as_of=as_of.isoformat(), current_price=current, details={"pva_status": pva.get("status")})
    latest = pva.get("latest") or {}
    if not all(_finite(latest.get(key)) for key in ("P", "V", "A", "ATR")):
        return _no_trade("PVA 最新 D1 P/V/A/ATR 不完整；不把 pre-seed 0 當成訊號。", as_of=as_of.isoformat(), current_price=current)

    pivots = d1.get("pivots", [])
    highs = [candidate for candidate in _valid_pivot_highs(pivots, candles, current_index) if float(candidate["price"]) > current]
    if not highs:
        return _no_trade("沒有高於現價且尚未被日線收盤突破的已確認結構高點。", as_of=as_of.isoformat(), current_price=current)
    trigger = sorted(
        highs,
        key=lambda item: (float(item["price"]) - current, -int(item["confirmed_at_index"])),
    )[0]
    entry = next_tick(float(trigger["price"]))

    active = [zone for zone in [*d1.get("zones", []), *w1_zones] if zone.get("chart_only_active")]
    if trigger.get("classification") != "strong":
        return _no_trade(
            "最近的已確認結構高點僅為 ambiguous；不跳過最近 trigger 改用更遠 strong 高點。",
            as_of=as_of.isoformat(),
            current_price=current,
            details={
                "trigger_source": trigger["source_id"],
                "trigger_classification": trigger.get("classification"),
            },
            wait_condition="等待最近 trigger 取得 strong reaction review 後，再重評 D1 突破條件。",
            watch_levels={"trigger": trigger},
        )
    entry_obstacles = [
        zone
        for zone in active
        if zone.get("type") in {"ob", "fvg"}
        and zone.get("dir") == -1
        and float(zone["low"]) <= entry <= float(zone["high"])
    ]
    if entry_obstacles:
        obstacle = sorted(entry_obstacles, key=lambda zone: (float(zone["high"]) - float(zone["low"]), zone["id"]))[0]
        return _no_trade(
            "entry 落在 active bearish OB/FVG obstacle 內；不把遠端 target 當成穿越障礙的買進理由。",
            as_of=as_of.isoformat(),
            current_price=current,
            details={"trigger_source": trigger["source_id"], "obstacle_source": obstacle["id"]},
            wait_condition="等待 bearish obstacle 被有效收盤突破並完成 follow-through，再重新計算 entry。",
            watch_levels={"trigger": trigger, "obstacle": obstacle},
        )
    defense_candidates: list[tuple[float, Mapping[str, Any], float]] = []
    for zone in active:
        if zone.get("type") == "ob" and zone.get("dir") == 1 and float(zone["high"]) < current:
            defense_candidates.append((current - float(zone["high"]), zone, float(zone["low"])))
    for candidate in _valid_pivot_lows(pivots, candles, current_index):
        if float(candidate["price"]) < current:
            defense_candidates.append((current - float(candidate["price"]), candidate, float(candidate["price"])))
    defense_source: Mapping[str, Any] | None = None
    defense_level: float | None = None
    if defense_candidates:
        _, defense_source, defense_level = sorted(
            defense_candidates,
            key=lambda item: (item[0], -int(item[1].get("confirmed_at_index", item[1].get("origin", {}).get("born_index", 0)))),
        )[0]
    if defense_source is None or defense_level is None:
        return _no_trade("沒有高於可驗證防守來源的有效 D1 防守位。", as_of=as_of.isoformat(), current_price=current, details={"trigger_source": trigger["source_id"]})

    atr_buffer = float(latest["ATR"])
    stop = previous_tick(defense_level - atr_buffer)
    if not (stop > 0 and stop < entry):
        return _no_trade(
            "防守來源加 ATR buffer 後無法形成 entry 下方停損。",
            as_of=as_of.isoformat(),
            current_price=current,
            details={"trigger_source": trigger["source_id"], "defense_source": defense_source.get("source_id", defense_source.get("id"))},
        )

    if htf_bias == "偏空":
        return _no_trade(
            "W1 結構偏空；不自動生成 D1 逆勢多方計畫。",
            as_of=as_of.isoformat(),
            current_price=current,
            details={
                "W1_bias": htf_bias,
                "W1_last_event": (w1_read or {}).get("last_event"),
                "trigger_source": trigger["source_id"],
                "defense_source": defense_source.get("source_id", defense_source.get("id")),
            },
            wait_condition="等待 W1 結構恢復偏多或轉中性，再檢查同一 D1 trigger／defense；目前不逆勢買入。",
            watch_levels={"trigger": trigger, "defense": defense_source},
        )

    target_candidates: list[dict[str, Any]] = []
    for candidate in highs:
        level = float(candidate["price"])
        if level > entry:
            # Take profit at (or one valid tick below) the source level; never
            # invent a break above an opposing supply/liquidity reference.
            target_candidates.append({"price": previous_tick(level), "source_id": candidate["source_id"], "source_type": "confirmed_swing_high", "date": candidate["date"], "basis": "prior unbroken confirmed liquidity high"})
    for zone in active:
        if zone.get("dir") != -1 or zone.get("type") not in {"ob", "fvg"} or float(zone["high"]) <= entry:
            continue
        target_candidates.append({"price": previous_tick(float(zone["low"])), "source_id": zone["id"], "source_type": zone["type"], "date": zone["origin"]["formation_date"], "basis": "active opposing supply zone"})
    dedup: dict[tuple[float, str], dict[str, Any]] = {(item["price"], item["source_id"]): item for item in target_candidates}
    targets = sorted(dedup.values(), key=lambda item: (item["price"], item["source_id"]))[:3]
    if not targets:
        return _no_trade(
            "沒有高於 entry 的實際 opposing supply/liquidity source，不能製造 2R target。",
            as_of=as_of.isoformat(),
            current_price=current,
            details={"trigger_source": trigger["source_id"], "defense_source": defense_source.get("source_id", defense_source.get("id"))},
            watch_levels={"trigger": trigger, "defense": defense_source},
        )

    risk = entry - stop
    for target in targets:
        target["rr"] = (float(target["price"]) - entry) / risk if risk > 0 else None
    if targets[0]["rr"] is None or targets[0]["rr"] < 1:
        return _no_trade(
            "最近 opposing target 的實際來源位距離不足（RR<1）；不跳過近端障礙改用更遠的合成目標。",
            as_of=as_of.isoformat(),
            current_price=current,
            details={
                "trigger_source": trigger["source_id"],
                "defense_source": defense_source.get("source_id", defense_source.get("id")),
                "barrier_source": targets[0]["source_id"],
                "barrier_price": targets[0]["price"],
                "barrier_rr": targets[0]["rr"],
            },
            wait_condition="等待 W1 非偏空且最近 opposing source 與 entry 拉開至 RR>=1；不跳過近端障礙。",
            watch_levels={"trigger": trigger, "defense": defense_source, "targets": targets},
        )
    pva_supportive_now = float(latest["P"]) > 0 and float(latest["V"]) >= 0 and float(latest["A"]) >= 0
    return {
        "status": "conditional",
        "timeframe": "D1",
        "entry": entry,
        "add": next_tick(entry),
        "stop": stop,
        "targets": targets,
        "target_sources": [target["source_id"] for target in targets],
        "trigger_source": trigger["source_id"],
        "defense_source": defense_source.get("source_id", defense_source.get("id")),
        "zone_low": float(defense_source.get("low", defense_level)),
        "zone_high": float(defense_source.get("high", defense_level)),
        "reason": "只保留來源連結的 D1 突破／回踩情境；不把最新 K、OB/FVG 或 PVA 單獨當進場訊號。",
        "wait_condition": f"未來 D1 日收盤站上 {entry:g}，下一交易日回踩守住並有 follow-through；同時 PVA P/V/A 必須為正向或明確恢復。跳空不追。",
        "confirmation": {
            "latest_bar_not_trigger": True,
            "future_body_close_required": True,
            "follow_through_required": True,
            "W1_bias": htf_bias,
            "W1_gate": "偏空時 no_trade；偏多／中性才允許 D1 條件路徑。",
            "pva_currently_supportive": pva_supportive_now,
            "pva_future_condition": "P>0 且 V>=0、A>=0，或 V>0 且 A>=0 並由負 P 回升；不是獲利門檻。",
            "atr_buffer": atr_buffer,
            "atr_buffer_factor": 1.0,
            "risk": risk,
        },
        "as_of": as_of.isoformat(),
        "current_price": current,
    }


def _unavailable_analysis(stock: Mapping[str, Any], *, report_date: date, reason: str, input_hash: str) -> dict[str, Any]:
    candles = stock.get("candles") if isinstance(stock.get("candles"), list) else []
    current = None
    if candles and isinstance(candles[-1], Mapping) and _finite(candles[-1].get("close")):
        current = float(candles[-1]["close"])
    return {
        "as_of": report_date.isoformat(),
        "current_price": current,
        "candle_sha256": input_hash,
        "analysis_status": "unavailable",
        "method_receipts": [],
        "pva": {"timeframe": "D1", "status": "unready", "reason": reason, "latest": None, "nullable_timeline": []},
        "timeframes": {},
        "structure": {},
        "zones": [],
        "plan": {
            **_no_trade(reason, as_of=report_date.isoformat(), current_price=current),
            "analysis_status": "unavailable",
        },
    }


def analyze_stock(
    stock: Mapping[str, Any],
    method_paths: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    """Return one stock's technical_analysis without mutating ``stock``."""
    methods = method_paths or {}
    pva_path = Path(methods.get("pva", DEFAULT_PVA_PATH))
    detector_path = Path(methods.get("detector", DEFAULT_DETECTOR_PATH))
    symbol = str(stock.get("symbol", ""))
    report_date = _date(stock.get("report_date", REPORT_DATE.isoformat())) if stock.get("report_date") else REPORT_DATE
    input_hash = _canonical_hash(stock.get("technical_candles", stock.get("candles", [])))
    try:
        technical_source = stock.get("technical_candles")
        if technical_source is None:
            raise TechnicalInputError("technical_candles is missing; 235-bar candles are not a PVA fallback")
        candles = _validate_candles(technical_source, as_of=report_date, minimum=MIN_TECHNICAL_BARS)
        post_seed = len(candles) - PVA_EMA_SEED
        if post_seed < MIN_POST_SEED_BARS:
            raise TechnicalInputError(f"only {post_seed} post-EMA200 bars; need >= {MIN_POST_SEED_BARS}")
        candle_hash = _canonical_hash(candles)

        pva_receipt = _source_receipt(
            pva_path,
            method_id="pva",
            params={"timeframe": "D1", "pva_source": "hlc3", "anchor_mode": "EMA", "anchor_ema_length": 200, "atr_period": 14, "velocity_smooth": 3},
            gap_policy="observed exchange bars only; no synthetic weekend rows or fills",
        )
        detector_receipt = _source_receipt(
            detector_path,
            method_id="nexus-structure",
            params={"timeframes": ["D1", "W1"], "fractalLen": 5, "internalPivotBars": 1, "replay_prefixes": True},
            detector_pivots_export="data-url append export { detectPivots }",
            parity_claim="actual detector revision only; no Pine 2.1/canonical true-swing parity claim",
        )
        pva, _series = _pva_analysis(candles, symbol, pva_path)
        d1_engine = _run_detector(candles, timeframe="D1", detector_path=detector_path, mintick=_tick(float(candles[-1]["close"])).__float__(), replay=True)
        d1_pivots = _pivot_candidates(d1_engine["pivots"], candles, timeframe="D1")
        d1_breaks = _normalize_breaks(d1_engine["current"].get("structureBreaks", []), candles, "D1")
        d1_current_ids = {
            str(raw["id"])
            for key in ("fvgZones", "obZones")
            for raw in d1_engine["current"].get(key, [])
        }
        d1_zones = [
            _zone_validation(
                raw,
                candles,
                "D1",
                current_engine_ids=d1_current_ids,
                as_of=_date(candles[-1]["date"]),
            )
            for raw in d1_engine["replay"].get("fvgZones", []) + d1_engine["replay"].get("obZones", [])
        ]
        d1 = {
            "timeframe": "D1",
            "bar_count": len(candles),
            "as_of": candles[-1]["date"],
            "engine": {"summary": d1_engine["current"].get("summary", {}), "replay_candidate_counts": {"fvg": len(d1_engine["replay"].get("fvgZones", [])), "ob": len(d1_engine["replay"].get("obZones", []))}},
            "pivots": d1_pivots,
            "breaks": d1_breaks,
            "zones": d1_zones,
            "raw_engine": d1_engine["current"],
        }

        weekly, weekly_metadata = aggregate_completed_weekly(candles, report_date, stock.get("week_completion"))
        w1_engine = _run_detector(weekly, timeframe="W1", detector_path=detector_path, mintick=_tick(float(candles[-1]["close"])).__float__(), replay=True)
        w1_pivots = _pivot_candidates(w1_engine["pivots"], weekly, timeframe="W1")
        w1_breaks = _normalize_breaks(w1_engine["current"].get("structureBreaks", []), weekly, "W1")
        w1_current_ids = {
            str(raw["id"])
            for key in ("fvgZones", "obZones")
            for raw in w1_engine["current"].get(key, [])
        }
        w1_zones = [
            _zone_validation(
                raw,
                weekly,
                "W1",
                current_engine_ids=w1_current_ids,
                as_of=_date(weekly[-1]["date"]),
            )
            for raw in w1_engine["replay"].get("fvgZones", []) + w1_engine["replay"].get("obZones", [])
        ]
        w1 = {
            **weekly_metadata,
            "candles": weekly,
            "engine": {"summary": w1_engine["current"].get("summary", {}), "replay_candidate_counts": {"fvg": len(w1_engine["replay"].get("fvgZones", [])), "ob": len(w1_engine["replay"].get("obZones", []))}},
            "pivots": w1_pivots,
            "breaks": w1_breaks,
            "zones": w1_zones,
            "raw_engine": w1_engine["current"],
            "pva": {"status": "not_computed", "reason": "W1 EMA200 requires more completed weekly bars; D1 PVA is the supported read."},
        }
        structure = {
            "D1": _structure_read(candles, d1, pva),
            "W1": _structure_read(weekly, w1, {"status": "not_computed", "latest": {"P": None}}),
            "method_note": "Pivots are mechanical detector candidates requiring manual review; no canonical true-swing label is asserted.",
        }
        plan = _derive_plan(candles, pva, d1, as_of=report_date, w1_read=structure["W1"], w1_zones=w1_zones)
        zones = d1_zones + w1_zones
        method_receipts = [pva_receipt, detector_receipt]
        if isinstance(stock.get("_technical_source_receipt"), Mapping):
            method_receipts.insert(0, dict(stock["_technical_source_receipt"]))
        else:
            method_receipts.insert(0, {
                "id": "technical-candles",
                "source_path": "technical_candles",
                "source_sha256": candle_hash,
                "revision": "input-inline",
                "params": {
                    "field": "technical_candles",
                    "imputation": False,
                    "excluded_rows": len(stock.get("technical_excluded_rows", []) or []),
                },
            })
        return {
            "as_of": report_date.isoformat(),
            "current_price": float(candles[-1]["close"]),
            "candle_sha256": candle_hash,
            "analysis_status": "complete",
            "method_receipts": method_receipts,
            "pva": pva,
            "timeframes": {"D1": d1, "W1": w1},
            "structure": structure,
            "zones": zones,
            "plan": plan,
        }
    except TechnicalInputError as exc:
        reason = str(exc)
        if stock.get("_technical_source_error"):
            reason = str(stock["_technical_source_error"])
        return _unavailable_analysis(stock, report_date=report_date, reason=reason, input_hash=input_hash)


def analyze_report(data: Mapping[str, Any], method_paths: Mapping[str, str | Path] | None = None) -> dict[str, Any]:
    return _analyze_report_with_extended(data, method_paths=method_paths, extended_dir=None)


def _load_extended_candles(extended_dir: Path, symbol: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = extended_dir / f"{symbol}.json"
    if not path.exists():
        raise TechnicalInputError(f"extended technical source missing for {symbol}: {path.name}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    candles = payload.get("candles")
    if not isinstance(candles, list):
        raise TechnicalInputError(f"extended technical source has no candles: {path.name}")
    return candles, {
        "id": "technical-candles",
        "source_path": path.name,
        "source_sha256": _sha256(path),
        "revision": "review-evidence",
        "params": {"symbol": symbol, "field": "candles", "imputation": False},
    }


def _analyze_report_with_extended(
    data: Mapping[str, Any],
    *,
    method_paths: Mapping[str, str | Path] | None = None,
    extended_dir: Path | None,
) -> dict[str, Any]:
    report_date = _date(data.get("report_date", REPORT_DATE.isoformat()))
    stocks = []
    for stock in data.get("stocks", []):
        stock_for_analysis: Mapping[str, Any] = {**stock, "report_date": report_date.isoformat()}
        if extended_dir is not None and stock.get("technical_candles") is None:
            try:
                extended_candles, receipt = _load_extended_candles(extended_dir, str(stock.get("symbol", "")))
                stock_for_analysis = {**stock_for_analysis, "technical_candles": extended_candles, "_technical_source_receipt": receipt}
            except (OSError, json.JSONDecodeError, TechnicalInputError) as exc:
                stock_for_analysis = {**stock_for_analysis, "_technical_source_error": str(exc)}
        analysis = analyze_stock(stock_for_analysis, method_paths)
        stocks.append({"symbol": stock.get("symbol"), "name": stock.get("name"), "technical_analysis": analysis})
    return {"report_date": report_date.isoformat(), "source_input": f"stock-audit-{report_date.isoformat()}.json", "stocks": stocks}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pva-path", type=Path, default=DEFAULT_PVA_PATH)
    parser.add_argument("--detector-path", type=Path, default=DEFAULT_DETECTOR_PATH)
    parser.add_argument("--extended-dir", type=Path, default=None, help="Read-only directory containing <symbol>.json technical candle files")
    args = parser.parse_args(argv)
    data = json.loads(args.input.read_text(encoding="utf-8"))
    result = _analyze_report_with_extended(
        data,
        method_paths={"pva": args.pva_path, "detector": args.detector_path},
        extended_dir=args.extended_dir,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    incomplete = [
        str(stock.get("symbol"))
        for stock in result["stocks"]
        if stock.get("technical_analysis", {}).get("analysis_status") != "complete"
    ]
    if incomplete:
        print(
            f"Wrote evidence with unavailable analysis for {len(incomplete)} stocks: {','.join(incomplete)}; {args.output}",
            file=sys.stderr,
        )
        return 2
    print(f"Wrote complete technical analysis for {len(result['stocks'])} stocks: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
