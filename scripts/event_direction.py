#!/usr/bin/env python3
"""Bull/bear direction for a headline, per (event x sector).

The pre-market board used to be risk-framed only: every transmission path in
geo_focus says how a headline *can* hurt Taiwan equities, so a Fed cut, a tariff
truce and an eased export control all landed in the same "watch" list as their
opposites. This module adds the missing polarity axis.

Design rules (issue #9):

* Direction sits on the (event, sector) pair, not on the event. The same Fed cut
  is +1 for tech and 0 for banks; the page buckets by the path's primary sector.
* Every non-zero direction names the rule that fired and the text it matched,
  so a wrong call can be traced to one regex rather than to a model.
* A negation cue earlier in the same clause flips the matched rule
  ("no plans to ... push them out of its supply chain" is bullish).
* If nothing fires, or both directions fire, the answer is 0. It never guesses.
* Each path has a scope gate. A US-Canada tariff or an export control on Russian
  diesel is real news but not a Taiwan-equity call; it stays 0 with the gate as
  its reason, instead of filling the bearish column with noise -- which is the
  exact skew this module exists to fix.

Paths without a rule table return 0 / ``path_not_modelled`` until #11.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

RULE_VERSION = "direction-v1"

BULL, NEUTRAL, BEAR = 1, 0, -1


@dataclass(frozen=True)
class Rule:
    rule_id: str
    sign: int
    pattern: re.Pattern[str]


def _rules(path: str, sign: int, name: str, *patterns: str) -> list[Rule]:
    return [Rule(f"{path}.{name}", sign, re.compile(p, re.I)) for p in patterns]


# --- negation ---------------------------------------------------------------
# A cue counts only if it sits before the match inside the same clause. Clauses
# break on the speaker colon, sentence punctuation and "but"; commas do not
# break, because wire copy lists names with commas inside one negated clause
# ("no plans to target Ericsson, ASML, Samsung, or SK Hynix or push them out").
NEGATION = re.compile(
    r"\b(no|not|never|none|nor|without|won't|wouldn't|can't|cannot|"
    r"doesn't|don't|didn't|isn't|aren't|wasn't|haven't|hasn't|"
    r"den(y|ies|ied)|rules? out|ruled out|reject(s|ed)?|preclude(s|d)?|"
    r"no plans?|no intention|unlikely|(warn|caution|argu)\w*( [\w']+){0,3} against)\b|不會|沒有|否認|無意|不打算",
    re.I,
)
CLAUSE_BREAK = re.compile(r"[:;!?]|(?<!\d)\.(?!\d)|\bbut\b|\bhowever\b", re.I)


def _clause_start(text: str, index: int) -> int:
    start = 0
    for found in CLAUSE_BREAK.finditer(text, 0, index):
        start = found.end()
    return start


# A rule matching a description of the past ("cut rates gradually last year")
# says nothing about what happens next, so the hit is dropped.
HISTORICAL = re.compile(r"\b(last (year|month|week)|in 20[12]\d|previously|earlier this year|a year ago)\b", re.I)


def _clause(text: str, start: int, end: int) -> str:
    following = CLAUSE_BREAK.search(text, end)
    return text[_clause_start(text, start):following.start() if following else len(text)]


def _negation_before(text: str, index: int) -> str | None:
    window = text[_clause_start(text, index):index]
    cues = list(NEGATION.finditer(window))
    return cues[-1].group(0) if cues else None


# --- per-path tables ----------------------------------------------------------
# `sectors` maps each sector the path already lists to a multiplier: 1 follows
# the headline's sign, 0 means "no defensible call" (left neutral, not guessed).
# `primary` is the sector the page buckets the event by.

US_ANCHOR = re.compile(
    r"\bfed\b|federal reserve|\bfomc\b|powell|warsh|\bus\b|u\.s\.|united states|"
    r"american|treasury|\bpce\b|white house|trump|bessent|"
    # Fed officials are often quoted by surname alone.
    r"jefferson|waller|bowman|\bbarr\b|\bcook\b|kugler|miran|logan|hammack|musalem|"
    r"goolsbee|daly|kashkari|schmid|collins|barkin|paulson|williams|bostic|harker|"
    r"jefferson|perli",
    re.I,
)
# A US data release prints "Actual x (Forecast y, ...)"; for inflation prints a
# beat is hawkish (bearish tech), a miss is dovish.
US_INFLATION_PRINT = re.compile(
    r"^us\b.{0,40}\b(cpi|pce|ppi)\b.{0,40}actual\s*(-?[\d.]+)\s*%?\s*\(\s*forecast\s*(-?[\d.]+)",
    re.I,
)
NON_US_CENTRAL_BANK = re.compile(
    r"\b(ecb|boe|boj|bok|boc|rba|rbnz|snb|pboc|riksbank|norges)\b|"
    r"bank of (england|japan|canada|korea)|reserve bank",
    re.I,
)

TW_TRADE_ANCHOR = re.compile(
    r"taiwan|china|chinese|beijing|xi\b|asia|asean|vietnam|"
    r"semiconductor|chip|electronic|server|global|all countries|every country|"
    r"reciprocal|universal|worldwide|trading partners",
    re.I,
)
THIRD_PARTY = re.compile(
    r"canad|mexic|\beu\b|europe|\buk\b|britain|british|india|australia|brazil|"
    r"switzerland|swiss|german|france|french|italy|japan|korea|ottawa|ontario|usmca|"
    r"\bboc\b|macklem|carney|sheinbaum|leblanc",
    re.I,
)
CHIP_ANCHOR = re.compile(
    r"chip|semiconductor|\bai\b|asml|nvidia|tsmc|samsung|hynix|huawei|smic|"
    r"entity list|advanced computing|foundry|wafer|gpu|hbm|rare earth|gallium|"
    r"germanium|supply chain|supplier|lithograph|tech curb",
    re.I,
)

# A US actor (or Taiwan itself) has to be party to the tariff for it to be a
# Taiwan-equity call; China-Switzerland or EU-UK deals are somebody else's trade.
US_TRADE_ACTOR = re.compile(
    r"\bus\b|u\.s\.|united states|american|washington|trump|white house|\bustr\b|"
    r"greer|lutnick|bessent|section (232|301|338)",
    re.I,
)
# Entity-list additions over human rights are not technology controls.
NON_TECH_LISTING = re.compile(r"xinjiang|uyghur|forced labou?r|human rights", re.I)

_TIGHTEN = r"(export controls?|restrictions?|curbs?|bans?|entity list)"

PATH_RULES: dict[str, dict[str, Any]] = {
    "fed_rates": {
        "primary": "科技股全體",
        "sectors": {"科技股全體": 1, "金融": 0, "壽險": 0},
        "horizon": "short",
        "rules": [
            *_rules("fed_rates", BULL, "cut",
                    r"\brates? cuts?\b", r"\bcut(s|ting)? (interest |policy )?rates?\b",
                    r"\b(lower|reduc)\w* (interest |policy )?rates\b",
                    r"\broom to (cut|ease)\b", r"\b(support|favou?r|open to)\w*\s.{0,25}\bcuts?\b"),
            *_rules("fed_rates", BULL, "dovish",
                    r"\bdovish\b", r"\bdisinflation\b",
                    r"\binflation\b.{0,30}\b(cool|eas|slow|fall|fell|declin|moderat|subsid|retreat)\w*",
                    r"\b(cool|eas|slow)\w* inflation\b",
                    r"\byields? (fall|fell|drop|declin|slid)\w*",
                    # Fires alongside the hawkish "pressures" noun on purpose: "limit
                    # some inflationary pressures" is then a conflict, i.e. 0.
                    r"\b(limit|contain|tam|cool)\w*\s.{0,15}\b(inflation(ary)?|price) pressures?\b"),
            *_rules("fed_rates", BEAR, "hike",
                    r"\brates? (hikes?|increases?)\b", r"\b(raise|hike|increas)\w* (interest |policy )?rates?\b",
                    r"\b(take back|unwind|revers)\w*\s.{0,20}\bcuts\b"),
            *_rules("fed_rates", BEAR, "hawkish",
                    r"\bhawkish\b", r"\btightening\b",
                    r"\binflation\b.{0,30}\b(rise|rose|rising|accelerat|hot|sticky|persist|elevated|"
                    r"broaden|higher|too high|excessive|picks? up|picked up|climb|jump|surge|troubling|increas)\w*",
                    r"\b(troubling|worrying|concerning)\b.{0,20}\binflation\b",
                    r"\binflation\b.{0,25}\babove (the )?(\d|target)",
                    r"\b(higher|hotter|sticky|persistent|elevated|broadening)\s.{0,15}inflation\b",
                    r"\binflation(ary)? pressures?\b", r"\bprice pressures?\b", r"\bpressures? on (inflation|prices)\b",
                    r"\b(no rush|not in a hurry|no hurry)\b.{0,25}\b(cut|eas)\w*",
                    r"\byields? (rise|rose|rising|jump|climb|surge)\w*",
                    r"\bhigher than .{0,15}(hoped|expected)\b"),
        ],
    },
    "tariff": {
        "primary": "電子代工",
        "sectors": {"電子代工": 1, "工具機": 1, "鋼鐵": 1, "紡織": 1},
        "horizon": "long",
        "rules": [
            *_rules("tariff", BULL, "relief",
                    r"\b(cut|lower|reduc|halv|remov|eliminat|scrap|drop|suspend|pause|delay|postpon|"
                    r"exempt|waiv|ease|lift|roll\w* back|par\w* back)\w*\s.{0,40}\btariffs?\b",
                    r"\btariffs?\b.{0,30}\b(cut|lowered|reduced|removed|paused|suspended|delayed|"
                    r"postponed|lifted|halved|exempted)\b",
                    r"\btariff (relief|reprieve|exemption|truce|cuts?|reduction)\b",
                    r"\bextend\w* (the )?suspension\b",
                    r"\bframework for .{0,30}tariff cuts\b"),
            *_rules("tariff", BULL, "deal",
                    r"\b(reach|sign|agree|finali[sz]|conclud|complet|seal)\w*\s.{0,30}\b(trade )?(deal|agreement)\b",
                    r"\btrade (deal|agreement|truce) (reached|signed|agreed|finali[sz]ed)\b",
                    r"\b(free-trade|trade) deal removing tariffs\b",
                    r"\bprogress\b.{0,20}\btrade (talks|negotiations)\b"),
            *_rules("tariff", BEAR, "impose",
                    r"\b(impos|levy|levie|slap|rais|hik|increas|enforc)\w*\s.{0,40}\btariffs?\b",
                    r"\b(new|additional|higher|fresh|broad|extra|retaliatory)\s.{0,20}\btariffs?\b",
                    r"\btariffs?\b.{0,30}\b(take effect|to begin|begin|start)\w*",
                    r"\banti-dumping (probe|duty|duties|investigation|measures)\b",
                    r"\btrade war\b"),
            *_rules("tariff", BEAR, "talks_fail",
                    r"\btrade talks\b.{0,20}\b(suspended|collapse\w*|fail\w*|broke down|break down)\b",
                    r"\bdeclined to complete trade\b"),
        ],
    },
    "export_control": {
        "primary": "半導體",
        "sectors": {"半導體": 1, "AI伺服器": 1, "IC設計": 1, "電子零組件": 1},
        "horizon": "long",
        "rules": [
            *_rules("export_control", BULL, "ease",
                    r"\b(ease|eases|eased|easing|relax\w*|loosen\w*|lift\w*|scrap\w*|remov\w*|"
                    r"roll\w* back|exempt\w*|waive\w*|pause\w*|suspend\w*)\b.{0,40}\b"
                    r"(export controls?|restrictions?|curbs?|bans?|sanctions?|entity list)\b",
                    r"\b(export controls?|restrictions?|curbs?|bans?|sanctions?)\b.{0,30}"
                    r"\b(eased|lifted|relaxed|removed|suspended|paused)\b",
                    r"\b(export control|sanctions?) relief\b",
                    r"\b(grant|approv|issu)\w*\s.{0,30}\blicen[cs]es?\b",
                    r"\blicen[cs]es? (granted|approved|issued)\b",
                    r"\ballow\w*\s.{0,40}\b(sales?|sell|exports?|ship\w*)\b",
                    r"\b(resum|restart)\w*\s.{0,30}\b(sales?|shipments?|exports?)\b"),
            *_rules("export_control", BEAR, "tighten",
                    rf"\b(tighter|tighten\w*|new|additional|expand\w*|broaden\w*|stricter)\s.{{0,30}}\b{_TIGHTEN}",
                    rf"\b(impos|add|plac|put)\w*\s.{{0,40}}\b{_TIGHTEN}",
                    r"\b(listing|listed|adds?|added)\b.{0,40}\bentity list\b",
                    r"\b(chip|semiconductor)s?\b.{0,20}\b(ban|curb)s?\b",
                    r"\b(restrict|block)\w*\s.{0,30}\b(chips?|semiconductors?|exports?|sales?|shipments?)\b",
                    r"\b(push|kick|forc|cut)\w*\s.{0,40}\bout of\b.{0,20}\bsupply chain\b",
                    r"\btarget\w*\s.{0,20}\b(suppliers?|chips?|semiconductors?|asml|tsmc)\b",
                    r"\bvows? export controls\b"),
        ],
    },
}


@dataclass(frozen=True)
class Assessment:
    direction: int
    reason: str
    horizon: str
    primary: str | None
    sectors: Mapping[str, int]


def _neutral(reason: str, spec: Mapping[str, Any] | None) -> Assessment:
    sectors = {name: 0 for name in (spec or {}).get("sectors", {})}
    return Assessment(NEUTRAL, reason, (spec or {}).get("horizon", "short"),
                      (spec or {}).get("primary"), sectors)


def _scope_gate(path_id: str, text: str) -> str | None:
    """Return a gate reason when the headline is off-scope for a TW call."""
    if path_id == "fed_rates":
        if NON_US_CENTRAL_BANK.search(text) and not re.search(r"\bfed\b|fomc|federal reserve", text, re.I):
            return "fed_rates.gate:non_us_central_bank"
        if not US_ANCHOR.search(text):
            return "fed_rates.gate:non_us"
    elif path_id == "tariff":
        if not (US_TRADE_ACTOR.search(text) or re.search(r"taiwan", text, re.I)):
            return "tariff.gate:no_us_or_taiwan"
        if THIRD_PARTY.search(text) and not TW_TRADE_ANCHOR.search(text):
            return "tariff.gate:third_party"
    elif path_id == "export_control":
        if NON_TECH_LISTING.search(text) or not CHIP_ANCHOR.search(text):
            return "export_control.gate:not_chip"
    return None


def _inflation_print(text: str) -> tuple[int, str] | None:
    found = US_INFLATION_PRINT.search(text)
    if not found:
        return None
    actual, forecast = float(found.group(2)), float(found.group(3))
    if actual > forecast:
        return BEAR, f"fed_rates.print_beat:{actual:g}>{forecast:g}"
    if actual < forecast:
        return BULL, f"fed_rates.print_miss:{actual:g}<{forecast:g}"
    return NEUTRAL, f"fed_rates.print_inline:{actual:g}={forecast:g}"


def assess(title: str, path_id: str) -> Assessment:
    """Direction of one headline on one transmission path."""
    text = " ".join(str(title or "").split())
    spec = PATH_RULES.get(path_id)
    if spec is None:
        return _neutral("path_not_modelled", None)

    gate = _scope_gate(path_id, text)
    if gate:
        return _neutral(gate, spec)

    if path_id == "fed_rates":
        printed = _inflation_print(text)
        if printed is not None:
            sign, reason = printed
            return _finish(sign, reason, spec)

    hits: list[tuple[int, str]] = []
    for rule in spec["rules"]:
        found = rule.pattern.search(text)
        if not found:
            continue
        if HISTORICAL.search(_clause(text, found.start(), found.end())):
            continue
        cue = _negation_before(text, found.start())
        snippet = found.group(0).strip()
        if cue:
            hits.append((-rule.sign, f"{rule.rule_id}:'{snippet}' negated_by:'{cue}'"))
        else:
            hits.append((rule.sign, f"{rule.rule_id}:'{snippet}'"))

    if not hits:
        return _neutral("no_rule", spec)
    signs = {sign for sign, _ in hits}
    if len(signs) > 1:
        return _neutral("conflict:" + " | ".join(reason for _, reason in hits), spec)
    return _finish(hits[0][0], " | ".join(reason for _, reason in hits), spec)


def _finish(sign: int, reason: str, spec: Mapping[str, Any]) -> Assessment:
    sectors = {name: sign * mult for name, mult in spec["sectors"].items()}
    return Assessment(sign, reason, spec["horizon"], spec["primary"], sectors)


def label_of(direction: int) -> str:
    return {BULL: "bull", BEAR: "bear"}.get(direction, "neutral")


def impact_rows(
    event: Mapping[str, Any],
    *,
    rule_version: str = RULE_VERSION,
) -> list[dict[str, Any]]:
    """Map one focus event to radar.event_impact rows (target_type='sector').

    Every sector of the path gets a row, including 0s: a neutral call is still a
    recorded decision, and the reason column says why it was left neutral.
    """
    event_id = str(event.get("id") or "").strip()
    if not event_id:
        raise ValueError("focus event is missing id")
    magnitude = event.get("score")
    if not isinstance(magnitude, (int, float)) or isinstance(magnitude, bool):
        magnitude = 0.0
    magnitude = round(min(1.0, max(0.0, float(magnitude))), 3)
    rows = []
    for impact in event.get("impacts") or []:
        rows.append({
            "event_id": event_id,
            "target_type": "sector",
            "target_id": impact["sector"],
            "rule_version": rule_version,
            "path_id": event.get("pathId"),
            "direction": int(impact["direction"]),
            "magnitude": magnitude,
            "horizon": event.get("horizon") or "short",
            "reason": event.get("directionReason"),
        })
    return rows


def annotate(event: dict[str, Any], path_id: str | None = None) -> dict[str, Any]:
    """Attach direction fields to a focus event in place and return it."""
    pid = path_id or event.get("pathId")
    result = assess(str(event.get("titleEn") or ""), str(pid or ""))
    event["pathId"] = pid
    event["direction"] = result.direction
    event["directionReason"] = result.reason
    event["horizon"] = result.horizon
    sectors = dict(result.sectors) or {str(name): 0 for name in event.get("sectors") or []}
    event["impacts"] = [{"sector": name, "direction": value} for name, value in sectors.items()]
    return event
