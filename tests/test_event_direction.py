"""Bull/bear direction model for the pre-market board (issue #9)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job/scripts"))

from event_direction import PATH_RULES, RULE_VERSION, annotate, assess, impact_rows  # noqa: E402
from geo_focus import PATH_ID_BY_LABEL, PATHS, build_focus_events  # noqa: E402

LABELS = json.loads((ROOT / "tests" / "fixtures" / "direction_labels.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 11, 18, 0, 0, tzinfo=timezone.utc)


def test_labelled_set_accuracy_meets_the_issue_bar() -> None:
    rows = LABELS["labels"]
    assert len(rows) >= 200  # issue #11
    assert {row["path"] for row in rows} == set(PATH_RULES)
    assert set(PATH_RULES) == {path["id"] for path in PATHS}
    hits = sum(assess(row["title"], row["path"]).direction == row["expected"] for row in rows)
    assert hits / len(rows) >= 0.80


def test_each_path_meets_the_bar_on_its_own() -> None:
    """A strong path must not hide a weak one inside the overall rate."""
    for path in PATH_RULES:
        rows = [row for row in LABELS["labels"] if row["path"] == path]
        assert len(rows) >= 10, path
        hits = sum(assess(row["title"], path).direction == row["expected"] for row in rows)
        assert hits / len(rows) >= 0.80, path


def test_labelled_set_never_calls_the_opposite_sign() -> None:
    """A miss may fall back to 0; a wrong-way call is the failure that misleads."""
    flipped = [
        row["title"] for row in LABELS["labels"]
        if assess(row["title"], row["path"]).direction * row["expected"] < 0
    ]
    assert flipped == []


def test_issue_example_no_plan_to_push_out_of_supply_chain_is_bullish() -> None:
    title = ("US Under Secretary of State for Economic Affairs Helberg: The US has no plans to "
             "target suppliers such as Ericsson, ASML, Samsung, or SK Hynix or push them out "
             "of its supply chain - Semafor Event.")
    result = assess(title, "export_control")
    assert result.direction == 1
    assert result.sectors["半導體"] == 1
    assert "negated_by" in result.reason


def test_negation_flips_and_is_traceable() -> None:
    assert assess("Fed's Daly: I don't see evidence calling for pre-emptive rate hikes.", "fed_rates").direction == 1
    assert assess("Fed's Hammack: Inflation pressures appear to be broadening.", "fed_rates").direction == -1
    assert assess("Fed's Musalem: There is no inflation pressure coming from the labor market.",
                  "fed_rates").direction == 1


def test_unknown_or_conflicting_stays_neutral() -> None:
    assert assess("Fed's Hammack: The labor market is stable", "fed_rates").reason == "no_rule"
    mixed = assess("Fed's Collins: Higher productivity has helped limit some inflationary pressures.", "fed_rates")
    assert mixed.direction == 0 and mixed.reason.startswith("conflict:")


def test_scope_gates_keep_third_party_news_out_of_the_columns() -> None:
    assert assess("Trump: half of Canada tariffs paused for three days", "tariff").reason == "tariff.gate:third_party"
    assert assess("China and Switzerland Agree on Expanded Free-Trade Deal Removing Tariffs",
                  "tariff").reason == "tariff.gate:no_us_or_taiwan"
    assert assess("Reserve Bank of Australia Deputy Gov Hauser: Inflation Remains Excessively High",
                  "fed_rates").direction == 0
    assert assess("South Korea's foreign ministry: commercial diesel and jet fuel excluded from export "
                  "controls to Russia", "export_control").reason == "export_control.gate:not_chip"


def test_us_inflation_print_is_read_against_forecast() -> None:
    assert assess("US Core PCE Prices Advance Actual 2.5% (Forecast 2.4%, Previous 3.3%)", "fed_rates").direction == -1
    assert assess("US PPI MoM Actual 0% (Forecast 0.2%, Previous -0.3%)", "fed_rates").direction == 1
    assert assess("US CPI MoM Actual 0.1% (Forecast 0.1%, Previous -0.4%)", "fed_rates").direction == 0


def test_direction_is_per_sector_not_per_event() -> None:
    result = assess("Barclays and SocGen forecast Fed rate hikes in September and December.", "fed_rates")
    assert result.sectors == {"科技股全體": -1, "金融": 0, "壽險": 0}


def test_unknown_path_is_neutral() -> None:
    result = assess("Anything", "not_a_path")
    assert (result.direction, result.reason) == (0, "path_not_modelled")


def test_a_threat_is_not_a_closure() -> None:
    assert assess("Iran threatens to close the Strait of Hormuz", "hormuz_energy").direction == 0


def test_one_headline_can_split_sectors_the_issue_example() -> None:
    """Issue #11: lane blocked -> shipping +1, electronics contract makers -1."""
    result = assess("Iran's revolutionary guards: A container ship sunk in the south of the Strait of "
                    "Hormuz after hitting a naval mine - State media", "shipping_lane")
    assert result.direction == -1
    assert result.sectors["貨櫃航運"] == 1
    assert result.sectors["電子代工"] == -1


