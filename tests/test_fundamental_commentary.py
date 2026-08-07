"""Narrative commentary over the cached quarterly statements.

The detail page renders numbers; this is the layer that says what they mean.
Writing that prose takes a model, so the pipeline is split: this module builds
the prompt and validates what comes back, while *executing* the prompt is
injected. Today Claude Code runs it by hand once a quarter; an API-backed
runner can replace the executor later without changing the stored format.

These tests pin the parts that must not drift: the prompt carries real figures
rather than asking a model to recall them, commentary is only kept when it
matches the quarter it describes, and a symbol whose generation fails keeps the
commentary it already had.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from scripts.fundamental_commentary import (
    build_commentary_prompt,
    generate_commentary,
    symbols_needing_commentary,
    validate_commentary,
)

ANCHOR = datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc)


def _context(quarter: str = "2026Q1") -> dict:
    return {
        "fiscal_quarter": quarter,
        "basis": "parent_only",
        "currency": "TWD 億元",
        "quarters": [
            {"period": quarter, "revenue": 11341.0, "gross_margin": 0.6624,
             "operating_margin": 0.5810, "net_margin": 0.5048, "eps": 22.08},
            {"period": "2025Q4", "revenue": 10461.0, "gross_margin": 0.6232,
             "operating_margin": 0.5400, "net_margin": 0.4834, "eps": 19.51},
        ],
        "health": {"cash": 30356.0, "current_ratio": 2.488, "debt_ratio": 0.315},
        "valuation": {"ttm_eps": 74.39},
        "statements": {
            "income": {quarter: {"revenue": 11341.0, "rd_expense": 677.6,
                                 "operating_income": 6590.0}},
            "balance": {quarter: {"cash": 30356.0, "total_assets": 86609.0,
                                  "total_equity": 59324.0}},
            "cash_flow": {quarter: {"operating": 6990.0, "capex": -3490.0}},
        },
    }


def _commentary(quarter: str = "2026Q1") -> dict:
    return {
        "fiscal_quarter": quarter,
        "highlights": [
            "營收 11,341 億,較前季 10,461 億成長 8.4%",
            "毛利率 66.2%,較前季 62.3% 擴張 3.9 個百分點",
            "營業現金流 6,990 億,資本支出 3,490 億,自由現金流 3,500 億",
        ],
    }


# ── selecting work ────────────────────────────────────────────────────────


def test_a_symbol_with_no_commentary_needs_it() -> None:
    due = symbols_needing_commentary(
        {"TWSE:2330": _context()}, commentary={},
    )

    assert due == ["TWSE:2330"]


def test_commentary_for_the_current_quarter_is_not_regenerated() -> None:
    """This costs real money per symbol per quarter; a re-run must be free."""
    due = symbols_needing_commentary(
        {"TWSE:2330": _context()},
        commentary={"TWSE:2330": _commentary()},
    )

    assert due == []


def test_commentary_describing_a_stale_quarter_is_regenerated() -> None:
    """Prose about 2025Q4 sitting beside 2026Q1 figures is worse than none."""
    due = symbols_needing_commentary(
        {"TWSE:2330": _context("2026Q1")},
        commentary={"TWSE:2330": _commentary("2025Q4")},
    )

    assert due == ["TWSE:2330"]


def test_a_symbol_without_statements_is_skipped_not_attempted() -> None:
    """Spending a generation on a symbol with nothing to describe produces
    invented prose, which is the one output worth paying to avoid."""
    due = symbols_needing_commentary(
        {"TWSE:2330": {"fiscal_quarter": "2026Q1", "quarters": []}},
        commentary={},
    )

    assert due == []


# ── the prompt ────────────────────────────────────────────────────────────


def test_prompt_carries_the_actual_figures() -> None:
    """The model must summarise supplied numbers, never recall them: asking it
    to remember a company's revenue is asking it to make one up."""
    prompt = build_commentary_prompt("2330", _context())

    assert "11341" in prompt or "11,341" in prompt
    assert "2026Q1" in prompt
    assert "2330" in prompt


