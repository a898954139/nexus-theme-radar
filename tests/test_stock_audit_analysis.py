"""AC B/D/E: independent numeric oracles; synthetic bars never publish."""
import pytest
from scripts.build_stock_audit import analyze, valid_candles


def bars(count=120):
    from datetime import date, timedelta
    return [dict(date=str(date(2025,1,1)+timedelta(days=i)),open=i+99,high=i+102,low=i+98,close=i+100,volume=1000) for i in range(count)]


def test_real_ohlcv_boundary_rejects_short_nonfinite_and_impossible_bars():
    assert not valid_candles(bars(59))
    assert valid_candles(bars())
    for change in ({'close':float('nan')},{'volume':-1},{'low':9999}):
        data=bars(); data[-1].update(change)
        assert not valid_candles(data)


def test_price_averages_valuation_and_horizon_risk_are_computed_before_render():
    a=analyze(bars(),[10,20,30,40])
    assert a['ma20']==209.5
    assert a['ma60']==189.5
    assert a['baseline_pe']==25
    assert a['premium_pct']==60
    assert a['percentile']==100
    assert [x['term'] for x in a['operations']]==['短線','中線','長線']
    for op in a['operations']:
        assert op['stop']<op['entry']<op['add']<op['take_profit']
        assert op['take_profit']==pytest.approx(op['entry']+2*(op['entry']-op['stop']),abs=.02)


def test_incomplete_prices_do_not_produce_analysis():
    with pytest.raises(ValueError): analyze(bars(59),[10,20])


def test_published_snapshot_has_real_observed_prices_and_distinct_source_clocks():
    import json
    from pathlib import Path
    p=json.loads((Path(__file__).parents[1]/'data/stock-audit-latest.json').read_text())
    assert p['report_date']=='2026-10-22'
    s=p['stocks'][0]
    assert s['symbol']=='2317'
    assert s['price']==245
    last=s['technical']['candles'][-1]
    assert (last['open'],last['high'],last['low'],last['close'],last['volume'])==(249.5,250.5,244.5,245,26653604)
    assert len(s['technical']['candles'])==236
    assert s['fundamentals']['pe']==16.15
    assert s['valuation']['baseline_pe']==16.725
    assert s['valuation']['premium_pct']==pytest.approx(-3.43796712)
    refs=p['forecast']['references']
    assert len(refs)==7
    assert next(r for r in refs if '台指期' in r['label'])['as_of']=='2026-10-22T05:00:00+08:00'
    assert all(r['status']==200 for r in p['source_receipts'])
    assert '盤中快照' in refs[0]['label']


def test_growth_quality_recovery_counts_only_completed_underwater_periods():
    from scripts.build_stock_audit import quality
    data=bars()
    # A peak100, 2 completed underwater sessions then recovery; final drawdown unclosed.
    for c,close in zip(data,[100,90,95,100]+[100]*115+[80]):
        c['close']=close
    q=quality(data)
    assert q['ttr_days']==3
    assert '非含息' in q['index_shape']
    assert '不作基本面篩選' in q['method']