def test_positive_paths_fill_the_bull_column() -> None:
    assert assess("Chip Rally Drives Nasdaq 100 to Record as Oil Falls – US Market Wrap",
                  "us_tech_rally").direction == 1
    assert assess("Nvidia's Huang: Neocloud demand is ‘off the charts' - CNBC $NVDA", "ai_capex").direction == 1
    assert assess("Moody's ratings affirms TSMC's AA3 ratings; changes outlook to positive.",
                  "tw_fundamental").direction == 1
    assert assess("China general manufacturing PMI at 52.0 in October vs forecast 51.6",
                  "china_macro").direction == 1
    assert assess("Brent and US crude futures down over 1% after Kyodo reports that Iran offered to "
                  "reopen the strait within 7 days", "hormuz_energy").direction == 1


def test_v2_noise_stays_neutral() -> None:
    assert assess("Russian air strikes kill two in Ukraine's Kyiv: authorities",
                  "military_conflict").reason == "military_conflict.gate:regional"
    assert assess("Russian forces strike Ukrainian cargo ship and tanker in Black Sea and Ukraine port: IFX",
                  "shipping_lane").reason == "shipping_lane.gate:not_tw_route"
    assert assess("Brent Crude futures settle at $95.84/bbl, up 2 cents, 0.02%.",
                  "hormuz_energy").reason.startswith("hormuz_energy.small_move")
    assert assess("Qatar: Want an agreement to reopen the Strait of Hormuz and establish a ceasefire "
                  "simultaneously. - IRNA", "hormuz_energy").direction == 0
    assert assess("New Zealand dollar rises 0.60% to $0.5656", "fx_capital").reason == "fx_capital.gate:not_twd"


def test_negated_attack_plan_is_bullish() -> None:
    result = assess("US has no immediate plan to attack Iran, Trump tells FT", "military_conflict")
    assert result.direction == 1 and "negated_by" in result.reason


def test_focus_events_carry_direction_fields() -> None:
    entries = [{"title": "Fed's Logan: It is clear that Fed needs at least two more "
                         "quarter-percentage-point rate increases.",
                "link": "https://example.test/a", "published_at": NOW - timedelta(minutes=20)}]
    event = build_focus_events(entries, {}, now=NOW)[0]
    assert event["pathId"] == "fed_rates"
    assert event["direction"] == -1
    assert event["horizon"] == "short"
    assert event["directionReason"].startswith("fed_rates.hike")
    assert {"sector": "科技股全體", "direction": -1} in event["impacts"]


def test_old_payload_rows_are_reannotated_from_their_label() -> None:
    legacy = {"id": "x", "titleEn": "Trump administration weighing fresh broad tariffs on semiconductors",
              "pathLabel": "關稅/貿易", "sectors": ["電子代工"], "score": 0.5}
    annotate(legacy, PATH_ID_BY_LABEL[legacy["pathLabel"]])
    assert legacy["pathId"] == "tariff" and legacy["direction"] == -1


def test_impact_rows_match_the_event_impact_table() -> None:
    event = annotate({"id": "financialjuice-abc", "score": 1.4, "pathLabel": "出口管制/科技戰",
                      "titleEn": "EU set to lift sanction on Chinese firm to save ASML supplier.",
                      "sectors": []}, "export_control")
    rows = impact_rows(event)
    assert {row["target_id"] for row in rows} == {"半導體", "AI伺服器", "IC設計", "電子零組件"}
    for row in rows:
        assert row["target_type"] == "sector"
        assert row["rule_version"] == RULE_VERSION
        assert row["direction"] in (-1, 0, 1)
        assert 0 <= row["magnitude"] <= 1
        assert row["horizon"] in ("short", "long")
        assert row["reason"]


def test_page_renders_bull_and_bear_columns_and_keeps_neutral_in_full_list() -> None:
    """The feed must surface bullish news as readily as bearish (sentiment skew
    fix) and keep neutral events reachable in the full list."""
    feed = (ROOT / "front/src" / "lib" / "feed.ts").read_text(encoding="utf-8")
    home = (ROOT / "front/src" / "components" / "home" / "ThemeRadarHome.tsx").read_text(encoding="utf-8")
    assert "{ id: 'bull', label: '利多' }" in feed
    assert "{ id: 'bear', label: '利空' }" in feed
    assert "完整清單" in home
    assert "（含中性）" in home