def test_prompt_states_the_basis_and_units() -> None:
    """億元 vs 元, and parent-only vs consolidated, both change what a figure
    means. A prompt that omits them invites a plausible wrong sentence."""
    prompt = build_commentary_prompt("2330", _context())

    assert "億元" in prompt
    assert "parent_only" in prompt or "母公司" in prompt


def test_prompt_forbids_recommendations() -> None:
    """This is a public page; personalised investment advice is not ours to
    give, whatever the numbers say."""
    prompt = build_commentary_prompt("2330", _context())

    assert "投資建議" in prompt


# ── validating what comes back ────────────────────────────────────────────


def test_commentary_for_the_wrong_quarter_is_rejected() -> None:
    result = validate_commentary(_commentary("2025Q4"), expected_quarter="2026Q1")

    assert result is None


def test_commentary_without_highlights_is_rejected() -> None:
    assert validate_commentary({"fiscal_quarter": "2026Q1"}, expected_quarter="2026Q1") is None
    assert validate_commentary(
        {"fiscal_quarter": "2026Q1", "highlights": []}, expected_quarter="2026Q1",
    ) is None


def test_non_string_highlights_are_rejected() -> None:
    """A dict or a number here renders as [object Object] on the page."""
    result = validate_commentary(
        {"fiscal_quarter": "2026Q1", "highlights": ["ok", {"nested": 1}]},
        expected_quarter="2026Q1",
    )

    assert result is None


def test_valid_commentary_is_returned_unchanged() -> None:
    payload = _commentary()

    assert validate_commentary(payload, expected_quarter="2026Q1") == payload


# ── generating ────────────────────────────────────────────────────────────


def test_generate_writes_commentary_keyed_by_instrument_id() -> None:
    def run(prompt: str) -> dict:
        return _commentary()

    result, report = generate_commentary(
        {"TWSE:2330": _context()}, commentary={}, run=run,
    )

    assert list(result) == ["TWSE:2330"]
    assert result["TWSE:2330"]["fiscal_quarter"] == "2026Q1"
    assert report.succeeded == 1


def test_a_failing_generation_keeps_the_previous_commentary() -> None:
    """Losing last quarter's prose because this quarter's call failed makes the
    page worse than not running at all."""

    def run(prompt: str) -> dict:
        raise RuntimeError("model unavailable")

    prior = {"TWSE:2330": _commentary("2025Q4")}
    result, report = generate_commentary(
        {"TWSE:2330": _context("2026Q1")}, commentary=prior, run=run,
    )

    assert result["TWSE:2330"] == prior["TWSE:2330"]
    assert report.failed == 1
    assert "TWSE:2330" in report.failures


def test_rejected_commentary_counts_as_a_failure_not_a_success() -> None:
    """A model answering about the wrong quarter must not be recorded as done,
    or the next run will skip it."""

    def run(prompt: str) -> dict:
        return _commentary("2020Q1")

    result, report = generate_commentary(
        {"TWSE:2330": _context("2026Q1")}, commentary={}, run=run,
    )

    assert "TWSE:2330" not in result
    assert report.failed == 1


def test_one_failure_does_not_lose_the_others() -> None:
    def run(prompt: str) -> dict:
        if "2317" in prompt:
            raise RuntimeError("boom")
        return _commentary()

    result, report = generate_commentary(
        {"TWSE:2330": _context(), "TWSE:2317": _context()},
        commentary={}, run=run,
    )

    assert "TWSE:2330" in result
    assert report.succeeded == 1
    assert report.failed == 1


def test_dry_run_reports_the_work_without_generating() -> None:
    def run(prompt: str) -> dict:  # pragma: no cover - must not be called
        raise AssertionError("dry run must not generate")

    result, report = generate_commentary(
        {"TWSE:2330": _context()}, commentary={}, run=run, dry_run=True,
    )

    assert result == {}
    assert report.selected == ["TWSE:2330"]
    assert report.succeeded == 0


def test_output_is_json_serialisable() -> None:
    result, _ = generate_commentary(
        {"TWSE:2330": _context()}, commentary={}, run=lambda p: _commentary(),
    )

    json.dumps(result, ensure_ascii=False)
