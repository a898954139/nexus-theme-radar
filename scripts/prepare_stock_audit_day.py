"""Collect an observed day into an unrenderable research input (never copy decisions)."""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from urllib.parse import urlencode
from zoneinfo import ZoneInfo


def exchange_day(value):
    parts=[int(x) for x in re.findall(r'\d+',value)]
    if len(parts)!=3:
        raise ValueError('Invalid exchange date')
    year,month,day=parts
    return date(year+1911 if year<1911 else year,month,day).isoformat()


def number(value):
    result=float(str(value).replace(',','').strip())
    if not math.isfinite(result):raise ValueError('Non-finite official number')
    return result


def read_month(symbol,endpoint,month,cache,receipts):
    name=f'{month}-{endpoint}.json';path=cache/symbol/name
    url='https://www.twse.com.tw/exchangeReport/'+endpoint+'?'+urlencode(dict(response='json',date=month,stockNo=symbol))
    if not path.exists():
        path.parent.mkdir(parents=True,exist_ok=True)
        result=subprocess.run(['/usr/bin/curl','--fail','--silent','--show-error','--location','--max-time','45',url],capture_output=True,check=True)
        payload=json.loads(result.stdout)
        if payload.get('stat')!='OK' or not isinstance(payload.get('data'),list):
            raise ValueError(f'No official {endpoint} source for {symbol}/{month}')
        path.write_bytes(result.stdout)
    raw=path.read_bytes();payload=json.loads(raw)
    if payload.get('stat')!='OK' or not isinstance(payload.get('data'),list):
        raise ValueError(f'Invalid cached official source: {path.name}')
    receipts.append(dict(symbol=symbol,endpoint=endpoint,month=month,url=url,sha256=hashlib.sha256(raw).hexdigest(),cache_file=f"{symbol}/{name}",read_at=datetime.now(ZoneInfo('Asia/Taipei')).isoformat()))
    return payload['data']


def prepare(baseline,target,cache):
    target=date.fromisoformat(target);old=date.fromisoformat(baseline['report_date'])
    if target<old:
        raise ValueError('Baseline must not be later than the requested day')
    result=deepcopy(baseline);receipts=[];exclusions=[]
    month_cursor=old.replace(day=1);months=[]
    while month_cursor<=target:
        months.append(month_cursor.strftime('%Y%m01'))
        month_cursor=(month_cursor.replace(day=28)+timedelta(days=4)).replace(day=1)
    for stock in result['stocks']:
        daily={c['date']:c for c in stock['technical_candles']}
        pes={p['date']:p for p in stock['pe_history']}
        for month in months:
            for row in read_month(stock['symbol'],'STOCK_DAY',month,cache,receipts):
                day=exchange_day(row[0])
                if day>target.isoformat():
                    continue
                try:
                    bar=dict(date=day,open=number(row[3]),high=number(row[4]),low=number(row[5]),close=number(row[6]),volume=number(row[1]))
                except (ValueError, IndexError) as exc:
                    if len(row)>=7 and str(row[1]).replace(',','').strip()=='0' and all(str(row[i]).strip() in {'--','-',''} for i in (3,4,5,6)):
                        if day in daily:raise ValueError(f'Revised OHLC overlap became unpriced: {stock["symbol"]} {day}')
                        exclusions.append(dict(symbol=stock['symbol'],date=day,endpoint='STOCK_DAY',reason='official_zero_volume_unpriced',raw_row=row))
                        continue
                    raise ValueError(f'Malformed official OHLC row: {stock["symbol"]} {day}') from exc
                if not 0<bar['low']<=min(bar['open'],bar['close'])<=max(bar['open'],bar['close'])<=bar['high']:
                    raise ValueError('Malformed official OHLC')
                if day in daily and daily[day]!=bar:
                    raise ValueError(f'Revised OHLC overlap needs explicit adjudication: {stock["symbol"]} {day}')
                daily[day]=bar
            for row in read_month(stock['symbol'],'BWIBBU',month,cache,receipts):
                day=exchange_day(row[0])
                if day<=target.isoformat():
                    try:pe=number(row[3])
                    except (ValueError, IndexError) as exc:
                        if len(row)>3 and str(row[3]).strip() in {'--','-',''}:
                            if day in pes:raise ValueError(f'Revised PE overlap became missing: {stock["symbol"]} {day}')
                            exclusions.append(dict(symbol=stock['symbol'],date=day,endpoint='BWIBBU',reason='official_missing_pe',raw_row=row))
                            continue
                        raise ValueError(f'Malformed official PE row: {stock["symbol"]} {day}') from exc
                    if pe>0:
                        if day in pes and pes[day]['pe']!=pe:raise ValueError(f'Revised PE overlap needs explicit adjudication: {stock["symbol"]} {day}')
                        pes[day]=dict(date=day,pe=pe)
                    else:raise ValueError(f'Nonpositive official PE: {stock["symbol"]} {day}')
        if target.isoformat() not in daily or target.isoformat() not in pes:
            raise ValueError(f'Requested date has no observed quote/PE: {stock["symbol"]} {target}')
        # Keep the same rolling 12-calendar-month convention as the baseline.
        month_index=target.year*12+target.month-1-11
        start=date(month_index//12,month_index%12+1,1).isoformat()
        stock['technical_candles']=[c for day,c in sorted(daily.items()) if day<=target.isoformat()]
        stock['candles']=[c for c in stock['technical_candles'] if c['date']>=start]
        stock['pe_history']=[p for day,p in sorted(pes.items()) if start<=day<=target.isoformat()]
        stock['report_date']=target.isoformat()
        stock.pop('technical_analysis',None)
        stock.pop('research',None)
        stock['research_required']=True
    result['report_date']=target.isoformat()
    result['forecast_cutoff']=datetime.combine(target+timedelta(days=1),datetime.min.time(),ZoneInfo('Asia/Taipei')).replace(hour=6).isoformat()
    result['retrieved_at']=datetime.now(ZoneInfo('Asia/Taipei')).isoformat()
    result['research_status']='inputs_only'
    result.pop('market',None)  # Overnight observations and calendar must be gathered for this day.
    result['input_receipts']=receipts
    result['input_exclusions']=exclusions
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date',required=True)
    parser.add_argument('--baseline',required=True,type=Path)
    parser.add_argument('--cache-dir',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    data=prepare(json.loads(args.baseline.read_text()),args.date,args.cache_dir)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(f'Prepared {data["report_date"]} observed inputs; research and market are intentionally required before render.')

if __name__=='__main__':main()
