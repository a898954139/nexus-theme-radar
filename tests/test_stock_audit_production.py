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
