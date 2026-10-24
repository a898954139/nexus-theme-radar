"""New-day production must reuse the format without laundering incomplete research."""
import copy
import importlib.util
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).parents[1]

def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def morning_data():
    data = json.loads((ROOT/'reports/stock-audit-2026-10-21.json').read_text())
    data.update({
        'report_date': '2026-10-22',
        'data_as_of': '2026-10-21',
        'forecast_cutoff': '2026-10-22T06:00:00+08:00',
        'research_status': 'reviewed',
    })
    data['market'].update(us_session_date='2026-10-21',night_session_date='2026-10-21')
    data['market']['economic_events'] = [{
        'name': 'FOMC meeting',
        'dates': ['2026-10-27', '2026-10-28'],
        'source': 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm',
    }]
    return data

def test_format_detects_missing_entry_table():
    m=load('produce_stock_audit_report')
    html=(ROOT/'reports/stock-audit-2026-10-21.html').read_text()
    assert m.same_format(html,html)
    assert not m.same_format(html,html.replace('class="entry-plan"','class="wrong"',1))
    assert not m.same_format(html,html.replace('stock-audit.css','other.css'))

def test_producer_refuses_inputs_only_without_writing(tmp_path):
    m=load('produce_stock_audit_report')
    data=json.loads((ROOT/'reports/stock-audit-2026-10-21.json').read_text())
    data['research_status']='inputs_only'
    with pytest.raises(ValueError,match='reviewed'):
        m.produce(data,ROOT/'reports/stock-audit-2026-10-21.html',tmp_path)
    assert not list(tmp_path.iterdir())


def test_producer_requires_explicit_data_as_of_for_new_publication(tmp_path):
    m=load('produce_stock_audit_report')
    data=json.loads((ROOT/'reports/stock-audit-2026-10-21.json').read_text())
    data['research_status']='reviewed'
    with pytest.raises(ValueError,match='data_as_of'):
        m.produce(data,ROOT/'reports/stock-audit-2026-10-21.html',tmp_path)
    assert not list(tmp_path.iterdir())


def test_producer_uses_publication_date_but_validates_prior_session_data(tmp_path):
    m=load('produce_stock_audit_report')
    result=m.produce(morning_data(),ROOT/'reports/stock-audit-2026-10-21.html',tmp_path)
    assert result['report_date']=='2026-10-22'
    html=(tmp_path/'stock-audit-2026-10-22.html').read_text()
    assert 'Stock Audit｜2026-10-22 台股投資決策卡' in html
    assert '10/21 台股收盤' in html
    assert '資料截止 2026-10-22 06:00（台北）' in html
    assert '10/21 15:00–10/22 05:00 夜盤' in html
    assert (tmp_path/'stock-audit-2026-10-22.json').is_file()
    assert not (tmp_path/'stock-audit-2026-10-21.html').exists()


@pytest.mark.parametrize('mutate,match', [
    (lambda d: d['stocks'][0]['candles'][-1].update(date='2026-10-22'), 'complete'),
    (lambda d: [r.update(as_of='2026-10-23T04:00:00+08:00' if r['label'] != '台指期夜盤' else '2026-10-23T05:00:00+08:00') for r in d['market']['references']], 'market'),
    (lambda d: d['market'].update(calendar_notice='10/23 休市', next_session_date='2026-10-27', calendar_source=['https://www.twse.com.tw/holidaySchedule/holidaySchedule?response=json&queryYear=115']), 'calendar'),
])
def test_producer_rejects_future_morning_evidence_without_writing(tmp_path,mutate,match):
    m=load('produce_stock_audit_report')
    data=morning_data(); mutate(data)
    with pytest.raises(ValueError,match=match):
        m.produce(data,ROOT/'reports/stock-audit-2026-10-21.html',tmp_path)
    assert not list(tmp_path.iterdir())

