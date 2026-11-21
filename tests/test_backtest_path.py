"""Single-path backtest: event -> T+k sector excess return and foreign flow (issue #12)."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job/scripts"))

import backtest_path as bt  # noqa: E402
import sector_history as sh  # noqa: E402

HAWK = "Fed's Logan: It is clear that Fed needs at least two more quarter-percentage-point rate increases."
DOVE = "Fed's Daly: I don't see evidence calling for pre-emptive rate hikes."
DAYS = ["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-16", "2026-11-17", "2026-11-18"]


def history(electronics: list[float], taiex: list[float], foreign: list[float] | None = None) -> dict:
    out = sh.load_history(Path("/nonexistent"))
    for day, e, t in zip(DAYS, electronics, taiex):
        out["indices"][day] = {"電子工業": e, sh.TAIEX_KEY: t, "金融保險": 0.1}
    for day, net in zip(DAYS, foreign or []):
        out["foreign_net"][day] = {"半導體業": net, "金融保險": 5.0}
    return out


def event(title: str, stamp: str, path: str = "fed_rates") -> dict:
    return {"id": f"e-{stamp}", "titleEn": title, "publishedAt": stamp, "pathId": path}


def test_base_close_is_the_last_close_the_event_could_not_move() -> None:
    taipei = bt.TAIPEI
    # 10:00 Taipei on 11-12 (market open) -> base = 11-11 close
    assert DAYS[bt.base_index(DAYS, datetime(2026, 11, 12, 10, 0, tzinfo=taipei))] == "2026-11-11"
    # 14:00 Taipei on 11-12 (after the close) -> base = 11-12
    assert DAYS[bt.base_index(DAYS, datetime(2026, 11, 12, 14, 0, tzinfo=taipei))] == "2026-11-12"
    # Saturday -> the Friday close
    assert DAYS[bt.base_index(DAYS, datetime(2026, 11, 14, 9, 0, tzinfo=taipei))] == "2026-11-13"
    assert bt.base_index(DAYS, datetime(2026, 11, 1, tzinfo=taipei)) is None


def test_excess_return_and_foreign_flow_are_measured_after_the_base() -> None:
    hist = history([1.0, -2.0, 3.0, 1.0, 1.0, 1.0, 1.0], [0.5, -1.0, 1.0, 0.0, 0.0, 0.0, 0.0],
                   [100, -300, 50, 20, 10, 0, 0])
    # US evening of 11-10 = 11-11 morning Taipei, before the open -> base 11-10
    hawk = event(HAWK, "2026-11-10T22:00:00+00:00")
    rows, _ = bt.build_outcomes([hawk], hist, ["fed_rates"])
    assert len(rows) == 1  # 金融/壽險 multipliers are 0 on fed_rates -> not called
    row = rows[0]
    assert (row["target_id"], row["base_date"], row["direction"]) == ("科技股全體", "2026-11-10", -1)
    assert row["excess_t1"] == round(-2.0 - -1.0, 3)  # electronics -2% vs TAIEX -1%
    assert row["foreign_t1"] == -300
    assert row["foreign_t3"] == -300 + 50 + 20
    expected_t5 = bt.compound([-2.0, 3.0, 1.0, 1.0, 1.0]) - bt.compound([-1.0, 1.0, 0.0, 0.0, 0.0])
    assert row["excess_t5"] == round(expected_t5, 3)


def test_missing_days_leave_the_metric_empty_rather_than_guessed() -> None:
    hist = history([1.0] * 7, [0.0] * 7)  # no foreign data at all
    late = event(HAWK, "2026-11-18T07:00:00+00:00")  # 15:00 Taipei on the last day: no T+1 yet
    rows, _ = bt.build_outcomes([late], hist, ["fed_rates"])
    assert rows[0]["excess_t1"] is None and rows[0]["foreign_t1"] is None


def test_hit_rate_counts_same_sign_and_neutral_events_are_skipped() -> None:
    hist = history([-1.0, -1.0, 2.0, 1.0, 1.0, 1.0, 1.0], [0.0] * 7, [0, -10, 10, 5, 5, 5, 5])
    events = [
        event(HAWK, "2026-11-10T22:00:00+00:00"),  # bear; T+1 excess -1 -> hit
        event(DOVE, "2026-11-11T22:00:00+00:00"),  # bull; T+1 excess +2 -> hit
        event(HAWK, "2026-11-12T22:00:00+00:00"),  # bear; T+1 excess +1 -> miss
        event("Fed's Hammack: The labor market is stable", "2026-11-12T22:00:00+00:00"),  # neutral
    ]
    rows, _ = bt.build_outcomes(events, hist, ["fed_rates"])
    summary = {(r["metric"], r["horizon_days"]): r for r in bt.summarise(rows)}
    t1 = summary[("excess_return", 1)]
    assert (t1["sample_size"], t1["hit_rate"], t1["bull"], t1["bear"]) == (3, round(2 / 3, 4), 1, 2)
    assert t1["avg_signed_value"] == round((1 + 2 - 1) / 3, 3)
    assert summary[("foreign_net", 1)]["sample_size"] == 3


def test_logic_is_path_agnostic_and_unmapped_sectors_are_reported() -> None:
    hist = history([0.0] * 7, [1.0] * 7)
    strike = event("Iran's Fars News Agency: IRGC launched strikes on US base in Bahrain in retaliation "
                   "for 'hostile' US actions", "2026-11-12T22:00:00+00:00", "military_conflict")
    rows, unmapped = bt.build_outcomes([strike], hist, ["military_conflict"])
    assert [r["target_id"] for r in rows] == ["大盤全體"]
    assert rows[0]["direction"] == -1
    # 大盤全體 is scored on the TAIEX itself, not on an always-zero excess
    assert rows[0]["excess_t1"] == 1.0
    assert unmapped["military_conflict"] == {"航太國防", "黃金相關"}
    assert all(t in bt.SECTOR_TARGETS for rule in bt.PATH_RULES.values()
               for t, m in rule["sectors"].items() if m and t not in {"黃金相關", "航太國防"})


def test_attach_backtest_puts_hit_rate_and_t1_flow_on_cards() -> None:
    hist = history([-1.0] * 7, [0.0] * 7, [-50] * 7)
    events = [event(HAWK, f"2026-11-1{i}T22:00:00+00:00") for i in range(0, 6)]
    result = bt.build_result(events, hist, ["fed_rates"], datetime(2026, 11, 19, tzinfo=timezone.utc))
    badge = result["badges"]["fed_rates"]
    assert badge["target"] == "科技股全體" and badge["n"] >= bt.MIN_SAMPLE and badge["hitRate"] == 1.0
    cards = [{"titleEn": HAWK, "pathId": "fed_rates"}, {"titleEn": "x", "pathId": "tariff", "flowAfter": {}}]
    assert bt.attach_backtest(cards, result) == 1
    assert cards[0]["pathBacktest"]["hitRate"] == 1.0
    assert cards[0]["flowAfter"]["foreignT1"] == -50
    assert "flowAfter" not in cards[1] and "pathBacktest" not in cards[1]  # stale values cleared


def test_event_history_merge_dedupes_by_title() -> None:
    first = bt.merge_event_history({}, [event(HAWK, "2026-11-10T22:00:00+00:00")])
    again = bt.merge_event_history(first, [event(f"  {HAWK} ", "2026-11-12T22:00:00+00:00"),
                                           {"titleEn": "no path", "publishedAt": "2026-11-12"}])
    assert again["added"] == 0 and len(again["events"]) == 1
    assert again["events"][0]["publishedAt"] == "2026-11-10T22:00:00+00:00"


def test_mi_index_parser_keeps_composites_and_reads_the_sign_from_colour() -> None:
    payload = {"stat": "OK", "tables": [{
        "fields": ["指數", "收盤指數", "漲跌(+/-)", "漲跌點數", "漲跌百分比(%)", "特殊處理註記"],
        "data": [["發行量加權股價指數", "40,194.91", "<p style='color:red'>+</p>", "102.80", "0.26", ""],
                 ["電子工業類指數", "2,465.47", "<p style='color:red'>+</p>", "21.45", "0.88", ""],
                 ["航運類指數", "200.00", "<p style='color:green'>-</p>", "3.00", "1.48", ""],
                 ["未含電子指數", "1", "+", "1", "1.90", ""]]}]}
    assert sh.parse_index_changes(payload) == {sh.TAIEX_KEY: 0.26, "電子工業": 0.88, "航運": -1.48}
    assert sh.parse_index_changes({"stat": "很抱歉，沒有符合條件的資料!"}) == {}


def test_holidays_are_remembered_and_today_is_retried() -> None:
    hist = sh.load_history(Path("/nonexistent"))
    calls = []

    def get(url, params):
        calls.append(params["date"])
        return {"stat": "no data"}

    days = sh.pending_index_days(hist, date(2026, 11, 13), date(2026, 11, 16), after_close=True)
    assert days == [date(2026, 11, 13), date(2026, 11, 16)]
    sh.update_indices(hist, get, days, pause_seconds=0, today=date(2026, 11, 16))
    assert hist["closed"] == ["2026-11-13"]
    assert sh.pending_index_days(hist, date(2026, 11, 13), date(2026, 11, 16), after_close=True) == [date(2026, 11, 16)]
    assert sh.pending_index_days(hist, date(2026, 11, 13), date(2026, 11, 16), after_close=False) == []


def test_sector_foreign_sums_skip_partial_days(tmp_path) -> None:
    registry = {}
    for i in range(20):
        symbol = f"{2300 + i}"
        registry[symbol] = "半導體業"
        series = [["2026-11-12", 1000, 0, 0, 1000]]
        if i < 5:
            series.append(["2026-11-11", 9999000, 0, 0, 0])  # only a quarter of the market reported
        (tmp_path / f"TWSE-{symbol}.json").write_text(json.dumps({
            "symbol": symbol, "fields": ["date", "foreign_net", "trust_net", "dealer_net", "total_net"],
            "series": series}), encoding="utf-8")
    sums = sh.sum_foreign_by_industry(tmp_path, registry)
    assert sums == {"2026-11-12": {"半導體業": 20.0}}


def test_db_write_is_one_transaction_with_both_tables() -> None:
    hist = history([-1.0] * 7, [0.0] * 7, [-50] * 7)
    result = bt.build_result([event(HAWK, "2026-11-10T22:00:00+00:00")], hist, ["fed_rates"],
                             datetime(2026, 11, 19, tzinfo=timezone.utc))
    executed = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def executemany(self, sql, rows):
            executed.append((sql.split()[2], list(rows)))

    class Tx(Cursor):
        pass

    class Connection:
        def transaction(self):
            return Tx()

        def cursor(self):
            return Cursor()

    counts = bt.write_backtest(Connection(), result)
    assert [name for name, _ in executed] == ["radar.path_backtest", "radar.event_outcome"]
    assert counts["outcome_rows"] == 1
    summary_row = executed[0][1][0]
    assert summary_row["rule_version"] == bt.RULE_VERSION and 0 <= summary_row["hit_rate"] <= 1
    migration = (ROOT / "db/supabase" / "migrations" / "20261119090000_create_radar_path_backtest.sql").read_text()
    for column in ("hit_rate", "avg_signed_value", "trading_days", "foreign_t1", "excess_t5"):
        assert column in migration
