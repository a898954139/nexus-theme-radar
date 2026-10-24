"""Reader sees conclusions and numerical signals, not implementation narration."""
import json
from pathlib import Path
from bs4 import BeautifulSoup
from scripts import render_stock_audit as renderer
ROOT=Path(__file__).parents[1]

def test_technical_details_omit_process_narration_and_method_fingerprints():
    data=json.loads((ROOT/'reports/stock-audit-2026-10-21.json').read_text())
    soup=BeautifulSoup(renderer.render(data),'html.parser')
    assert not soup.select('.technical-basis')
    for forbidden in ['此版本與 Pine v2.1','EMA seed 後有','方法指紋：','另逐檔依市場拒絕','detector']:
        assert forbidden not in soup.get_text()
    assert len(soup.select('.structure-evidence'))==5


def test_numbers_have_sign_and_role_semantics_without_color_only_meaning():
    soup=BeautifulSoup(renderer.render(json.loads((ROOT/'reports/stock-audit-2026-10-21.json').read_text())),'html.parser')
    assert soup.select('.metric-positive') and soup.select('.metric-negative')
    for node in soup.select('.method-summary[data-method="pva"] .metric-positive'):
        assert '+' in node.text
    for node in soup.select('.method-summary[data-method="pva"] .metric-negative'):
        assert '-' in node.text
    assert all(c.select_one('.entry-plan tr[data-kind="entry"] .metric-entry') for c in soup.select('.stock'))


def test_sign_classes_treat_zero_as_neutral_and_keep_original_palette_roles():
    assert renderer.metric_sign_class(0)=='metric-neutral'
    assert renderer.metric_sign_class(-1)=='metric-negative'
    assert renderer.metric_sign_class(1)=='metric-positive'
    css=(ROOT/'reports/stock-audit.css').read_text()
    for cls,token in [('positive','red'),('negative','green'),('entry','gold'),('neutral','text'),('muted','muted')]:
        assert f'.metric-{cls} {{ color: var(--{token}); }}' in css


def test_zone_directions_and_break_date_meaning_survive_without_colors():
    data=json.loads((ROOT/'reports/stock-audit-2026-10-21.json').read_text())
    soup=BeautifulSoup(renderer.render(data),'html.parser')
    for stock in data['stocks']:
        card=soup.select_one('#stock-'+stock['symbol'])
        for item in card.select('.method-summary[data-source-id]'):
            source=next(z for z in stock['technical_analysis']['zones'] if z['id']==item['data-source-id'])
            assert ('多方' if source['dir']==1 else '空方') in item.text
        events=[e for tf in ['D1','W1'] for e in stock['technical_analysis']['timeframes'][tf]['breaks'] if not e['internal']]
        if events:assert '偵測確認' in card.select_one('.structure-evidence').text


def test_taiwan_signed_values_use_red_up_green_down_and_risk_is_separate():
    css=(ROOT/'reports/stock-audit.css').read_text()
    assert '.metric-positive { color: var(--red); }' in css
    assert '.metric-negative { color: var(--green); }' in css
    assert '.metric-risk { color: var(--red); }' in css
    assert 'fill: var(--red)' in css.split('.candles .rise rect {',1)[1].split('}',1)[0]
    assert 'stroke: var(--green)' in css.split('.candles .fall rect {',1)[1].split('}',1)[0]


def test_raised_market_red_override_is_screen_only_so_print_stays_neutral():
    css=(ROOT/'reports/stock-audit.css').read_text()
    assert '@media screen { .market-row .metric-positive { color: var(--red-readable); } }' in css
    assert '.metric-entry, .metric-risk, .metric-neutral, .metric-muted { color: var(--text); }' in css


def test_numeric_text_roles_meet_small_text_contrast_on_their_surfaces():
    import re
    css=(ROOT/'reports/stock-audit.css').read_text()
    tokens=dict(re.findall(r'(--[a-z-]+):\s*(#[0-9a-fA-F]{6})',css.split('}',1)[0]))
    def luminance(hex_color):
        channels=[int(hex_color[i:i+2],16)/255 for i in [1,3,5]]
        linear=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in channels]
        return sum(a*b for a,b in zip(linear,[.2126,.7152,.0722]))
    for ink,surface in [('red','card-bg'),('red-readable','surface-bg'),('green','card-bg'),('green','surface-bg'),('gold','card-bg')]:
        a,b=sorted([luminance(tokens['--'+ink]),luminance(tokens['--'+surface])])
        assert (b+.05)/(a+.05)>=4.5,(ink,surface)
