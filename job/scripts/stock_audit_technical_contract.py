"""Offline acceptance boundary for source-linked Stock Audit technical research.

No foreign-module imports, network requests, signals or order execution. CI can
validate the stored research snapshot using its own OHLC evidence alone.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
import math
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


TZ_TAIPEI = ZoneInfo('Asia/Taipei')

METHOD_HASHES = {
    'pva': 'd3da82708a9034de6536d0d73d4a3f42aa689e01c0672dc17f3c0629988a0857',
    'nexus-structure': '154e66ad866d782efbca59bd9c7a424ba29fa6228c27a1d2a33bfb609ae98929',
}


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def number(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def close(a, b):
    return number(a) and number(b) and math.isclose(a, b, rel_tol=1e-8, abs_tol=1e-7)


def _https_url(value):
    parsed = urlparse(value) if isinstance(value, str) else None
    return bool(parsed and parsed.scheme == 'https' and parsed.netloc and not parsed.username and not parsed.password)


def validate_week_completion(metadata, as_of, forecast_cutoff=None):
    """Validate calendar evidence needed to close the report week early."""
    if metadata is None:
        return True
    try:
        cutoff_text = forecast_cutoff or metadata['forecast_cutoff']
        cutoff = datetime.fromisoformat(cutoff_text)
        if cutoff.tzinfo is None or cutoff != datetime.combine(date.fromisoformat(as_of) + timedelta(days=1), time(6), tzinfo=TZ_TAIPEI):
            return False
        if metadata['as_of'] != as_of or metadata['last_session_date'] != as_of:
            return False
        report_day = date.fromisoformat(as_of)
        if report_day.weekday() >= 5:
            return False
        announced = datetime.fromisoformat(metadata['announced_at'])
        if announced.tzinfo is None or announced > cutoff:
            return False
        next_session = date.fromisoformat(metadata['next_session_date'])
        week_friday = report_day + timedelta(days=4 - report_day.weekday())
        if next_session <= week_friday:
            return False
        expected_weekdays = []
        cursor = report_day + timedelta(days=1)
        while cursor < next_session:
            if cursor.weekday() < 5:
                expected_weekdays.append(cursor.isoformat())
            cursor += timedelta(days=1)
        if metadata['remaining_weekdays'] != expected_weekdays:
            return False
        closed = metadata['closed_dates']
        if sorted(item['date'] for item in closed) != expected_weekdays:
            return False
        if not metadata.get('calendar_source') or not all(_https_url(url) for url in metadata['calendar_source']):
            return False
        for item in closed:
            if item['status'] not in {'full_day_closed', 'scheduled_holiday'} or not _https_url(item['source']):
                return False
            if item.get('announced_at'):
                announced_at = datetime.fromisoformat(item['announced_at'])
                if announced_at.tzinfo is None or announced_at > cutoff:
                    return False
        return True
    except (KeyError, TypeError, ValueError):
        return False


def weekly_bars(candles, as_of, week_completion=None):
    cutoff = date.fromisoformat(as_of)
    monday = cutoff - timedelta(days=cutoff.weekday())
    if week_completion is not None and not validate_week_completion(week_completion, as_of):
        raise ValueError('Invalid week_completion evidence')
    include_current_week = week_completion is not None
    groups = {}
    for index, candle in enumerate(candles):
        day = date.fromisoformat(candle['date'])
        if day > cutoff:
            raise ValueError('weekly_bars cannot include a future session')
        week = day - timedelta(days=day.weekday())
        if week < monday or (include_current_week and week == monday):
            groups.setdefault(week, []).append((index, candle))
    return [dict(date=rows[-1][1]['date'], open=rows[0][1]['open'],
                 high=max(c['high'] for _, c in rows), low=min(c['low'] for _, c in rows),
                 close=rows[-1][1]['close'], volume=sum(c['volume'] for _, c in rows))
            for _, rows in sorted(groups.items())]


def _validate_pva(analysis, candles):
    pva = analysis['pva']; latest = pva['latest']; settings = pva['settings']
    if pva['status'] != 'ready' or pva['timeframe'] != 'D1':
        return False
    if (settings['anchor_mode'], settings['anchor_ema_length'], settings['atr_period'], settings['velocity_smooth'], settings['pva_source']) != ('EMA', 200, 14, 3, 'hlc3'):
        return False
    timeline = pva['nullable_timeline']
    if len(timeline) != len(candles) or pva['post_seed_bar_count'] != len(candles)-200:
        return False
    if pva['post_seed_bar_count'] < 400 or pva['readiness']['ema200_seed_date'] != candles[199]['date']:
        return False
    if not pva['readiness']['preseed_zero_excluded'] or not all(pva['full_finite'].values()):
        return False
    # Rebuild every recurrence from independent OHLC seeds. A valid latest
    # equation cannot establish that its trusted predecessor was correct.
    anchor = atr = velocity = None
    anchor_sum = tr_sum = 0.0
    previous_position = 0.0
    previous_velocity = None
    delta_seed = []
    for index, (row, candle) in enumerate(zip(timeline, candles)):
        hlc3 = (candle['high']+candle['low']+candle['close'])/3
        anchor_sum += hlc3
        tr = candle['high']-candle['low']
        if index:
            previous_close = candles[index-1]['close']
            tr = max(tr, abs(candle['high']-previous_close), abs(candle['low']-previous_close))
        tr_sum += tr
        if index == 199:
            anchor = anchor_sum/200
        elif index > 199:
            anchor = (2/201)*hlc3+(1-2/201)*anchor
        if index == 13:
            atr = tr_sum/14
        elif index > 13:
            atr = (1/14)*tr+(1-1/14)*atr
        position = (candle['close']-anchor)/atr if anchor is not None and atr else 0.0
        if index:
            delta = position-previous_position
            if velocity is None:
                delta_seed.append(delta)
                if len(delta_seed) == 3:
                    velocity = sum(delta_seed)/3
            else:
                velocity = .5*delta+.5*velocity
        acceleration = velocity-previous_velocity if velocity is not None and previous_velocity is not None else None
        expected = {'anchor':anchor, 'ATR':atr if atr and atr>0 else None,
                    'P':position if index>=199 else None,
                    'V':velocity if index>=201 else None,
                    'A':acceleration if index>=202 else None}
        if row['date'] != candle['date'] or row['ready'] != all(v is not None for v in expected.values()):
            return False
        for key, value in expected.items():
            if (row[key] is not None if value is None else not close(row[key],value)):
                return False
        previous_position, previous_velocity = position, velocity
    return (latest['date'] == candles[-1]['date']
            and all(close(latest[k], timeline[-1][k]) for k in ['P','V','A','anchor','ATR']))



def source_map(analysis):
    result = {}
    for tf in ['D1', 'W1']:
        for point in analysis['timeframes'][tf]['pivots']:
            key = point['source_id']
            if key in result:
                raise ValueError('Duplicate technical source ID')
            result[key] = point
    for zone in analysis['zones']:
        key = zone['id']
        if key in result:
            raise ValueError('Duplicate technical source ID')
        result[key] = zone
    return result


def _validate_sources(analysis, bars_by_tf):
    sources = source_map(analysis)
    for tf, bars in bars_by_tf.items():
        obj = analysis['timeframes'][tf]
        if obj['bar_count'] != len(bars) or obj['as_of'] != bars[-1]['date']:
            return False
        for pivot in obj['pivots']:
            i = pivot['index']; end = pivot['confirmed_at_index']
            if not 0 <= i < end < len(bars) or pivot['date'] != bars[i]['date'] or pivot['confirmed_at'] != bars[end]['date']:
                return False
            key = 'high' if pivot['kind'] == 'swing_high' else 'low'
            if not close(pivot['price'], bars[i][key]):
                return False
            reaction = pivot['reaction']
            r_end = reaction['review_end_index']
            if not end <= r_end < len(bars) or reaction['review_end_date'] != bars[r_end]['date']:
                return False
        for event in obj['breaks']:
            start, end = event['start_index'], event['end_index']
            if not 0 <= start < end < len(bars):
                return False
            level = bars[start]['high' if event['dir'] == 1 else 'low']
            if not close(event['price'], level) or event['start_date'] != bars[start]['date'] or event['confirmation_date'] != bars[end]['date']:
                return False
            if not (bars[end]['close'] > level if event['dir'] == 1 else bars[end]['close'] < level):
                return False
    for zone in analysis['zones']:
        bars = bars_by_tf[zone['timeframe']]; origin = zone['origin']
        start, born = origin['start_index'], origin['born_index']
        if not 0 <= start <= born < len(bars) or not number(zone['low']) or not number(zone['high']) or zone['low'] >= zone['high']:
            return False
        if origin['start_date'] != bars[start]['date'] or origin['formation_date'] != bars[born]['date']:
            return False
        if zone['type'] == 'ob':
            bounds = (bars[start]['low'], bars[start]['high'])
        elif zone['type'] == 'fvg' and born >= 2:
            bounds = (bars[born-2]['high'], bars[born]['low']) if zone['dir'] == 1 else (bars[born]['high'], bars[born-2]['low'])
        else:
            return False
        if not close(zone['low'], bounds[0]) or not close(zone['high'], bounds[1]):
            return False
        if zone['chart_only_active']:
            if not zone['reviewed_valid'] or zone.get('expired') or zone['exhausted'] or zone['invalidation']:
                return False
            touches = 0
            for candle in bars[born+1:]:
                if zone['type'] == 'ob':
                    if (candle['close'] < zone['low'] if zone['dir'] == 1 else candle['close'] > zone['high']):
                        return False
                    if candle['high'] >= zone['low'] and candle['low'] <= zone['high']:
                        touches += 1
                elif (candle['low'] <= zone['low'] if zone['dir'] == 1 else candle['high'] >= zone['high']):
                    return False
            if zone['type'] == 'ob' and (touches < 1 or touches >= 3 or not zone.get('reaction')):
                return False
    return True


def _validate_canonical_review(analysis, bars_by_tf):
    review = analysis['canonical_review']
    if review['as_of'] != analysis['as_of'] or review['candle_sha256'] != analysis['candle_sha256']:
        return False
    sources = source_map(analysis)
    sources.update({e['source_id']:e for tf in ['D1','W1'] for e in analysis['timeframes'][tf]['breaks']})
    phases = {'continuation','pullback','re_accumulation','distribution','range','no_man_s_land'}
    for tf in ['D1','W1']:
        read = review[tf]
        if (read != analysis['structure'][tf] or read['as_of'] != bars_by_tf[tf][-1]['date']
                or read['phase'] not in phases or read['bias'] not in {'bullish','bearish','neutral','range'}
                or not read['interpretation']):
            return False
    rows = {f"{tf}:candle-{i}-{c['date']}":c for tf,bars in bars_by_tf.items() for i,c in enumerate(bars)}
    if {q['role'] for q in review['reviews']} != {'trigger','defense','W1_bias_source'} or len(review['reviews']) != 3:
        return False
    for item in review['reviews']:
        source = sources[item['source_id']]
        if (not close(item['price'],source['price']) or not item['reason']
                or item['qualification'] not in {'qualified','rejected','uncertain'}
                or not item['evidence'] or not item['price_citations']):
            return False
        for evidence in item['evidence']:
            candle = rows[evidence['source_candle_id']]
            if any(evidence[k] != candle[k] for k in ['date','open','high','low','close']) or ('volume' in evidence and evidence['volume'] != candle['volume']):
                return False
        for citation in item['price_citations']:
            candle = rows[citation['candle_id']]
            if (citation['date'] != candle['date'] or citation['field'] not in {'open','high','low','close'}
                    or not close(citation['value'],candle[citation['field']])):
                return False
        role = item['role']
        if role in {'trigger','defense'}:
            watch_point = analysis['plan'].get('watch_levels', {}).get(role)
            if watch_point and watch_point.get('source_id',watch_point.get('id')) != item['source_id']:
                return False
            if analysis['plan']['status']=='conditional' and analysis['plan'][role+'_source'] != item['source_id']:
                return False
        if item['qualification'] == 'rejected' and item['role'] in analysis['plan'].get('watch_levels', {}):
            return False
        if analysis['plan']['status']=='conditional' and item['role'] in {'trigger','defense'}:
            if item['qualification']!='qualified' or not item['execution_qualified']:
                return False
    return True


def _tick_at(value):
    return Decimal('.01' if value<10 else '.05' if value<50 else '.1' if value<100 else '.5' if value<500 else '1' if value<1000 else '5')


def _next_tick(value):
    step=_tick_at(value)
    return float((Decimal(str(value))/step).to_integral_value(rounding=ROUND_FLOOR)*step+step)


def _previous_tick(value):
    step=_tick_at(value-1e-6)
    return float((Decimal(str(value))/step).to_integral_value(rounding=ROUND_CEILING)*step-step)


def nearest_opposing_barriers(analysis, candles, entry):
    """Independent eligible-source scan: a caller cannot choose a farther RR."""
    candidates=[];last=len(candles)-1
    for point in analysis['timeframes']['D1']['pivots']:
        if point.get('kind')!='swing_high' or point['confirmed_at_index']>=last or point['price']<=entry:
            continue
        if any(c['close']>point['price'] for c in candles[point['confirmed_at_index']+1:]):
            continue
        candidates.append((_previous_tick(point['price']),point['source_id']))
    for zone in analysis['zones']:
        if zone.get('chart_only_active') and zone['dir']==-1 and zone['high']>entry:
            candidates.append((_previous_tick(zone['low']),zone['id']))
    if not candidates:
        return []
    nearest=min(p for p,_ in candidates)
    return [(p,key) for p,key in candidates if close(p,nearest)]


def _validate_plan(analysis, candles):
    plan = analysis['plan']; sources = source_map(analysis)
    if plan['timeframe'] != 'D1' or plan['as_of'] != candles[-1]['date'] or not plan['reason'] or not plan['wait_condition']:
        return False
    def valid_targets(targets, entry=None, stop=None):
        for target in targets:
            source = sources[target['source_id']]
            if 'price' in source:
                if source.get('kind') != 'swing_high':
                    return False
                level = source['price']
            else:
                if source.get('dir') != -1 or not source.get('chart_only_active'):
                    return False
                level = source['low']
            if not number(target['price']) or not _previous_tick(level)-1e-7 <= target['price'] <= level+1e-7:
                return False
            if entry is not None and (target['price'] <= entry or not close(target['rr'], (target['price']-entry)/(entry-stop))):
                return False
        return True

    if plan['status'] == 'no_trade':
        watch = plan.get('watch_levels', {})
        for key in ['trigger', 'defense', 'obstacle']:
            point = watch.get(key)
            if point and point != sources[point.get('source_id', point.get('id'))]:
                return False
        return (all(plan[k] is None for k in ['entry','add','stop'])
                and plan['targets'] == [] and valid_targets(watch.get('targets', [])))
    if plan['status'] != 'conditional':
        return False
    entry, add, stop = (plan[k] for k in ['entry','add','stop'])
    if not all(number(v) for v in [entry,add,stop]) or not 0 < stop < entry < add or not plan['targets']:
        return False
    trigger = sources[plan['trigger_source']]; defense = sources[plan['defense_source']]
    if entry <= candles[-1]['close']:
        return False
    if trigger.get('kind') != 'swing_high' or trigger['index'] >= len(candles)-1 or trigger['confirmed_at_index'] >= len(candles) or trigger['price'] >= entry:
        return False
    if any(c['close'] > trigger['price'] for c in candles[trigger['confirmed_at_index']:]):
        return False
    if defense.get('type') == 'ob' and not defense['chart_only_active']:
        return False
    defense_level=defense['price'] if 'price' in defense else defense['low']
    if not close(entry,_next_tick(trigger['price'])) or not close(add,_next_tick(entry)):
        return False
    if not close(stop,_previous_tick(defense_level-analysis['pva']['latest']['ATR'])):
        return False
    if trigger['date']>=candles[-1]['date'] or trigger.get('classification')!='strong':
        return False
    if any(zone.get('chart_only_active') and zone['dir'] == -1
           and zone['low'] <= entry <= zone['high'] for zone in analysis['zones']):
        return False
    if not valid_targets(plan['targets'],entry,stop):
        return False
    nearest=nearest_opposing_barriers(analysis,candles,entry)
    first=plan['targets'][0]
    if not nearest or not any(close(first['price'],price) and first['source_id']==source_id for price,source_id in nearest):
        return False
    if [t['price'] for t in plan['targets']]!=sorted(t['price'] for t in plan['targets']):
        return False
    return plan['targets'][0]['rr'] >= 1 and analysis['structure']['W1']['bias'] not in {'偏空','bearish'}


def valid_technical(stock, as_of, forecast_cutoff=None):
    try:
        candles = stock['technical_candles']; analysis = stock['technical_analysis']
        if len(candles) < 600 or analysis['analysis_status'] != 'complete' or analysis['as_of'] != as_of:
            return False
        dates = [date.fromisoformat(c['date']).isoformat() for c in candles]
        if dates != sorted(set(dates)) or dates[-1] != as_of or not close(analysis['current_price'], candles[-1]['close']):
            return False
        for c in candles:
            if not all(number(c[k]) and c[k] > 0 for k in ['open','high','low','close']) or not number(c['volume']) or c['volume'] < 0 or not c['low'] <= min(c['open'],c['close']) <= max(c['open'],c['close']) <= c['high']:
                return False
        original = {c['date']:c for c in candles}
        if any(original.get(c['date']) != c for c in stock['candles']) or analysis['candle_sha256'] != canonical_hash(candles):
            return False
        receipts = {r['id']:r for r in analysis['method_receipts']}
        if any(receipts[k]['source_sha256'] != expected for k, expected in METHOD_HASHES.items()):
            return False
        completion = stock.get('week_completion')
        if completion is not None and not validate_week_completion(completion, as_of, forecast_cutoff):
            return False
        bars = {'D1':candles, 'W1':weekly_bars(candles,as_of,completion)}
        if not bars['W1'] or not _validate_pva(analysis,candles) or not _validate_sources(analysis,bars) or not _validate_canonical_review(analysis,bars) or not _validate_plan(analysis,candles):
            return False
        return True
    except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError, OverflowError):
        return False
