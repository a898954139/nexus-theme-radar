// Nexus 結構分析 on the stock page: the pinned Nexus structure detector's
// mechanical read for every radar stock (Mac job nexus-structure, daily after
// the close). D1 + completed W1 bias from the latest BOS / CHoCH, live FVG / OB
// zones and unbroken swing highs / lows around the close, PVA when available.
// Renders nothing while loading or when the stock has no read.
import React, { useEffect, useState } from 'react';
import { fetchNexusStructure, NexusBias, NexusLevel, NexusStructure, NexusTimeframeRead } from '../../services/nexusStructure';
import { daysSince, STALE_AFTER_DAYS } from './StockAuditCard';
import './nexus-structure-card.css';

const KIND_LABEL: Record<NexusLevel['kind'], string> = { fvg: 'FVG 缺口', ob: 'OB 訂單塊', swing_high: '前高', swing_low: '前低' };
const SIDE_LABEL: Record<NexusLevel['side'], string> = { resistance: '壓力', support: '支撐', inside: '所在區' };

function md(date: string | null) { return date ? `${Number(date.slice(5, 7))}/${Number(date.slice(8, 10))}` : '—'; }
function price(value: number) { return value.toLocaleString('en-US', { maximumFractionDigits: 2 }); }
function tone(bias: NexusBias) { return bias === '偏多' ? 'up' : bias === '偏空' ? 'down' : 'flat'; }
function taipeiToday() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
}

function span(level: NexusLevel) { return level.low === level.high ? price(level.low) : `${price(level.low)}–${price(level.high)}`; }

/** Distance from the close to the level's near edge, in % of the close. */
export function distancePct(level: NexusLevel, close: number): number {
  if (level.side === 'inside') return 0;
  const edge = level.side === 'resistance' ? level.low : level.high;
  return (edge / close - 1) * 100;
}

const TimeframeTag: React.FC<{ name: string; read: NexusTimeframeRead | null }> = ({ name, read }) => {
  if (!read) return <span className="tag">{name}：資料不足</span>;
  return <span className={`tag nx-${tone(read.bias)}`}>
    {name}：{read.bias}
    {read.last_event ? <>（{md(read.last_event_date)} {read.last_event} <b className="mono-num">{read.last_event_price != null ? price(read.last_event_price) : '—'}</b>）</> : '（尚無結構突破）'}
  </span>;
};

const LevelRow: React.FC<{ level: NexusLevel; close: number }> = ({ level, close }) => {
  const pct = distancePct(level, close);
  return <tr className={`nx-${level.side}`}>
    <th>{SIDE_LABEL[level.side]}</th>
    <td>{level.timeframe === 'W1' ? '週' : '日'} {KIND_LABEL[level.kind]}{level.state === 'candidate' ? <small>未回測</small> : null}</td>
    <td className="mono-num">{span(level)}</td>
    <td className="mono-num">{level.side === 'inside' ? '區內' : `${pct > 0 ? '+' : '−'}${Math.abs(pct).toFixed(1)}%`}</td>
    <td className="mono-num">{md(level.formed_on)}</td>
  </tr>;
};

export const NexusStructureCard: React.FC<{ code: string; exchange?: string }> = ({ code, exchange }) => {
  const [read, setRead] = useState<NexusStructure | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setRead(null);
    fetchNexusStructure(code, exchange, controller.signal).then((value) => {
      if (!controller.signal.aborted) setRead(value);
    });
    return () => controller.abort();
  }, [code, exchange]);

  if (!read) return null;
  const age = daysSince(read.as_of, taipeiToday());
  const resistance = read.levels.filter((l) => l.side === 'resistance').sort((a, b) => b.low - a.low);
  const inside = read.levels.filter((l) => l.side === 'inside');
  const support = read.levels.filter((l) => l.side === 'support').sort((a, b) => b.high - a.high);
  const pva = read.pva;
  return <section className="daily-report nexus-card" data-testid="nexus-structure-card">
    <div className="daily-report-head">
      <span className="page-kicker">NEXUS CORE · Nexus 結構分析</span>
      <span className="mono-num">{md(read.as_of)} 收盤資料{age > STALE_AFTER_DAYS ? `，已 ${age} 天未更新` : ''}</span>
    </div>
    <div className="daily-report-tags">
      <span className={`tag nx-${tone(read.bias)} nx-strong`}>綜合：{read.bias === '分歧' ? '週日線分歧' : read.bias}</span>
      <TimeframeTag name="週線" read={read.timeframes.W1} />
      <TimeframeTag name="日線" read={read.timeframes.D1} />
      {pva.status === 'ready' && pva.P != null ? <span className="tag">PVA P <b className="mono-num">{pva.P.toFixed(2)}</b>{pva.V != null ? <> V <b className="mono-num">{pva.V.toFixed(2)}</b></> : null}{pva.A != null ? <> A <b className="mono-num">{pva.A.toFixed(2)}</b></> : null}</span> : null}
    </div>
    <p className="daily-report-conclusion">{read.summary}</p>
    {read.levels.length ? <div className="table-scroll"><table className="nx-levels">
      <thead><tr><th>位置</th><th>來源</th><th>價位</th><th>距收盤</th><th>形成</th></tr></thead>
      <tbody>
        {resistance.map((l) => <LevelRow key={`r-${l.timeframe}-${l.kind}-${l.low}-${l.high}`} level={l} close={read.close} />)}
        <tr className="nx-close"><th>收盤</th><td>{md(read.as_of)}</td><td className="mono-num">{price(read.close)}</td><td /><td /></tr>
        {inside.map((l) => <LevelRow key={`i-${l.timeframe}-${l.kind}-${l.low}-${l.high}`} level={l} close={read.close} />)}
        {support.map((l) => <LevelRow key={`s-${l.timeframe}-${l.kind}-${l.low}-${l.high}`} level={l} close={read.close} />)}
      </tbody>
    </table></div> : null}
    {read.breaks.length ? <div className="nx-breaks"><span>近期結構突破</span>{read.breaks.map((b) => <span key={`${b.timeframe}-${b.confirmed_on}-${b.label}-${b.price}`} className={`nx-break nx-${b.dir > 0 ? 'up' : 'down'}`}>
      {b.timeframe === 'W1' ? '週' : '日'} {md(b.confirmed_on)} {b.strong ? '強勢 ' : ''}{b.label} {b.dir > 0 ? '↑' : '↓'} <b className="mono-num">{price(b.price)}</b>
    </span>)}</div> : null}
    <p className="daily-report-foot">Nexus 結構偵測器{read.detector_revision ? ` ${read.detector_revision.slice(0, 8)}` : ''} 機械判讀：方向取最近一次外部 BOS／CHoCH；FVG／OB 為尚未失效的區塊，前高／前低為尚未被突破的擺動點。{pva.status !== 'ready' ? 'PVA 本次未計算。' : ''}僅供判讀，不是下單指令。</p>
  </section>;
};
