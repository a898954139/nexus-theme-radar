"""Contract tests for the Goodinfo quarterly fundamentals adapter.

The emitted payload is consumed verbatim by the downstream Hermes producer as
``fundamental_context``. Every expectation below is pinned against real captured
Goodinfo HTML (``tests/fixtures/goodinfo``) and against the hand-verified values
that were used when the nexus-market-analysis-v2 skill was validated on 2344.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from scripts.goodinfo_fundamentals import (
    GoodinfoUnavailable,
    build_fundamental_context,
    client_key_for,
    fetch_symbol_fundamentals,
    parse_financial_table,
    sanity_check,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "goodinfo"
ANCHOR = datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc)


def _fixture(symbol: str, report: str) -> str:
    return (FIXTURE_DIR / f"{symbol}_{report}.html").read_text(encoding="utf-8")


def _fake_session(pages: dict[str, str], *, fail_on: set[str] | None = None):
    """Session double mirroring the requests surface used by the adapter."""

    fail_on = fail_on or set()
    calls: list[str] = []

    class Response:
        def __init__(self, report: str) -> None:
            self.report = report
            self.headers: dict[str, str] = {}
            self.encoding = "utf-8"
            self.text = pages.get(report, "")

        def raise_for_status(self) -> None:
            if self.report in fail_on:
                raise requests.HTTPError("503 fixture")

        def close(self) -> None:
            return None

    class Session:
        def get(self, url: str, **_kwargs):
            report = url.split("RPT_CAT=", 1)[1].split("&", 1)[0]
            calls.append(report)
            return Response(report)

    return Session(), calls


# ─── parsing ────────────────────────────────────────────────────────────────


def test_parses_quarterly_income_statement_from_real_html() -> None:
    rows = parse_financial_table(_fixture("2344", "IS_QUAR"))

    assert rows["periods"][:3] == ["2026Q1", "2025Q4", "2025Q3"]
    assert rows["metrics"]["營業收入"]["2026Q1"] == pytest.approx(382.5)
    assert rows["metrics"]["營業收入"]["2025Q4"] == pytest.approx(266.3)


def test_parses_balance_sheet_and_cash_flow_from_real_html() -> None:
    balance = parse_financial_table(_fixture("2344", "BS_QUAR"))
    cash_flow = parse_financial_table(_fixture("2344", "CF_QUAR"))

    assert balance["metrics"]["現金及約當現金"]["2026Q1"] == pytest.approx(255.2)
    # Thousands separators in the source HTML must survive parsing.
    assert balance["metrics"]["流動資產合計"]["2026Q1"] == pytest.approx(1106.0)
    assert cash_flow["metrics"]["營業活動之淨現金流入(出)"]["2026Q1"] == pytest.approx(123.7)


# ─── contract shape ─────────────────────────────────────────────────────────


def test_context_matches_hand_verified_skill_input_for_2344() -> None:
    """These exact values were fed to the v2 skill during validation."""

    context = build_fundamental_context(
        symbol="2344",
        income=parse_financial_table(_fixture("2344", "IS_QUAR")),
        balance=parse_financial_table(_fixture("2344", "BS_QUAR")),
        cash_flow=parse_financial_table(_fixture("2344", "CF_QUAR")),
        fetched_at=ANCHOR,
    )

    newest = context["quarters"][0]
    assert newest["period"] == "2026Q1"
    assert newest["revenue"] == pytest.approx(382.5)
    assert newest["gross_margin"] == pytest.approx(0.534, abs=1e-3)
    assert newest["operating_margin"] == pytest.approx(0.328, abs=1e-3)
    assert newest["net_margin"] == pytest.approx(0.264, abs=1e-3)
    assert newest["eps"] == pytest.approx(2.25)

    assert context["health"]["cash"] == pytest.approx(255.2)
    assert context["health"]["current_ratio"] == pytest.approx(1.47, abs=1e-2)
    assert context["health"]["debt_ratio"] == pytest.approx(0.465, abs=1e-3)


def test_health_keys_carry_the_quarter_suffix() -> None:
    """The v2 prompt requires the suffix and strips it itself. Emitting bare
    keys silently changes what the skill receives."""

    context = build_fundamental_context(
        symbol="2344",
        income=parse_financial_table(_fixture("2344", "IS_QUAR")),
        balance=parse_financial_table(_fixture("2344", "BS_QUAR")),
        cash_flow=parse_financial_table(_fixture("2344", "CF_QUAR")),
        fetched_at=ANCHOR,
    )

    assert context["health"]["net_income_2026Q1"] == pytest.approx(101.1)
    assert context["health"]["operating_cash_flow_2026Q1"] == pytest.approx(123.7)
    assert "net_income" not in context["health"]
    assert "operating_cash_flow" not in context["health"]


def test_net_income_uses_parent_only_basis() -> None:
    """Goodinfo lists both 稅後淨利 (101.1) and 合併稅後淨利 (101.2). The skill
    validation run used parent-only; mixing bases would be undeclared drift."""

    context = build_fundamental_context(
        symbol="2344",
        income=parse_financial_table(_fixture("2344", "IS_QUAR")),
        balance=parse_financial_table(_fixture("2344", "BS_QUAR")),
        cash_flow=parse_financial_table(_fixture("2344", "CF_QUAR")),
        fetched_at=ANCHOR,
    )

    assert context["health"]["net_income_2026Q1"] == pytest.approx(101.1)
    assert context["basis"] == "parent_only"


def test_emits_six_quarters_and_ttm_eps_without_price() -> None:
    context = build_fundamental_context(
        symbol="2344",
        income=parse_financial_table(_fixture("2344", "IS_QUAR")),
        balance=parse_financial_table(_fixture("2344", "BS_QUAR")),
        cash_flow=parse_financial_table(_fixture("2344", "CF_QUAR")),
        fetched_at=ANCHOR,
    )

    assert len(context["quarters"]) == 6
    # TTM = newest four quarters: 2.25 + 0.76 + 0.65 + (-0.29)
    assert context["valuation"]["ttm_eps"] == pytest.approx(3.37, abs=1e-2)
    # current_price/ttm_pe are the producer's to fill; radar must not invent them.
    assert "current_price" not in context["valuation"]
    assert "ttm_pe" not in context["valuation"]


def test_context_declares_provenance_and_is_json_serialisable() -> None:
    context = build_fundamental_context(
        symbol="2344",
        income=parse_financial_table(_fixture("2344", "IS_QUAR")),
        balance=parse_financial_table(_fixture("2344", "BS_QUAR")),
        cash_flow=parse_financial_table(_fixture("2344", "CF_QUAR")),
        fetched_at=ANCHOR,
    )

    assert context["source"].startswith("Goodinfo.tw")
    assert context["fetched_at"] == "2026-08-06T09:00:00Z"
    assert context["currency"] == "TWD 億元"
    assert context["fiscal_quarter"] == "2026Q1"
    json.dumps(context)


def test_tpex_symbol_uses_the_same_path() -> None:
    context = build_fundamental_context(
        symbol="8299",
        income=parse_financial_table(_fixture("8299", "IS_QUAR")),
        balance=parse_financial_table(_fixture("8299", "BS_QUAR")),
        cash_flow=parse_financial_table(_fixture("8299", "CF_QUAR")),
        fetched_at=ANCHOR,
    )

    assert context["quarters"][0]["period"] == "2026Q1"
    assert context["quarters"][0]["revenue"] == pytest.approx(409.7)
    assert context["quarters"][0]["eps"] == pytest.approx(68.8)


# ─── never invent ───────────────────────────────────────────────────────────


def test_missing_metric_is_recorded_not_defaulted_to_zero() -> None:
    """A zero would read as a real measurement to the skill."""

    balance = parse_financial_table(_fixture("2344", "BS_QUAR"))
    del balance["metrics"]["現金及約當現金"]

    context = build_fundamental_context(
        symbol="2344",
        income=parse_financial_table(_fixture("2344", "IS_QUAR")),
        balance=balance,
        cash_flow=parse_financial_table(_fixture("2344", "CF_QUAR")),
        fetched_at=ANCHOR,
    )

    assert "cash" not in context["health"]
    assert any("cash" in item for item in context["missing"])


def test_missing_quarterly_metric_is_omitted_not_zeroed() -> None:
    """A fabricated 0.0 EPS reads to the skill as a real loss-making quarter."""

    income = parse_financial_table(_fixture("2344", "IS_QUAR"))
    del income["metrics"]["每股稅後盈餘(元)"]

    context = build_fundamental_context(
        symbol="2344",
        income=income,
        balance=parse_financial_table(_fixture("2344", "BS_QUAR")),
        cash_flow=parse_financial_table(_fixture("2344", "CF_QUAR")),
        fetched_at=ANCHOR,
    )

    assert all("eps" not in quarter for quarter in context["quarters"])
    assert any("eps" in item for item in context["missing"])
    # ttm_eps must not be summed from nothing.
    assert "ttm_eps" not in context["valuation"]


def test_partially_missing_quarter_keeps_the_metrics_it_has() -> None:
    income = parse_financial_table(_fixture("2344", "IS_QUAR"))
    income["metrics"]["營業收入"]["2025Q3"] = None

    context = build_fundamental_context(
        symbol="2344",
        income=income,
        balance=parse_financial_table(_fixture("2344", "BS_QUAR")),
        cash_flow=parse_financial_table(_fixture("2344", "CF_QUAR")),
        fetched_at=ANCHOR,
    )

    affected = next(q for q in context["quarters"] if q["period"] == "2025Q3")
    assert "revenue" not in affected
    assert affected["eps"] == pytest.approx(0.65)


def test_unparseable_html_raises_rather_than_returning_empty() -> None:
    with pytest.raises(GoodinfoUnavailable):
        parse_financial_table("<html><body>maintenance</body></html>")


# ─── sanity checks ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "field,value",
    [("gross_margin", 1.8), ("debt_ratio", 1.4), ("current_ratio", -0.5)],
)
def test_sanity_check_flags_impossible_values(field: str, value: float) -> None:
    warnings = sanity_check({"quarters": [{"period": "2026Q1", field: value}], "health": {}})

    assert any(w["level"] == "error" and field in w["field"] for w in warnings)


def test_sanity_check_passes_real_data() -> None:
    context = build_fundamental_context(
        symbol="2344",
        income=parse_financial_table(_fixture("2344", "IS_QUAR")),
        balance=parse_financial_table(_fixture("2344", "BS_QUAR")),
        cash_flow=parse_financial_table(_fixture("2344", "CF_QUAR")),
        fetched_at=ANCHOR,
    )

    assert [w for w in sanity_check(context) if w["level"] == "error"] == []


# ─── fetch orchestration ────────────────────────────────────────────────────


def test_client_key_encodes_taiwan_offset() -> None:
    key = client_key_for(ANCHOR)

    assert key.startswith("2.8|38057.1435627105|46946.0324515993|-480|")


def test_fetch_requests_all_three_quarterly_reports() -> None:
    session, calls = _fake_session(
        {
            "IS_QUAR": _fixture("2344", "IS_QUAR"),
            "BS_QUAR": _fixture("2344", "BS_QUAR"),
            "CF_QUAR": _fixture("2344", "CF_QUAR"),
        }
    )

    context = fetch_symbol_fundamentals(session, "2344", fetched_at=ANCHOR, pause_seconds=0)

    assert calls == ["IS_QUAR", "BS_QUAR", "CF_QUAR"]
    assert context["quarters"][0]["period"] == "2026Q1"


def test_fetch_bounds_every_request_with_a_timeout() -> None:
    """Goodinfo is a scraped third party; an unbounded get hangs the quarterly
    run behind one stalled socket."""

    seen: list[dict[str, object]] = []

    class Response:
        def __init__(self, report: str) -> None:
            self.headers: dict[str, str] = {}
            self.encoding = "utf-8"
            self.text = _fixture("2344", report)

        def raise_for_status(self) -> None:
            return None

        def close(self) -> None:
            return None

    class Session:
        def get(self, url: str, **kwargs):
            seen.append(kwargs)
            return Response(url.split("RPT_CAT=", 1)[1].split("&", 1)[0])

    fetch_symbol_fundamentals(Session(), "2344", fetched_at=ANCHOR, pause_seconds=0)

    assert len(seen) == 3
    assert all(isinstance(call.get("timeout"), (int, float)) for call in seen)


@pytest.mark.parametrize("declare_length", [True, False])
def test_oversized_response_is_rejected(declare_length: bool) -> None:
    """Valid HTML, only far too large. Asserting on the message keeps this from
    passing for the unrelated reason that the body failed to parse."""

    oversized = _fixture("2344", "IS_QUAR") + "x" * (9 * 1024 * 1024)

    class Response:
        headers = {"Content-Length": str(len(oversized))} if declare_length else {}
        encoding = "utf-8"
        text = oversized

        def raise_for_status(self) -> None:
            return None

        def close(self) -> None:
            return None

    class Session:
        def get(self, url: str, **_kwargs):
            return Response()

    with pytest.raises(GoodinfoUnavailable, match="exceeds"):
        fetch_symbol_fundamentals(Session(), "2344", fetched_at=ANCHOR, pause_seconds=0)


def test_fetch_failure_raises_so_callers_can_degrade() -> None:
    session, _ = _fake_session(
        {"IS_QUAR": _fixture("2344", "IS_QUAR")}, fail_on={"BS_QUAR"}
    )

    with pytest.raises(GoodinfoUnavailable):
        fetch_symbol_fundamentals(session, "2344", fetched_at=ANCHOR, pause_seconds=0)


# ─── statement detail (per-stock page) ──────────────────────────────────────
#
# The radar only ever needed margins and EPS. A per-stock detail page needs the
# expense structure, the balance-sheet composition and all three cash flows --
# every one of which the parser already reads and then discards.
#
# These live under a separate ``statements`` key rather than being folded into
# ``quarters``: that payload is consumed verbatim by the downstream Hermes
# producer, and widening it would change a contract the detail page has no
# business changing.


def _context_2344() -> dict:
    return build_fundamental_context(
        symbol="2344",
        income=parse_financial_table(_fixture("2344", "IS_QUAR")),
        balance=parse_financial_table(_fixture("2344", "BS_QUAR")),
        cash_flow=parse_financial_table(_fixture("2344", "CF_QUAR")),
        fetched_at=ANCHOR,
    )


def test_statements_carry_the_operating_expense_breakdown() -> None:
    """推銷/管理/研發 is the whole point of an 經營分析 tab; without it the page
    can only restate the margins the radar already showed."""
    statements = _context_2344()["statements"]
    income = statements["income"]["2026Q1"]

    assert income["selling_expense"] == pytest.approx(7.95)
    assert income["admin_expense"] == pytest.approx(17.24)
    assert income["rd_expense"] == pytest.approx(52.26)
    assert income["operating_expense"] == pytest.approx(78.65)


def test_statements_carry_balance_sheet_composition() -> None:
    balance = _context_2344()["statements"]["balance"]["2026Q1"]

    assert balance["cash"] == pytest.approx(255.2)
    assert balance["inventory"] == pytest.approx(252.3)
    assert balance["receivables"] == pytest.approx(227.8)
    assert balance["total_assets"] == pytest.approx(2298.0)
    assert balance["total_equity"] == pytest.approx(1229.0)


def test_statements_carry_all_three_cash_flows() -> None:
    """Operating cash flow alone cannot distinguish a company funding itself
    from one funding itself by borrowing."""
    cash_flow = _context_2344()["statements"]["cash_flow"]["2026Q1"]

    assert cash_flow["operating"] == pytest.approx(123.7)
    assert cash_flow["investing"] == pytest.approx(-256.6)
    assert cash_flow["financing"] == pytest.approx(229.6)
    assert cash_flow["capex"] == pytest.approx(-29.16)


def test_cash_flow_ending_cash_tracks_the_balance_sheet_period_by_period() -> None:
    """The check that catches a column-stride misparse.

    A stride bug shifts every cash-flow figure by one period while leaving each
    value individually plausible, so range checks pass and the numbers are
    silently wrong. Ending cash and balance-sheet cash measure the same thing,
    so a correct parse pairs them within the same period.

    They are not asserted equal: Goodinfo's cash-flow statement is consolidated
    while the balance-sheet rows read here are parent-only, so a company with
    subsidiaries reports legitimately different figures (measured 2026-08-07:
    2344 2026Q2 is 618.3 consolidated against 430.1 parent-only). What a stride
    bug would produce instead is ending cash matching a *neighbouring* period's
    balance -- which is what this pins.
    """
    context = _context_2344()
    balances = context["statements"]["balance"]
    periods = list(balances)

    for index, period in enumerate(periods):
        ending_cash = context["statements"]["cash_flow"][period].get("ending_cash")
        own = balances[period].get("cash")
        if ending_cash is None or own is None:
            continue
        own_gap = abs(ending_cash - own)
        for neighbour in periods[max(0, index - 1):index] + periods[index + 1:index + 2]:
            other = balances[neighbour].get("cash")
            if other is None or other == own:
                continue
            assert own_gap <= abs(ending_cash - other), (
                f"{period}: ending cash sits closer to {neighbour}'s balance -- "
                "the cash-flow columns look shifted by one period"
            )


def test_statements_span_the_same_quarters_as_the_radar_payload() -> None:
    context = _context_2344()
    periods = [quarter["period"] for quarter in context["quarters"]]

    for section in ("income", "balance", "cash_flow"):
        assert list(context["statements"][section]) == periods


def test_a_line_absent_from_the_filing_is_omitted_not_zeroed() -> None:
    """Dividends are not paid every quarter. A fabricated 0.0 would render as
    "cut the dividend to zero" on the detail page."""
    cash_flow = _context_2344()["statements"]["cash_flow"]["2026Q1"]

    assert "dividends_paid" not in cash_flow


def test_statement_detail_does_not_disturb_the_downstream_contract() -> None:
    """``quarters``/``health``/``valuation`` are consumed verbatim by Hermes."""
    context = _context_2344()

    assert set(context["quarters"][0]) == {
        "period", "revenue", "gross_margin", "operating_margin", "net_margin", "eps",
    }
    assert context["basis"] == "parent_only"


def test_statement_detail_is_json_serialisable() -> None:
    json.dumps(_context_2344(), ensure_ascii=False)


def test_missing_statement_detail_is_recorded_in_missing() -> None:
    balance = parse_financial_table(_fixture("2344", "BS_QUAR"))
    del balance["metrics"]["存貨"]

    context = build_fundamental_context(
        symbol="2344",
        income=parse_financial_table(_fixture("2344", "IS_QUAR")),
        balance=balance,
        cash_flow=parse_financial_table(_fixture("2344", "CF_QUAR")),
        fetched_at=ANCHOR,
    )

    assert "inventory" not in context["statements"]["balance"]["2026Q1"]
    assert any("inventory" in item for item in context["missing"])
