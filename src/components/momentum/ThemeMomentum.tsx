import React, { useMemo, useState } from 'react';
import { DeviceType, MomentumTheme, RadarData } from '../../types';

interface ThemeMomentumProps {
  data: RadarData;
  device: DeviceType;
  onGoStock: (code: string, exchange?: string, tab?: 'fundamentals' | 'flows') => void;
}

const lineColors = ['#E8C56A', '#3FD0E8', '#7FD4A8', '#F0785F', '#B79BE0'];

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

function segmentsFor(values: Array<number | null>, width: number, height: number) {
  const points = values.map((value, index) => {
    if (value === null) return null;
    const x = values.length <= 1 ? width / 2 : (index / (values.length - 1)) * width;
    const y = height - ((Math.max(75, Math.min(100, value)) - 75) / 25) * height;
    return `${x},${y}`;
  });
  const segments: string[] = [];
  let current: string[] = [];
  points.forEach((point) => {
    if (point === null) {
      if (current.length > 1) segments.push(current.join(' '));
      current = [];
    } else {
      current.push(point);
    }
  });
  if (current.length > 1) segments.push(current.join(' '));
  return segments;
}

const ThemeStockChips: React.FC<{
  theme: MomentumTheme;
  onGoStock: ThemeMomentumProps['onGoStock'];
}> = ({ theme, onGoStock }) => {
  const symbols = uniqueSymbols(theme);
  const visibleSymbols = symbols.slice(0, 4);
  return (
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
      {symbols.length > 4 ? <span className="more-chip mono-num">＋{symbols.length - 4}</span> : null}
    </div>
  );
};

export const ThemeMomentum: React.FC<ThemeMomentumProps> = ({ data, device, onGoStock }) => {
  const themes = useMemo(() => data.momentumLatest.themes.slice(0, 5), [data.momentumLatest.themes]);
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
        <div className="section-heading"><span className="page-kicker">HISTORY · 五題材同框折線圖</span><span className="section-note mono-num">{observations.length} observations</span></div>
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
            <svg viewBox="0 0 600 140" role="img" aria-label="五題材熱度歷史折線圖" preserveAspectRatio="none">
              {[46, 92].map((y) => <line key={y} x1="0" x2="600" y1={y} y2={y} className="chart-grid-line" />)}
            {themes.map((theme, index) => {
              const values = observations.map((point) => point.themes.find((item) => item.theme_id === theme.theme_id)?.heat_score ?? null);
              const paths = segmentsFor(values, 600, 110).map((points) => <polyline key={points} points={points} fill="none" stroke={lineColors[index]} className={selectedThemeId && selectedThemeId !== theme.theme_id ? 'chart-line is-muted' : 'chart-line'} />);
              const latestValue = values[values.length - 1];
              const latestX = values.length <= 1 ? 300 : 600;
              const latestY = latestValue === null || latestValue === undefined ? 0 : 130 - ((Math.max(75, Math.min(100, latestValue)) - 75) / 25) * 110;
              const showPoint = selectedThemeId === theme.theme_id;
              return <g key={theme.theme_id}>{paths}{showPoint && latestValue !== null && latestValue !== undefined ? <><circle cx={latestX} cy={latestY} r="3" fill={lineColors[index]} /><text x={latestX + 7} y={latestY - 6} className="chart-value-label">{latestValue}</text></> : null}</g>;
            })}
            </svg>
          </div>
          <div className="history-axis-labels" style={{ gridTemplateColumns: `repeat(${Math.max(observations.length, 1)}, minmax(0, 1fr))` }}>{observations.map((point) => <span key={point.observed_hour}>{historyHour(point.observed_hour)}</span>)}</div>
        </div>
        {device === 'mobile' ? <p className="chart-mobile-note">左右滑動可查看完整圖表與圖例。</p> : null}
      </section>
    </div>
  );
};
