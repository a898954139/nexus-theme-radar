"""Actual PVA/Nexus report AC: no label-only upgrades or fabricated trade levels."""
from copy import deepcopy
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from scripts import render_stock_audit as renderer
from scripts.stock_audit_technical_contract import valid_technical

ROOT = Path(__file__).parents[1]


def snapshot():
    return json.loads((ROOT/'reports/stock-audit-2026-10-21.json').read_text())


def test_public_report_is_based_on_executed_pva_and_nexus_not_old_disclaimers():
    soup = BeautifulSoup((ROOT/'reports/stock-audit-2026-10-21.html').read_text(),'html.parser')
    assert len(soup.select('details.stock')) == 5
    for card in soup.select('details.stock'):
        assert card.select_one('.technical-summary [data-method="pva"]') is not None
        assert 'W1' in card.select_one('.chart-basis').text and 'D1' in card.select_one('.chart-basis').text
        assert card.select_one('.pva-diagnostics') is not None
        assert card.select_one('.structure-evidence') is not None
        assert '未使用 PVA' not in card.text
        assert '2R 毛目標' not in card.text


def test_every_stock_has_real_ready_source_linked_analysis_and_completed_weekly_bars():
    data=snapshot()
    for stock in data['stocks']:
        assert valid_technical(stock,data['report_date']),stock['symbol']
        t=stock['technical_analysis']
        assert len(stock['technical_candles'])>=600
        assert t['pva']['post_seed_bar_count']>=400
        assert t['timeframes']['W1']['as_of']=='2026-10-16'
        assert t['pva']['latest']['date']=='2026-10-21'
        assert t['pva']['settings']['anchor_mode']=='EMA'
        assert t['plan']['status'] in {'conditional','no_trade'}
    assert next(s for s in data['stocks'] if s['symbol']=='2317')['technical_excluded_rows']


def test_no_trade_is_complete_analysis_not_a_missing_candidate_or_fake_price():
    data=snapshot();html=renderer.render(data);soup=BeautifulSoup(html,'html.parser')
    for stock in data['stocks']:
        p=stock['technical_analysis']['plan'];card=soup.select_one('#stock-'+stock['symbol'])
        assert card is not None
        if p['status']=='no_trade':
            assert all(p[k] is None for k in ['entry','add','stop']) and p['targets']==[]
            assert card.select_one('.action').text=='D1 回踩規劃'
            assert '不進場' not in card.select_one('.entry-plan').text
            assert '非觸價委託' in card.select_one('.entry-plan').text
            assert stock['research']['operation_rationale'] in card.select_one('.operations').text


def test_technical_corruption_fails_closed_without_restoring_old_2r_plans():
    base=snapshot()
    for change in [
        lambda s:s['technical_analysis']['pva']['latest'].update(P=999),
        lambda s:s['technical_analysis'].update(candle_sha256='0'*64),
        lambda s:s['technical_analysis']['method_receipts'][1].update(source_sha256='0'*64),
        lambda s:s['technical_analysis']['plan'].update(entry=999,add=1000,stop=1),
        lambda s:s.pop('technical_analysis'),
    ]:
        data=deepcopy(base);change(data['stocks'][0]);assert not valid_technical(data['stocks'][0],data['report_date'])
        soup=BeautifulSoup(renderer.render(data),'html.parser');assert not soup.select_one('#stock-2317');assert len(soup.select('details.stock'))==4


def test_only_valid_unexhausted_source_zones_are_drawn_as_ob_or_fvg():
    data=snapshot();soup=BeautifulSoup(renderer.render(data),'html.parser')
    total=0
    for stock in data['stocks']:
        zones={z['id']:z for z in stock['technical_analysis']['zones']}
        card=soup.select_one('#stock-'+stock['symbol'])
        for rect in card.select('.poi-zone'):
            total+=1;z=zones[rect['data-source-id']]
            assert z['chart_only_active'] and z['reviewed_valid']
            assert not z['exhausted'] and not z['invalidation'] and not z['expired']
            assert float(rect['data-low'])==z['low'] and float(rect['data-high'])==z['high']
            assert rect['data-timeframe']==z['timeframe']
    assert total>0


