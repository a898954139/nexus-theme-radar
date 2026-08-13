"""Rules that decide what the pre-market board publishes.

The scoring axes and the sector aggregation each already produced a wrong-but-
plausible board during development -- commentary outranking a chokepoint
closure, and a theme taxonomy inflating every sector at once. Those are pinned
here because both failures render as a normal-looking page.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from geo_focus import (  # noqa: E402
    build_focus_events,
    classify_act,
    is_noise,
    match_paths,
    tier_of,
    weigh_speaker,
)
from market_pulse import SECTOR_NAMES, build_pulse, build_sector_board  # noqa: E402
from sector_flows import aggregate_sectors, build_flow_panels  # noqa: E402
from update_pre_market import merge_events  # noqa: E402

NOW = datetime(2026, 8, 12, 0, 0, tzinfo=timezone.utc)


def entry(title: str, minutes_ago: int = 30, link: str = "https://example.test/a"):
    return {
        "title": title,
        "link": link,
        "published_at": NOW - timedelta(minutes=minutes_ago),
    }


class TestTransmissionPaths:
    def test_chokepoint_attack_is_routed_to_shipping(self):
        """A Red Sea attack must reach shipping.

        This exact headline scored near zero once because only Hormuz was in
        the table, sinking a real attack on shipping below Fed commentary.
        """
        paths = match_paths(
            "Houthis attack deck cargo ship in Bab al-Mandab, killing three"
        )
        assert "shipping_lane" in {p["id"] for p in paths}

    def test_export_control_outranks_china_macro(self):
        weights = {p["id"]: p["weight"] for p in ()} or {
            p["id"]: p["weight"] for p in match_paths("chip export control on China")
        }
        assert weights["export_control"] == pytest.approx(1.0)

    def test_unrelated_headline_matches_nothing(self):
        assert match_paths("Local football club signs new midfielder") == []


class TestActType:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Iran will close the strait if attacked", "threat"),
            ("Fed's Venable: Job market appears broadly stable.", "opinion"),
            ("US announces sanctions on shipping firm", "decision"),
        ],
    )
    def test_classification(self, title, expected):
        assert classify_act(title)[0] == expected

    def test_opinion_is_damped_far_below_action(self):
        """Commentary must not compete with events on the same path."""
        assert classify_act("Fed's Goolsbee says rates look fine")[1] <= 0.4
        assert classify_act("US imposes new tariff")[1] == pytest.approx(1.0)


class TestSpeakerWeight:
    def test_regional_fed_ranks_below_principal(self):
        regional, _ = weigh_speaker("Atlanta Fed's Venable: Inflation is too high")
        principal, _ = weigh_speaker("Powell: We will hold rates")
        assert regional < principal

    def test_wire_event_without_speaker_is_not_penalised(self):
        """Unattributed wire copy describing an attack is reporting, not noise."""
        weight, label = weigh_speaker("Houthis attack cargo ship, killing three")
        assert weight >= 0.9
        assert label == "事件報導"


class TestNoiseFilter:
    @pytest.mark.parametrize(
        "title",
        ["US CPI Cribsheet - FJElite", "US Inflation Tracker - FJElite",
         "US to sell $110 bln 4-Week bills on August 13th"],
    )
    def test_sponsored_and_auction_notices_are_dropped(self, title):
        assert is_noise(title)

    def test_real_headline_survives(self):
        assert not is_noise("IRGC: energy pipelines will be at risk")


class TestFocusRanking:
    def test_repeated_commentary_folds_into_one_event(self):
        """One speaker restating a view is one story, not five."""
        entries = [
            entry("Fed's Venable: Inflation is too high"),
            entry("Atlanta Fed's Venable: Job market appears stable"),
            entry("Fed's Venable: Price pressures may resume"),
        ]
        events = build_focus_events(entries, {}, now=NOW)
        assert len(events) == 1
        assert len(events[0]["related"]) == 2

    def test_event_outranks_commentary(self):
        entries = [
            entry("Fed's Venable: Job market appears broadly stable"),
            entry("Strait of Hormuz will not be reopened until conditions are met"),
        ]
        events = build_focus_events(entries, {}, now=NOW)
        assert events[0]["pathLabel"] == "能源/荷姆茲"

    def test_translation_is_used_when_cached(self):
        title = "Strait of Hormuz will not be reopened"
        events = build_focus_events([entry(title)], {title: "霍爾木茲海峽不會重開"}, now=NOW)
        assert events[0]["titleZh"] == "霍爾木茲海峽不會重開"
        assert events[0]["titleEn"] == title

    def test_payload_carries_every_field_the_page_reads(self):
        events = build_focus_events([entry("US imposes chip export control")], {}, now=NOW)
        required = {"id", "tier", "actLabel", "speaker", "titleZh", "titleEn",
                    "channel", "sectors", "url", "related"}
        assert required <= set(events[0])

    def test_stale_headline_decays_below_fresh_one(self):
        fresh = build_focus_events([entry("US imposes chip export control", 30)], {}, now=NOW)
        stale = build_focus_events(
            [entry("US imposes chip export control", 60 * 40)], {}, now=NOW
        )
        assert stale[0]["score"] < fresh[0]["score"]


class TestTiers:
    def test_thresholds_are_ordered(self):
        assert tier_of(0.9) == "critical"
        assert tier_of(0.45) == "watch"
        assert tier_of(0.1) == "normal"


class TestWindow:
    def test_events_outside_window_are_expired_not_kept(self):
        old = {"titleEn": "old", "id": "a",
               "publishedAt": (NOW - timedelta(hours=100)).isoformat()}
        new = {"titleEn": "new", "id": "b",
               "publishedAt": (NOW - timedelta(hours=1)).isoformat()}
        kept, expired = merge_events([old], [new], NOW)
        assert [e["id"] for e in kept] == ["b"]
        assert [e["id"] for e in expired] == ["a"]

    def test_fresh_score_replaces_previous_for_same_headline(self):
        stamp = (NOW - timedelta(hours=1)).isoformat()
        previous = [{"titleEn": "x", "id": "a", "score": 0.9, "publishedAt": stamp}]
        fresh = [{"titleEn": "x", "id": "a", "score": 0.4, "publishedAt": stamp}]
        kept, _ = merge_events(previous, fresh, NOW)
        assert len(kept) == 1 and kept[0]["score"] == 0.4


class TestSectorBoard:
    def test_change_is_computed_against_previous_close(self):
        quotes = [{"id": "^024", "close": 110.0, "previousClose": 100.0}]
        assert build_sector_board(quotes, ["^024"]) == [{"name": "半導體", "chg": 10.0}]

    def test_rows_are_sorted_descending(self):
        quotes = [
            {"id": "^024", "close": 101.0, "previousClose": 100.0},
            {"id": "^033", "close": 105.0, "previousClose": 100.0},
        ]
        rows = build_sector_board(quotes, ["^024", "^033"])
        assert [r["chg"] for r in rows] == [5.0, 1.0]

    def test_zero_previous_close_is_skipped_not_divided(self):
        assert build_sector_board([{"id": "^024", "close": 5.0, "previousClose": 0}],
                                  ["^024"]) == []

    def test_sector_codes_map_to_verified_names(self):
        """Codes were once guessed from ranges and were wrong in a way that
        renders as a correct-looking chart."""
        assert SECTOR_NAMES["^024"] == "半導體"
        assert SECTOR_NAMES["^033"] == "航運"
        assert SECTOR_NAMES["^035"] == "金融"


class TestSectorFlows:
    def test_symbol_counts_once_into_its_official_industry(self):
        """The supply-chain taxonomy is multi-membership; using it here would
        credit one symbol's flow to dozens of sectors."""
        shards = [{
            "symbol": "2330",
            "fields": ["date", "foreign_net", "trust_net", "dealer_net", "total_net"],
            "series": [["2026-08-10", 1000, 0, 0, 1000]],
        }]
        as_of, totals = aggregate_sectors(shards, {"2330": "半導體業"})
        assert as_of == "2026-08-10"
        assert totals == {"半導體業": {"foreign_net": 1000, "trust_net": 0,
                                       "dealer_net": 0, "total_net": 1000}}

    def test_symbol_without_industry_is_skipped(self):
        shards = [{"symbol": "0050", "fields": ["date", "foreign_net"],
                   "series": [["2026-08-10", 999]]}]
        _, totals = aggregate_sectors(shards, {})
        assert totals == {}

    def test_only_the_latest_session_is_aggregated(self):
        shards = [
            {"symbol": "A", "fields": ["date", "foreign_net"],
             "series": [["2026-08-10", 100]]},
            {"symbol": "B", "fields": ["date", "foreign_net"],
             "series": [["2026-08-08", 500]]},
        ]
        as_of, totals = aggregate_sectors(shards, {"A": "半導體業", "B": "航運業"})
        assert as_of == "2026-08-10"
        assert "航運業" not in totals

    def test_panels_split_buy_and_sell_by_investor_type(self):
        totals = {
            "半導體業": {"foreign_net": 5_000_000, "trust_net": -2_000_000, "dealer_net": 0},
            "航運業": {"foreign_net": -3_000_000, "trust_net": 1_000_000, "dealer_net": 0},
        }
        panels = build_flow_panels(totals)
        assert [p["id"] for p in panels] == ["foreign", "trust", "dealer"]
        foreign = panels[0]
        assert foreign["buy"][0]["name"] == "半導體業"
        assert foreign["sell"][0]["name"] == "航運業"
        assert foreign["sell"][0]["value"] < 0

    def test_values_are_lots_not_raw_shares(self):
        """Upstream publishes shares; the page labels 張."""
        totals = {"半導體業": {"foreign_net": 1_000_000}}
        panel = build_flow_panels(totals)[0]
        assert panel["unit"] == "張"
        assert panel["buy"][0]["value"] == 1000


