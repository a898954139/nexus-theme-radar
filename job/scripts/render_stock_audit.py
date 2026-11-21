"""Pre-render the standalone, dated decision card. No network or browser calculations.

Input is a separate research snapshot, never the hourly/watchlist payload. Incomplete
candidates are excluded, and fewer than three complete candidates block output.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from html import escape
import hashlib
import json
import math
from pathlib import Path
import statistics
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


TZ_TAIPEI = ZoneInfo('Asia/Taipei')
TZ_NEW_YORK = ZoneInfo('America/New_York')


def display_date(value):
    day = date.fromisoformat(value) if isinstance(value, str) else value
    return f'{day.month}/{day.day}'


def expected_forecast_cutoff(report_date):
    day = date.fromisoformat(report_date) if isinstance(report_date, str) else report_date
    return datetime.combine(day + timedelta(days=1), time(6), tzinfo=TZ_TAIPEI)


def expected_us_close(report_date):
    day = date.fromisoformat(report_date) if isinstance(report_date, str) else report_date
    return datetime.combine(day, time(16), tzinfo=TZ_NEW_YORK).astimezone(TZ_TAIPEI)


def expected_night_close(report_date):
    day = date.fromisoformat(report_date) if isinstance(report_date, str) else report_date
    return datetime.combine(day + timedelta(days=1), time(5), tzinfo=TZ_TAIPEI)


def period_end(value):
    """Return a comparable end date for YYYY-MM, YYYYHn and YYYYQn periods."""
    text = str(value or '').strip().upper()
    try:
        if len(text) == 7 and text[4] == '-':
            year, month = int(text[:4]), int(text[5:])
            next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
            return next_month - timedelta(days=1)
        if len(text) == 6 and text[4] in {'H', 'Q'}:
            year, part = int(text[:4]), int(text[5])
            if text[4] == 'H':
                if part not in {1, 2}:
                    return None
                month = 6 if part == 1 else 12
            else:
                if part not in {1, 2, 3, 4}:
                    return None
                month = part * 3
            next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
            return next_month - timedelta(days=1)
    except (TypeError, ValueError):
        return None
    return None


def period_short(value):
    text = str(value or '').strip().upper()
    return text[4:] if len(text) >= 6 and text[4] in {'H', 'Q'} else text


def revenue_label(value, report_date):
    text = str(value)
    if len(text) == 7 and text[4] == '-':
        year, month = text[:4], int(text[5:])
        return f'{month} 月營收' if year == str(date.fromisoformat(report_date).year) else f'{year} 年 {month} 月營收'
    return f'{text} 月營收'


def financial_labels(financial, report_date):
    eps_period = str(financial['eps_period'])
    gross_period = str(financial['gross_margin_period'])
    short = period_short(eps_period)
    eps_label = f'{eps_period[:4]} {short} EPS' if len(eps_period) >= 6 and eps_period[4] in {'H', 'Q'} else f'{eps_period} EPS'
    return {
        'revenue': revenue_label(financial['revenue_month'], report_date),
        'eps': eps_label,
        'gross': f'{period_short(gross_period)} 毛利率',
        'period_meta': f'財報：{short} 累計／合併口徑',
        'income_source': f'{period_short(gross_period)} 損益原表',
        'footer': f'財務為合併 {short} 累計、月營收未經查核',
        'eps_basis': f'{short} EPS',
    }

try:
    from scripts.stock_audit_technical_contract import valid_technical, weekly_bars
except ModuleNotFoundError:
    from stock_audit_technical_contract import valid_technical, weekly_bars


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


def complete_stock(stock, report_date, forecast_cutoff=None):
    try:
        f = stock['financial']; candles = stock['candles']; history = stock['pe_history']
        if not str(stock['symbol']).isdigit() or len(str(stock['symbol'])) != 4 or not stock['name']:
            return False
        for key in ['revenue_twd_100m', 'revenue_yoy_pct', 'eps', 'gross_margin_pct']:
            if not finite(f[key]):
                return False
        if f['revenue_twd_100m'] <= 0 or f['eps'] <= 0 or not 0 <= f['gross_margin_pct'] <= 100:
            return False
        report_day = date.fromisoformat(report_date)
        if (period_end(f['revenue_month']) is None or period_end(f['eps_period']) is None
                or period_end(f['gross_margin_period']) is None
                or any(period_end(f[key]) > report_day for key in ['revenue_month', 'eps_period', 'gross_margin_period'])
                or period_end(f['eps_period']) != period_end(f['gross_margin_period'])
                or not http_url(f['source']) or not http_url(f['income_source'])):
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
        for key in ['investment_type', 'action', 'fundamentals', 'valuation', 'curve', 'technical', 'operation_rationale', 'conclusion', 'entry_outlook']:
            if not isinstance(research[key], str) or not research[key].strip():
                return False
        if not all(isinstance(research['nexus'][key], str) and research['nexus'][key].strip()
                   for key in ['bias', 'phase', 'actionability', 'pullback', 'invalidation', 'timeframe']):
            return False
        # Verify precomputed research against source facts; never invent a decision here.
        if not same_metrics(research['metrics'], metrics(stock)) or not valid_technical(stock, report_date, forecast_cutoff) or not valid_morning_brief(stock):
            return False
        return True
    except (KeyError, TypeError, ValueError, statistics.StatisticsError):
        return False


def validate_market(market, cutoff, report_date=None):
    try:
        refs = market['references']
        if {r['label'] for r in refs} != {'Nasdaq', 'S&P 500', '費城半導體', 'NVIDIA', 'Microsoft', 'Apple', '台指期夜盤'} or len(refs) != 7:
            raise ValueError('market categories')
        stop = datetime.fromisoformat(cutoff)
        report_day = date.fromisoformat(report_date) if report_date else (stop.astimezone(TZ_TAIPEI).date() - timedelta(days=1))
        expected_us = expected_us_close(report_day)
        expected_night = expected_night_close(report_day)
        for r in refs:
            observed = datetime.fromisoformat(r['as_of'])
            expected = expected_night if r['label'] == '台指期夜盤' else expected_us
            if observed != expected or observed > stop or not http_url(r['source']) or not finite(r['value']) or r['value'] <= 0 or not finite(r['change_pct']):
                raise ValueError('market source/clock')
        if not finite(market['spot_close']) or market['spot_close'] <= 0 or not http_url(market['spot_source']):
            raise ValueError('market spot')
        if market.get('spot_as_of'):
            expected_spot = datetime.combine(report_day, time(13, 30), tzinfo=TZ_TAIPEI)
            if datetime.fromisoformat(market['spot_as_of']) != expected_spot:
                raise ValueError('market spot clock')
        night = refs[-1]
        if night['label'] != '台指期夜盤' or not all(finite(market[k]) for k in ['night_high', 'night_low']):
            raise ValueError('market night')
        if not market['night_low'] <= night['value'] <= market['night_high']:
            raise ValueError('market range')
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f'Invalid market research: {exc}') from exc


def validate_report_scope(data):
    """Return publication day, market data day, cutoff, and explicit-mode flag.

    Legacy snapshots have only ``report_date`` and retain their original
    next-day cutoff semantics.  A morning snapshot explicitly separates the
    publication date from the prior session's ``data_as_of`` date.
    """
    publication_day = date.fromisoformat(data['report_date'])
    cutoff = datetime.fromisoformat(data['forecast_cutoff'])
    explicit_morning = 'data_as_of' in data
    if not explicit_morning:
        data_day = publication_day
        expected = expected_forecast_cutoff(data_day)
    else:
        data_day = date.fromisoformat(data['data_as_of'])
        if data_day >= publication_day:
            raise ValueError('data_as_of must be before report_date')
        expected = datetime.combine(publication_day, time(6), tzinfo=TZ_TAIPEI)
        if cutoff.date() != publication_day:
            raise ValueError('morning forecast_cutoff must fall on report_date')
    if cutoff != expected:
        message = ('forecast_cutoff must be report_date 06:00 Asia/Taipei'
                   if explicit_morning else
                   'forecast_cutoff must be the next calendar day at 06:00 Asia/Taipei')
        raise ValueError(message)
    return publication_day, data_day, cutoff, explicit_morning


def validate_morning_market(market, data_day, cutoff):
    """Reject post-cutoff calendar/market metadata in an explicit morning card."""
    expected_day = data_day.isoformat()
    if market.get('report_date') not in (None, expected_day):
        raise ValueError('morning market report_date is newer than data_as_of')
    if market.get('forecast_cutoff') not in (None, cutoff.isoformat()):
        raise ValueError('morning market forecast_cutoff is newer than data_as_of')
    for key in ('us_session_date','night_session_date'):
        if market.get(key) not in (None,expected_day):
            raise ValueError('Asynchronous market sessions require separate-clock support; do not reuse stale quotes')
    if any(market.get(key) for key in ('next_session_date','calendar_notice','calendar_source','calendar_evidence_file')):
        try:
            known_at = datetime.fromisoformat(market.get('calendar_known_at',''))
        except (ValueError, TypeError) as exc:
            raise ValueError('morning calendar requires a valid calendar_known_at') from exc
        if known_at.tzinfo is None or known_at > cutoff:
            raise ValueError('morning calendar notice was not known before the cutoff')



def calendar_context(market, report_date):
    next_session = market.get('next_session_date')
    notice = market.get('calendar_notice')
    sources = market.get('calendar_source') or []
    if notice and (not next_session or not sources or not all(http_url(source) for source in sources)):
        raise ValueError('calendar notice requires next session and official source')
    if next_session:
        next_session = date.fromisoformat(next_session).isoformat()
        if date.fromisoformat(next_session) <= report_date:
            raise ValueError('next_session_date must be after report_date')
    return next_session, notice


def important_events(market):
    event_key = next((key for key in ('economic_events','important_events','events') if key in market), None)
    events = market[event_key] if event_key else None
    if event_key and events == []:
        return '<b>重要財經事件</b> 本期未列入已核對的重要事件。'
    if not events:

        return '<b>重要財經事件</b> 下一次 FOMC：10/27–28（美東日期）。'+link('https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm','官方行事曆')
    if isinstance(events, str):
        return f'<b>重要財經事件</b> {escape(events)}'
    rendered = []
    for event in events:
        if isinstance(event, dict):
            label = event.get('label') or event.get('name') or '事件'
            dates = event.get('dates') or []
            if dates:
                label = f"{label}（{'、'.join(str(item) for item in dates)}）"
            source = event.get('source')
            rendered.append(link(source, label) if source and http_url(source) else escape(label))
        else:
            rendered.append(escape(str(event)))
    return '<b>重要財經事件</b> ' + ' · '.join(rendered)


def metrics(stock):
    """Financial/curve/quote diagnostics only; operations come from technical_analysis."""
    candles = stock['candles']; closes = [c['close'] for c in candles]
    pes = [p['pe'] for p in stock['pe_history']]; price = closes[-1]
    premium = (pes[-1] / statistics.median(pes) - 1) * 100
    valuation = '高於歷史中位數' if premium > 0 else '低於歷史中位數' if premium < 0 else '等於歷史中位數'
    return dict(price=price, ma20=statistics.mean(closes[-20:]), ma60=statistics.mean(closes[-60:]),
                premium=premium, pe=pes[-1], median=statistics.median(pes), pe_low=min(pes), pe_high=max(pes),
                valuation=valuation, distance_high=(price/max(c['high'] for c in candles)-1)*100, curve=curve(closes))


def observed_level(point):
    if not point:
        return None
    return point.get('price', point.get('low'))


def selected_zones(stock):
    bars = stock['candles'][-90:]
    low, high = min(c['low'] for c in bars), max(c['high'] for c in bars)
    price = bars[-1]['close']
    zones = [z for z in stock['technical_analysis']['zones']
             if z['chart_only_active'] and z['high'] >= low and z['low'] <= high]
    return sorted(zones, key=lambda z: (0 if z['type']=='ob' else 1,
                  max(z['low']-price, price-z['high'], 0), z['timeframe'], z['id']))[:4]


def brief_source_candles(stock):
    weekly=weekly_bars(stock['technical_candles'],stock['technical_analysis']['as_of'],stock.get('week_completion'))
    return {f"{tf}:candle-{i}-{c['date']}":c
            for tf,bars in [('D1',stock['technical_candles']),('W1',weekly)]
            for i,c in enumerate(bars)}


def valid_morning_brief(stock):
    """Validate presentation evidence, without upgrading a scenario to an order."""
    try:
        brief=stock['research']['morning_brief'];analysis=stock['technical_analysis']
        if (brief['as_of']!=analysis['as_of'] or brief['candle_sha256']!=analysis['candle_sha256']
                or brief['executable_now'] is not False or brief['scenario_type']!='future_conditional_reassessment_only'
                or brief['final_plan_status']!=analysis['plan']['status']):
            return False
        if not all(same_metrics(brief['pva'][k],analysis['pva']['latest'][k]) for k in ['P','V','A']):
            return False
        if not isinstance(brief['pva']['insight'],str) or not brief['pva']['insight'].strip():
            return False
        candles=brief_source_candles(stock);zones={z['id']:z for z in analysis['zones']}
        if len(brief['zones'])!=2 or {z['type'] for z in brief['zones']}!={'OB','FVG'}:
            return False
        for item in brief['zones']:
            source=zones[item['source_ids'][0]]
            if (source['type'].upper()!=item['type'] or source['timeframe']!=item['timeframe']
                    or not same_metrics(item['low'],source['low']) or not same_metrics(item['high'],source['high'])
                    or not item['insight']):
                return False
            state=item['state']
            if state not in {'active','invalidated','exhausted','candidate'}:
                return False
            if ((state=='active' and not source['chart_only_active'])
                    or (state=='invalidated' and not source['invalidation'])
                    or (state=='exhausted' and not source['exhausted'])
                    or (state=='candidate' and (source['reviewed_valid'] or source['invalidation'] or source['exhausted']))):
                return False
        rows=brief['entry_rows']
        band_keys={'low','high','low_ref','high_ref','condition','timeframe'}
        if (not 3<=len(rows)<=4 or not isinstance(brief['entry_band'],dict)
                or set(brief['entry_band'])!=band_keys
                or any(brief['entry_band'][k]!=rows[0][k] for k in band_keys)):
            return False
        for index,row in enumerate(rows):
            if not row['condition'] or not row['label'] or row['timeframe'] not in {'D1','W1'}:
                return False
            if not finite(row['low']) or not finite(row['high']) or not 0<row['low']<=row['high']:
                return False
            for bound in ['low','high']:
                ref=row[bound+'_ref'];candle=candles[ref['source_id']]
                if ref['field'] not in {'open','high','low','close'} or not same_metrics(row[bound],candle[ref['field']]):
                    return False
            declared=row['source_ids']
            if (not isinstance(declared,list) or not declared
                    or len(set(declared)) != len(declared)
                    or not all(isinstance(source_id,str) for source_id in declared)):
                return False
            source_id=declared[0]
            if source_id in zones:
                if len(declared) != 1:
                    return False
                source=zones[source_id]
                if (source['timeframe']!=row['timeframe']
                        or not same_metrics(row['low'],source['low']) or not same_metrics(row['high'],source['high'])
                        or (index==0 and not source['chart_only_active'])):
                    return False
                origin=source['origin'];tf=source['timeframe']
                defining={origin['start_index']} if source['type']=='ob' else {origin['born_index']-2,origin['born_index']}
                for bound in ['low','high']:
                    ref_id=row[bound+'_ref']['source_id']
                    if ref_id.split(':',1)[0]!=tf or int(ref_id.split(':candle-')[1].split('-',1)[0]) not in defining:
                        return False
            else:
                if (any(source_id not in candles or source_id.split(':',1)[0] != row['timeframe']
                        for source_id in declared)
                        or {row[k+'_ref']['source_id'] for k in ['low','high']} != set(declared)):
                    return False

        return True
    except (KeyError,TypeError,IndexError,ValueError):
        return False


def brief_price(row):
    return fmt(row['low']) if row['low']==row['high'] else fmt(row['low'])+'–'+fmt(row['high'])


def metric_sign_class(value):
    return 'metric-positive' if value>0 else 'metric-negative' if value<0 else 'metric-neutral'


def morning_methods(stock):
    brief=stock['research']['morning_brief'];p=brief['pva']
    values=' · '.join(f'<span class="{metric_sign_class(p[k])}">{k} {p[k]:+.3f}</span>' for k in ['P','V','A'])
    blocks=[f'<section class="method-summary" data-method="pva"><h4>PVA</h4><p class="method-value num">{values}</p><p class="method-insight">{escape(p["insight"])}</p></section>']
    states={'active':'有效','invalidated':'失效','exhausted':'耗盡','candidate':'候選'}
    source_zones={z['id']:z for z in stock['technical_analysis']['zones']}
    for z in brief['zones']:
        direction=source_zones[z['source_ids'][0]]['dir']
        side='多方' if direction==1 else '空方'
        color='metric-muted' if z['state']!='active' else 'metric-positive' if direction==1 else 'metric-negative'
        blocks.append(f'<section class="method-summary" data-method="{z["type"].lower()}" data-source-id="{escape(z["source_ids"][0],quote=True)}"><h4>{z["type"]}<small>{z["timeframe"]} · {side} · {states[z["state"]]}</small></h4><p class="method-value num {color}">{fmt(z["low"])}–{fmt(z["high"])}</p><p class="method-insight">{escape(z["insight"])}</p></section>')
    return '<div class="technical-summary">'+''.join(blocks)+'</div>'


def morning_entry_table(stock):
    brief=stock['research']['morning_brief'];rows=[]
    for index,row in enumerate(brief['entry_rows']):
        label='條件進場' if index==0 else row['label']
        kind='entry' if index==0 else 'reference'
        color='metric-entry' if index==0 else 'metric-risk' if '取消' in row['label'] else 'metric-neutral'
        timeframe='D1／W1' if index==0 and row['timeframe']=='W1' else row['timeframe']
        rows.append(f'<tr data-kind="{kind}"><th scope="row">{escape(label)}<small>{timeframe}</small></th><td class="level-price num {color}" data-low="{row["low"]}" data-high="{row["high"]}">{brief_price(row)}</td><td>{escape(row["condition"])}</td></tr>')
    return ('<table class="entry-plan"><caption>進場規劃 <small>條件價 · 非觸價委託</small></caption>'
            '<thead><tr><th scope="col">規劃</th><th scope="col">價位</th><th scope="col">確認條件</th></tr></thead>'
            '<tbody>'+''.join(rows)+'</tbody></table>'
            '<p class="plan-footnote">供進場評估，非可執行單；仍須確認收盤、回踩及近端風險報酬。</p>')


def technical_evidence(stock):
    analysis=stock['technical_analysis'];p=analysis['pva']['latest']
    diagnostics=''.join(cell(k,f'<span class="{metric_sign_class(p[k])}">{p[k]:+.3f}</span>') for k in ['P','V','A'])
    diagnostics+=cell('EMA200',fmt(p['anchor'])+' 元')+cell('ATR14',fmt(p['ATR'])+' 元')
    names={'bullish':'偏多','bearish':'偏空','neutral':'中性','range':'區間'}
    phases={'continuation':'延續','pullback':'回檔／反彈','re_accumulation':'再累積','distribution':'派發','range':'整理','no_man_s_land':'結構不明'}
    rows=[]
    for tf in ['W1','D1']:
        read=analysis['structure'][tf]
        color='metric-positive' if read['bias']=='bullish' else 'metric-negative' if read['bias']=='bearish' else 'metric-neutral'
        rows.append(cell(tf+' 結構',f'<span class="{color}">{names[read["bias"]]} · {phases[read["phase"]]}</span>'))
    for tf in ['W1','D1']:
        for e in [e for e in analysis['timeframes'][tf]['breaks'] if not e['internal']][-2:]:
            color='metric-positive' if e['dir']==1 else 'metric-negative'
            direction='向上' if e['dir']==1 else '向下'
            rows.append(cell(tf+' '+e['base'],f'<span class="{color}">{direction} {fmt(e["price"])} 元</span> · {e["confirmation_date"]} 偵測確認'))
    for z in selected_zones(stock):
        color='metric-positive' if z['dir']==1 else 'metric-negative'
        side='多方' if z['dir']==1 else '空方'
        rows.append(cell(z['timeframe']+' '+z['type'].upper(),f'<span class="{color}">{side} {fmt(z["low"])}–{fmt(z["high"])} 元</span>'))
    return (f'<p class="meta">D1 截至 {analysis["as_of"]} · W1 已收 {analysis["timeframes"]["W1"]["as_of"]}</p>'
            f'<dl class="facts curve pva-diagnostics">{diagnostics}</dl>'
            f'<dl class="ledger structure-evidence">{"".join(rows)}</dl>')


def operations_content(stock):
    plan = stock['technical_analysis']['plan']; reason = escape(stock['research']['operation_rationale'])
    if plan['status'] == 'no_trade':
        watch = plan.get('watch_levels', {})
        defense = observed_level(watch.get('defense'))
        defense_text = f'結構防守觀察 {fmt(defense)} 元，收盤失守時取消修復假設；這不是現有持倉的委託指令。' if defense is not None else '不設定不存在部位的止損單。'
        return (f'<p class="reading">{reason}</p>'
                f'<div class="operation"><h4>進場時機</h4><p>{escape(stock["research"]["entry_outlook"])}</p><p class="note">條件成立後仍須重算最近障礙與風險報酬；不是預定進場日期，也不是觸價買單。</p></div>'
                '<div class="operation"><h4>加碼條件</h4><p>不加碼。尚未形成可執行多方計畫，沒有入場條件就不執行加碼，也不在失效後攤平。</p></div>'
                f'<div class="operation"><h4>止損</h4><p>本期沒有新增委託，不設定交易止損。{defense_text}</p></div>'
                '<div class="operation"><h4>止盈</h4><p>不設定新部位止盈。圖中供給與流動性價位僅作壓力觀察，不能忽略近端障礙，另造更遠的 2R／3R 目標。</p></div>')
    targets = '／'.join(fmt(t['price'])+' 元' for t in plan['targets'])
    return (f'<p class="reading">{reason}</p>'
            f'<div class="operation"><h4>進場時機</h4><p>{escape(plan["wait_condition"])}</p><p class="num">條件價 {fmt(plan["entry"])} 元</p></div>'
            f'<div class="operation"><h4>加碼條件</h4><p>後續回踩守住結構，PVA 恢復且收於 {fmt(plan["add"])} 元以上才重新評估，不在失效後攤平。</p></div>'
            f'<div class="operation"><h4>止損</h4><p>來源防守位加 ATR 緩衝：{fmt(plan["stop"])} 元。跳空成交可能更差。</p></div>'
            f'<div class="operation"><h4>止盈</h4><p>既有供給／流動性：{targets}；不是固定 R 倍數推算的未來價格。</p></div>')


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
    analysis = stock['technical_analysis']; watch = analysis['plan'].get('watch_levels', {})
    support = observed_level(watch.get('defense'))
    resistance = observed_level(watch.get('trigger'))
    if support is not None and resistance is not None and support < resistance:
        top, bottom = max(20,y(resistance)), min(164,y(support))
        if top < bottom:
            out.append(f'<rect class="range-zone" data-zone-type="structural-observation" data-low="{support}" data-high="{resistance}" x="10" y="{top:.2f}" width="{right-10}" height="{bottom-top:.2f}"/>')
    for z in selected_zones(stock):
        top, bottom = max(20,y(z['high'])), min(164,y(z['low']))
        if top >= bottom:
            continue
        start_date = z['origin']['formation_date']
        offset = next((i for i,c in enumerate(bars) if c['date'] >= start_date),0)
        left = x(offset)
        side = 'bull' if z['dir']==1 else 'bear'
        label = f"{z['timeframe']} {z['type'].upper()} {fmt(z['low'])}–{fmt(z['high'])}，來源 {z['origin']['start_date']}，形成 {start_date}"
        out.append(f'<rect class="poi-zone poi-{side}" data-source-id="{escape(z["id"],quote=True)}" data-zone-type="{z["type"]}" data-timeframe="{z["timeframe"]}" data-low="{z["low"]}" data-high="{z["high"]}" x="{left:.2f}" y="{top:.2f}" width="{max(2,right-left):.2f}" height="{bottom-top:.2f}"><title>{escape(label)}</title></rect>')
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
    for index, (name, value) in enumerate([('resistance', resistance or hi), ('current', m['price']), ('support', support or lo)]):
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
    labels = financial_labels(f, day)
    r = stock['research']; summary = escape(r['conclusion'])
    analysis = stock['technical_analysis']
    preview = f'''<figure class="preview">{chart(stock,m)}<figcaption class="chart-basis"><span><strong>W1 週K＋D1 日K</strong> · {day} 收盤</span><span>{stock['candles'][-90]['date']}–{day} · 90 根日K · 成交量</span><span class="ma20-key">MA20 {fmt(m['ma20'])}</span><span>MA60 {fmt(m['ma60'])}</span><span>W1 截至 {analysis['timeframes']['W1']['as_of']}</span></figcaption></figure>'''
    methods=morning_methods(stock);entry_table=morning_entry_table(stock)
    technical = technical_evidence(stock)
    operations = operations_content(stock)
    return f'''<details class="stock" id="stock-{symbol}" open>
<summary><span class="identity"><strong>{name} <span class="symbol">{symbol}</span></strong><span class="price">{fmt(m['price'])} 元</span><span class="type">{escape(r['investment_type'])}</span><span class="quote-time">{day} 收盤</span></span><span class="action">D1 回踩規劃</span><span class="chevron" aria-hidden="true"></span></summary>
<div class="stock-body">{preview}{methods}{entry_table}
<details class="analysis"><summary>展開完整分析與操作條件<span aria-hidden="true">＋</span></summary><div class="analysis-body">
<section><h3>基本面分析</h3><p class="meta">價格：{day} 收盤 · {labels['period_meta']}</p>
<dl class="facts">{cell(labels['revenue'],fmt(f['revenue_twd_100m'])+' <small>億元</small>')}{cell('營收年增',pct(f['revenue_yoy_pct']))}{cell(labels['eps'],fmt(f['eps'])+' <small>元</small>')}{cell(labels['gross'],fmt(f['gross_margin_pct'])+'%')}</dl><p class="reading">{escape(r['fundamentals'])}</p>
<h4>估值位置</h4><dl class="ledger">{cell('目前本益比',fmt(m['pe'])+' 倍')}{cell('歷史 PE 中位數',fmt(m['median'])+' 倍')}{cell('歷史 PE 區間',fmt(m['pe_low'])+'–'+fmt(m['pe_high'])+' 倍')}{cell('相對中位數',pct(m['premium']))}</dl>
<p class="note">{stock['pe_history'][0]['date']}–{day}，{len(stock['pe_history'])} 筆 TWSE PE。歷史相對位置不是合理價；營收成長不等於獲利成長，也不能單獨證明溢價合理。</p>
<p class="reading">{escape(r['valuation'])}</p><h4>成長曲線檢查</h4><dl class="facts curve">{cell('Sharpe',fmt(q['sharpe']))}{cell('Sortino',fmt(q['sortino']))}{cell('最大回撤',fmt(q['max_drawdown_pct'])+'%')}{cell('TTR（最長已恢復）',str(q['ttr_sessions'])+' <small>交易日</small>')}{cell('指數擬合 R²',f"{q['r2']:.3f}")}{cell('本次未恢復回撤',str(q['underwater_sessions'])+' <small>交易日</small>')}</dl>
<p class="note">觀察窗 {stock['candles'][0]['date']}–{day}；未還原權息、非含息報酬，年化 252 日／無風險利率 0。R² 為 log 價格對交易日的線性擬合；一年窗口不能證明長期複利。曲線只回答持有體驗，不作公司基本面資格。</p>
<p class="reading">{escape(r['curve'])}</p><p class="sources">{link(f['source'],'月營收原表')} · {link(f['income_source'],labels['income_source'])} · {link(stock['sources'][1],'歷史 PE')}</p></section>
<section><h3>技術分析</h3>{technical}</section>
<section class="operations"><h3>操作</h3><p class="meta">W1 定方向／D1 定條件；不是即時委託或報酬預測</p>{operations}</section>
<section class="verdict"><h3>總結</h3><p>{summary}</p><p class="note">曲線與估值均不作買進保證。單一部位及總風險依個人承受度設定；本報告不指定配置比例。</p></section>
</div></details></div></details>'''


def render(data):
    # A returning reader may still cache the previous font CSS for ten minutes.
    css = Path(__file__).resolve().parents[1] / 'reports/stock-audit.css'
    stylesheet_version = hashlib.sha256(css.read_bytes()).hexdigest()[:12]
    publication_day, data_day, cutoff, explicit_morning = validate_report_scope(data)
    day = publication_day.isoformat(); data_day_iso = data_day.isoformat()
    data_day_display = display_date(data_day)
    validate_market(data['market'], data['forecast_cutoff'], data_day_iso)
    if explicit_morning:
        validate_morning_market(data['market'], data_day, cutoff)
    next_session, calendar_notice = calendar_context(data['market'], publication_day)
    next_calendar = publication_day + timedelta(days=1)
    forecast_day = publication_day if explicit_morning else next_calendar
    next_label = display_date(date.fromisoformat(next_session)) if next_session else display_date(next_calendar)
    if explicit_morning:
        next_label = display_date(forecast_day)
    us_close = expected_us_close(data_day)
    night_close = expected_night_close(data_day)
    captured_at = data.get('retrieved_at', data.get('reconstructed_at', '2026-10-23'))
    source_json = data.get('source_json_filename', f'stock-audit-{day}.json')
    stocks = [s for s in data['stocks'] if complete_stock(s, data_day_iso, data['forecast_cutoff'])][:5]
    if len(stocks) < 3 or len({s['symbol'] for s in stocks}) != len(stocks):
        raise ValueError('At least 3 complete, distinct stocks required; target not written')
    analysis = [s['research']['metrics'] for s in stocks]
    lead = f'{display_date(data_day)} 資料 → {display_date(publication_day)} 台股開盤分析' if explicit_morning else '先看價位，再看確認。'
    execution_note = '條件價只供規劃；收盤、回踩與近端風險報酬確認後，才重新評估執行。'
    strategy = '；'.join(escape(s['name'])+' '+brief_price(s['research']['morning_brief']['entry_band']) for s in stocks)
    market = data['market']; refs = market['references']; night = refs[-1]
    positive = sum(r['change_pct'] > 0 for r in refs)
    direction = '中性偏多' if positive >= 5 else '偏空' if positive <= 2 else '中性'
    outlook = ('開盤偏多條件增加；夜盤高點未突破，不把方向當作立即買進訊號。' if direction == '中性偏多'
               else '方向分歧，先等夜盤區間突破，不在區間中段追價。' if direction == '中性'
               else '開盤承壓條件增加；未重新站回夜盤區間前，不新增多單。')
    calendar_text = ''
    if calendar_notice and next_session:
        calendar_text = f' 交易日曆：{escape(calendar_notice)} 下一交易日：{display_date(date.fromisoformat(next_session))}；不將 {display_date(next_calendar)} 視為正常開盤。'
    basis = night['value'] - market['spot_close']
    cards = ''.join(stock_card(s, m, i == 0, data_day_iso) for i, (s, m) in enumerate(zip(stocks, analysis)))
    market_rows = ''.join(f'<div class="market-row"><span><b>{escape(r["label"])}</b><small>{escape(r["session"])}</small></span><span class="num">{fmt(r["value"])}<strong class="{metric_sign_class(r["change_pct"])}">{pct(r["change_pct"])}</strong></span></div>' for r in [night, refs[0], refs[2]])
    other_market_rows = ''.join(f'<div class="market-row"><span><b>{escape(r["label"])}</b><small>{escape(r["session"])}</small></span><span class="num">{fmt(r["value"])}<strong class="{metric_sign_class(r["change_pct"])}">{pct(r["change_pct"])}</strong></span></div>' for r in [refs[1], *refs[3:6]])
    market_sources = ' · '.join(link(r['source'], r['label']) for r in refs)
    if calendar_notice:
        market_sources += ' · ' + ' · '.join(link(url, '交易日曆') for url in market.get('calendar_source', []))
    checklist = ''.join(f'<li><a href="#stock-{s["symbol"]}">{escape(s["name"])}</a><span class="num">{brief_price(s["research"]["morning_brief"]["entry_band"])}</span><span>{escape(s["research"]["morning_brief"]["entry_band"]["condition"])}</span></li>' for s in stocks)
    nav = ''.join(f'<a href="#stock-{s["symbol"]}">{escape(s["name"])}</a>' for s in stocks)
    return f'''<!doctype html>
<html lang="zh-TW"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="NEXUS Stock Audit 台股中長期投資晨報，{day} 歷史重建決策卡"><title>Stock Audit｜{day} 台股投資決策卡</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&amp;family=IBM+Plex+Sans:wght@400;500;600&amp;family=IBM+Plex+Mono:wght@400;500;600&amp;family=Noto+Sans+TC:wght@400;500;700&amp;display=swap" rel="stylesheet"><link rel="stylesheet" href="stock-audit.css?v={stylesheet_version}"></head>
<body><a class="skip" href="#today">跳至今日結論</a><div class="shell"><header class="masthead"><a href="../index.html" class="brand" aria-label="NEXUS 題材雷達首頁">NEXUS<span>Stock Audit</span></a><span class="edition num">{publication_day:%Y.%m.%d}</span></header>
<main><section id="today" class="today"><h2>今日結論</h2><h1>台股中長期投資晨報</h1><p class="lead">{lead}</p><p class="strategy">{strategy}。以上為收復後回踩的條件價。</p>
<dl class="report-meta">{cell('資料時間',f'{data_day_display} 台股收盤')}{cell('資料來源','TWSE／MOPS／TAIFEX／Yahoo')}{cell('資料完整度',f'{len(stocks)} 檔完整收錄')}{cell('今日市場方向' if explicit_morning else '明日市場方向',direction)}</dl>
<a class="primary" href="#focus">查看進場條件 <span aria-hidden="true">↓</span></a><p class="archive">手機版預覽｜分析流程驗證尚未完成。歷史重建｜{escape(str(captured_at))} 擷取公開資料；非即時報價，也非當時封存且未修訂的資料。</p></section>
<section id="market" class="market"><h2>{'今日市場展望' if explicit_morning else '明日市場預測'}</h2><div class="section-intro"><strong class="direction">{direction}</strong><span>{next_label} 交易情境</span></div><p>外部市場 {positive}／7 項上漲，{outlook}{calendar_text}</p>
<div class="market-data">{market_rows}</div><details class="source-disclosure"><summary>S&amp;P 500 與大型科技股</summary><div class="market-data">{other_market_rows}</div></details><dl class="ledger">{cell('現貨基準',fmt(market['spot_close'])+' 點 · '+data_day_display+' 收盤')}{cell('期現價差',pct(basis/market['spot_close']*100)+'／'+fmt(basis)+' 點')}{cell('夜盤合約',market.get('night_contract','TX 202611 · 11 月合約'))}</dl>
<p class="note">價差為 11 月期貨夜盤收盤減前一日現貨收盤，非同步價差，包含跨月、持有成本與隔夜變動。</p>
<div class="conditions"><p><b>多方觸發</b>台指期突破夜盤高點 <span class="num">{fmt(market['night_high'])}</span> 且回踩不破，才延續偏多假設。</p><p><b>空方觸發</b>跌破夜盤低點 <span class="num">{fmt(market['night_low'])}</span> 且反彈站不回，取消偏多假設，不新增多單。</p></div>
<p class="event">{important_events(market)}</p>
<p class="note">資料截止 {cutoff.astimezone(TZ_TAIPEI):%Y-%m-%d %H:%M}（台北）；美股為 {data_day:%m/%d} 收盤＝{us_close:%m/%d %H:%M}，台指期為 {data_day:%m/%d} 15:00–{night_close:%m/%d %H:%M} 夜盤。<b>預測不是保證</b>：以漲跌家數形成的條件式情境，非回測機率模型；不推估報酬。</p><details class="source-disclosure"><summary>查看市場資料來源</summary><p class="sources">{market_sources} · {link(market['spot_source'],'台股現貨')}</p></details></section>
<section id="focus" class="focus"><h2>重點標的</h2><p class="section-hint">先看日 K 與決策價位，完整分析按需展開。</p><nav class="stock-nav" aria-label="快速定位標的">{nav}</nav>{cards}</section>
<section id="others"><h2>其他標的</h2><p>本期聚焦上述 {len(stocks)} 檔，不另列操作清單。</p></section>
<section id="checklist" class="checklist"><h2>今日執行清單</h2><ol>{checklist}</ol><p class="note">{execution_note}</p></section></main>
<footer><strong>NEXUS · 先定位，再決策。</strong><p>本報告為歷史研究與條件式計畫，不構成個人化投資建議。條件目標只取既有供給／流動性來源，不保證到達或成交；不指定配置比例。{financial_labels(stocks[0]['financial'],data_day_iso)['footer']}，TWSE PE 採官方口徑，不以 {financial_labels(stocks[0]['financial'],data_day_iso)['eps_basis']} 混算。</p><p>資料擷取：{escape(str(captured_at))}。資料可能經後續修訂，未驗證 point-in-time；股價與日 K 採未還原權息價。一年曲線不等於長期複利證據。</p>{link(source_json,'完整來源與研究快照')}</footer></div></body></html>
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
