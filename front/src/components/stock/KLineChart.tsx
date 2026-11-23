import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  IChartApi,
  LineSeries,
  LineStyle,
  MouseEventParams,
  SeriesMarker,
  Time,
  createChart,
  createSeriesMarkers,
} from 'lightweight-charts';
import { fetchNexusStructure, NexusStructure } from '../../services/nexusStructure';
import { NexusZonesPrimitive, ZoneBox } from './nexusZones';
import { InstitutionalFlowItem } from '../../types';
import { directionClass, formatLots } from '../common/ThemeFocusBoard';

/**
 * Own K-line chart (lightweight-charts) fed by /api/candles, replacing the
 * TradingView embed: Taiwan colours (red = up, green = down), the v10 gold
 * palette, and the three-institution net (張) in its own pane under volume.
 */

export interface Candle { date: string; open: number; high: number; low: number; close: number; volume: number }

type Range = '6mo' | '1y' | '2y';
const RANGES: Array<[Range, string]> = [['6mo', '半年'], ['1y', '1 年'], ['2y', '2 年']];
const MAS: Array<[number, string]> = [[5, 'MA5'], [20, 'MA20'], [60, 'MA60']];

interface Palette { bg: string; text: string; faint: string; grid: string; border: string; up: string; down: string; ma: string[]; upSoft: string; downSoft: string; upZone: string; downZone: string }

function palette(light: boolean): Palette {
  return light
    ? { bg: '#FFFFFF', text: '#5D6D79', faint: '#8A98A3', grid: 'rgba(31, 41, 51, 0.06)', border: '#E3E8EC', up: '#CF3A2F', down: '#15834A', ma: ['#B7791F', '#1F7FC4', '#7C5CBF'], upSoft: 'rgba(207, 58, 47, 0.45)', downSoft: 'rgba(21, 131, 74, 0.45)', upZone: 'rgba(207, 58, 47, 0.10)', downZone: 'rgba(21, 131, 74, 0.10)' }
    : { bg: '#0E0B08', text: '#B9AE9C', faint: '#7D7262', grid: 'rgba(255, 225, 170, 0.05)', border: 'rgba(255, 225, 170, 0.12)', up: '#F0605A', down: '#34C47C', ma: ['#E2B866', '#9C8455', '#D8D2C4'], upSoft: 'rgba(240, 96, 90, 0.42)', downSoft: 'rgba(52, 196, 124, 0.42)', upZone: 'rgba(240, 96, 90, 0.12)', downZone: 'rgba(52, 196, 124, 0.12)' };
}

export function movingAverage(candles: Candle[], days: number) {
  const out: Array<{ time: string; value: number }> = [];
  let sum = 0;
  candles.forEach((candle, index) => {
    sum += candle.close;
    if (index >= days) sum -= candles[index - days].close;
    if (index >= days - 1) out.push({ time: candle.date, value: Math.round(sum / days * 100) / 100 });
  });
  return out;
}

async function fetchCandles(code: string, exchange: string, range: Range, signal: AbortSignal): Promise<Candle[]> {
  const response = await fetch(`/api/candles?symbol=${encodeURIComponent(code)}&exchange=${exchange}&range=${range}`, { signal });
  if (!response.ok) throw new Error(`candles ${response.status}`);
  const body = (await response.json()) as { items?: Candle[] };
  return body.items ?? [];
}

const ZONE_NAME: Record<string, string> = { fvg: 'FVG', ob: 'OB' };

/** Nexus overlay inputs: FVG / OB boxes, swing-level price lines, D1/W1 break markers. Exported for tests. */
export function nexusOverlay(read: NexusStructure, candles: Candle[], colors: Pick<Palette, 'up' | 'down' | 'upZone' | 'downZone'>) {
  const first = candles[0]?.date ?? '';
  const dates = new Set(candles.map((c) => c.date));
  const boxes: ZoneBox[] = read.levels
    .filter((l) => l.kind === 'fvg' || l.kind === 'ob')
    .map((l) => ({
      from: l.formed_on && l.formed_on >= first ? l.formed_on : first,
      low: l.low,
      high: l.high,
      fill: l.dir > 0 ? colors.upZone : colors.downZone,
      stroke: l.dir > 0 ? colors.up : colors.down,
      label: `${l.timeframe === 'W1' ? '週' : '日'} ${ZONE_NAME[l.kind]}${l.state === 'candidate' ? '（未回測）' : ''}`,
    }));
  const lines = read.levels
    .filter((l) => l.kind === 'swing_high' || l.kind === 'swing_low')
    .map((l) => ({ price: l.low, color: l.side === 'support' ? colors.up : colors.down, title: `${l.timeframe === 'W1' ? '週' : '日'}${l.kind === 'swing_high' ? '前高' : '前低'}` }));
  const markers: SeriesMarker<Time>[] = read.breaks
    .filter((b) => dates.has(b.confirmed_on))
    .sort((a, b) => a.confirmed_on.localeCompare(b.confirmed_on))
    .map((b) => ({
      time: b.confirmed_on as Time,
      position: b.dir > 0 ? 'belowBar' : 'aboveBar',
      shape: b.dir > 0 ? 'arrowUp' : 'arrowDown',
      color: b.dir > 0 ? colors.up : colors.down,
      text: `${b.timeframe === 'W1' ? '週' : ''}${b.label}`,
    }));
  return { boxes, lines, markers };
}

