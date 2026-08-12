#!/usr/bin/env python3
"""Score global headlines by how they reach Taiwan equities.

The existing sources are Taiwan industry press; none of them break geopolitics
first. This module adds a global wire and answers the pre-market question those
sources cannot: did something happen overnight that moves the open?

Scoring multiplies five axes:

  path      how the event reaches Taiwan equities, and how hard
  act       what the headline *is* -- a decision, a threat, data, or an opinion
  speaker   whose statement it is
  corro     how many distinct substantive voices touch the same path
  recency   decay, since a pre-market board is about the last few hours

The act axis exists because an earlier version ranked eight Fed officials
restating one view above a Hormuz closure: counting headlines rewarded whoever
talked most. Opinions are damped to 0.4 so commentary cannot crowd out events.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

LOGGER = logging.getLogger(__name__)

FEED_URL = "https://www.financialjuice.com/feed.ashx?xy=rss"
SOURCE_ID = "financialjuice"
SOURCE_NAME = "FinancialJuice"

# --- Axis 1: transmission paths ------------------------------------------
# Each entry names the mechanism, not just a keyword bucket. `channel` is
# rendered verbatim on the page, split on the arrow into pills.
PATHS: tuple[dict[str, Any], ...] = (
    {
        "id": "taiwan_strait", "label": "台海情勢", "weight": 1.0,
        "channel": "外資撤離 → 系統性風險 → 全市場重估",
        "sectors": ("大盤全體", "金融", "權值股"),
        "kw": (r"taiwan strait", r"taiwan.{0,25}(invasion|blockade|incursion|tension|drill)",
               r"(pla|china|beijing).{0,30}taiwan", r"taiwan.{0,25}(militar|defen[cs]e)",
               r"bashi channel"),
    },
    {
        "id": "export_control", "label": "出口管制/科技戰", "weight": 1.0,
        "channel": "供應鏈直接斷鏈 → 出貨受阻",
        "sectors": ("半導體", "AI伺服器", "IC設計", "電子零組件"),
        "kw": (r"export control", r"entity list", r"chip.{0,18}(ban|curb|restrict|control)",
               r"semiconductor.{0,25}(restrict|sanction|tariff|ban|control)",
               r"\basml\b", r"nvidia.{0,18}(ban|licen|restrict)", r"tech.{0,12}(war|curb|ban)",
               r"advanced computing", r"foundry.{0,15}(restrict|ban)", r"huawei|smic"),
    },
    {
        "id": "tariff", "label": "關稅/貿易", "weight": 0.95,
        "channel": "出口成本↑ → 毛利壓縮 → 轉單效應",
        "sectors": ("電子代工", "工具機", "鋼鐵", "紡織"),
        "kw": (r"tariff", r"trade (deal|war|talks|deficit|agreement)", r"\bustr\b",
               r"section 301", r"trade negotiat", r"import dut", r"anti-dumping",
               r"trade barrier", r"customs dut"),
    },
    {
        "id": "shipping_lane", "label": "航道安全", "weight": 0.9,
        "channel": "繞道好望角 → 運價飆升 → 交期拉長",
        "sectors": ("貨櫃航運", "散裝航運", "航空貨運"),
        "kw": (r"red sea", r"bab al-?mandab", r"suez", r"houthi", r"panama canal",
               r"malacca", r"(attack|strike|seiz|hijack).{0,30}(ship|vessel|tanker|cargo)",
               r"(ship|vessel|tanker|cargo).{0,30}(attack|struck|seiz|hijack|sunk)",
               r"shipping lane", r"freight rate", r"port (strike|closure|congestion)"),
    },
    {
        "id": "hormuz_energy", "label": "能源/荷姆茲", "weight": 0.88,
        "channel": "油價↑ → 原料成本 → 輸入性通膨",
        "sectors": ("塑化", "航運", "油電燃氣", "紡織"),
        "kw": (r"strait of hormuz", r"\bopec\b", r"oil (price|output|supply|export|flow)",
               r"crude", r"energy (pipeline|infrastructure|facilit)", r"\blng\b",
               r"natural gas", r"refiner", r"barrel"),
    },
    {
        "id": "ai_capex", "label": "AI資本支出", "weight": 0.85,
        "channel": "雲端資本支出 → 台廠訂單能見度",
        "sectors": ("AI伺服器", "半導體", "散熱", "PCB", "光通訊"),
        "kw": (r"(capex|capital expenditure).{0,25}(ai|data ?cent|cloud)",
               r"(microsoft|google|amazon|meta|oracle).{0,30}(capex|data ?cent|invest)",
               r"nvidia.{0,25}(order|demand|revenue|guidance|gpu)",
               r"\bhbm\b|\bcowos\b", r"data ?cent(er|re).{0,20}(build|expan|invest)"),
    },
    {
        "id": "military_conflict", "label": "軍事衝突", "weight": 0.85,
        "channel": "避險情緒 → 資金撤離風險資產",
        "sectors": ("航運", "航太國防", "黃金相關", "大盤全體"),
        "kw": (r"missile|airstrike|warship|troops|drone strike", r"\birgc\b",
               r"(strike|attack|bomb)(s|ed|ing)?\b.{0,25}(iran|israel|ukraine|russia|yemen)",
               r"ceasefire|war must end", r"nuclear (test|program|weapon)",
               r"invasion|mobiliz", r"retaliat"),
    },
    {
        "id": "fed_rates", "label": "Fed/利率", "weight": 0.82,
        "channel": "資金成本 → 科技股評價重估",
        "sectors": ("科技股全體", "金融", "壽險"),
        "kw": (r"\bfed\b|federal reserve", r"\bfomc\b", r"powell",
               r"rate (cut|hike|decision|path)", r"interest rate",
               r"inflation|\bcpi\b|\bppi\b|\bpce\b", r"treasury yield",
               r"jobless|payroll|labor market|unemployment"),
    },
    {
        "id": "supply_chain", "label": "供應鏈斷料", "weight": 0.8,
        "channel": "關鍵料件短缺 → 產線停擺",
        "sectors": ("電子零組件", "半導體", "汽車零組件"),
        "kw": (r"supply chain", r"chip shortage", r"rare earth", r"critical mineral",
               r"gallium|germanium|graphite", r"wafer (supply|shortage)",
               r"component shortage", r"production (halt|cut|suspend)"),
    },
    {
        "id": "fx_capital", "label": "匯率/資金", "weight": 0.75,
        "channel": "台幣走勢 → 外資進出 + 匯兌損益",
        "sectors": ("金融", "壽險", "電子出口股"),
        "kw": (r"\bdollar\b|\bdxy\b", r"\byuan\b|renminbi", r"\byen\b",
               r"currency|forex|exchange rate", r"capital (flow|outflow|control)",
               r"\btwd\b|taiwan dollar"),
    },
    {
        "id": "china_macro", "label": "中國經濟", "weight": 0.72,
        "channel": "終端需求 → 台廠拉貨動能",
        "sectors": ("電子代工", "工具機", "水泥", "鋼鐵", "觀光"),
        "kw": (r"china.{0,25}(gdp|growth|stimulus|export|import|pmi|deflation)",
               r"\bpboc\b", r"chinese (economy|demand|consumer)",
               r"property (crisis|developer|default)", r"evergrande"),
    },
)

# --- Axis 2: what the headline is ----------------------------------------
ACT_TYPES: tuple[tuple[str, float, str, tuple[str, ...]], ...] = (
    ("decision", 1.0, "決議行動", (
        r"\b(raise|cut|hold|lower)s?\b.{0,18}\brate", r"rate decision",
        r"\b(announce|impose|ban|sanction|block|approve|sign)(s|d|ed)?\b",
        r"(closed|closure|reopen|shut).{0,18}(strait|port|pipeline)",
        r"\b(strike|attack|launch)(s|ed)?\b", r"executive order", r"takes effect")),
    ("threat", 0.92, "威脅/預告", (
        r"\b(will|would|could|may|plans? to|threaten)\b.{0,30}"
        r"(close|attack|strike|hit|target|retaliat|ban|sanction|tariff)",
        r"if .{0,40}(arises|happens|continues|again)", r"no shortage of",
        r"warn(s|ed|ing)?\b", r"not be reopened")),
    ("data", 0.78, "數據發布", (
        r"\b(cpi|ppi|gdp|pmi|nfp)\b",
        r"\b(rose|fell|declined|increased|up|down)\b.{0,22}\b(to|by)\b.{0,14}[\d.]+\s*(%|bln|trln|mln)",
        r"(report|index|survey|reading).{0,14}\b(shows?|at|hits?)\b",
        r"\bq[1-4]\b.{0,24}[\d.]+", r"average for")),
    ("opinion", 0.40, "評論看法", (
        r"\b(says?|said|sees?|expects?|believes?|thinks?|notes?|adds?)\b",
        r"\bspeaks?\b", r"\b(view|outlook|assessment|question is)\b",
        r"appears?\b", r"indicators? say", r"understanding of")),
)

# --- Axis 3: whose statement ---------------------------------------------
SPEAKER_TIERS: tuple[tuple[float, tuple[str, ...]], ...] = (
    (1.0, ("fomc", "powell", "ecb", "boj", "pboc", "treasury", "white house",
           "trump", "president", "ustr", "opec", "imf")),
    (0.85, ("minister", "secretary", "governor", "central bank", "official",
            "spokesperson", "adviser", "supreme leader", "irgc")),
    (0.6, ("fitch", "moody", "s&p", "goldman", "morgan", "citi", "ubs", "natixis")),
)
FED_PRINCIPALS = ("powell", "fomc", "chair")
FED_REGIONAL = ("goolsbee", "venable", "atlanta", "ny fed", "new york fed", "chicago",
                "st. louis", "dallas", "boston", "richmond", "cleveland", "kansas")

# Wire copy describing an event carries no "Speaker:" prefix; it must not be
# penalised against a named official merely voicing an opinion.
EVENT_MARKERS = (r"(attack|strike|seiz|hijack|sunk|killed|explosion|fire)",
                 r"(closed|reopen|halt|suspend|resume)",
                 r"(rose|fell|surge|plunge|jump|drop)")

# Sponsored placements and auction notices are not reporting.
NOISE = (r"fjelite", r"cribsheet", r"^us to sell", r"bills? on", r"auction",
         r"pre-recorded", r"^\w+ (report|data)$")

TIER_CRITICAL = 0.60
TIER_WATCH = 0.36


def strip_prefix(title: str) -> str:
    return re.sub(r"^FinancialJuice:\s*", "", str(title or "")).strip()


def is_noise(title: str) -> bool:
    low = title.lower()
    return any(re.search(p, low) for p in NOISE)


def match_paths(title: str) -> list[dict[str, Any]]:
    low = title.lower()
    return [p for p in PATHS if any(re.search(k, low) for k in p["kw"])]


# A conditional or future framing makes a headline a threat even though it also
# contains an action verb: "will close the strait if attacked" has not happened.
# Without this, hypotheticals score as completed actions -- the strongest tier.
CONDITIONAL = re.compile(
    r"\b(if|unless|should|would|could|may|might|plans? to|threaten|warn|vow|"
    r"plan|prepare|plans|ready to)\b|\bwill\b",
    re.I,
)


def classify_act(title: str) -> tuple[str, float, str]:
    low = title.lower()
    best = ("opinion", 0.40, "評論看法")
    for key, weight, label, patterns in ACT_TYPES:
        if weight > best[1] and any(re.search(p, low) for p in patterns):
            best = (key, weight, label)
    if best[0] == "decision" and CONDITIONAL.search(low):
        return ("threat", 0.92, "威脅/預告")
    return best


def weigh_speaker(title: str) -> tuple[float, str]:
    head = title.split(":", 1)[0].strip() if ":" in title else ""
    low = head.lower()
    if not head or len(head) > 60:
        if any(re.search(p, title.lower()) for p in EVENT_MARKERS):
            return 0.9, "事件報導"
        return 0.5, "事件報導"
    if "fed" in low or "federal reserve" in low:
        if any(k in low for k in FED_PRINCIPALS):
            return 1.0, head
        if any(k in low for k in FED_REGIONAL):
            return 0.55, head
        return 0.7, head
    for weight, keys in SPEAKER_TIERS:
        if any(k in low for k in keys):
            return weight, head
    return 0.55, head


def _canonical_voice(title: str) -> str:
    """Group restatements by one speaker, ignoring regional Fed prefixes."""
    head = title.split(":", 1)[0].strip() if ":" in title else ""
    if not head or len(head) > 60:
        return "event:" + re.sub(r"[^a-z]", "", title.lower())[:24]
    return re.sub(r"^(atlanta|ny|new york|chicago|st\.? louis|dallas|boston|richmond|"
                  r"cleveland|kansas city)\s+", "", head, flags=re.I).lower()


def decay(published: datetime, now: datetime) -> float:
    hours = (now - published).total_seconds() / 3600
    if hours <= 3:
        return 1.0
    if hours <= 9:
        return 0.88
    if hours <= 24:
        return 0.65
    return 0.4


def tier_of(score: float) -> str:
    if score >= TIER_CRITICAL:
        return "critical"
    if score >= TIER_WATCH:
        return "watch"
    return "normal"


def build_focus_events(
    entries: Iterable[Mapping[str, Any]],
    translations: Mapping[str, str],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Rank entries into the page's FocusEvent shape, newest-relevant first.

    `entries` items need `title`, `link` and `published_at` (aware datetime).
    """
    moment = now or datetime.now(timezone.utc)
    staged: list[dict[str, Any]] = []
    for entry in entries:
        title = strip_prefix(entry.get("title"))
        if not title or is_noise(title):
            continue
        paths = match_paths(title)
        if not paths:
            continue
        published = entry.get("published_at")
        if not isinstance(published, datetime):
            continue
        path = max(paths, key=lambda p: p["weight"])
        act_key, act_weight, act_label = classify_act(title)
        speaker_weight, speaker = weigh_speaker(title)
        staged.append({
            "title": title, "path": path, "act": act_key, "act_weight": act_weight,
            "act_label": act_label, "speaker": speaker, "speaker_weight": speaker_weight,
            "voice": _canonical_voice(title), "published": published,
            "url": entry.get("link") or "",
        })

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in staged:
        grouped.setdefault((item["voice"], item["path"]["id"]), []).append(item)

    # Corroboration counts distinct voices that said something substantive on a
    # path, so repeated commentary cannot inflate it.
    substantive: dict[str, set[str]] = {}
    for (voice, path_id), members in grouped.items():
        if any(m["act"] != "opinion" for m in members):
            substantive.setdefault(path_id, set()).add(voice)

    events: list[dict[str, Any]] = []
    for (_, path_id), members in grouped.items():
        members.sort(key=lambda m: (m["act_weight"], m["published"]), reverse=True)
        lead = members[0]
        voices = len(substantive.get(path_id, ()))
        corroboration = min(1.0, 0.62 + 0.13 * voices)
        score = round(
            lead["path"]["weight"] * lead["act_weight"] * lead["speaker_weight"]
            * corroboration * decay(lead["published"], moment),
            3,
        )
        events.append({
            "id": f"{SOURCE_ID}-{abs(hash(lead['title'])) & 0xFFFFFFF:07x}",
            "tier": tier_of(score),
            "score": score,
            "actLabel": lead["act_label"],
            "speaker": lead["speaker"],
            "publishedAt": lead["published"].astimezone(timezone.utc).isoformat(),
            "titleZh": translations.get(lead["title"], lead["title"]),
            "titleEn": lead["title"],
            "channel": lead["path"]["channel"],
            "pathLabel": lead["path"]["label"],
            "sectors": list(lead["path"]["sectors"]),
            "url": lead["url"],
            "related": [
                {"title": translations.get(m["title"], m["title"]), "url": m["url"]}
                for m in members[1:]
            ],
        })
    events.sort(key=lambda e: e["score"], reverse=True)
    return events