class TestMarketPulse:
    def test_row_carries_the_fields_the_ticker_reads(self):
        rows = build_pulse(
            [{"id": "DJI", "close": 53770.27, "previousClose": 53791.85}],
            symbols=[("DJI", "道瓊", 2)],
        )
        assert rows == [{
            "id": "DJI", "label": "道瓊", "value": "53,770.27",
            "delta": "-0.04%", "up": False,
            # Seeded from previousClose when no OHLC is supplied.
            "series": [53791.85, 53770.27],
        }]

    def test_series_accumulates_across_runs(self):
        """The feed publishes a quote, not a history; sparkline points are
        carried forward run to run."""
        previous = [{"id": "DJI", "series": [1.0, 2.0]}]
        rows = build_pulse(
            [{"id": "DJI", "close": 3.0, "previousClose": 2.0}],
            previous, symbols=[("DJI", "道瓊", 2)],
        )
        assert rows[0]["series"] == [1.0, 2.0, 3.0]

    def test_series_is_capped_to_the_window(self):
        previous = [{"id": "DJI", "series": [1, 2, 3, 4, 5, 6, 7, 8]}]
        rows = build_pulse(
            [{"id": "DJI", "close": 9.0, "previousClose": 8.0}],
            previous, symbols=[("DJI", "道瓊", 2)], points=8,
        )
        assert rows[0]["series"] == [2, 3, 4, 5, 6, 7, 8, 9.0]

    def test_missing_symbol_keeps_last_good_row(self):
        """One absent symbol must not blank the whole bar."""
        previous = [{"id": "DJI", "label": "道瓊", "value": "1", "delta": "+0.00%",
                     "up": True, "series": [1.0]}]
        rows = build_pulse([], previous, symbols=[("DJI", "道瓊", 2)])
        assert rows == previous

    def test_missing_symbol_without_history_is_dropped(self):
        assert build_pulse([], symbols=[("DJI", "道瓊", 2)]) == []