def test_legacy_financial_and_price_evidence_was_not_changed_by_technical_rebuild():
    from scripts.stock_audit_technical_contract import canonical_hash
    expected={
        '2317':'2422b0912cf5396d66ed4a79c02027d509a9621057ec0314ebc6816e536f712a',
        '2308':'b59652d5034a5db189e5512047dd9109dba192b42ed742c07c1e6771ccf64175',
        '2454':'090a733933cded7a0d1a97cb507b2ef78a31596a25ed12a2f9c866adc61f54bc',
        '3017':'95d415a36118da4ee56e7dd9b96334e898c1c001b401ff070a2d3ec3bbca9c0b',
        '2368':'fa258f0f50e02e7a1ba9209a568f45ef6f881d13d5928810f1d57e05217da9e0',
    }
    keys=['symbol','name','candles','pe_history','financial','sources']
    for stock in snapshot()['stocks']:
        assert canonical_hash({k:stock[k] for k in keys})==expected[stock['symbol']]


def test_linked_pva_history_corruption_is_rejected_even_when_latest_equations_match():
    data = snapshot(); stock = data['stocks'][0]
    pva = stock['technical_analysis']['pva']; prev, last = pva['nullable_timeline'][-2:]
    prev['anchor'] += 100
    candle = stock['technical_candles'][-1]
    last['anchor'] = prev['anchor'] + ((candle['high']+candle['low']+candle['close'])/3-prev['anchor'])*2/201
    last['P'] = (candle['close']-last['anchor'])/last['ATR']
    last['V'] = .5*(last['P']-prev['P'])+.5*prev['V']
    last['A'] = last['V']-prev['V']
    pva['latest'].update({k:last[k] for k in ['P','V','A','anchor','ATR']})
    assert not valid_technical(stock,data['report_date'])


def test_no_trade_observation_target_must_have_a_real_matching_source():
    data = snapshot(); stock = next(s for s in data['stocks'] if s['symbol']=='3017')
    stock['technical_analysis']['plan']['watch_levels']['targets'] = [{'price':999999,'source_id':'NONEXISTENT'}]
    assert not valid_technical(stock,data['report_date'])
    soup = BeautifulSoup(renderer.render(data),'html.parser')
    assert not soup.select_one('#stock-3017')
    assert '999,999' not in soup.text


def test_canonical_review_cites_actual_bars_and_rejects_stale_direction_or_swept_floor():
    data=snapshot();by={s['symbol']:s for s in data['stocks']}
    assert by['2317']['technical_analysis']['structure']['W1']['phase']=='range'
    assert 'defense' not in by['2317']['technical_analysis']['plan']['watch_levels']
    assert by['2454']['technical_analysis']['structure']['W1']['bias']=='neutral'
    assert by['2368']['technical_analysis']['structure']['W1']['phase']=='range'
    for symbol,stock in by.items():
        review=stock['technical_analysis']['canonical_review']
        assert len(review['reviews'])==3
        assert all(q['price_citations'] and q['reason'] for q in review['reviews'])
        stock['technical_analysis']['canonical_review']['reviews'][0]['price_citations'][0]['value']+=999
        assert not valid_technical(stock,data['report_date']),symbol


def test_contract_independently_rejects_conditional_entry_inside_opposing_supply():
    from scripts.stock_audit_technical_contract import _validate_plan
    candles=[{'date':f'2026-10-{i:02d}','close':100} for i in range(16,22)]
    trigger={'source_id':'high','kind':'swing_high','index':1,'confirmed_at_index':3,'date':'2026-10-17','price':110,'classification':'strong'}
    defense={'source_id':'low','kind':'swing_low','index':2,'price':90}
    target={'source_id':'target','kind':'swing_high','price':150,'index':0,'confirmed_at_index':1,'date':'2026-10-16'}
    analysis={'timeframes':{'D1':{'pivots':[trigger,defense,target]},'W1':{'pivots':[]}},'zones':[],
              'pva':{'latest':{'ATR':2}},'structure':{'W1':{'bias':'neutral'}},
              'plan':{'status':'conditional','timeframe':'D1','as_of':'2026-10-21','reason':'fixture','wait_condition':'fixture',
                      'entry':110.5,'add':111,'stop':87.9,'trigger_source':'high','defense_source':'low',
                      'targets':[{'source_id':'target','price':149.5,'rr':39/22.6}]}}
    assert _validate_plan(analysis,candles)  # independent, valid hand-calculated baseline
    analysis['zones'].append({'id':'supply','type':'ob','dir':-1,'low':105,'high':115,'chart_only_active':True})
    assert not _validate_plan(analysis,candles)
    analysis['zones']=[]
    candles[-1]['close']=120
    assert not _validate_plan(analysis,candles)  # not a future trigger above current price
    candles[-1]['close']=100
    candles[-2]['close']=111
    assert not _validate_plan(analysis,candles)  # already broken cannot be recycled


