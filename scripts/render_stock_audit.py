"""Pre-render the standalone, dated decision card. No network or browser calculations.

Input is a separate research snapshot, never the hourly/watchlist payload. Incomplete
candidates are excluded, and fewer than three complete candidates block output.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from html import escape
import hashlib
import json
import math
from pathlib import Path
import statistics
from urllib.parse import urlparse


def fmt(value):
    return f'{value:,.2f}'.rstrip('0').rstrip('.')


def pct(value):
    return f'{value:+.2f}%'


def link(url, label):
    return f'<a href="{escape(url, quote=True)}" rel="noreferrer">{escape(label)}</a>'


def http_url(value):
    parsed = urlparse(value) if isinstance(value, str) else None
    return parsed and parsed.scheme == 'https' and parsed.netloc and not parsed.username and not parsed.password


def finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def tick(value):
    for ceiling, size in [(10, '.01'), (50, '.05'), (100, '.1'), (500, '.5'), (1000, '1')]:
        if value < ceiling:
            return Decimal(size)
    return Decimal('5')


def next_tick(value):
    v = Decimal(str(value)); step = tick(value)
    return float((v / step).to_integral_value(rounding=ROUND_FLOOR) * step + step)


def previous_tick(value):
    v = Decimal(str(value)); step = tick(float(v - Decimal('.000001')))
    return float((v / step).to_integral_value(rounding=ROUND_CEILING) * step - step)


def curve(closes):
    returns = [b / a - 1 for a, b in zip(closes, closes[1:])]
    std = statistics.stdev(returns)
    downside = math.sqrt(statistics.mean(min(r, 0) ** 2 for r in returns))
    if not std or not downside:
        raise ValueError('Undefined curve diagnostics')
    peak = closes[0]; start = None; recovered = []; worst = 0
    for i, close in enumerate(closes[1:], 1):
        worst = min(worst, (close / peak - 1) * 100)
        if close >= peak:
            if start is not None:
                recovered.append(i - start)
            peak, start = close, None
        elif start is None:
            start = i - 1
    # R² on log(close) against trading-session index; not a forecast or qualification.
    logs = [math.log(c) for c in closes]; center = (len(logs) - 1) / 2
    ybar = statistics.mean(logs)
    slope = sum((i - center) * (y - ybar) for i, y in enumerate(logs)) / sum((i - center) ** 2 for i in range(len(logs)))
    total = sum((y - ybar) ** 2 for y in logs)
    error = sum((y - (ybar + slope * (i - center))) ** 2 for i, y in enumerate(logs))
    return dict(sharpe=statistics.mean(returns) / std * math.sqrt(252),
                sortino=statistics.mean(returns) / downside * math.sqrt(252),
                max_drawdown_pct=worst, ttr_sessions=max(recovered, default=0),
                underwater_sessions=0 if start is None else len(closes) - 1 - start,
                r2=max(0, min(1, 1 - error / total)) if total else 0)


def same_metrics(stored, computed):
    """Permit only floating-point roundoff across Python runtimes, not changed facts."""
    if isinstance(computed, dict):
        return isinstance(stored, dict) and stored.keys() == computed.keys() and all(
            same_metrics(stored[k], v) for k, v in computed.items())
    if isinstance(computed, list):
        return isinstance(stored, list) and len(stored) == len(computed) and all(
            same_metrics(a, b) for a, b in zip(stored, computed))
    if finite(computed):
        return finite(stored) and math.isclose(stored, computed, rel_tol=1e-10, abs_tol=1e-8)
    return stored == computed


def complete_stock(stock, report_date):
    try:
        f = stock['financial']; candles = stock['candles']; history = stock['pe_history']
        if not str(stock['symbol']).isdigit() or len(str(stock['symbol'])) != 4 or not stock['name']:
            return False
        for key in ['revenue_twd_100m', 'revenue_yoy_pct', 'eps', 'gross_margin_pct']:
            if not finite(f[key]):
                return False
        if f['revenue_twd_100m'] <= 0 or f['eps'] <= 0 or not 0 <= f['gross_margin_pct'] <= 100:
            return False
        if f['revenue_month'] != '2026-09' or f['eps_period'] != '2026H1' or f['gross_margin_period'] != '2026H1' or not http_url(f['source']) or not http_url(f['income_source']):
            return False
        if not f['unit_verified'] or not f['period_verified']:
            return False
        if len(stock['sources']) != 2 or not all(http_url(url) for url in stock['sources']):
            return False
        if len(candles) < 149 or len(history) < 60:
            return False
        for rows in [candles, history]:
            dates = [date.fromisoformat(c['date']).isoformat() for c in rows]
            if dates != sorted(set(dates)) or dates[-1] != report_date:
                return False
        for c in candles:
            if not all(finite(c[k]) and c[k] > 0 for k in ['open', 'high', 'low', 'close']):
                return False
            if not finite(c['volume']) or c['volume'] < 0 or not c['low'] <= min(c['open'], c['close']) <= max(c['open'], c['close']) <= c['high']:
                return False
        if not all(finite(p['pe']) and p['pe'] > 0 for p in history):
            return False
        research = stock['research']
        for key in ['investment_type', 'action', 'fundamentals', 'valuation', 'curve', 'technical', 'operation_rationale', 'conclusion']:
            if not isinstance(research[key], str) or not research[key].strip():
                return False
        if not all(isinstance(research['nexus'][key], str) and research['nexus'][key].strip()
                   for key in ['bias', 'phase', 'actionability', 'pullback', 'invalidation', 'timeframe']):
            return False
        # Verify precomputed research against source facts; never invent a decision here.
        if not same_metrics(research['metrics'], metrics(stock)):
            return False
        return True
    except (KeyError, TypeError, ValueError, statistics.StatisticsError):
        return False


def validate_market(market, cutoff):
    try:
        refs = market['references']
        if {r['label'] for r in refs} != {'Nasdaq', 'S&P 500', '費城半導體', 'NVIDIA', 'Microsoft', 'Apple', '台指期夜盤'} or len(refs) != 7:
            raise ValueError('market categories')
        stop = datetime.fromisoformat(cutoff)
        for r in refs:
            observed = datetime.fromisoformat(r['as_of'])
            expected = '2026-10-22T05:00:00+08:00' if r['label'] == '台指期夜盤' else '2026-10-22T04:00:00+08:00'
            if observed != datetime.fromisoformat(expected) or observed > stop or not http_url(r['source']) or not finite(r['value']) or r['value'] <= 0 or not finite(r['change_pct']):
                raise ValueError('market source/clock')
        if not finite(market['spot_close']) or market['spot_close'] <= 0 or not http_url(market['spot_source']):
            raise ValueError('market spot')
        night = refs[-1]
        if night['label'] != '台指期夜盤' or not all(finite(market[k]) for k in ['night_high', 'night_low']):
            raise ValueError('market night')
        if not market['night_low'] <= night['value'] <= market['night_high']:
            raise ValueError('market range')
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f'Invalid market research: {exc}') from exc


def metrics(stock):
    candles = stock['candles']; closes = [c['close'] for c in candles]
    pes = [p['pe'] for p in stock['pe_history']]; price = closes[-1]
    ma20 = statistics.mean(closes[-20:]); ma60 = statistics.mean(closes[-60:])
    support = min(c['low'] for c in candles[-20:]); resistance = max(c['high'] for c in candles[-20:])
    premium = (pes[-1] / statistics.median(pes) - 1) * 100
    valuation = '高於歷史中位數' if premium > 0 else '低於歷史中位數' if premium < 0 else '等於歷史中位數'
    if price >= ma20 >= ma60:
        bias, phase = '中期偏多', '趨勢延續'
    elif price < ma20 and ma20 >= ma60:
        bias, phase = '中期偏多', '短線回踩'
    elif price < ma20 < ma60:
        bias, phase = '中期偏空', '修正階段'
    else:
        bias, phase = '中期中性', '區間整理'
    entry = next_tick(resistance); stop = previous_tick(support)
    add = next_tick(entry)
    targets = []
    for window in [20, 60, 120]:
        high = max(c['high'] for c in candles[-window:])
        low = min(c['low'] for c in candles[-window:])
        buy = next_tick(high); risk = buy - previous_tick(low)
        raw = buy + 2 * risk
        step = tick(raw)
        target = float((Decimal(str(raw)) / step).to_integral_value(rounding=ROUND_CEILING) * step)
        targets.append(target)
    return dict(price=price, ma20=ma20, ma60=ma60, support=support, resistance=resistance,
                premium=premium, pe=pes[-1], median=statistics.median(pes), pe_low=min(pes), pe_high=max(pes),
                valuation=valuation, bias=bias, phase=phase, entry=entry, stop=stop, add=add, targets=targets,
                distance_high=(price / max(c['high'] for c in candles) - 1) * 100,
                curve=curve(closes))


def chart(stock, m):
    allbars = stock['candles']; bars = allbars[-90:]; width = 600; right = 500
    averages = {window: [statistics.mean(c['close'] for c in allbars[end-window:end])
                        for end in range(len(allbars)-89, len(allbars)+1)] for window in [20, 60]}
    lo = min(min(c['low'] for c in bars), *averages[20], *averages[60]) * .98
    hi = max(max(c['high'] for c in bars), *averages[20], *averages[60]) * 1.02
    y = lambda p: 20 + (hi - p) / (hi - lo) * 144
    x = lambda i: 10 + i * (right - 10) / (len(bars) - 1)
    vmax = max(c['volume'] for c in bars) or 1
    out = [f'<svg viewBox="0 0 {width} 240" role="img" aria-labelledby="chart-{stock["symbol"]}"><title id="chart-{stock["symbol"]}">{escape(stock["name"])}近90交易日日K、成交量、20日及60日均線；{bars[0]["date"]}至{bars[-1]["date"]}</title>']
    for value in [lo, (lo + hi) / 2, hi]:
        out.append(f'<path class="grid" d="M10 {y(value):.2f}H{right}"/>')
    zone_x = x(len(bars) - 20)
    out.append(f'<rect class="range-zone" data-low="{m["support"]}" data-high="{m["resistance"]}" x="{zone_x:.2f}" y="{y(m["resistance"]):.2f}" width="{right-zone_x:.2f}" height="{y(m["support"])-y(m["resistance"]):.2f}"/>')
    out.append(f'<rect class="retest-zone" data-low="{m["resistance"]}" data-high="{m["entry"]}" x="{zone_x:.2f}" y="{y(m["entry"]):.2f}" width="{right-zone_x:.2f}" height="{y(m["resistance"])-y(m["entry"]):.2f}"/>')
    out.append(f'<path class="range-boundary" d="M{zone_x:.2f} {y(m["support"]):.2f}H{right} M{zone_x:.2f} {y(m["resistance"]):.2f}H{right}"/>')
    out.append('<g class="candles">')
    for i, c in enumerate(bars):
        state = 'rise' if c['close'] >= c['open'] else 'fall'
        out.append(f'<g class="{state}"><path d="M{x(i):.2f} {y(c["high"]):.2f}V{y(c["low"]):.2f}"/><rect x="{x(i)-1.7:.2f}" y="{min(y(c["open"]),y(c["close"])):.2f}" width="3.4" height="{max(1,abs(y(c["close"])-y(c["open"]))):.2f}"/></g>')
    out.append('</g><g class="volume">')
    for i, c in enumerate(bars):
        height = 36 * c['volume'] / vmax
        out.append(f'<rect x="{x(i)-1.7:.2f}" y="{214-height:.2f}" width="3.4" height="{height:.2f}"/>')
    out.append('</g>')
    for window in [20, 60]:
        points = []
        for i in range(len(bars)):
            end = len(allbars) - len(bars) + i + 1
            value = statistics.mean(c['close'] for c in allbars[end-window:end])
            points.append(f'{"M" if not points else "L"}{x(i):.2f},{y(value):.2f}')
        out.append(f'<path class="ma ma{window}" d="{" ".join(points)}"/>')
    # Separate label positions without moving their true-price lines.
    previous_label = -6
    for index, (name, value) in enumerate([('resistance', m['resistance']), ('current', m['price']), ('support', m['support'])]):
        actual = y(value)
        label_y = max(previous_label + 26, min(actual, 164 - (2-index)*26))
        previous_label = label_y
        if name == 'current':
            out.append(f'<path class="current-price-line" data-price="{value}" d="M10 {actual:.2f}H{right}"/>')
        out.append(f'<path class="axis-leader" d="M{right+3} {actual:.2f}L{right+12} {label_y:.2f}"/><text class="axis-{name}" x="598" text-anchor="end" y="{label_y+5:.2f}">{fmt(value)}</text>')
    for i in [0, 44, 89]:
        out.append(f'<text x="{x(i):.2f}" y="235" text-anchor="{"start" if i==0 else "end" if i==89 else "middle"}">{bars[i]["date"][5:]}</text>')
    out.append('</svg>')
    return ''.join(out)


def cell(label, value):
    return f'<div><dt>{escape(label)}</dt><dd>{value}</dd></div>'


def stock_card(stock, m, first, day):
    f = stock['financial']; q = m['curve']; symbol = stock['symbol']; name = escape(stock['name'])
    r = stock['research']; summary = escape(r['conclusion'])
    quick = ''.join(f'<span class="quick-level" data-level="{key}"><span>{label}</span><b class="num">{fmt(value)}</b></span>'
                    for key, label, value in [('entry','進場觸發',m['entry']), ('add','加碼',m['add']),
                                              ('stop','止損',m['stop']), ('profit','短止盈',m['targets'][0])])
    brief = escape(r['conclusion'].split('。')[0] + '。')
    preview = f'''<figure class="preview">{chart(stock,m)}<figcaption><span>日 K · 近 90 交易日 · 成交量</span><span class="ma20-key">MA20 {fmt(m['ma20'])}</span><span class="ma60-key">MA60 {fmt(m['ma60'])}</span><span>現價 {fmt(m['price'])}／支撐 {fmt(m['support'])}／壓力 {fmt(m['resistance'])}</span><span>陰影：近 20 日區間；金色窄帶：突破後回踩 {fmt(m['resistance'])}–{fmt(m['entry'])} 元，非 OB。</span></figcaption></figure>'''
    return f'''<details class="stock" id="stock-{symbol}"{' open' if first else ''}>
<summary><span class="identity"><strong>{name} <span class="symbol">{symbol}</span></strong><span class="price">{fmt(m['price'])} 元</span><span class="type">{escape(r['investment_type'])}</span><span class="quote-time">{day} 收盤</span></span><span class="action">{escape(r['action'])}</span><span class="chevron" aria-hidden="true"></span><span class="quick-levels" aria-label="短線情境價位，需符合突破與次日回踩條件">{quick}</span><span class="quick-context">短線情境｜收盤突破，次日回踩才分批；不是現價買入。</span></summary>
<div class="stock-body">{preview}<p class="quick-verdict">{brief}</p>
<details class="analysis"><summary>展開完整分析與操作條件<span aria-hidden="true">＋</span></summary><div class="analysis-body">
<section><h3>基本面分析</h3><p class="meta">價格：{day} 收盤 · 財報：H1 累計／合併口徑</p>
<dl class="facts">{cell('9 月營收',fmt(f['revenue_twd_100m'])+' <small>億元</small>')}{cell('營收年增',pct(f['revenue_yoy_pct']))}{cell('2026 H1 EPS',fmt(f['eps'])+' <small>元</small>')}{cell('H1 毛利率',fmt(f['gross_margin_pct'])+'%')}</dl><p class="reading">{escape(r['fundamentals'])}</p>
<h4>估值位置</h4><dl class="ledger">{cell('目前本益比',fmt(m['pe'])+' 倍')}{cell('歷史 PE 中位數',fmt(m['median'])+' 倍')}{cell('歷史 PE 區間',fmt(m['pe_low'])+'–'+fmt(m['pe_high'])+' 倍')}{cell('相對中位數',pct(m['premium']))}</dl>
<p class="note">{stock['pe_history'][0]['date']}–{day}，{len(stock['pe_history'])} 筆 TWSE PE。歷史相對位置不是合理價；營收成長不等於獲利成長，也不能單獨證明溢價合理。</p>
<p class="reading">{escape(r['valuation'])}</p><h4>成長曲線檢查</h4><dl class="facts curve">{cell('Sharpe',fmt(q['sharpe']))}{cell('Sortino',fmt(q['sortino']))}{cell('最大回撤',fmt(q['max_drawdown_pct'])+'%')}{cell('TTR（最長已恢復）',str(q['ttr_sessions'])+' <small>交易日</small>')}{cell('指數擬合 R²',f"{q['r2']:.3f}")}{cell('本次未恢復回撤',str(q['underwater_sessions'])+' <small>交易日</small>')}</dl>
<p class="note">觀察窗 {stock['candles'][0]['date']}–{day}；未還原權息、非含息報酬，年化 252 日／無風險利率 0。R² 為 log 價格對交易日的線性擬合；一年窗口不能證明長期複利。曲線只回答持有體驗，不作公司基本面資格。</p>
<p class="reading">{escape(r['curve'])}</p><p class="sources">{link(f['source'],'月營收原表')} · {link(f['income_source'],'H1 損益原表')} · {link(stock['sources'][1],'歷史 PE')}</p></section>
<section><h3>技術分析</h3>
<dl class="ledger">{cell('Bias／方向',escape(r['nexus']['bias']))}{cell('Phase／階段',escape(r['nexus']['phase']))}{cell('Actionability／操作性',escape(r['action']))}{cell('結構支撐',fmt(m['support'])+' 元')}{cell('結構壓力',fmt(m['resistance'])+' 元')}{cell('距觀察窗前高',pct(m['distance_high']))}</dl>
<p class="reading">{escape(r['technical'])}</p><p class="reading"><b>回踩條件：</b>{escape(r['nexus']['pullback'])}<br><b>失效條件：</b>{escape(r['nexus']['invalidation'])}</p><p class="note">日線簡化情境：方向採現價／MA20／MA60，支撐壓力為近 20 日日 K 低／高點；不是盤中 BOS／CHoCH 訊號。{link(stock['sources'][0],'TWSE 日 K 原表')}</p></section>
<section class="operations"><h3>操作</h3><p class="meta">條件式情境，不是委託單或報酬預測</p><p class="reading">{escape(r['operation_rationale'])}</p>
<div class="operation"><h4>進場時機</h4><p><b class="num">{fmt(m['entry'])} 元</b>以上收盤，次一交易日回踩 <b class="num">{fmt(m['resistance'])}–{fmt(m['entry'])}</b> 區間並收回進場價，才分批；跳空不追。</p></div>
<div class="operation"><h4>加碼條件</h4><p>持倉後另一交易日回踩 <b class="num">{fmt(m['entry'])} 元</b>不破，且收於 <b class="num">{fmt(m['add'])} 元</b>以上再加碼；不在同一天重複進場。</p></div>
<div class="operation"><h4>止損</h4><p>跌破 <b class="num">{fmt(m['stop'])} 元</b>即退出，不等待反彈、不攤平。跳空或流動性不足時，成交價可能更差。</p></div>
<div class="operation"><h4>止盈</h4><p>短線 <b class="num">{fmt(m['targets'][0])}</b>／中線 <b class="num">{fmt(m['targets'][1])}</b>／長線 <b class="num">{fmt(m['targets'][2])} 元</b>。</p><p class="note">三個價位分別以 20／60／120 日高點突破、對應窗口低點止損的 2R 毛目標計算，屬替代情境，不能共用停損或累加配置。中／長線完整進場及停損見下列數值。</p>
<dl class="ledger">{long_scenarios(stock)}</dl></div></section>
<section class="verdict"><h3>總結</h3><p>{summary}</p><p class="note">曲線與估值均不作買進保證。單一部位及總風險依個人承受度設定；本報告不指定配置比例。</p></section>
</div></details></div></details>'''


def long_scenarios(stock):
    result = []
    for term, window in [('中線', 60), ('長線', 120)]:
        bars = stock['candles'][-window:]
        entry = next_tick(max(c['high'] for c in bars)); stop = previous_tick(min(c['low'] for c in bars))
        result.append(cell(term+'獨立情境',f'進場 {fmt(entry)}／止損 {fmt(stop)} 元'))
    return ''.join(result)


def render(data):
    # A returning reader may still cache the previous font CSS for ten minutes.
    css = Path(__file__).resolve().parents[1] / 'reports/stock-audit.css'
    stylesheet_version = hashlib.sha256(css.read_bytes()).hexdigest()[:12]
    day = data['report_date']; date.fromisoformat(day)
    if day != '2026-10-21' or data['forecast_cutoff'] != '2026-10-22T06:00:00+08:00':
        raise ValueError('Wrong dated report scope')
    validate_market(data['market'], data['forecast_cutoff'])
    stocks = [s for s in data['stocks'] if complete_stock(s, day)][:5]
    if len(stocks) < 3 or len({s['symbol'] for s in stocks}) != len(stocks):
        raise ValueError('At least 3 complete, distinct stocks required; target not written')
    analysis = [s['research']['metrics'] for s in stocks]
    strategy = '；'.join(escape(s['name']) + escape(s['research']['action']) for s in stocks)
    market = data['market']; refs = market['references']; night = refs[-1]
    positive = sum(r['change_pct'] > 0 for r in refs)
    direction = '中性偏多' if positive >= 5 else '偏空' if positive <= 2 else '中性'
    outlook = ('開盤偏多條件增加；夜盤高點未突破，不把方向當作立即買進訊號。' if direction == '中性偏多'
               else '方向分歧，先等夜盤區間突破，不在區間中段追價。' if direction == '中性'
               else '開盤承壓條件增加；未重新站回夜盤區間前，不新增多單。')
    basis = night['value'] - market['spot_close']
    cards = ''.join(stock_card(s, m, i == 0, day) for i, (s, m) in enumerate(zip(stocks, analysis)))
    market_rows = ''.join(f'<div class="market-row"><span><b>{escape(r["label"])}</b><small>{escape(r["session"])}</small></span><span class="num">{fmt(r["value"])}<strong>{pct(r["change_pct"])}</strong></span></div>' for r in [night, refs[0], refs[2]])
    other_market_rows = ''.join(f'<div class="market-row"><span><b>{escape(r["label"])}</b><small>{escape(r["session"])}</small></span><span class="num">{fmt(r["value"])}<strong>{pct(r["change_pct"])}</strong></span></div>' for r in [refs[1], *refs[3:6]])
    market_sources = ' · '.join(link(r['source'], r['label']) for r in refs)
    checklist = ''.join(f'<li><a href="#stock-{s["symbol"]}">{escape(s["name"])}</a><span>收盤突破 <b class="num">{fmt(m["entry"])}</b>，再等次日回踩；失效 <b class="num">{fmt(m["stop"])}</b> 元。</span></li>' for s, m in zip(stocks, analysis))
    nav = ''.join(f'<a href="#stock-{s["symbol"]}">{escape(s["name"])}</a>' for s in stocks)
    return f'''<!doctype html>
<html lang="zh-TW"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="NEXUS Stock Audit 台股中長期投資晨報，2026-10-21 歷史重建決策卡"><title>Stock Audit｜2026-10-21 台股投資決策卡</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&amp;family=IBM+Plex+Sans:wght@400;500;600&amp;family=IBM+Plex+Mono:wght@400;500;600&amp;family=Noto+Sans+TC:wght@400;500;700&amp;display=swap" rel="stylesheet"><link rel="stylesheet" href="stock-audit.css?v={stylesheet_version}"></head>
<body><a class="skip" href="#today">跳至今日結論</a><div class="shell"><header class="masthead"><a href="../index.html" class="brand" aria-label="NEXUS 題材雷達首頁">NEXUS<span>Stock Audit</span></a><span class="edition num">2026.10.21</span></header>
<main><section id="today" class="today"><h2>今日結論</h2><h1>台股中長期投資晨報</h1><p class="lead">不追價。<br>突破後回踩，才分批。</p><p class="strategy">{strategy}。條件未成立，不因隔夜偏多就追買。</p>
<dl class="report-meta">{cell('資料時間','10/21 台股收盤')}{cell('資料來源','TWSE／MOPS／TAIFEX／Yahoo')}{cell('資料完整度',f'{len(stocks)} 檔完整收錄')}{cell('明日市場方向',direction)}</dl>
<a class="primary" href="#focus">查看進場條件 <span aria-hidden="true">↓</span></a><p class="archive">歷史重建｜2026-10-23 擷取公開資料；非即時報價，也非當時封存且未修訂的資料。</p></section>
<section id="market" class="market"><h2>明日市場預測</h2><div class="section-intro"><strong class="direction">{direction}</strong><span>10/22 交易情境</span></div><p>外部市場 {positive}／7 項上漲，{outlook}</p>
<div class="market-data">{market_rows}</div><details class="source-disclosure"><summary>S&amp;P 500 與大型科技股</summary><div class="market-data">{other_market_rows}</div></details><dl class="ledger">{cell('現貨基準',fmt(market['spot_close'])+' 點 · 10/21 收盤')}{cell('期現價差',pct(basis/market['spot_close']*100)+'／'+fmt(basis)+' 點')}{cell('夜盤合約','TX 202611 · 11 月合約')}</dl>
<p class="note">價差為 11 月期貨夜盤收盤減前一日現貨收盤，非同步價差，包含跨月、持有成本與隔夜變動。</p>
<div class="conditions"><p><b>多方觸發</b>台指期突破夜盤高點 <span class="num">{fmt(market['night_high'])}</span> 且回踩不破，才延續偏多假設。</p><p><b>空方觸發</b>跌破夜盤低點 <span class="num">{fmt(market['night_low'])}</span> 且反彈站不回，取消偏多假設，不新增多單。</p></div>
<p class="event"><b>重要財經事件</b> 下一次 FOMC：10/27–28（美東日期）。{link('https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm','官方行事曆')}</p>
<p class="note">資料截止 2026-10-22 06:00（台北）；美股為 10/21 收盤＝10/22 04:00，台指期為 10/21 15:00–10/22 05:00 夜盤。<b>預測不是保證</b>：以漲跌家數形成的條件式情境，非回測機率模型；不推估報酬。</p><details class="source-disclosure"><summary>查看市場資料來源</summary><p class="sources">{market_sources} · {link(market['spot_source'],'台股現貨')}</p></details></section>
<section id="focus" class="focus"><h2>重點標的</h2><p class="section-hint">先讀結論，再點開價位。每檔資訊集中在同一張卡。</p><nav class="stock-nav" aria-label="快速定位標的">{nav}</nav>{cards}</section>
<section id="others"><h2>其他標的</h2><p>本期聚焦上述 {len(stocks)} 檔，不另列操作清單。</p></section>
<section id="checklist" class="checklist"><h2>今日執行清單</h2><ol>{checklist}</ol><p class="note">只在條件成立時執行；未觸價不追、不在止損後攤平。三種週期擇一，風險預算不可重複計算。</p></section></main>
<footer><strong>NEXUS · 先定位，再決策。</strong><p>本報告為歷史研究與條件式計畫，不構成個人化投資建議。目標價為未扣費用與滑價的 2R 情境，不是報酬保證；不指定配置比例。財務為合併 H1 累計、月營收未經查核，TWSE PE 採官方口徑，不以 H1 EPS 混算。</p><p>資料擷取：2026-10-23。資料可能經後續修訂，未驗證 point-in-time；股價與日 K 採未還原權息價。一年曲線不等於長期複利證據。</p>{link('stock-audit-2026-10-21.json','完整來源與研究快照')}</footer></div></body></html>
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    html = render(json.loads(args.input.read_text()))
    temp = args.output.with_suffix('.tmp')
    temp.write_text(html)
    temp.replace(args.output)
    print(f'Rendered verified dated research to {args.output}')


if __name__ == '__main__':
    main()