interface Hover { candle: Candle; prev?: Candle; ma: Array<number | undefined>; flow?: number }

const price = (value: number) => value.toLocaleString('en-US', { minimumFractionDigits: value < 100 ? 2 : 1, maximumFractionDigits: 2 });

export const KLineChart: React.FC<{ code: string; exchange: 'TWSE' | 'TPEX' | null; flows: InstitutionalFlowItem[] }> = ({ code, exchange, flows }) => {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [range, setRange] = useState<Range>('1y');
  const [candles, setCandles] = useState<Candle[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [hover, setHover] = useState<Hover | null>(null);
  const [nexus, setNexus] = useState<NexusStructure | null>(null);
  const [showNexus, setShowNexus] = useState(true);
  const light = typeof document !== 'undefined' && document.documentElement.dataset.theme === 'light';

  useEffect(() => {
    if (!exchange) { setFailed(true); return undefined; }
    const controller = new AbortController();
    setCandles(null);
    setFailed(false);
    fetchCandles(code, exchange, range, controller.signal)
      .then((rows) => { if (!controller.signal.aborted) { setCandles(rows); setFailed(rows.length < 2); } })
      .catch(() => { if (!controller.signal.aborted) setFailed(true); });
    return () => controller.abort();
  }, [code, exchange, range]);

  useEffect(() => {
    let active = true;
    setNexus(null);
    if (exchange) fetchNexusStructure(code, exchange).then((value) => { if (active) setNexus(value); });
    return () => { active = false; };
  }, [code, exchange]);

  const flowLots = useMemo(() => new Map(flows.map((flow) => [flow.date, Math.round(flow.total_net / 1000)])), [flows]);

  const defaultHover = useMemo<Hover | null>(() => {
    if (!candles?.length) return null;
    const last = candles.length - 1;
    const ma = MAS.map(([days]) => movingAverage(candles.slice(-days), days)[0]?.value);
    return { candle: candles[last], prev: candles[last - 1], ma, flow: flowLots.get(candles[last].date) };
  }, [candles, flowLots]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || !candles || candles.length < 2) return undefined;
    const colors = palette(light);
    const chart = createChart(host, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: colors.bg }, textColor: colors.text, fontFamily: "'Noto Sans TC', 'PingFang TC', system-ui, sans-serif", fontSize: 11, attributionLogo: false, panes: { separatorColor: colors.border, separatorHoverColor: colors.border } },
      grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: colors.faint, style: LineStyle.Dashed, labelBackgroundColor: '#3A3024' }, horzLine: { color: colors.faint, style: LineStyle.Dashed, labelBackgroundColor: '#3A3024' } },
      rightPriceScale: { borderColor: colors.border },
      timeScale: { borderColor: colors.border, rightOffset: 4, barSpacing: 7, minBarSpacing: 2 },
      localization: { locale: 'zh-TW', dateFormat: 'yyyy-MM-dd' },
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: colors.up, downColor: colors.down, borderUpColor: colors.up, borderDownColor: colors.down, wickUpColor: colors.up, wickDownColor: colors.down,
      priceLineColor: colors.faint, priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    });
    candleSeries.setData(candles.map((candle) => ({ time: candle.date, open: candle.open, high: candle.high, low: candle.low, close: candle.close })));

    if (nexus && showNexus) {
      const overlay = nexusOverlay(nexus, candles, colors);
      candleSeries.attachPrimitive(new NexusZonesPrimitive(overlay.boxes, colors.text));
      overlay.lines.forEach((line) => candleSeries.createPriceLine({ price: line.price, color: line.color, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: line.title }));
      if (overlay.markers.length) createSeriesMarkers(candleSeries, overlay.markers);
    }

    const maSeries = MAS.map(([days], index) => {
      const series = chart.addSeries(LineSeries, { color: colors.ma[index], lineWidth: index === 0 ? 1 : 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      series.setData(movingAverage(candles, days));
      return series;
    });

    const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false }, 1);
    volume.setData(candles.map((candle, index) => ({ time: candle.date, value: candle.volume, color: candle.close >= (candles[index - 1]?.close ?? candle.open) ? colors.upSoft : colors.downSoft })));

    const flowData = candles.filter((candle) => flowLots.has(candle.date)).map((candle) => { const value = flowLots.get(candle.date) ?? 0; return { time: candle.date, value, color: value >= 0 ? colors.up : colors.down }; });
    const flowSeries = flowData.length ? chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false }, 2) : null;
    flowSeries?.setData(flowData);

    // price : volume : 法人 = 70 : 15 : 15 of the chart height
    const panes = chart.panes();
    panes[0]?.setStretchFactor(flowSeries ? 0.7 : 0.82);
    panes[1]?.setStretchFactor(flowSeries ? 0.15 : 0.18);
    panes[2]?.setStretchFactor(0.15);

    const fit = Math.max(40, Math.floor(host.clientWidth / 7));
    const visible = Math.min(candles.length, fit, range === '6mo' ? 130 : range === '1y' ? 160 : 200);
    chart.timeScale().setVisibleLogicalRange({ from: candles.length - visible, to: candles.length + 3 });

    const byDate = new Map(candles.map((candle, index) => [candle.date, index]));
    const onMove = (param: MouseEventParams<Time>) => {
      if (!param.time) { setHover(null); return; }
      const index = byDate.get(String(param.time));
      if (index === undefined) return;
      const ma = maSeries.map((series) => { const point = param.seriesData.get(series) as { value?: number } | undefined; return point?.value; });
      setHover({ candle: candles[index], prev: candles[index - 1], ma, flow: flowLots.get(candles[index].date) });
    };
    chart.subscribeCrosshairMove(onMove);
    return () => { chart.unsubscribeCrosshairMove(onMove); chart.remove(); chartRef.current = null; };
  }, [candles, flowLots, light, range, nexus, showNexus]);

  const shown = hover ?? defaultHover;
  const change = shown?.prev ? shown.candle.close - shown.prev.close : 0;
  const changePct = shown?.prev ? change / shown.prev.close * 100 : 0;
  const tvUrl = exchange ? `https://www.tradingview.com/symbols/${exchange}-${code}/` : 'https://www.tradingview.com/markets/stocks-taiwan/';
  const colors = palette(light);

  return (
    <section className="stock-technical-panel kline">
      <div className="kline-bar">
        <div className="kline-legend">
          {shown ? <>
            <span className="kline-date mono-num">{shown.candle.date}</span>
            <span>開 <b className="mono-num">{price(shown.candle.open)}</b></span>
            <span>高 <b className="mono-num">{price(shown.candle.high)}</b></span>
            <span>低 <b className="mono-num">{price(shown.candle.low)}</b></span>
            <span>收 <b className={`mono-num ${directionClass(change)}`}>{price(shown.candle.close)}</b></span>
            <span className={`mono-num ${directionClass(change)}`}>{change >= 0 ? '+' : ''}{price(change)}（{changePct >= 0 ? '+' : ''}{changePct.toFixed(2)}%）</span>
            <span>量 <b className="mono-num">{shown.candle.volume.toLocaleString('zh-TW')}</b> 張</span>
            {shown.flow !== undefined ? <span>法人 <b className={`mono-num ${directionClass(shown.flow)}`}>{formatLots(shown.flow)}</b> 張</span> : null}
            {MAS.map(([, label], index) => shown.ma[index] !== undefined ? <span key={label} className="kline-ma"><i style={{ background: colors.ma[index] }} />{label} <b className="mono-num">{price(shown.ma[index] as number)}</b></span> : null)}
          </> : <span>{failed ? '' : 'K 線資料載入中…'}</span>}
        </div>
        <div className="kline-ranges" role="group" aria-label="期間">
          {nexus ? <button type="button" className={showNexus ? 'is-selected' : ''} aria-pressed={showNexus} onClick={() => setShowNexus((value) => !value)} title="在圖上顯示 Nexus 結構：FVG／OB 區塊、前高前低、BOS／CHoCH">Nexus 結構</button> : null}
          {RANGES.map(([value, label]) => <button key={value} type="button" className={range === value ? 'is-selected' : ''} onClick={() => setRange(value)}>{label}</button>)}
        </div>
      </div>
      <div className="kline-shell">
        {failed ? <div className="kline-fallback"><strong>K 線資料暫時無法取得</strong><a href={tvUrl} target="_blank" rel="noreferrer">改到 TradingView 查看 {exchange ?? ''}:{code} ↗</a></div> : null}
        <div ref={hostRef} className="kline-host" />
      </div>
      <div className="kline-foot">
        <span>日 K・價格來源 Yahoo Finance（可能延遲）・下方依序為成交量與三大法人合計買賣超（張）{nexus && showNexus ? `・Nexus 結構 ${nexus.as_of.slice(5).replace('-', '/')}：紅框＝多方 FVG／OB、綠框＝空方，虛線＝未破前高前低，箭頭＝BOS／CHoCH` : ''}</span>
        <a href={tvUrl} target="_blank" rel="noreferrer">TradingView ↗</a>
      </div>
    </section>
  );
};
