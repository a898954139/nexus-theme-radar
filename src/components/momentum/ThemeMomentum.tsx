import React, { useMemo, useState } from 'react';
import { ThemeStocksCanvas } from '../common/ThemeStocksCanvas';
import { buildThemeStockEntries, mergeInstrumentRefs } from '../../lib/themeStocks';
import { DeviceType, MomentumTheme, RadarData } from '../../types';

interface ThemeMomentumProps {
  data: RadarData;
  device: DeviceType;
  onGoStock: (code: string, exchange?: string, tab?: 'fundamentals' | 'flows') => void;
}

const lineColors = ['#E8C56A', '#3FD0E8', '#7FD4A8', '#F0785F', '#B79BE0'];
const CHART_WIDTH = 600;
const CHART_VIEWBOX_HEIGHT = 220;
const CHART_TOP = 20;
const CHART_HEIGHT = 168;
const CHART_BOTTOM = CHART_TOP + CHART_HEIGHT;

function stageLabel(stage: string) {
  return ({ new: '加速中', accelerating: '加速中', expanding: '擴散', stable: '持平', cooling: '退燒' } as Record<string, string>)[stage] ?? stage;
}

function signed(value: number | null) {
  if (value === null || Number.isNaN(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value}`;
}

function historyHour(timestamp: string) {
  return new Date(timestamp).toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit', hour12: false });
}

function historyAxisHour(timestamp: string) {
  return String(new Date(timestamp).getHours()).padStart(2, '0');
}

function historyRangeLabel(observations: RadarData['momentumHistory']['observations']) {
  const first = observations[0]?.observed_hour;
  const last = observations[observations.length - 1]?.observed_hour;
  if (!first || !last) return '—';
  const date = new Date(first);
  const day = `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  return `${day} ${historyHour(first)} – ${historyHour(last)}`;
}

function uniqueSymbols(theme: MomentumTheme) {
  const seen = new Set<string>();
  return [...theme.direct_symbols, ...theme.related_symbols].filter((item) => {
    if (seen.has(item.instrument_id)) return false;
    seen.add(item.instrument_id);
    return true;
  });
}

function chartY(value: number, height: number) {
  return CHART_TOP + height - (Math.max(0, Math.min(100, value)) / 100) * height;
}

interface ChartPoint {
  x: number;
  y: number;
  value: number;
}

function chartPointsFor(values: Array<number | null>, width: number, height: number) {
  return values.map<ChartPoint | null>((value, index) => {
    if (value === null) return null;
    const x = values.length <= 1 ? width / 2 : (index / (values.length - 1)) * width;
    return { x, y: chartY(value, height), value };
  });
}

function keyPointIndexes(length: number, maxPoints = 8) {
  if (length <= maxPoints) return new Set(Array.from({ length }, (_, index) => index));
  return new Set(Array.from({ length: maxPoints }, (_, index) => Math.round((index / (maxPoints - 1)) * (length - 1))));
}

function segmentsFor(values: Array<number | null>, width: number, height: number) {
  const points = chartPointsFor(values, width, height);
  const segments: string[] = [];
  let current: ChartPoint[] = [];
  points.forEach((point) => {
    if (point === null) {
      if (current.length > 1) segments.push(current.map(({ x, y }) => `${x},${y}`).join(' '));
      current = [];
    } else {
      current.push(point);
    }
  });
  if (current.length > 1) segments.push(current.map(({ x, y }) => `${x},${y}`).join(' '));
  return segments;
}

const ThemeStockChips: React.FC<{
  theme: MomentumTheme;
  onGoStock: ThemeMomentumProps['onGoStock'];
}> = ({ theme, onGoStock }) => {
  const symbols = uniqueSymbols(theme);
  const visibleSymbols = symbols.slice(0, 4);
  const [canvasOpen, setCanvasOpen] = useState(false);
  return (
    <>
      <div className="momentum-stock-chips">
        {visibleSymbols.map((stock) => (
          <div className="momentum-stock-chip" key={stock.instrument_id}>
            <button type="button" className="stock-code-link" onClick={() => onGoStock(stock.symbol, stock.exchange, 'fundamentals')}>
              <span className="chip-color-bar" />
              <b className="mono-num">{stock.symbol}</b><span>{stock.name_zh}</span>
            </button>
            <button type="button" className="chip-flow-link" onClick={() => onGoStock(stock.symbol, stock.exchange, 'flows')}>法人</button>
          </div>
        ))}
        {symbols.length > 4 ? <button type="button" className="more-chip mono-num" aria-label={`展開${theme.name_zh}全部 ${symbols.length} 檔股票`} onClick={() => setCanvasOpen(true)}>＋{symbols.length - 4}</button> : null}
      </div>
      {canvasOpen ? <ThemeStocksCanvas themeName={theme.name_zh} stocks={buildThemeStockEntries(theme.direct_symbols, theme.related_symbols)} onClose={() => setCanvasOpen(false)} onGoStock={onGoStock} /> : null}
    </>
  );
};

export const ThemeMomentum: React.FC<ThemeMomentumProps> = ({ data, device, onGoStock }) => {
  const themes = useMemo(() => {
    const rankingById = new Map(data.themeRanking.themes.map((theme) => [theme.theme_id, theme]));
    return data.momentumLatest.themes.slice(0, 5).map((theme) => {
      const ranking = rankingById.get(theme.theme_id);
      return {
        ...theme,
        direct_symbols: mergeInstrumentRefs(theme.direct_symbols, ranking?.direct_mentions ?? []),
        related_symbols: mergeInstrumentRefs(theme.related_symbols, ranking?.supply_chain_candidates ?? [])
      };
    });
  }, [data.momentumLatest.themes, data.themeRanking.themes]);
  const [range, setRange] = useState<'24h' | '72h' | '7d'>('24h');
  const [selectedThemeId, setSelectedThemeId] = useState(themes[0]?.theme_id ?? '');
  const rangeHours = range === '24h' ? 24 : range === '72h' ? 72 : 168;
  const observations = useMemo(() => {
    const source = data.momentumHistory.observations.slice().sort((a, b) => new Date(a.observed_hour).getTime() - new Date(b.observed_hour).getTime());
    const latest = source[source.length - 1];
    if (!latest) return source;
    const cutoff = new Date(latest.observed_hour).getTime() - rangeHours * 60 * 60 * 1000;
    return source.filter((point) => new Date(point.observed_hour).getTime() >= cutoff);
  }, [data.momentumHistory.observations, rangeHours]);

  return (
    <div className="page-content momentum-page">
      <header className="page-intro">
        <span className="page-kicker">PUBLIC THEME MOMENTUM · v0.9</span>
        <h1>哪些台股題材正在升溫？</h1>
        <div className="gold-rule" />
        <p>依目前熱度與 24 小時熱度加速度排序，並列出每個題材的相關個股：點代號進基本面分析，點「法人」直接看三大法人資金流向。資料只呈現公開彙總結果，不代表投資建議。</p>
      </header>

      <div className="range-tabs" role="tablist" aria-label="動能區間">
        {(['24h', '72h', '7d'] as const).map((value) => <button className={range === value ? 'is-selected' : ''} key={value} type="button" onClick={() => setRange(value)}>{value}</button>)}
      </div>

      <section className="momentum-latest-section">
        <div className="section-heading momentum-heading"><span className="page-kicker">LATEST · 最新題材動能 · {range}</span><span className="section-note">公開彙總</span></div>
        <div className="momentum-table-wrap">
          <div className="momentum-table-head"><span>#</span><span>題材</span><span>相關個股（點代號看基本面 · 點法人看資金流向）</span><span>動能</span><span>熱度</span><span>階段</span></div>
          {themes.map((theme) => (
            <article className="momentum-row" key={theme.theme_id}>
              <span className="rank-num mono-num">{String(theme.rank).padStart(2, '0')}</span>
              <div className="momentum-theme-name"><strong>{theme.name_zh}</strong><span>{theme.qualification_status === 'qualified' ? 'qualified' : 'near threshold'}</span></div>
              <ThemeStockChips theme={theme} onGoStock={onGoStock} />
              <strong className={`momentum-value mono-num ${theme.momentum_score >= 0 ? 'positive' : 'negative'}`}>{signed(theme.momentum_score)}</strong>
              <strong className="heat-value mono-num">{theme.heat_score}</strong>
              <span className="stage-value">{stageLabel(theme.lifecycle_stage)}</span>
            </article>
          ))}
        </div>
      </section>

      <section className="momentum-history-section">
        <div className="section-heading"><span className="page-kicker">HISTORY · 動能走勢</span></div>
        <div className="history-context"><span>五大題材 · 動能分數 · 逐小時（缺少的小時保留為斷點）</span><span className="mono-num">{historyRangeLabel(observations)}</span></div>
        <div className="history-legend">
          {themes.map((theme, index) => {
            const active = selectedThemeId === theme.theme_id;
            return (
              <button className={`legend-chip ${active ? 'is-active' : ''}`} key={theme.theme_id} type="button" onClick={() => setSelectedThemeId(active ? '' : theme.theme_id)}>
                <span className="legend-swatch" style={{ background: lineColors[index] }} />
                <span>{theme.name_zh}</span>
                <b className="mono-num">{theme.heat_score}</b>
                <em className={theme.momentum_score >= 0 ? 'positive' : 'negative'}>{signed(theme.momentum_score)}</em>
              </button>
            );
          })}
        </div>
        <div className="history-chart-scroll">
          <div className="history-chart-wrap">
            <svg viewBox={`0 0 ${CHART_WIDTH} ${CHART_VIEWBOX_HEIGHT}`} role="img" aria-label="五題材熱度歷史折線圖" preserveAspectRatio="none">
              {[25, 50, 75].map((value) => {
                const y = chartY(value, CHART_HEIGHT);
                return <line key={value} x1="0" x2={CHART_WIDTH} y1={y} y2={y} className="chart-grid-line" />;
              })}
              {themes.map((theme, index) => {
                const values = observations.map((point) => point.themes.find((item) => item.theme_id === theme.theme_id)?.heat_score ?? null);
                const points = chartPointsFor(values, CHART_WIDTH, CHART_HEIGHT);
                const paths = segmentsFor(values, CHART_WIDTH, CHART_HEIGHT).map((path) => <polyline key={path} points={path} fill="none" stroke={lineColors[index]} className={selectedThemeId && selectedThemeId !== theme.theme_id ? 'chart-line is-muted' : 'chart-line'} />);
                const showPoints = selectedThemeId === theme.theme_id;
                return (
                  <g key={theme.theme_id}>
                    {paths}
                    {showPoints ? points.map((point, pointIndex) => {
                      if (!point) return null;
                      const labelX = Math.max(8, Math.min(CHART_WIDTH - 8, point.x));
                      const labelY = Math.max(12, point.y - 8);
                      return (
                        <g key={`${theme.theme_id}-${pointIndex}`}>
                          <circle cx={point.x} cy={point.y} r="4" fill="var(--shell-bg)" stroke={lineColors[index]} strokeWidth="2" />
                          <text x={labelX} y={labelY} textAnchor="middle" className="chart-value-label">{point.value}</text>
                        </g>
                      );
                    }) : null}
                  </g>
                );
              })}
              {Array.from(keyPointIndexes(observations.length)).map((index) => {
                const point = observations[index];
                if (!point) return null;
                const x = observations.length <= 1 ? CHART_WIDTH / 2 : (index / (observations.length - 1)) * CHART_WIDTH;
                const labelX = Math.max(18, Math.min(CHART_WIDTH - 18, x));
                return <text key={point.observed_hour} x={labelX} y={CHART_BOTTOM + 22} textAnchor="middle" className="chart-axis-label">{historyAxisHour(point.observed_hour)}</text>;
              })}
            </svg>
          </div>
        </div>
        {device === 'mobile' ? <p className="chart-mobile-note">左右滑動可查看完整圖表與圖例。</p> : null}
      </section>
    </div>
  );
};