def test_collection_cannot_copy_decisions_or_fabricate_missing_session():
    m=load('prepare_stock_audit_day')
    data=json.loads((ROOT/'reports/stock-audit-2026-10-21.json').read_text())
    cache=ROOT/'.omx/reviews/stock-audit-target-research/raw'
    if not cache.exists():pytest.skip('local official source fixture unavailable')
    result=m.prepare(data,'2026-10-22',cache)
    assert [s['candles'][-1]['close'] for s in result['stocks']]==[245,1560,4010,3145,1115]
    assert [s['pe_history'][-1]['pe'] for s in result['stocks']]==[16.15,49.65,66.23,41.92,40.02]
    assert all('research' not in s and 'technical_analysis' not in s for s in result['stocks'])
    assert 'market' not in result
    with pytest.raises(ValueError,match='no observed quote/PE'):
        m.prepare(copy.deepcopy(data),'2026-10-23',cache)

@pytest.mark.parametrize('broken,allowed', [('BROKEN',False),('--',True)])
def test_collection_distinguishes_malformed_from_unpriced(monkeypatch,broken,allowed):
    m=load('prepare_stock_audit_day')
    data=json.loads((ROOT/'reports/stock-audit-2026-10-21.json').read_text())
    def rows(symbol,endpoint,month,cache,receipts):
        if endpoint=='BWIBBU':return [['115年10月22日','','','16.15']]
        return [['115/10/17','0' if allowed else '100','',broken,broken,broken,broken],
                ['115/10/22','100','','245','250','240','245']]
    monkeypatch.setattr(m,'read_month',rows)
    if allowed:
        assert m.prepare(data,'2026-10-22',Path('/unused'))['input_exclusions'][0]['reason']=='official_zero_volume_unpriced'
    else:
        with pytest.raises(ValueError,match='Malformed official OHLC'):
            m.prepare(data,'2026-10-22',Path('/unused'))


def test_format_allows_data_dependent_method_badges():
    m=load('produce_stock_audit_report')
    html=(ROOT/'reports/stock-audit-2026-10-21.html').read_text()
    assert m.same_format(html,html.replace('D1 · 多方 · 有效','W1 · 空方 · 耗盡'))


def test_explicit_empty_event_review_does_not_inherit_old_fomc():
    m=load('render_stock_audit')
    assert 'FOMC' not in m.important_events({'economic_events':[]})


def test_format_accepts_three_to_five_cards_without_changing_components():
    from bs4 import BeautifulSoup
    m=load('produce_stock_audit_report')
    html=(ROOT/'reports/stock-audit-2026-10-21.html').read_text()
    soup=BeautifulSoup(html,'html.parser');soup.select('details.stock')[-1].decompose()
    assert m.same_format(html,str(soup))


def test_missing_pe_revision_cannot_retain_baseline_value(monkeypatch):
    m=load('prepare_stock_audit_day')
    data=json.loads((ROOT/'reports/stock-audit-2026-10-21.json').read_text())
    def rows(symbol,endpoint,month,cache,receipts):
        if endpoint=='BWIBBU':return [['115年10月21日','','','--']]
        return []
    monkeypatch.setattr(m,'read_month',rows)
    with pytest.raises(ValueError,match='Revised PE overlap'):
        m.prepare(data,'2026-10-22',Path('/unused'))


def test_collector_baseline_uses_observed_date_not_morning_edition(monkeypatch):
    m=load('prepare_stock_audit_day')
    data=json.loads((ROOT/'reports/stock-audit-2026-10-21.json').read_text())
    data.update(report_date='2026-10-22',data_as_of='2026-10-21',review_provenance={'stale':True})
    monkeypatch.setattr(m,'read_month',lambda *args: [])
    prepared=m.prepare(data,'2026-10-21',Path('/unused'))
    assert prepared['report_date']=='2026-10-21'
    assert 'data_as_of' not in prepared and 'review_provenance' not in prepared
    assert all('research' not in s and 'financial_review' not in s for s in prepared['stocks'])
