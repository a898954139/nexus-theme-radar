"""Manual, fail-closed Stock Audit snapshot. Not part of the hourly news job.

Price plans are reproducible 2R breakout scenarios, not forecasts or analyst targets.
No quality statistic is a fundamentals selection predicate. No new dependencies.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import statistics
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo('Asia/Taipei')


def number(value):
    n = float(str(value).replace(',', '').replace('▲', '').replace('▼', '-').replace('%', ''))
    if not math.isfinite(n):
        raise ValueError('Non-finite source value')
    return n


def valid_candles(candles):
    if len(candles) < 60:
        return False
    try:
        dates = [date.fromisoformat(c['date']) for c in candles]
        return dates == sorted(set(dates)) and all(
            all(math.isfinite(c[k]) and c[k] > 0 for k in ['open', 'high', 'low', 'close'])
            and math.isfinite(c['volume']) and c['volume'] >= 0
            and c['low'] <= min(c['open'], c['close']) <= max(c['open'], c['close']) <= c['high']
            for c in candles)
    except (KeyError, TypeError, ValueError):
        return False


def analyze(candles, pe_history):
    if not valid_candles(candles) or not pe_history or not all(math.isfinite(p) and p > 0 for p in pe_history):
        raise ValueError('Incomplete price / valuation input')
    closes = [c['close'] for c in candles]
    baseline = statistics.median(pe_history)
    operations = []
    # A breakout of the preceding window's high, one-TWD buffer; 2R gross target.
    # Whole TWD levels are valid ticks for the selected 2317 price band.
    for term, window, horizon in [('短線', 20, '約 1–4 週'), ('中線', 60, '約 1–3 個月'), ('長線', 120, '約 3–12 個月')]:
        if len(candles) < window:
            raise ValueError('Insufficient horizon history')
        sample = candles[-window:]
        entry = math.ceil(max(c['high'] for c in sample)) + 1
        stop = math.floor(min(c['low'] for c in sample)) - 1
        risk = entry - stop
        operations.append(dict(term=term, horizon=horizon, entry=entry, add=entry + 1,
                               stop=stop, take_profit=entry + 2 * risk,
                               timing=f'日收盤突破近 {window} 交易日高點後，下一交易日不低於進場價才分批；跳空不追價。',
                               add_condition='突破後另一交易日回測進場價不破，且再次收於加碼價以上；不在跌破停損後攤平。'))
    return dict(ma20=statistics.mean(closes[-20:]), ma60=statistics.mean(closes[-60:]),
                support=min(c['low'] for c in candles[-20:]), resistance=max(c['high'] for c in candles[-20:]),
                baseline_pe=baseline, premium_pct=round((pe_history[-1]/baseline-1)*100, 8),
                percentile=sum(p <= pe_history[-1] for p in pe_history)/len(pe_history)*100,
                operations=operations)


def quality(candles):
    closes = [c['close'] for c in candles]
    returns = [b/a-1 for a,b in zip(closes, closes[1:])]
    mean = statistics.mean(returns)
    std = statistics.stdev(returns)
    downside = math.sqrt(statistics.mean(min(r,0)**2 for r in returns))
    if std == 0 or downside == 0:
        raise ValueError('Undefined growth diagnostics')
    peak = closes[0]
    start = None
    recovered = []
    for i, close in enumerate(closes[1:],1):
        if close >= peak:
            if start is not None:
                recovered.append(i-start)
            peak, start = close, None
        elif start is None:
            start = i-1
    if not recovered:
        raise ValueError('No observed completed recovery')
    return dict(sharpe=mean/std*math.sqrt(252), sortino=mean/downside*math.sqrt(252),
                ttr_days=max(recovered), index_shape=f'價格指數（首日 = 100）：末值 {closes[-1]/closes[0]*100:.2f}；非含息報酬。',
                period=f"{candles[0]['date']} – {candles[-1]['date']}",
                method='日簡單報酬、年化 252 日、無風險利率 0；Sortino 分母為全樣本負報酬平方均值根。TTR 為窗口內已恢復前高的最長交易日數，不把尚未恢復的回撤當已恢復。僅為選股後成長曲線檢查，不作基本面篩選。',
                source='https://www.twse.com.tw/zh/trading/historical/stock-day.html')


class Source:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'Mozilla/5.0 NexusStockAudit/1.0'
        self.receipts = []

    def get(self, url):
        response = self.session.get(url, timeout=35)
        response.raise_for_status()
        self.receipts.append(dict(url=url, fetched_at=datetime.now(timezone.utc).isoformat(), status=response.status_code))
        return response


def roc_date(value):
    parts = str(value).replace('年','/').replace('月','/').replace('日','').split('/')
    return date(int(parts[0])+1911, int(parts[1]), int(parts[2])).isoformat()


def collect_stock(source, report_date):
    candles, valuations = {}, {}
    # Twelve calendar-month queries, with the exact observed window displayed.
    for offset in range(11,-1,-1):
        month_index = report_date.year*12+report_date.month-1-offset
        year, month0 = divmod(month_index,12)
        base = f'https://www.twse.com.tw/exchangeReport/'
        suffix = f'?response=json&date={year}{month0+1:02d}01&stockNo=2317'
        prices = source.get(base+'STOCK_DAY'+suffix).json()
        pes = source.get(base+'BWIBBU'+suffix).json()
        if prices.get('stat') != 'OK' or pes.get('stat') != 'OK':
            raise ValueError('TWSE monthly input unavailable')
        for row in prices['data']:
            day=roc_date(row[0])
            if day <= report_date.isoformat():
                candles[day]=dict(date=day,volume=number(row[1]),open=number(row[3]),high=number(row[4]),low=number(row[5]),close=number(row[6]))
        for row in pes['data']:
            day=roc_date(row[0])
            if day <= report_date.isoformat():
                valuations[day]=number(row[3])
    candles = [candles[k] for k in sorted(candles)]
    if not candles or candles[-1]['date'] != report_date.isoformat() or candles[-1]['date'] not in valuations:
        raise ValueError('Report-date price / PE absent')
    pe_history = [valuations[k] for k in sorted(valuations)]
    a = analyze(candles, pe_history)
    f=json.loads((ROOT/'data/fundamentals/TWSE-2317.json').read_text())
    latest=f['quarters'][0]
    if not latest['revenue'] or not latest['eps'] or not f['fetched_at'] or not f['source']:
        raise ValueError('Fundamentals absent')
    return dict(symbol='2317',name='鴻海',price=candles[-1]['close'],
                price_as_of=f'{report_date}T13:30:00+08:00',
                source=f'https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={report_date:%Y%m}01&stockNo=2317',
                fundamentals=dict(revenue=latest['revenue'],revenue_unit=f['currency'],period=latest['period'],eps=latest['eps'],ttm_eps=f['valuation']['ttm_eps'],pe=pe_history[-1],as_of=f['fetched_at'],source='https://goodinfo.tw/tw/StockFinDetail.asp?RPT_CAT=IS_QUAR&STOCK_ID=2317',
                                  analysis=f"個體 {latest['period']} 營收較前季 {(latest['revenue']/f['quarters'][1]['revenue']-1)*100:+.2f}%，EPS 較前季 {(latest['eps']/f['quarters'][1]['eps']-1)*100:+.2f}%；毛利率 {latest['gross_margin']*100:.2f}%。當季營運較前季成長，不等於未來成長保證。PE 採證交所公布口徑，與個體 EPS 分列，不混算。"),
                valuation=dict(source=f'https://www.twse.com.tw/exchangeReport/BWIBBU?response=json&date={report_date:%Y%m}01&stockNo=2317',baseline_label=f"TWSE 歷史 PE 中位數（{min(valuations)} – {max(valuations)}）",baseline_pe=a['baseline_pe'],premium_pct=a['premium_pct'],percentile=a['percentile'],sample_count=len(pe_history),analysis='相對位置按歷史 PE 小於等於當日 PE 的筆數比例計算；比較歷史不代表合理價或未來報酬。'),
                technical=dict(candles=candles,ma20=a['ma20'],ma60=a['ma60'],support=a['support'],resistance=a['resistance'],analysis='支撐／壓力分別採近 20 交易日最低／最高價。均線為日收盤簡單平均；日 K 為未還原權息成交價，跨除權息比較須留意價格調整。'),
                operations=a['operations'],quality=quality(candles),summary='只採條件式突破計畫，不按現價追買。三種週期擇一，不重複配置；目標是入場風險的 2 倍，不是分析師目標價。風險過大或無法遵守停損時不交易。')


def collect_forecast(source, report_date):
    refs=[]
    for symbol,label in [('^IXIC','Nasdaq'),('^GSPC','S&P 500'),('^SOX','SOX'),('AAPL','Apple'),('MSFT','Microsoft'),('NVDA','NVIDIA')]:
        url=f'https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}?range=5d&interval=1d'
        chart=source.get(url).json()['chart']['result'][0]
        meta=chart['meta']
        ts=datetime.fromtimestamp(meta['regularMarketTime'],timezone.utc)
        # chartPreviousClose is range start, not prior session: use previous valid daily close.
        previous=[c for t,c in zip(chart['timestamp'],chart['indicators']['quote'][0]['close']) if c is not None and datetime.fromtimestamp(t,ZoneInfo('America/New_York')).date()<ts.astimezone(ZoneInfo('America/New_York')).date()]
        if not previous or abs((ts.astimezone(TZ).date()-report_date).days)>1:
            raise ValueError('Market snapshot stale or previous session absent')
        value=number(meta['regularMarketPrice']); prev=number(previous[-1])
        refs.append(dict(label=label+' · 盤中快照',value=value,change_pct=(value/prev-1)*100,as_of=ts.isoformat(),source=url))
    url='https://www.taifex.com.tw/cht/3/futDailyMarketReport?queryType=2&marketCode=1&dateaddcnt=0&commodity_id=TX&queryDate='+quote(report_date.strftime('%Y/%m/%d'),safe='')
    soup=BeautifulSoup(source.get(url).text,'html.parser')
    expected=(report_date-timedelta(days=1)).strftime('%Y/%m/%d')+' 15:00'
    if expected not in ' '.join(soup.get_text(' ',strip=True).split()):
        raise ValueError('Night session date not confirmed')
    rows=[[td.get_text(' ',strip=True) for td in tr.select('td')] for tr in soup.select('table.table_f tbody tr')]
    contracts=[row for row in rows if len(row)>=9 and row[0]=='TX' and len(row[1])==6]
    if not contracts:
        raise ValueError('Night futures missing')
    row=sorted(contracts,key=lambda row:row[1])[0]
    refs.append(dict(label=f'台指期夜盤 {row[1]} · 場次結束',value=number(row[5]),change_pct=number(row[7]),as_of=f'{report_date}T05:00:00+08:00',source=url))
    positive=sum(r['change_pct']>0 for r in refs)
    bias='偏多' if positive>=5 else '偏空' if positive<=2 else '震盪'
    return dict(summary=f'下一台股交易日以{bias}情境準備，不是確定漲跌預測。美股為各自時間的盤中快照、台指期為已結束夜盤，並非同步行情。若開盤無法延續夜盤方向，取消方向假設，以開盤區間突破及回測為準。',references=refs,as_of=max(r['as_of'] for r in refs))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date',type=date.fromisoformat,required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'data/stock-audit-latest.json')
    args=parser.parse_args()
    if args.date>datetime.now(TZ).date():
        raise ValueError('Future report date')
    source=Source()
    stock=collect_stock(source,args.date)
    forecast=collect_forecast(source,args.date)
    payload=dict(schema_version=1,generated_at=datetime.now(timezone.utc).isoformat(),report_date=str(args.date),
                 conclusion='先確認價格位置，再決定是否承擔風險。只採條件式突破計畫；未觸及對應週期的進場條件前不追價。',forecast=forecast,stocks=[stock],source_receipts=source.receipts)
    encoded=json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    temporary=args.output.with_suffix('.tmp')
    temporary.write_text(encoded)
    temporary.replace(args.output)
    print(f"Published snapshot {args.date}: {len(payload['stocks'])} complete stock, {len(forecast['references'])} market references; {len(source.receipts)} source receipts")


if __name__=='__main__':
    main()
