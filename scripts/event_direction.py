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

direction-v2 (issue #11) models every geo_focus path, adds the positive paths
(us_tech_rally, tw_fundamental, policy_support) and lets a path's sector
multipliers differ in sign (shipping disruption: 航運 +1, 電子代工 -1).
``Assessment.direction`` is always the call for the path's ``primary`` bucket,
which the page uses to pick the 利多 / 利空 column.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

RULE_VERSION = "direction-v2"

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


# A wish or a conditional ("want an agreement to reopen", "prices to plunge
# when the conflict ends") has not happened; v2 paths drop such hits.
WISH = re.compile(
    r"\b(want|wants|wanted|hope|hopes|would|could|might|if|when|unless|seeks?|should|has to|have to|"
    r"must|conditions?|framework|base case|discuss\w*)\b",
    re.I,
)
WISH_PATHS = frozenset({"taiwan_strait", "shipping_lane", "hormuz_energy", "military_conflict",
                        "ai_capex", "supply_chain", "fx_capital", "china_macro", "us_tech_rally",
                        "tw_fundamental", "policy_support"})
UNTIL_TAIL = re.compile(r"\buntil\b.*$", re.I)
# "Chip rally drives Nasdaq to record as oil falls": the trailing clause is about
# another asset and must not cancel the move the headline is about.
OTHER_ASSET_TAIL = re.compile(r"\b(as|while|after|amid) (oil|crude|yields?|treasur\w*|the dollar|gold|bonds?)\b.*$", re.I)

# Futures settlements print every day; a sub-1% move is noise, not a call.
SETTLE_MOVE = re.compile(r"\bsettles?\b.{0,60}\b(up|down)\b[^%]{0,25}?([\d.]+)\s*%", re.I)
SETTLE_MIN_PCT = 1.0

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

# --- direction-v2 scope anchors (issue #11) ------------------------------------
# Black Sea / Ukraine port strikes are war news, not a Taiwan freight lane.
BLACK_SEA = re.compile(r"black sea|odesa|odessa|ukrain\w* port|danube", re.I)
TW_SEA_LANE = re.compile(r"red sea|hormuz|suez|bab[ -]?(el|al)|malacca|taiwan strait|panama", re.I)
# Russia-Ukraine strikes and routine missile tests repeat daily; only conflicts
# that involve the US, China/Taiwan, Iran or the Gulf move the TW tape.
MAJOR_POWER_CONFLICT = re.compile(
    r"\bus\b|u\.s\.|united states|american|pentagon|trump|centcom|iran|irgc|israel|gulf|"
    r"bahrain|qatar|uae|china|taiwan|nato",
    re.I,
)
TW_FX_ANCHOR = re.compile(r"taiwan|\btwd\b|dollar index|\bdxy\b|asian currenc|foreign investors?", re.I)
MARKET_MOVE_ANCHOR = re.compile(
    r"shares?|stocks?|futures|nasdaq 100|\bsox\b|semiconductor index|market wrap|\$tsm|adr", re.I
)
TECH_POLICY_ANCHOR = re.compile(r"chip|semiconductor|taiwan|tsmc|electronic|\bai\b|solar|green|ev\b", re.I)
# China data prints: "PMI at 52.0 vs forecast 51.6", "GDP rises 4.5% y/y, poll estimated 4.4%".
CHINA_PRINT = re.compile(
    r"\b(gdp|pmi|retail sales|industrial output|exports)\b.{0,30}?\b(?:at|rises?|rose|grows?|grew|up)\s+\+?(-?[\d.]+)%?"
    r".{0,40}?\b(?:vs\.?\s*forecast|forecast|poll(?:\s*estimated)?|estimate[ds]?)\s*:?\s*\+?(-?[\d.]+)",
    re.I,
)

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

    # --- direction-v2 (issue #11) --------------------------------------------
    # From here on a rule's sign is the headline's sign for the market bucket
    # (`primary`); `sectors` multipliers may be -1, so one headline can be good
    # for shipping and bad for electronics at once.
    "taiwan_strait": {
        "primary": "大盤全體",
        "sectors": {"大盤全體": 1, "金融": 1, "權值股": 1},
        "horizon": "short",
        "rules": [
            *_rules("taiwan_strait", BEAR, "escalate",
                    r"\b(launch|start|begin|stage|hold|conduct)\w*\s.{0,30}\b(military |joint |live-fire )?(drills?|exercises?|blockade)\b",
                    r"\b(blockade|invasion|invade|quarantine)\b",
                    r"\bjoint sword\b|\bstrait thunder\b"),
            *_rules("taiwan_strait", BULL, "deescalate",
                    r"\b(drills?|exercises?)\b.{0,30}\b(end|ended|conclud\w*|over|wrap\w* up)\b",
                    r"\b(resum\w*|restart\w*)\s.{0,20}\b(dialogue|talks)\b.{0,20}\btaiwan\b"),
        ],
    },
    "shipping_lane": {
        "primary": "電子代工",
        "sectors": {"電子代工": 1, "貨櫃航運": -1, "散裝航運": -1, "航空貨運": -1},
        "horizon": "short",
        "rules": [
            *_rules("shipping_lane", BEAR, "disrupt",
                    r"\b(vessel|ship|tanker|carrier|cargo)s?\b.{0,40}\b(struck|hit|attacked|sunk|sank|seized|hijacked|disabled|ablaze|caught fire)\b",
                    r"\b(attack|strike|struck|projectile|drone|mine)\w*\b.{0,40}\b(vessel|ship|tanker|cargo)\w*\b.{0,40}\b(transit|strait|red sea|hormuz|bab|suez)\w*",
                    r"\b(attack|incident)\w*\b.{0,30}\b(tanker|vessel|ship)\b.{0,15}\btransiting\b",
                    r"\b(traffic|transits?|shipping)\b.{0,60}\b(reduced|halted|suspended|disrupted|blocked)\b",
                    r"\b(blockade|closure|closed)\b.{0,30}\b(red sea|bab el|bab al|suez|strait|lane)\b",
                    r"\bfreight rates?\b.{0,20}\b(surge|soar|jump|spike|climb|rise|rising)\w*"),
            *_rules("shipping_lane", BULL, "restore",
                    r"\b(reduce|lower|ease|easing|cut)\w*\s.{0,20}\bfreight rates?\b",
                    r"\bfreight rates?\b.{0,20}\b(fall|fell|drop|slide|slid|eas|declin)\w*",
                    r"\b(reopen|resum|restor)\w*\s.{0,30}\b(traffic|transits?|shipping|navigation|route)\b",
                    r"\b(traffic|transits?|shipping|navigation)\b.{0,20}\b(resumed|restored|reopened|normali[sz]ed)\b"),
        ],
    },
    "hormuz_energy": {
        "primary": "大盤全體",
        "sectors": {"大盤全體": 1, "航運": 1, "油電燃氣": 1, "紡織": 1, "塑化": 0},
        "horizon": "short",
        "rules": [
            *_rules("hormuz_energy", BEAR, "supply_shock",
                    r"\b(crude|oil|brent|wti)\b.{0,60}\bup \$?[\d.]+",
                    r"\b(?<!non-)(oil|crude) prices?\b.{0,30}\b(jump|surge|soar|spike|rall|climb|rise|rose)\w*",
                    r"\b(brent|wti)\b.{0,30}\b(jump|surge|soar|spike|rall|climb|rise|rose)\w*",
                    r"\b(tanker|vessel|ship)s?\b.{0,40}\b(hit|struck|ignit\w*|caught fire|disabled|seized)\b",
                    r"\b(disabl|attack|seiz)\w*\s.{0,40}\b(tankers?|vessels?)\b",
                    r"\bhormuz\b.{0,40}\b(closed|closure|blocked|stay closed|remain closed|will not be reopened|won't reopen)\b",
                    r"\b(closed|close|closure)\b.{0,25}\bto (all )?ships\b",
                    r"\b(opec\+?)\b.{0,30}\b(cut|reduc)\w*\s.{0,15}\b(output|production|supply)\b",
                    r"\b(attack|strike|drone)\w*\b.{0,30}\b(refiner(y|ies)|oil (field|facilit)|pipeline)\b.{0,40}\b(saudi|aramco|jeddah|riyadh|gulf|iraq|kuwait|uae|qatar|iran)\b",
                    r"\b(saudi|aramco|jeddah|riyadh|gulf|iraq|kuwait|uae|qatar|iran)\b.{0,40}\b(attack|strike|drone)\w*\b.{0,30}\b(refiner(y|ies)|oil (field|facilit)|pipeline)\b"),
            *_rules("hormuz_energy", BULL, "supply_relief",
                    r"\b(crude|oil|brent|wti)\b.{0,60}\bdown \$?[\d.]+",
                    r"\b(?<!non-)(oil|crude) (prices?|futures)\b.{0,30}\b(fall|fell|drop|slid|slump|plung|tumbl|declin)\w*",
                    r"\b(brent|wti|crude futures)\b.{0,30}\b(fall|fell|drop|slid|slump|plung|tumbl|declin|down)\w*",
                    r"\b(reopen|resum|restor)\w*\s.{0,30}\b(strait|crude flow|flows?|output|pipeline|exports?)\b",
                    r"\b(opec\+?)\b.{0,30}\b(raise|boost|increas)\w*\s.{0,15}\b(output|production|supply)\b"),
        ],
    },
    "military_conflict": {
        "primary": "大盤全體",
        "sectors": {"大盤全體": 1, "航太國防": -1, "黃金相關": -1, "航運": 0},
        "horizon": "short",
        "rules": [
            *_rules("military_conflict", BEAR, "escalate",
                    r"\b(launch|carr)\w*\s.{0,15}\bstrikes? on\b",
                    r"\b(weigh|plan|consider|prepar|drew plans)\w*\s.{0,25}\b(strikes?|attack|bomb)\w*",
                    r"\b(strikes?|attack|bomb)\w*\s.{0,15}\b(on|against)\s.{0,10}\b(us|u\.s\.|american|iran)\b",
                    r"\bmissiles?\b.{0,40}\btargeting\b",
                    r"\b(reject|rule out|refus)\w*\s.{0,15}\bceasefire\b",
                    r"\bno (forthcoming )?extension of\b.{0,25}\bceasefire\b",
                    r"\bincreased bombing\b"),
            *_rules("military_conflict", BULL, "deescalate",
                    r"\bceasefire\b.{0,25}\b(agreed|reached|extended|signed|holds)\b",
                    r"\b(agree|reach|extend|sign)\w*\s.{0,20}\bceasefire\b",
                    r"\bpeace (deal|agreement)\b.{0,20}\b(signed|reached|agreed)\b"),
        ],
    },
    "ai_capex": {
        "primary": "AI伺服器",
        "sectors": {"AI伺服器": 1, "半導體": 1, "散熱": 1, "PCB": 1, "光通訊": 1},
        "horizon": "long",
        "rules": [
            *_rules("ai_capex", BULL, "demand_up",
                    r"\b(capex|capital expenditure|spending)\b.{0,20}\b(to )?(speed up|accelerat|increas|rise|raise|boost|jump)\w*",
                    r"\b(raise|boost|lift|increas)\w*\s.{0,20}\b(capex|capital expenditure|spending)\b",
                    r"\bdemand\b.{0,20}\b(off the charts|strong|robust|exceed|outstrip|surg)\w*",
                    r"\b(strong|robust|surging)\s.{0,10}\bdemand\b",
                    r"\brevenue\b.{0,40}\bup [\d.]+%",
                    r"\b(beat|top|exceed)\w*\s.{0,20}\b(estimates|expectations|forecast)\b",
                    r"\b(invest|spend)\w*\s.{0,25}\$[\d.]+\s?(b|bn|billion)\b",
                    r"\b(buy|buys|bought|acquir)\w*\s.{0,25}\bdata ?cent(er|re)\b",
                    r"\bexpand\w*\s.{0,15}\bpartnership\b.{0,30}\b(gpu|nvidia|ai)\b"),
            *_rules("ai_capex", BEAR, "demand_down",
                    r"\b(cut|reduc|slash|delay|paus|cancel|scal\w* back)\w*\s.{0,25}\b(capex|capital expenditure|spending|data ?cent\w*|orders?)\b",
                    r"\b(capex|spending|demand|orders?)\b.{0,20}\b(slow|weak|fall|fell|declin|disappoint)\w*",
                    r"\b(miss|missed|below)\b.{0,20}\b(estimates|expectations|forecast)\b",
                    r"\bai bubble\b"),
        ],
    },
    "supply_chain": {
        "primary": "電子零組件",
        "sectors": {"電子零組件": 1, "半導體": 1, "汽車零組件": 1},
        "horizon": "short",
        "rules": [
            *_rules("supply_chain", BEAR, "shortage",
                    r"\b(chip|component|wafer|material)s? shortage\b",
                    r"\bshortage\b.{0,30}\b(halt|stop|cut|suspend)\w*",
                    r"\b(halt|suspend|stop)\w*\s.{0,20}\b(production|output|lines?)\b.{0,30}\b(shortage|chips?)\b",
                    r"\b(ban|halt|suspend|restrict)\w*\s.{0,25}\brare earth\w*\s.{0,10}\bexports?\b"),
            *_rules("supply_chain", BULL, "restore",
                    r"\b(resum|restor|lift|eas)\w*\s.{0,25}\b(rare earth|gallium|germanium)\b.{0,25}\b(exports?|licen[cs]es?|supply|shipments?)\b",
                    r"\b(broaden|expand|deepen)\w*\s.{0,15}\bcommitments?\b.{0,25}\bsupply chain\b",
                    r"\binvest\b.{0,25}\b(tens of billions|\$?[\d.]+\s?(b|bn|billion))\b.{0,30}\bsupply chain\b"),
        ],
    },
    "fx_capital": {
        "primary": "大盤全體",
        "sectors": {"大盤全體": 1, "金融": 1, "壽險": -1, "電子出口股": -1},
        "horizon": "short",
        "rules": [
            *_rules("fx_capital", BEAR, "outflow",
                    r"\bforeign investors?\b.{0,30}\b(net sell\w*|net sold|profit-taking|dumped|outflows?)\b",
                    r"\bforeign net selling\b",
                    r"\btaiwan dollar\b.{0,30}\b(fall|fell|weak\w*|declin\w*|depreciat\w*|slid|slump)\w*",
                    r"\b(dollar index|dxy)\b.{0,20}\b(rise|rose|jump|climb|gain|rall|surge)\w*"),
            *_rules("fx_capital", BULL, "inflow",
                    r"\bforeign investors?\b.{0,30}\b(net bought|net buy\w*|inflows?)\b",
                    r"\btaiwan dollar\b.{0,30}\b(strengthen\w*|ris\w*|rose|gain\w*|appreciat\w*|rall\w*)",
                    r"\b(dollar index|dxy)\b.{0,20}\b(drop|fall|fell|slid|declin|weak)\w*"),
        ],
    },
    "china_macro": {
        "primary": "電子代工",
        "sectors": {"電子代工": 1, "工具機": 1, "水泥": 1, "鋼鐵": 1, "觀光": 1},
        "horizon": "long",
        "rules": [
            *_rules("china_macro", BULL, "upside",
                    r"\b(upgrade|raise|lift)\w*\s.{0,40}\b(gdp|growth)\b.{0,20}\b(forecasts?|outlook)?",
                    r"\b(stimulus|rate cut|cut\w* (reserve requirement|rrr|interest rates?|lpr))\b",
                    r"\b(extend|continu)\w*\s.{0,15}\bsuspension of\s.{0,10}\bexports? controls?\b"),
            *_rules("china_macro", BEAR, "downside",
                    r"\b(downgrade|cut|lower)\w*\s.{0,40}\b(gdp|growth)\b.{0,10}\bforecasts?\b",
                    r"\b(pmi|gdp|retail sales|industrial output|exports)\b.{0,40}\bdown from\b",
                    r"\bdeflation\b|\bproperty (crisis|default)\b"),
        ],
    },
    "us_tech_rally": {
        "primary": "電子權值股",
        "sectors": {"電子權值股": 1, "半導體": 1, "AI伺服器": 1},
        "horizon": "short",
        "rules": [
            *_rules("us_tech_rally", BULL, "rally",
                    r"\b(rall\w*|record|surg\w*|jump\w*|soar\w*|gain\w*|rise|rises|rose|climb\w*)\b",
                    ),
            *_rules("us_tech_rally", BEAR, "selloff",
                    r"\b(declin\w*|drop\w*|tumbl\w*|plung\w*|slump\w*|sell-?off|fall|falls|fell|sink\w*|slid\w*)\b"),
        ],
    },
    "tw_fundamental": {
        "primary": "個股及供應鏈",
        "sectors": {"個股及供應鏈": 1, "半導體": 1, "電子代工": 1},
        "horizon": "long",
        "rules": [
            *_rules("tw_fundamental", BULL, "beat",
                    r"\b(record|all-time) (high|revenue|sales|profit)\b|\b(hits?|at) (a )?record\b",
                    r"\b(raise|lift|boost|upgrade)\w*\s.{0,20}\b(guidance|forecast|outlook|target)\b",
                    r"\boutlook to positive\b",
                    r"\b(commence|start|begin)\w*\s.{0,20}\b(volume |mass )?(shipments?|shipping|production)\b",
                    r"\b(strong|robust)\s.{0,10}\bdemand\b|\bdemand\b.{0,15}\b(strong|robust)\b",
                    r"\b(win|wins|won|secur\w*|land\w*)\s.{0,20}\b(order|contract|deal)s?\b",
                    r"\b(revenue|sales|profit)\b.{0,25}\bup [\d.]+%"),
            *_rules("tw_fundamental", BEAR, "miss",
                    r"\b(cut|lower|slash|downgrade)\w*\s.{0,25}\b(guidance|forecast|outlook|target)\b",
                    r"\boutlook to negative\b",
                    r"\b(revenue|sales|profit)\b.{0,25}\bdown [\d.]+%",
                    r"\b(lose|lost|loses)\s.{0,20}\b(order|contract|customer)s?\b"),
        ],
    },
    "policy_support": {
        "primary": "半導體",
        "sectors": {"半導體": 1, "電子零組件": 1, "綠能": 1},
        "horizon": "long",
        "rules": [
            *_rules("policy_support", BULL, "support",
                    r"\b(finali[sz]e|award|grant|approv|expand|extend)\w*\s.{0,30}\b(chips act|subsid\w*|tax credits?|award|incentives?|tariff exemptions?)\b",
                    r"\b(grant|approv)\w*\s.{0,15}\btariff (exemption|exclusion)\b"),
            *_rules("policy_support", BEAR, "withdraw",
                    r"\b(claw\w* back|revok\w*|cancel\w*|cut\w*|scrap\w*|halt\w*)\s.{0,25}\b(chips act|subsid\w*|tax credits?|awards?|incentives?)\b"),
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
    elif path_id == "shipping_lane":
        if BLACK_SEA.search(text) and not TW_SEA_LANE.search(text):
            return "shipping_lane.gate:not_tw_route"
    elif path_id == "military_conflict":
        if not MAJOR_POWER_CONFLICT.search(text):
            return "military_conflict.gate:regional"
    elif path_id == "fx_capital":
        if not TW_FX_ANCHOR.search(text):
            return "fx_capital.gate:not_twd"
    elif path_id == "us_tech_rally":
        if not MARKET_MOVE_ANCHOR.search(text):
            return "us_tech_rally.gate:not_a_price_move"
    elif path_id == "policy_support":
        if not TECH_POLICY_ANCHOR.search(text):
            return "policy_support.gate:not_tech"
    elif path_id == "china_macro":
        if not re.search(r"china|chinese|pboc|beijing", text, re.I):
            return "china_macro.gate:not_china"
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

    if path_id == "china_macro":
        found = CHINA_PRINT.search(text)
        if found:
            actual, forecast = float(found.group(2)), float(found.group(3))
            if actual != forecast:
                sign = BULL if actual > forecast else BEAR
                verb = "beat" if sign == BULL else "miss"
                return _finish(sign, f"china_macro.print_{verb}:{actual:g} vs {forecast:g}", spec)
            return _finish(NEUTRAL, f"china_macro.print_inline:{actual:g}={forecast:g}", spec)

    if path_id == "fed_rates":
        printed = _inflation_print(text)
        if printed is not None:
            sign, reason = printed
            return _finish(sign, reason, spec)

    if path_id == "us_tech_rally":
        text = OTHER_ASSET_TAIL.sub("", text)
    if path_id == "hormuz_energy":
        settle = SETTLE_MOVE.search(text)
        if settle and float(settle.group(2)) < SETTLE_MIN_PCT:
            return _neutral(f"hormuz_energy.small_move:{settle.group(1)} {settle.group(2)}%", spec)

    hits: list[tuple[int, str]] = []
    for rule in spec["rules"]:
        found = rule.pattern.search(text)
        if not found:
            continue
        clause = _clause(text, found.start(), found.end())
        if HISTORICAL.search(clause):
            continue
        # "stay closed until Tehran's conditions are met" is a status, not a wish.
        if path_id in WISH_PATHS and WISH.search(UNTIL_TAIL.sub("", clause)):
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
    if result.sectors:
        # Keep the chips in step with the rule table, also for events carried
        # over from a snapshot written before a path gained sectors.
        event["sectors"] = list(result.sectors)
    event["impacts"] = [{"sector": name, "direction": value} for name, value in sectors.items()]
    return event
