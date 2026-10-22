import React, { useEffect, useMemo, useRef, useState } from 'react';
import { StockAuditCandle, StockAuditTechnical } from '../../services/stockAudit';

interface StockAuditChartProps {
  symbol: string;
  price: number;
  technical: StockAuditTechnical;
}

interface ChartPoint {
  x: number;
  y: number;
}

const PLOT_LEFT = 34;
const PLOT_RIGHT_MARGIN = 46;
const PLOT_TOP = 20;
const PLOT_BOTTOM = 212;
const VOLUME_TOP = 228;
const VOLUME_BOTTOM = 276;

function movingAverage(candles: StockAuditCandle[], window: number): Array<number | null> {
  let total = 0;
  return candles.map((candle, index) => {
    total += candle.close;
    if (index >= window) total -= candles[index - window].close;
    return index + 1 >= window ? total / window : null;
  });
}

function chartNumber(value: number): string {
  return value.toLocaleString('zh-TW', { maximumFractionDigits: 2 });
}

function shortDate(value: string): string {
  return value.slice(5);
}

function linePath(points: Array<ChartPoint | null>): string {
  return points.reduce((path, point) => {
    if (!point) return path;
    return `${path}${path ? 'L' : 'M'}${point.x.toFixed(2)},${point.y.toFixed(2)} `;
  }, '').trim();
}