class TestPulseSeedsFromSession:
    def test_first_run_seeds_a_shape_from_todays_ohlc(self):
        """Accumulating one point per run would draw a flat line for days after
        a deploy; the session's own path is real and available immediately."""
        rows = build_pulse(
            [{"id": "DJI", "close": 53770.27, "previousClose": 53791.85,
              "open": 53797.47, "low": 53731.96, "high": 53969.36}],
            symbols=[("DJI", "道瓊", 2)],
        )
        assert rows[0]["series"] == [53791.85, 53797.47, 53969.36, 53731.96, 53770.27]

    def test_seed_only_applies_when_no_history_exists(self):
        previous = [{"id": "DJI", "series": [1.0, 2.0]}]
        rows = build_pulse(
            [{"id": "DJI", "close": 3.0, "previousClose": 2.0,
              "open": 9.9, "low": 9.8, "high": 9.7}],
            previous, symbols=[("DJI", "道瓊", 2)],
        )
        assert rows[0]["series"] == [1.0, 2.0, 3.0]

    def test_partial_ohlc_still_yields_a_series(self):
        rows = build_pulse(
            [{"id": "DJI", "close": 10.0, "previousClose": 9.0}],
            symbols=[("DJI", "道瓊", 2)],
        )
        assert rows[0]["series"] == [9.0, 10.0]


def test_pre_market_flow_styles_do_not_collide_with_the_flows_page() -> None:
    """`.flow-board` belongs to the standalone 資金流向 page. Redefining it for
    the homepage board silently rewrote that page's layout."""
    css = (ROOT / "src" / "index.css").read_text(encoding="utf-8")
    component = (ROOT / "src" / "components" / "home" / "PreMarketFocus.tsx").read_text(encoding="utf-8")
    board = css[css.index("/* ---------- 類股買賣超 ---------- */"):]
    for shared in (".flow-board {", ".flow-row {", ".flow-rank {", ".flow-value {"):
        assert shared not in board, f"{shared} would override the flows page"
    assert 'className="pm-flow-board"' in component


def test_calm_state_copy_does_not_claim_a_daily_reset() -> None:
    """The board refreshes hourly over a rolling 72h window, so wording that
    implies a per-day digest would misdescribe when it changes."""
    component = (ROOT / "src" / "components" / "home" / "PreMarketFocus.tsx").read_text(encoding="utf-8")
    assert "今日盤前無重大事件" not in component
    assert "目前無重大事件" in component


def test_sparkline_can_shrink_so_it_cannot_overflow_its_card() -> None:
    """A fixed-width spark beside a fixed-width price overflowed the card on
    long values, painting the line past the card edge."""
    css = (ROOT / "src" / "index.css").read_text(encoding="utf-8")
    rule = css[css.index(".pulse-spark {"):css.index("}", css.index(".pulse-spark {"))]
    assert "flex: 1 1 auto" in rule
    assert "overflow: hidden" in rule
