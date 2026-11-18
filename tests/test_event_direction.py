"""Bull/bear direction model for the pre-market board (issue #9)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from event_direction import RULE_VERSION, annotate, assess, impact_rows  # noqa: E402
from geo_focus import PATH_ID_BY_LABEL, build_focus_events  # noqa: E402

LABELS = json.loads((ROOT / "tests" / "fixtures" / "direction_labels.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 11, 18, 0, 0, tzinfo=timezone.utc)


def test_labelled_set_accuracy_meets_the_issue_bar() -> None:
    rows = LABELS["labels"]
    assert len(rows) >= 60
    assert {row["path"] for row in rows} == {"fed_rates", "tariff", "export_control"}
    hits = sum(assess(row["title"], row["path"]).direction == row["expected"] for row in rows)
    assert hits / len(rows) >= 0.80


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


def test_unmodelled_paths_are_neutral_until_issue_11() -> None:
    result = assess("Iran threatens to close the Strait of Hormuz", "hormuz_energy")
    assert (result.direction, result.reason) == (0, "path_not_modelled")


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
    component = (ROOT / "src" / "components" / "home" / "PreMarketFocus.tsx").read_text(encoding="utf-8")
    assert '<DirectionColumn side="bull"' in component
    assert '<DirectionColumn side="bear"' in component
    assert "完整清單" in component
    assert "顯示一般新聞" in component
