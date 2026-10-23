"""Target-only AC: complete research before render, truthful clocks and native mobile cards."""
import importlib.util
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

ROOT = Path(__file__).parents[1]


def test_target_is_a_decision_card_not_a_research_collage():
    soup = BeautifulSoup((ROOT / 'reports/stock-audit-2026-10-21.html').read_text(), 'html.parser')
    headings = [h.get_text(' ', strip=True) for h in soup.select('main > section > h2')]
    assert headings == ['今日結論', '明日市場預測', '重點標的', '其他標的', '今日執行清單']
    cards = soup.select('details.stock')
    assert 3 <= len(cards) <= 5
    assert [c.has_attr('open') for c in cards] == [True] + [False] * (len(cards) - 1)
    for card in cards:
        assert [h.text for h in card.select('h3')] == ['基本面分析', '技術分析', '操作', '總結']
        assert len(card.select('svg[role="img"]')) == 1
        assert [h.text for h in card.select('.operations h4')] == ['進場時機', '加碼條件', '止損', '止盈']
        assert card.select_one('.price')
    for text in ['待驗證', '待更新', '待確認', 'financial gate', '通過觀察', '回穩', '停買', '第一段', '第二段']:
        assert text not in soup.get_text()
    assert soup.find('script') is None  # No financial work, loading, or JS-only chart in frontend.
    assert not soup.select('table')


