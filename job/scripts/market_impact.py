"""Market-impact scoring that does not depend on a theme keyword match.

Why this exists (docs/MISTAKES.md M026): the theme radar and the pre-market
board both dropped any headline that matched no theme / transmission path
*before* anyone asked how much it moved the market. On 2026-11-23 about 120
headlines on 黃仁勳 returning as NVIDIA CEO (the reason the US opened sharply
higher) were ingested and every one was discarded at theme score 0.

The order is now: keep by market impact, then map to Taiwan stocks.

Impact comes from four independent signals, each auditable in
`impact_signals`:

- mover:  the headline names a market mover (job/config/market_movers.json)
- move:   it reports a market reaction (暴漲/重挫/盤前飆/+7% ...)
- event:  it reports a high-impact corporate or policy event (CEO 下台/回鍋,
          調查, 制裁 ...)
- burst:  data-driven, no keyword list: a term in the headline is suddenly
          carried by many distinct headlines from several sources. Catches
          stories nobody configured.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MOVERS_PATH = ROOT / "config" / "market_movers.json"

# A headline at or above this is kept even with no theme match.
IMPACT_KEEP_MIN = 0.6

MOVER_WEIGHT = 0.45
MOVE_WEIGHT = 0.35
EVENT_WEIGHT = 0.3
BURST_WEIGHT = 0.6

# Burst: a term carried by this many distinct headlines in the last 24h, from
# at least BURST_MIN_SOURCES sources, at BURST_MIN_RATIO x its earlier daily
# rate (so words that are always there, 台股 / 美股, never burst).
BURST_RECENT_HOURS = 24
BURST_MIN_HEADLINES = 10
BURST_MIN_SOURCES = 3
BURST_MIN_RATIO = 2.5
BURST_FULL_HEADLINES = 30

STRONG_MOVE = re.compile(
    r"暴漲|暴跌|狂飆|飆漲|飆逾|飆升|大漲|重挫|狂瀉|崩跌|崩逾|暴雷|急彈|強彈|急殺|急跌|重摔|大摔|腰斬|蒸發|"
    r"漲停|跌停|股災|閃崩|熔斷|"
    r"(?<![A-Za-z0-9])(surg\w*|soar\w*|plung\w*|tumbl\w*|crash\w*|skyrocket\w*|plummet\w*|rout)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
MILD_MOVE = re.compile(
    r"盤前|夜盤|期指|反彈|走高|走低|翻紅|翻黑|大跌|下挫|"
    r"(?<![A-Za-z0-9])(rall\w*|jump\w*|slump\w*|sell-?off|premarket|futures)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
# A percentage counts only next to a price verb: "營收年增35%" is not a move.
PERCENT = re.compile(
    r"(?:漲|跌|彈|飆|挫|瀉|崩|升|降|(?<![A-Za-z0-9])(?:up|down|rose|fell|gain\w*|lost|drop\w*|jump\w*)(?![A-Za-z0-9]))"
    r"\D{0,6}?(\d+(?:\.\d+)?)\s*[%％]",
    re.IGNORECASE,
)
PERCENT_MOVE_MIN = 3.0

EVENT = re.compile(
    r"執行長|董事長|下台|辭職|請辭|卸任|去職|離職|回鍋|回任|重返|復職|撤換|換帥|接班|"
    r"調查|查帳|起訴|刑事|醜聞|制裁|禁令|禁售|管制|收購|併購|破產|"
    r"(?<![A-Za-z0-9])(ceo|chief executive|resign\w*|step(s|ped)? down|oust\w*|reinstat\w*|"
    r"probe|indict\w*|sanction\w*|ban|bans|banned|acqui\w*|bankrupt\w*)(?![A-Za-z0-9])",
    re.IGNORECASE,
)

LATIN_TOKEN = re.compile(r"[a-z][a-z0-9]{2,}")
CJK_RUN = re.compile(r"[㐀-鿿]+")


@dataclass(frozen=True)
class Mover:
    id: str
    name_zh: str
    kind: str
    weight: float
    aliases: tuple[str, ...]
    tw_theme_ids: tuple[str, ...]
    pre_market_path: str | None


@dataclass
class Impact:
    score: float = 0.0
    signals: list[str] = field(default_factory=list)
    movers: list[Mover] = field(default_factory=list)

    @property
    def keep(self) -> bool:
        return self.score >= IMPACT_KEEP_MIN


def load_market_movers(path: str | Path | None = None) -> list[Mover]:
    payload = json.loads(Path(path or DEFAULT_MOVERS_PATH).read_text(encoding="utf-8"))
    movers: list[Mover] = []
    seen: set[str] = set()
    for raw in payload.get("entities") or []:
        mover_id = str(raw.get("id") or "").strip()
        aliases = tuple(str(a).strip() for a in raw.get("aliases") or [] if str(a).strip())
        weight = float(raw.get("weight") or 0)
        if not mover_id or mover_id in seen or not aliases or not 0 < weight <= 1:
            raise ValueError(f"invalid market mover entry: {raw!r}")
        seen.add(mover_id)
        movers.append(
            Mover(
                id=mover_id,
                name_zh=str(raw.get("name_zh") or mover_id),
                kind=str(raw.get("kind") or ""),
                weight=weight,
                aliases=aliases,
                tw_theme_ids=tuple(str(t) for t in raw.get("tw_theme_ids") or []),
                pre_market_path=raw.get("pre_market_path") or None,
            )
        )
    return movers


def _alias_in(text: str, alias: str) -> bool:
    folded = alias.casefold()
    if re.fullmatch(r"[a-z0-9][a-z0-9 .&+/-]*", folded):
        return re.search(rf"(?<![a-z0-9]){re.escape(folded)}(?![a-z0-9])", text) is not None
    return folded in text


def movers_in(text: str, movers: Iterable[Mover]) -> list[tuple[Mover, str]]:
    folded = text.casefold()
    found: list[tuple[Mover, str]] = []
    for mover in movers:
        alias = next((a for a in mover.aliases if _alias_in(folded, a)), None)
        if alias:
            found.append((mover, alias))
    return found


def move_strength(text: str) -> tuple[float, str | None]:
    strong = STRONG_MOVE.search(text)
    if strong:
        return 1.0, strong.group(0)
    for match in PERCENT.finditer(text):
        value = float(match.group(1))
        if PERCENT_MOVE_MIN <= value < 100:
            return 1.0, match.group(0)
    mild = MILD_MOVE.search(text)
    if mild:
        return 0.5, mild.group(0)
    return 0.0, None


def event_hit(text: str) -> str | None:
    found = EVENT.search(text)
    return found.group(0) if found else None


def headline_terms(title: str) -> set[str]:
    folded = title.casefold()
    terms = set(LATIN_TOKEN.findall(folded))
    for run in CJK_RUN.findall(folded):
        terms.update(run[i:i + 3] for i in range(len(run) - 2))
    return terms


def _normalized_title(title: str) -> str:
    return re.sub(r"[\s　，,。！!？?：:「」『』|｜/／()（）\[\]【】-]+", "", title.casefold())


@dataclass(frozen=True)
class Burst:
    term: str
    headlines: int
    sources: int
    ratio: float

    @property
    def strength(self) -> float:
        # 0.5 at the threshold, 1.0 at BURST_FULL_HEADLINES: a full burst
        # keeps a story on its own, a smaller one needs a second signal.
        span = max(1, BURST_FULL_HEADLINES - BURST_MIN_HEADLINES)
        return 0.5 + 0.5 * min(1.0, max(0, self.headlines - BURST_MIN_HEADLINES) / span)

    def label(self) -> str:
        return f"burst:{self.term}({self.headlines}則/{self.sources}來源)"


def find_bursts(
    records: Iterable[Mapping[str, Any]],
    *,
    anchor: datetime,
    window_hours: int,
    title_of,
    published_of,
    source_of,
) -> dict[str, Burst]:
    """Terms whose distinct-headline count spiked in the last 24h."""

    recent_cutoff = anchor - timedelta(hours=BURST_RECENT_HOURS)
    earlier_days = max(1.0, (window_hours - BURST_RECENT_HOURS) / 24)
    recent_titles: dict[str, set[str]] = {}
    recent_sources: dict[str, set[str]] = {}
    earlier_titles: dict[str, set[str]] = {}
    seen: set[tuple[str, bool]] = set()
    for record in records:
        title = str(title_of(record) or "")
        published = published_of(record)
        if not title or published is None:
            continue
        key = _normalized_title(title)
        recent = published >= recent_cutoff
        if (key, recent) in seen:
            continue
        seen.add((key, recent))
        for term in headline_terms(title):
            if recent:
                recent_titles.setdefault(term, set()).add(key)
                recent_sources.setdefault(term, set()).add(str(source_of(record) or ""))
            else:
                earlier_titles.setdefault(term, set()).add(key)

    bursts: dict[str, Burst] = {}
    for term, titles in recent_titles.items():
        count = len(titles)
        sources = len(recent_sources.get(term, ()))
        if count < BURST_MIN_HEADLINES or sources < BURST_MIN_SOURCES:
            continue
        earlier_daily = len(earlier_titles.get(term, ())) / earlier_days
        ratio = count / max(1.0, earlier_daily)
        if ratio < BURST_MIN_RATIO:
            continue
        bursts[term] = Burst(term, count, sources, round(ratio, 1))
    return bursts


def score_impact(
    title: str,
    movers: Iterable[Mover],
    bursts: Mapping[str, Burst] | None = None,
) -> Impact:
    impact = Impact()
    text = " ".join(str(title or "").split())
    if not text:
        return impact

    total = 0.0
    found = movers_in(text, movers)
    if found:
        best = max(mover.weight for mover, _ in found)
        total += MOVER_WEIGHT * best
        impact.movers = [mover for mover, _ in found]
        impact.signals.extend(f"mover:{mover.id}({alias})" for mover, alias in found)

    strength, move_text = move_strength(text)
    if strength:
        total += MOVE_WEIGHT * strength
        impact.signals.append(f"move:{move_text}")

    event_text = event_hit(text)
    if event_text:
        total += EVENT_WEIGHT
        impact.signals.append(f"event:{event_text}")

    if bursts:
        hits = [bursts[t] for t in headline_terms(text) if t in bursts]
        if hits:
            top = max(hits, key=lambda b: (b.headlines, b.term))
            total += BURST_WEIGHT * top.strength
            impact.signals.append(top.label())

    impact.score = round(min(1.0, total), 3)
    return impact
