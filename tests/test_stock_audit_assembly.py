"""Focused contract tests for the offline reviewed-report assembler."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.assemble_stock_audit_day import _canonical_review, assemble


def test_assembly_rejects_mismatched_report_dates_before_joining_inputs():
    with pytest.raises(ValueError, match="report_date"):
        assemble(
            {"report_date": "2026-10-22", "stocks": []},
            {"report_date": "2026-10-21", "review_status": "complete_bounded_discretionary_review_not_strategy_validation", "symbols": {}},
            {"report_date": "2026-10-22", "forecast_cutoff": "2026-10-23T06:00:00+08:00"},
            {"report_date": "2026-10-22", "stocks": []},
        )


def test_assembly_rejects_stale_weekly_review_instead_of_redating_it():
    analysis = {
        "as_of": "2026-10-22",
        "candle_sha256": "candle-hash",
        "timeframes": {"W1": {"as_of": "2026-10-22"}},
    }
    review = {
        "as_of": "2026-10-22",
        "W1": {"as_of": "2026-10-21"},
        "D1": {},
        "reviews": [],
    }
    with pytest.raises(ValueError, match="W1 as_of"):
        _canonical_review(review, analysis)


def test_assembly_rejects_missing_review_candidate_instead_of_intersecting_silently():
    base = {
        "report_date": "2026-10-22",
        "stocks": [{"symbol": "2317"}, {"symbol": "2308"}, {"symbol": "2454"}],
    }
    computed = {
        "report_date": "2026-10-22",
        "stocks": [{"symbol": "2317"}, {"symbol": "2308"}],
    }
    review = {
        "report_date": "2026-10-22",
        "review_status": "complete_bounded_discretionary_review_not_strategy_validation",
        "symbols": {"2317": {}, "2308": {}, "2454": {}},
    }
    market = {"report_date": "2026-10-22", "forecast_cutoff": "2026-10-23T06:00:00+08:00"}
    with pytest.raises(ValueError, match="symbol sets"):
        assemble(computed, review, market, base)


def test_cli_rejects_review_of_different_computed_bytes(tmp_path):
    import subprocess
    import sys
    review=tmp_path/'review.json';review.write_text('{"computed_sha256":"wrong"}')
    computed=tmp_path/'computed.json';computed.write_text('{}')
    result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/assemble_stock_audit_day.py'),
        '--computed',str(computed),'--review',str(review),'--market',str(computed),
        '--baseline',str(computed),'--financial-review',str(computed),'--output',str(tmp_path/'out.json')],capture_output=True,text=True)
    assert result.returncode!=0 and 'computed_sha256' in result.stderr
    assert not (tmp_path/'out.json').exists()


def test_financial_review_binds_real_facts_and_rejects_changed_eps():
    import hashlib
    import json
    from scripts.assemble_stock_audit_day import validate_financial_review
    facts={'source':'https://example.com/revenue','income_source':'https://example.com/income','eps':12.3}
    review={'financial_sha256':hashlib.sha256(json.dumps(facts,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest(),
            'as_of':'2026-10-22','reviewed':True,'sources':[facts['source'],facts['income_source']],
            'insight':'營收維持增長，但獲利與毛利率仍需持續追蹤。'}
    validate_financial_review(review,facts,'2026-10-22','2317')
    with pytest.raises(ValueError,match='financial review'):
        validate_financial_review(review,dict(facts,eps=13),'2026-10-22','2317')
    with pytest.raises(ValueError,match='financial review'):
        validate_financial_review({},facts,'2026-10-22','2317')


def test_morning_edition_changes_label_not_observed_source_dates():
    from scripts.assemble_stock_audit_day import morning_edition
    source={'report_date':'2026-10-21','forecast_cutoff':'2026-10-22T06:00:00+08:00',
            'stocks':[{'candles':[{'date':'2026-10-21','close':250}]}]}
    edition=morning_edition(source,'2026-10-22')
    assert edition['report_date']=='2026-10-22' and edition['data_as_of']=='2026-10-21'
    assert edition['stocks']==source['stocks'] and source['report_date']=='2026-10-21'
    with pytest.raises(ValueError):morning_edition(source,'2026-10-21')
