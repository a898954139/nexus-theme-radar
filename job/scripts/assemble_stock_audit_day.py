"""Assemble one reviewed Stock Audit report from independent evidence inputs.

The assembler is intentionally offline: computed technical output, canonical
review adjudication, market evidence, and supplied financial facts are joined
only after their dates and source-linked contract validate.  It never invents
price levels, copies old valuation/technical prose, or edits public artifacts.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date
import json
import hashlib
from pathlib import Path
import sys

try:
    from scripts.render_stock_audit import complete_stock, metrics, validate_market, validate_report_scope
except ModuleNotFoundError:
    from render_stock_audit import complete_stock, metrics, validate_market, validate_report_scope


def _load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def _merge_receipts(*groups: list[dict]) -> list[dict]:
    """Keep all point-in-time receipts once, preserving input order."""
    merged = []
    seen = set()
    for group in groups:
        for receipt in group or []:
            key = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            if key not in seen:
                seen.add(key)
                merged.append(deepcopy(receipt))
    return merged


def _period_label(value: str) -> str:
    text = str(value)
    return text[4:] if len(text) >= 6 and text[4] in {'H', 'Q'} else text


def _financial_labels(financial: dict) -> dict[str, str]:
    eps_period = str(financial['eps_period'])
    gross_period = str(financial['gross_margin_period'])
    short = _period_label(eps_period)
    eps_label = f'{eps_period[:4]} {short} EPS' if len(eps_period) >= 6 and eps_period[4] in {'H', 'Q'} else f'{eps_period} EPS'
    revenue_month = str(financial['revenue_month'])
    if len(revenue_month) == 7 and revenue_month[4] == '-':
        revenue_label = f'{int(revenue_month[5:])} 月營收'
    else:
        revenue_label = f'{revenue_month} 月營收'
    return {
        'revenue': revenue_label,
        'eps': eps_label,
        'gross': f'{_period_label(gross_period)} 毛利率',
    }


def _curve_text(metrics_row: dict) -> str:
    curve = metrics_row['curve']
    return (
        f"Sharpe {curve['sharpe']:.2f}、Sortino {curve['sortino']:.2f}、"
        f"最大回撤 {curve['max_drawdown_pct']:.2f}%、TTR {curve['ttr_sessions']} 交易日、"
        f"指數擬合 R² {curve['r2']:.3f}；本次未恢復回撤 {curve['underwater_sessions']} 交易日。"
    )


def _valuation_text(metrics_row: dict) -> str:
    return (
        f"目前 PE {metrics_row['pe']:.2f} 倍，歷史中位數 {metrics_row['median']:.2f} 倍，"
        f"相對中位數 {metrics_row['premium']:+.2f}%；歷史區間 "
        f"{metrics_row['pe_low']:.2f}–{metrics_row['pe_high']:.2f} 倍。"
    )


def _canonical_review(review_symbol: dict, analysis: dict) -> dict:
    review = {
        'as_of': analysis['as_of'],
        'candle_sha256': analysis['candle_sha256'],
        'D1': deepcopy(review_symbol['D1']),
        'W1': deepcopy(review_symbol['W1']),
        'reviews': deepcopy(review_symbol['reviews']),
    }
    # The review is point-in-time evidence, so its weekly interpretation must
    # already match the completed weekly bars. Never silently re-date stale
    # adjudication during assembly.
    if review_symbol['W1'].get('as_of') != analysis['timeframes']['W1']['as_of']:
        raise ValueError(
            f"{analysis.get('symbol', 'stock')}: review W1 as_of does not match computed W1 as_of"
        )
    note = review['W1'].get('basis_note', '')
    completion = analysis['timeframes']['W1'].get('week_completion')
    if completion:
        review['W1']['basis_note'] = (
            note + ('；' if note else '') +
            f"calendar evidence closes the week through {review['W1']['as_of']}"
        )
    return review


def _prune_public_technical(analysis: dict) -> None:
    """Keep source-linked pivots/breaks while dropping bulky detector internals."""
    for timeframe in ('D1', 'W1'):
        frame = analysis.get('timeframes', {}).get(timeframe, {})
        frame.pop('raw_engine', None)
        frame.pop('zones', None)


def _build_research(stock: dict, analysis: dict, review_symbol: dict, baseline_research: dict | None) -> dict:
    metrics_row = metrics(stock)
    financial = stock['financial']
    labels = _financial_labels(financial)
    review_research = review_symbol['research']
    canonical = analysis['canonical_review']
    plan = analysis['plan']
    old = baseline_research or {}
    d1 = canonical['D1']; w1 = canonical['W1']
    plan_status = plan['status']
    action = '本期不進場' if plan_status == 'no_trade' else '條件重評，未形成即時委託'
    return {
        # The baseline may supply fact wording only.  Classification must come
        # from the fresh review, or remain neutral when no classification was
        # adjudicated for this date.
        'investment_type': review_research.get('investment_type', '條件觀察'),
        'action': action,
        # Only this field may borrow baseline research prose; the other prose is
        # regenerated from current quote/PE/curve/review evidence below.
        'fundamentals': '',  # Required source-bound financial review is assigned before validation.
        'valuation': _valuation_text(metrics_row),
        'curve': _curve_text(metrics_row),
        'technical': review_research['technical'],
        'operation_rationale': review_research['operation_rationale'],
        'conclusion': review_research['conclusion'],
        'entry_outlook': review_symbol.get('execution_note', plan.get('wait_condition', '目前不執行。')),
        'metrics': metrics_row,
        'nexus': {
            'bias': f"W1 {w1['bias']}／D1 {d1['bias']}",
            'phase': f"W1 {w1['phase']}／D1 {d1['phase']}",
            'actionability': action,
            'pullback': review_research['operation_rationale'],
            'invalidation': review_research['conclusion'],
            'timeframe': f"W1 截至 {analysis['timeframes']['W1']['as_of']}／D1 截至 {analysis['as_of']}",
        },
        'morning_brief': deepcopy(review_symbol['morning_brief']),
    }


def _assemble_stock(symbol: str, baseline: dict, computed: dict, review_symbol: dict, financial_review: dict) -> dict:
    stock = deepcopy(baseline)
    analysis = deepcopy(computed['technical_analysis'])
    if analysis.get('analysis_status') != 'complete':
        raise ValueError(f'{symbol}: technical analysis is not complete')
    if review_symbol.get('as_of') != computed['technical_analysis']['as_of']:
        raise ValueError(f'{symbol}: review/report date mismatch')
    if review_symbol.get('plan_status') != analysis['plan']['status']:
        raise ValueError(f'{symbol}: review plan_status disagrees with computed plan')

    canonical = _canonical_review(review_symbol, analysis)
    _prune_public_technical(analysis)
    analysis['detector_structure'] = analysis['structure']
    analysis['canonical_review'] = canonical
    analysis['structure'] = {'D1': canonical['D1'], 'W1': canonical['W1']}
    qualifications = {item['role']: item['qualification'] for item in review_symbol['reviews']}
    for role in ('trigger', 'defense'):
        if qualifications.get(role) == 'rejected':
            analysis['plan'].setdefault('watch_levels', {}).pop(role, None)
    brief = review_symbol['morning_brief']
    if brief.get('as_of') != analysis['as_of'] or brief.get('candle_sha256') != analysis['candle_sha256']:
        raise ValueError(f'{symbol}: morning brief does not match computed evidence')
    stock['technical_analysis'] = analysis
    stock['research'] = _build_research(stock, analysis, review_symbol, None)
    stock['research']['fundamentals'] = financial_review['insight']
    stock['financial_review'] = deepcopy(financial_review)
    return stock


def validate_financial_review(fact_review, facts, report_date, symbol):
    expected=hashlib.sha256(json.dumps(facts,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    if (fact_review.get('financial_sha256')!=expected or fact_review.get('as_of')!=report_date
            or fact_review.get('reviewed') is not True
            or set(fact_review.get('sources',[]))!={facts['source'],facts['income_source']}
            or not isinstance(fact_review.get('insight'),str) or len(fact_review['insight'].strip())<15):
        raise ValueError(f'{symbol}: invalid source-bound financial review')


def assemble(computed: dict, review: dict, market: dict, baseline: dict | None = None, financial_review: dict | None = None) -> dict:
    report_date = computed.get('report_date')
    if report_date != review.get('report_date') or report_date != market.get('report_date'):
        raise ValueError('computed/review/market report_date mismatch')
    if review.get('review_status') != 'complete_bounded_discretionary_review_not_strategy_validation':
        raise ValueError('review is not complete_bounded_discretionary_review_not_strategy_validation')
    if market.get('forecast_cutoff') is None:
        raise ValueError('market forecast_cutoff missing')
    if baseline is None:
        raise ValueError('baseline is required for supplied financial facts')
    if baseline.get('report_date') != report_date:
        raise ValueError('baseline report_date mismatch')
    baseline_by_symbol = {str(stock['symbol']): stock for stock in baseline.get('stocks', [])}
    computed_by_symbol = {str(stock['symbol']): stock for stock in computed.get('stocks', [])}
    review_by_symbol = {str(symbol): value for symbol, value in review.get('symbols', {}).items()}
    sets = (set(baseline_by_symbol), set(computed_by_symbol), set(review_by_symbol))
    if not (sets[0] == sets[1] == sets[2]):
        raise ValueError('baseline/computed/review symbol sets disagree')
    symbols = [str(stock['symbol']) for stock in computed.get('stocks', [])]
    if len(symbols) != len(set(symbols)) or not 3 <= len(symbols) <= 5:
        raise ValueError('review must contain 3–5 distinct symbols')
    if not financial_review or financial_review.get('as_of') != report_date:
        raise ValueError('Source-bound financial_review required for this report date')
    stocks = []
    for symbol in symbols:
        fact_review=financial_review.get('symbols',{}).get(symbol,{})
        facts=baseline_by_symbol[symbol]['financial']
        validate_financial_review(fact_review,facts,report_date,symbol)
        stocks.append(_assemble_stock(symbol, baseline_by_symbol[symbol], computed_by_symbol[symbol], review_by_symbol[symbol],fact_review))
    result = {
        'report_date': report_date,
        'forecast_cutoff': market['forecast_cutoff'],
        'retrieved_at': market.get('retrieved_at', market.get('reconstructed_at')),
        'reconstructed_at': market.get('reconstructed_at'),
        'point_in_time_verified': market.get('point_in_time_verified', False),
        'stocks': stocks,
        'market': deepcopy(market),
        'source_receipts': _merge_receipts(
            market.get('source_receipts', []),
            baseline.get('source_receipts', []),
            baseline.get('input_receipts', []),
        ),
        'input_receipts': deepcopy(baseline.get('input_receipts', [])),
        'technical_method_manifest': {
            symbol: deepcopy(computed_by_symbol[symbol]['technical_analysis'].get('method_receipts', []))
            for symbol in symbols
        },
        'research_status': 'reviewed',
        'review_provenance': {
            key: review[key]
            for key in ['schema_version', 'report_date', 'review_status', 'input_sha256', 'computed_sha256', 'method', 'limitations']
            if key in review
        },
    }
    # Local evidence filenames are useful during collection but must not leak
    # into a public reviewed snapshot; calendar URLs remain in calendar_source.
    result['market'].pop('calendar_evidence_file', None)
    # Use the same public contract as the renderer before writing any output.
    validate_market(result['market'], result['forecast_cutoff'], result['report_date'])
    for stock in stocks:
        if not complete_stock(stock, report_date, result['forecast_cutoff']):
            raise ValueError(f"{stock['symbol']}: assembled stock fails complete_stock")
    return result


def morning_edition(data, report_date):
    """Attach an edition without changing any observed/reviewed source dates."""
    result=deepcopy(data)
    result['data_as_of']=data.get('data_as_of',data['report_date'])
    result['report_date']=report_date
    result['source_json_filename']=f'stock-audit-{report_date}.json'
    validate_report_scope(result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--computed', type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--market', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--financial-review', type=Path, required=True)
    parser.add_argument('--report-date', help='Morning publication date; source review dates stay unchanged')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    review = _load(args.review)
    for path, field in ((args.computed, 'computed_sha256'), (args.baseline, 'input_sha256')):
        if review.get(field) != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError(f'Review {field} does not match the supplied evidence file')
    result = assemble(_load(args.computed), review, _load(args.market), _load(args.baseline), _load(args.financial_review))
    if args.report_date:
        result=morning_edition(result,args.report_date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix('.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temp.replace(args.output)
    print(f"Assembled reviewed Stock Audit {result['report_date']}: {len(result['stocks'])} stocks -> {args.output}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