def test_watch_source_cannot_be_swapped_to_an_unreviewed_older_pivot():
    data=snapshot();stock=next(s for s in data['stocks'] if s['symbol']=='3017')
    analysis=stock['technical_analysis']
    older=next(p for p in analysis['timeframes']['D1']['pivots'] if p['kind']=='swing_low' and p['date']<'2024-01-01')
    analysis['plan']['watch_levels']['defense']=deepcopy(older)
    assert not valid_technical(stock,data['report_date'])
    assert not BeautifulSoup(renderer.render(data),'html.parser').select_one('#stock-3017')


def test_full_conditional_boundary_rejects_skipping_a_near_barrier_for_far_rr():
    """Test-only review override proves the boundary, not a real eligible trade.

    Published discretionary reviews remain no_trade. Real candles, indicator
    chains and source IDs are retained; hypothetical qualification is explicit.
    """
    from scripts.stock_audit_technical_contract import _next_tick, _previous_tick
    data=snapshot();stock=data['stocks'][0];a=stock['technical_analysis']
    reviews={q['role']:q for q in a['canonical_review']['reviews']}
    for role in ['trigger','defense']:
        reviews[role].update(qualification='qualified',execution_qualified=True)
    sources={p['source_id']:p for p in a['timeframes']['D1']['pivots']}
    trigger=sources[reviews['trigger']['source_id']];defense=sources[reviews['defense']['source_id']]
    zone=next(z for z in a['zones'] if z['chart_only_active'] and z['dir']==-1 and z['low']==292.5)
    entry=_next_tick(trigger['price']);stop=_previous_tick(defense['price']-a['pva']['latest']['ATR'])
    target=_previous_tick(zone['low'])
    a['plan']={'status':'conditional','timeframe':'D1','as_of':data['report_date'],'reason':'TEST ONLY hypothetical qualification',
               'wait_condition':'TEST ONLY future close and follow-through','entry':entry,'add':_next_tick(entry),'stop':stop,
               'trigger_source':trigger['source_id'],'defense_source':defense['source_id'],
               'targets':[{'source_id':zone['id'],'price':target,'rr':(target-entry)/(entry-stop)}]}
    # Far292 target cannot bypass real259/266.5 liquidity barriers.
    assert not valid_technical(stock,data['report_date'])
    other=next(p for p in a['timeframes']['D1']['pivots'] if p['kind']=='swing_low' and p['date']<'2024-01-01')
    a['plan']['defense_source']=other['source_id']
    a['plan']['stop']=_previous_tick(other['price']-a['pva']['latest']['ATR'])
    a['plan']['targets'][0]['rr']=(target-entry)/(entry-a['plan']['stop'])
    assert not valid_technical(stock,data['report_date'])


def test_expected_entry_conditions_are_visible_without_opening_analysis():
    data=snapshot();soup=BeautifulSoup(renderer.render(data),'html.parser')
    expected={'2317':('251–253.5','251'),'2308':('1,665–1,775','1,790'),
              '2454':('4,360–4,475','4,400'),'3017':('3,285','3,050'),'2368':('1,215','1,310')}
    for stock in data['stocks']:
        card=soup.select_one('#stock-'+stock['symbol'])
        table=card.select_one(':scope > .stock-body > .entry-plan')
        assert table is not None and '條件進場' in table.text
        assert all(level in table.text for level in expected[stock['symbol']])
        assert stock['research']['entry_outlook'] in card.select_one('.operations').text
        assert not card.select_one('details.analysis').has_attr('open')
        assert card.select_one('.action').text=='D1 回踩規劃'
    assert '不是預定進場日期' in soup.text
