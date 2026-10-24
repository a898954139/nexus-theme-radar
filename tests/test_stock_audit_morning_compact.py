"""Morning brief AC: numerical evidence plus insight, not binary trade status."""
import json
from pathlib import Path
from copy import deepcopy
from bs4 import BeautifulSoup
from scripts import render_stock_audit as renderer

ROOT=Path(__file__).parents[1]

def snapshot():
    return json.loads((ROOT/'reports/stock-audit-2026-10-21.json').read_text())


def test_morning_cards_show_method_insights_and_numeric_entry_table():
    soup=BeautifulSoup(renderer.render(snapshot()),'html.parser')
    for card in soup.select('details.stock'):
        body=card.select_one('.stock-body')
        sections=body.select(':scope > .technical-summary .method-summary')
        assert [s['data-method'].upper() for s in sections]==['PVA','OB','FVG']
        assert all(s.select_one('.method-value').text.strip() and s.select_one('.method-insight').text.strip() for s in sections)
        table=body.select_one(':scope > .entry-plan')
        assert table and [h.text for h in table.select('thead th')]==['規劃','價位','確認條件']
        entry=table.select_one('tbody tr[data-kind="entry"]')
        assert entry and any(c.isdigit() for c in entry.select_one('.level-price').text)
        assert '不進場' not in entry.text
        assert not body.select(':scope > .entry-outlook, :scope > .quick-context, :scope > .quick-verdict')
        assert not card.select_one('.analysis').has_attr('open')


def test_conditional_entry_figures_have_independent_expected_ranges_and_raw_state_stays_no_trade():
    expected={'2317':(251,253.5),'2308':(1665,1775),'2454':(4360,4475),'3017':(3285,3285),'2368':(1215,1215)}
    data=snapshot();soup=BeautifulSoup(renderer.render(data),'html.parser')
    for stock in data['stocks']:
        assert stock['technical_analysis']['plan']['status']=='no_trade'
        cell=soup.select_one('#stock-'+stock['symbol']+' .entry-plan tr[data-kind="entry"] .level-price')
        assert (float(cell['data-low']),float(cell['data-high']))==expected[stock['symbol']]


def test_morning_brief_rejects_unbacked_numbers_and_false_zone_lifecycle():
    for mutate in [
        lambda b:b['pva'].update(P=999),
        lambda b:b['entry_rows'][0].update(low=99999),
        lambda b:b['entry_rows'][1]['low_ref'].update(source_id='made-up-source'),
        lambda b:b.update(executable_now=True),
        lambda b:b['zones'][0].update(state='active'),
    ]:
        data=snapshot();stock=next(s for s in data['stocks'] if s['symbol']=='2308')
        mutate(stock['research']['morning_brief'])
        assert not renderer.valid_morning_brief(stock)
        assert not BeautifulSoup(renderer.render(data),'html.parser').select_one('#stock-2308')


def test_short_insights_and_conditions_are_escaped_not_executable_markup():
    data=snapshot();brief=data['stocks'][0]['research']['morning_brief']
    payload='<img src=x onerror=alert(1)>'
    brief['pva']['insight']=payload;brief['entry_rows'][0]['condition']=payload;brief['entry_band']['condition']=payload
    card=BeautifulSoup(renderer.render(data),'html.parser').select_one('#stock-2317')
    assert not card.select('img,script') and payload in card.select_one('.method-insight').text
    assert payload in card.select_one('.entry-plan').text


def test_true_ohlc_from_other_date_cannot_replace_declared_fvg_entry():
    data=snapshot();stock=data['stocks'][0];b=stock['research']['morning_brief'];c=stock['technical_candles'][0]
    ref={'source_id':'D1:candle-0-'+c['date'],'field':'close'}
    for row in [b['entry_rows'][0],b['entry_band']]:
        row.update(low=c['close'],high=c['close'],low_ref=ref.copy(),high_ref=ref.copy())
    assert not renderer.valid_morning_brief(stock)
    assert not BeautifulSoup(renderer.render(data),'html.parser').select_one('#stock-2317')


def test_unverified_weekly_copy_cannot_change_a_planned_price():
    data=snapshot();stock=next(s for s in data['stocks'] if s['symbol']=='2368');b=stock['research']['morning_brief']
    ref=b['entry_band']['low_ref'];index=int(ref['source_id'].split(':candle-')[1].split('-')[0])
    stock['technical_analysis']['timeframes']['W1']['candles'][index][ref['field']]=999999
    for row in [b['entry_rows'][0],b['entry_band']]:row.update(low=999999,high=999999)
    assert not renderer.valid_morning_brief(stock)
    assert not BeautifulSoup(renderer.render(data),'html.parser').select_one('#stock-2368')


def test_incomplete_entry_band_is_excluded_instead_of_crashing_report():
    for missing in ['low','high','condition','timeframe','low_ref','high_ref',None]:
        data=snapshot();b=data['stocks'][0]['research']['morning_brief']
        if missing is None:b['entry_band']={}
        else:b['entry_band'].pop(missing)
        assert not renderer.valid_morning_brief(data['stocks'][0])
        assert not BeautifulSoup(renderer.render(data),'html.parser').select_one('#stock-2317')