def load_renderer():
    spec = importlib.util.spec_from_file_location('audit_renderer', ROOT / 'scripts/render_stock_audit.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source():
    import json
    return json.loads((ROOT / 'reports/stock-audit-2026-10-21.json').read_text())


def test_missing_research_excludes_stock_and_its_recommendation():
    m = load_renderer()
    data = source()
    data['stocks'][0]['financial']['eps'] = None
    html = m.render(data)
    assert '鴻海' not in html
    assert html.count('class="stock"') == 4
    data['stocks'] = data['stocks'][:3]
    with pytest.raises(ValueError, match='3'):
        m.render(data)


def test_wrong_source_dates_or_unusable_ohlcv_do_not_render():
    m = load_renderer()
    for mutate in [
        lambda d: d['stocks'][0]['candles'][-1].update(date='2026-10-22'),
        lambda d: d['stocks'][0]['candles'][-1].update(low=999999),
        lambda d: d['stocks'][0]['financial'].update(revenue_yoy_pct=float('nan')),
        lambda d: d['stocks'][0]['financial'].update(source='javascript:alert(1)'),
        lambda d: d['stocks'][0].update(pe_history=[]),
        lambda d: d['stocks'][0].update(candles=d['stocks'][0]['candles'][-120:]),
        lambda d: d['stocks'][0].update(candles=d['stocks'][0]['candles'][-148:]),
        lambda d: d['stocks'][0].update(sources=d['stocks'][0]['sources'][:1]),
        lambda d: d['stocks'][0]['financial'].update(gross_margin_period='2025H1'),
        lambda d: d['stocks'][0]['financial'].pop('gross_margin_period'),
        lambda d: d['stocks'][0].pop('research', None),
    ]:
        d = source(); mutate(d)
        assert '鴻海' not in m.render(d)
    d = source(); d['market']['references'][0]['as_of'] = '2026-10-23T04:00:00+08:00'
    with pytest.raises(ValueError, match='market'):
        m.render(d)
    d = source(); d['market']['references'].pop()
    with pytest.raises(ValueError, match='market'):
        m.render(d)


def test_curve_and_tick_calculations_have_independent_oracles():
    m = load_renderer()
    curve = m.curve([100, 80, 100, 90])
    assert curve['max_drawdown_pct'] == pytest.approx(-20)
    assert curve['ttr_sessions'] == 2
    assert curve['underwater_sessions'] == 1
    assert 0 <= curve['r2'] <= 1
    assert m.next_tick(499.5) == 500
    assert m.next_tick(1000) == 1005
    assert m.previous_tick(1000) == 999
    assert m.previous_tick(500) == 499.5


def test_published_target_matches_reproducible_input_and_all_source_values():
    m = load_renderer(); data = source()
    assert m.render(data) == (ROOT / 'reports/stock-audit-2026-10-21.html').read_text()
    soup = BeautifulSoup(m.render(data), 'html.parser')
    for stock in data['stocks']:
        card = soup.select_one('#stock-' + stock['symbol'])
        assert card is not None
        assert card.select_one('.price').text == m.fmt(stock['candles'][-1]['close']) + ' 元'
        assert '2026-10-21' in card.text
        assert m.fmt(stock['financial']['eps']) in card.text
        assert m.fmt(stock['pe_history'][-1]['pe']) in card.text
        assert len(card.select('.candles rect')) == 90
    assert '2026-10-22 06:00' in soup.text
    assert '預測不是保證' in soup.text
    assert '多方觸發' in soup.text and '空方觸發' in soup.text
    assert '夜盤' in soup.text and '價差' in soup.text


def test_individual_research_is_rendered_not_replaced_by_a_uniform_signal():
    m = load_renderer(); data = source()
    soup = BeautifulSoup(m.render(data), 'html.parser')
    expected = {
        '2317': ('等突破', '不列為長線核心'),
        '2308': ('等回踩', '100 交易日仍未恢復'),
        '2454': ('小部位', '57.17%'),
        '3017': ('小部位', '高波動小部位'),
        '2368': ('等回踩', '51.77%'),
    }
    for symbol, (action, finding) in expected.items():
        card = soup.select_one('#stock-' + symbol)
        assert card.select_one('.action').text == action
        assert finding in card.text
    del data['stocks'][0]['research']['valuation']
    assert '鴻海' not in m.render(data)


def test_corrupted_precomputed_research_is_excluded_before_render():
    m = load_renderer(); data = source()
    data['stocks'][0]['research']['metrics']['median'] = 1
    assert '鴻海' not in m.render(data)


def test_report_keeps_original_nexus_font_roles():
    """The main site's font faces and weights are the independent brand reference."""
    from urllib.parse import parse_qs, urlparse
    css = (ROOT / 'reports/stock-audit.css').read_text()
    main = BeautifulSoup((ROOT / 'index.html').read_text(), 'html.parser')
    report = BeautifulSoup((ROOT / 'reports/stock-audit-2026-10-21.html').read_text(), 'html.parser')
    main_url = next(a['href'] for a in main.select('link[href]') if 'fonts.googleapis.com/css2' in a['href'])
    report_url = next(a['href'] for a in report.select('link[href]') if 'fonts.googleapis.com/css2' in a['href'])
    assert set(parse_qs(urlparse(report_url).query)['family']) == set(parse_qs(urlparse(main_url).query)['family'])
    assert "font-family: 'IBM Plex Sans', 'Noto Sans TC', system-ui, sans-serif" in css
    assert "font-family: 'Space Grotesk', sans-serif" in css
    assert "font-family: 'IBM Plex Mono', 'Noto Sans TC', ui-monospace, monospace" in css
    for selector in ['h1', 'h2', 'h3', 'h4', '.lead', '.identity strong']:
        block = css.split(selector + ' {', 1)[1].split('}', 1)[0]
        assert 'font-weight: 500' in block, selector


def test_report_versions_css_so_existing_readers_get_new_fonts():
    import hashlib
    from urllib.parse import parse_qs, urlparse
    soup = BeautifulSoup((ROOT / 'reports/stock-audit-2026-10-21.html').read_text(), 'html.parser')
    stylesheet = next(a['href'] for a in soup.select('link[rel="stylesheet"]') if 'stock-audit.css' in a['href'])
    expected = hashlib.sha256((ROOT / 'reports/stock-audit.css').read_bytes()).hexdigest()[:12]
    assert parse_qs(urlparse(stylesheet).query).get('v') == [expected]


def test_report_uses_original_nexus_palette_and_color_roles():
    import re
    def root_tokens(text):
        root = text.split(':root {', 1)[1].split('}', 1)[0]
        return {k: v.strip() for k, v in re.findall(r'(--[a-z-]+):\s*([^;]+);', root)}
    main = root_tokens((ROOT / 'src/index.css').read_text())
    css = (ROOT / 'reports/stock-audit.css').read_text()
    report = root_tokens(css)
    for key in ['--page-bg', '--shell-bg', '--surface-bg', '--card-bg', '--line', '--sub-line',
                '--text-hi', '--text', '--muted', '--faint', '--gold', '--gold-hover',
                '--gold-bg', '--green', '--red', '--weakest']:
        assert report.get(key) == main[key], key
    for key, value in {'--ground':'var(--page-bg)', '--surface':'var(--card-bg)',
                       '--raised':'var(--surface-bg)', '--rule':'var(--line)',
                       '--accent':'var(--gold)', '--control':'var(--weakest)'}.items():
        assert report[key] == value
    assert 'background: var(--shell-bg)' in css.split('.shell {', 1)[1].split('}', 1)[0]
    assert 'background: var(--gold)' in css.split('.primary {', 1)[1].split('}', 1)[0]
    assert 'fill: var(--green)' in css.split('.candles .rise rect {', 1)[1].split('}', 1)[0]
    assert 'stroke: var(--red)' in css.split('.candles .fall rect {', 1)[1].split('}', 1)[0]


def test_print_keeps_new_palette_roles_readable_on_white_paper():
    import re
    css = (ROOT / 'reports/stock-audit.css').read_text()
    root = css.split('@media print {', 1)[1].split(':root {', 1)[1].split('}', 1)[0]
    tokens = {k:v.strip() for k,v in re.findall(r'(--[a-z-]+):\s*([^;]+);', root)}
    for key in ['--ground','--surface','--shell-bg','--surface-bg']:
        assert tokens.get(key) == '#fff', key
    assert tokens.get('--text-hi') == '#000'
    assert tokens['--text'] == '#000'


def test_scan_layer_exposes_prices_before_optional_analysis():
    m = load_renderer(); data = source()
    soup = BeautifulSoup(m.render(data), 'html.parser')
    for stock in data['stocks']:
        card = soup.select_one('#stock-' + stock['symbol'])
        header = card.find('summary', recursive=False)
        metrics = stock['research']['metrics']
        assert header.select_one('.price').text == m.fmt(metrics['price']) + ' 元'
        assert '2026-10-21' in header.text
        expected = {'entry': metrics['entry'], 'add': metrics['add'], 'stop': metrics['stop'], 'profit': metrics['targets'][0]}
        assert {n['data-level']:n.select_one('b').text for n in header.select('.quick-level')} == {k:m.fmt(v) for k,v in expected.items()}
        assert '短線情境' in header.text and '回踩' in header.text
        analysis = card.select_one('details.analysis')
        assert analysis and not analysis.has_attr('open')
        body = card.select_one('.stock-body')
        assert body.select_one('figure') and body.select_one('.quick-verdict')
        assert body.find('figure', recursive=False)
        assert [h.text for h in analysis.select('h3')] == ['基本面分析','技術分析','操作','總結']
        # Every original research sentence remains in the optional analysis.
        for key in ['fundamentals','valuation','curve','technical','operation_rationale','conclusion']:
            assert stock['research'][key] in analysis.get_text()


def test_chart_highlights_only_sourced_ranges_not_invented_order_blocks():
    m = load_renderer(); data = source()
    soup = BeautifulSoup(m.render(data), 'html.parser')
    for stock in data['stocks']:
        card = soup.select_one('#stock-' + stock['symbol'])
        metrics = stock['research']['metrics']
        chart = card.select_one('svg')
        assert chart.select_one('.range-zone')['data-low'] == str(metrics['support'])
        assert chart.select_one('.range-zone')['data-high'] == str(metrics['resistance'])
        assert chart.select_one('.retest-zone')['data-low'] == str(metrics['resistance'])
        assert chart.select_one('.retest-zone')['data-high'] == str(metrics['entry'])
        assert chart.select_one('.current-price-line')['data-price'] == str(metrics['price'])
        assert not chart.select('[data-zone-type="ob"]')
        assert '非 OB' in card.select_one('figcaption').text


def test_overlay_geometry_uses_actual_price_scale_not_just_labels():
    """Hand-worked oracle: padded scale88.2–112.2, 144px /24=6px per TWD."""
    from datetime import date, timedelta
    m = load_renderer()
    candles = [dict(date=str(date(2025,1,1)+timedelta(days=i)),open=100,high=110,low=90,close=100,volume=10) for i in range(149)]
    stock = dict(name='fixture',symbol='0000',candles=candles)
    html = BeautifulSoup(m.chart(stock,dict(support=90,resistance=110,entry=111,price=100)), 'html.parser')
    zone = html.select_one('.range-zone'); retest = html.select_one('.retest-zone')
    assert float(zone['y']) == pytest.approx(33.2)
    assert float(zone['height']) == pytest.approx(120)
    assert float(retest['y']) == pytest.approx(27.2)
    assert float(retest['height']) == pytest.approx(6)
    assert html.select_one('.current-price-line')['d'] == 'M10 93.20H500'


def test_technical_basis_is_explicit_in_preview_and_expanded_analysis():
    m = load_renderer(); data = source()
    soup = BeautifulSoup(m.render(data), 'html.parser')
    for stock in data['stocks']:
        card = soup.select_one('#stock-' + stock['symbol'])
        basis = card.select_one('.chart-basis')
        assert basis is not None
        assert basis.find_parent('details', class_='analysis') is None
        assert '日 K（D1）' in basis.text
        assert stock['candles'][-1]['date'] in basis.text and '收盤' in basis.text
        assert 'MA20／MA60' in basis.text and '近 20 日高低區間' in basis.text
        assert '參考 Nexus 框架' in basis.text
        assert '非完整結構分析' in basis.text and '未使用 PVA' in basis.text
        caption = card.select_one('figcaption').text
        assert stock['candles'][-90]['date'] in caption and stock['candles'][-1]['date'] in caption
        assert '90 交易日' in caption
        detail = card.select_one('.technical-basis')
        assert detail is not None and detail.find_parent('details', class_='analysis')
        assert 'D1' in detail.text and '4H／1H／分 K' in detail.text
        assert stock['candles'][0]['date'] in detail.text and str(len(stock['candles'])) in detail.text
        assert '成交量僅展示，未執行 PVA' in detail.text