export const StockAuditChart: React.FC<StockAuditChartProps> = ({ symbol, price, technical }) => {
  const candles = technical.candles;
  const frameRef = useRef<HTMLDivElement>(null);
  const [viewWidth, setViewWidth] = useState(() => {
    if (typeof window === 'undefined') return 640;
    return Math.max(320, Math.min(720, window.innerWidth - 48));
  });

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return undefined;
    const updateWidth = () => {
      setViewWidth(Math.max(320, Math.min(720, Math.round(frame.getBoundingClientRect().width))));
    };
    updateWidth();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(updateWidth);
    observer.observe(frame);
    return () => observer.disconnect();
  }, []);

  const chart = useMemo(() => {
    const plotRight = viewWidth - PLOT_RIGHT_MARGIN;
    const visibleStart = Math.max(0, candles.length - 90);
    const visibleCandles = candles.slice(visibleStart);
    const values = visibleCandles.flatMap((candle) => [candle.high, candle.low]);
    const min = Math.min(...values, technical.support, price);
    const max = Math.max(...values, technical.resistance, price);
    const padding = Math.max((max - min) * 0.08, max * 0.01);
    const scaleMin = Math.max(0, min - padding);
    const scaleMax = max + padding;
    const xStep = (plotRight - PLOT_LEFT) / Math.max(visibleCandles.length - 1, 1);
    const y = (value: number) => PLOT_BOTTOM - ((value - scaleMin) / Math.max(scaleMax - scaleMin, 1)) * (PLOT_BOTTOM - PLOT_TOP);
    const volumeMax = Math.max(...visibleCandles.map((candle) => candle.volume), 1);
    const ma20All = movingAverage(candles, 20);
    const ma60All = movingAverage(candles, 60);
    const ma20 = ma20All.slice(visibleStart);
    const ma60 = ma60All.slice(visibleStart);
    return {
      visibleCandles,
      viewWidth,
      plotRight,
      scaleMin,
      scaleMax,
      xStep,
      y,
      volumeMax,
      ma20,
      ma60,
      ma20Path: linePath(ma20.map((value, index) => value === null ? null : { x: PLOT_LEFT + index * xStep, y: y(value) })),
      ma60Path: linePath(ma60.map((value, index) => value === null ? null : { x: PLOT_LEFT + index * xStep, y: y(value) }))
    };
  }, [candles, price, technical.resistance, technical.support, viewWidth]);

  const visibleCandles = chart.visibleCandles;
  const lastDate = visibleCandles[visibleCandles.length - 1].date;
  const firstDate = visibleCandles[0].date;
  const candleWidth = Math.max(2.8, Math.min(8, chart.xStep * 0.58));
  const yTicks = [0, 0.5, 1].map((fraction) => chart.scaleMax - (chart.scaleMax - chart.scaleMin) * fraction);
  const labelEvery = Math.max(1, Math.floor(visibleCandles.length / 5));
  const priceY = chart.y(price);
  const supportY = chart.y(technical.support);
  const resistanceY = chart.y(technical.resistance);

  return (
    <figure className="stock-audit-chart" data-testid="stock-audit-chart">
      <div className="stock-audit-chart-frame" ref={frameRef}>
        <svg
          viewBox={`0 0 ${chart.viewWidth} 300`}
          role="img"
          aria-labelledby={`${symbol}-chart-title ${symbol}-chart-desc`}
          preserveAspectRatio="none"
        >
          <title id={`${symbol}-chart-title`}>{symbol} 日線 K 線</title>
          <desc id={`${symbol}-chart-desc`}>最近 {visibleCandles.length} 個交易日的 OHLCV、MA20、MA60、支撐與壓力位置</desc>
          <g className="stock-audit-chart-grid" aria-hidden="true">
            {yTicks.map((value) => <line key={value} x1={PLOT_LEFT} x2={chart.plotRight} y1={chart.y(value)} y2={chart.y(value)} />)}
          </g>
          <g className="stock-audit-chart-axis" aria-hidden="true">
            {yTicks.map((value) => <text key={value} x={chart.viewWidth - 4} y={chart.y(value) + 3} textAnchor="end">{chartNumber(value)}</text>)}
            <text x={PLOT_LEFT} y={VOLUME_BOTTOM + 17}>{shortDate(firstDate)}</text>
            <text x={chart.plotRight} y={VOLUME_BOTTOM + 17} textAnchor="end">{shortDate(lastDate)}</text>
          </g>
          <g className="stock-audit-chart-levels" aria-hidden="true">
            <line className="is-support" x1={PLOT_LEFT} x2={chart.plotRight} y1={supportY} y2={supportY} />
            <line className="is-resistance" x1={PLOT_LEFT} x2={chart.plotRight} y1={resistanceY} y2={resistanceY} />
            <line className="is-current" x1={PLOT_LEFT} x2={chart.plotRight} y1={priceY} y2={priceY} />
            <text className="is-support-label" x={PLOT_LEFT + 5} y={supportY - 5}>支撐 {chartNumber(technical.support)}</text>
            <text className="is-resistance-label" x={PLOT_LEFT + 5} y={resistanceY - 5}>壓力 {chartNumber(technical.resistance)}</text>
            <text className="is-current-label" x={chart.plotRight - 5} y={priceY - 5} textAnchor="end">現價 {chartNumber(price)}</text>
          </g>
          <g className="stock-audit-chart-candles" aria-hidden="true">
            {visibleCandles.map((candle, index) => {
              const x = PLOT_LEFT + index * chart.xStep;
              const openY = chart.y(candle.open);
              const closeY = chart.y(candle.close);
              const rising = candle.close >= candle.open;
              const bodyTop = Math.min(openY, closeY);
              const bodyHeight = Math.max(Math.abs(openY - closeY), 1.2);
              return (
                <g key={candle.date} className={rising ? 'is-up' : 'is-down'}>
                  <line x1={x} x2={x} y1={chart.y(candle.high)} y2={chart.y(candle.low)} />
                  <rect x={x - candleWidth / 2} y={bodyTop} width={candleWidth} height={bodyHeight} />
                </g>
              );
            })}
          </g>
          <path className="stock-audit-chart-ma is-ma20" d={chart.ma20Path} aria-hidden="true" />
          <path className="stock-audit-chart-ma is-ma60" d={chart.ma60Path} aria-hidden="true" />
          <g className="stock-audit-chart-volume" aria-hidden="true">
            {visibleCandles.map((candle, index) => {
              const x = PLOT_LEFT + index * chart.xStep;
              const height = (candle.volume / chart.volumeMax) * (VOLUME_BOTTOM - VOLUME_TOP);
              return <rect key={candle.date} x={x - candleWidth / 2} y={VOLUME_BOTTOM - height} width={candleWidth} height={Math.max(height, 1)} className={candle.close >= candle.open ? 'is-up' : 'is-down'} />;
            })}
          </g>
          <g className="stock-audit-chart-date-ticks" aria-hidden="true">
            {visibleCandles.map((candle, index) => index % labelEvery === 0 ? (
              <text key={candle.date} x={PLOT_LEFT + index * chart.xStep} y={VOLUME_BOTTOM + 17}>{shortDate(candle.date)}</text>
            ) : null)}
          </g>
        </svg>
      </div>
      <figcaption className="stock-audit-chart-caption">
        <span className="stock-audit-chart-legend"><i className="is-current" />現價 <b>{chartNumber(price)}</b></span>
        <span className="stock-audit-chart-legend"><i className="is-ma20" />MA20 <b>{chartNumber(technical.ma20)}</b></span>
        <span className="stock-audit-chart-legend"><i className="is-ma60" />MA60 <b>{chartNumber(technical.ma60)}</b></span>
        <span className="stock-audit-chart-legend"><i className="is-volume" />成交量</span>
      </figcaption>
    </figure>
  );
};

