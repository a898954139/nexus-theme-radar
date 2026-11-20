import React, { useMemo, useRef, useState } from 'react';
import { ThemeStocksCanvas } from '../common/ThemeStocksCanvas';
import { ThemeCarousel } from '../common/ThemeCarousel';
import { FocusTable } from '../common/FocusTable';
import { DivergingBars, PageHero, PageTabs, scrollToRef } from '../common/FeedKit';
import { formatLots, rankedFocusThemes, shortDate } from '../common/ThemeFocusBoard';
import { SectionHead } from '../home/FeedBlocks';
import { buildThemeStockEntries, mergeInstrumentRefs } from '../../lib/themeStocks';
import { DeviceType, MomentumTheme, RadarData, ThemeFocusData } from '../../types';

interface ThemeMomentumProps {
  data: RadarData;
  focus?: ThemeFocusData | null;
  device: DeviceType;
  onGoStock: (code: string, exchange?: string, tab?: 'fundamentals' | 'flows') => void;
}

const lineColors = ['#E8C56A', '#3FD0E8', '#7FD4A8', '#F0785F', '#B79BE0'];
const CHART_TOP = 20;
const CHART_HEIGHT = 110;

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

function chartY(value: number, height: number) {
  return CHART_TOP + height - (Math.max(0, Math.min(100, value)) / 100) * height;
}

function segmentsFor(values: Array<number | null>, width: number, height: number) {
  const points = values.map((value, index) => {
    if (value === null) return null;
    const x = values.length <= 1 ? width / 2 : (index / (values.length - 1)) * width;
    const y = chartY(value, height);
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

export const ThemeMomentum: React.FC<ThemeMomentumProps> = ({ data, focus = null, device, onGoStock }) => {
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

  const focusThemes = useMemo(() => rankedFocusThemes(focus), [focus]);
  const focusRef = useRef<HTMLElement>(null);
  const latestRef = useRef<HTMLElement>(null);
  const historyRef = useRef<HTMLElement>(null);
  const newsRef = useRef<HTMLElement>(null);
  const [activeTab, setActiveTab] = useState('focus');
  const [newsOpen, setNewsOpen] = useState(false);
  const mobile = device === 'mobile';
  const go = (id: string, ref: React.RefObject<HTMLElement>) => { setActiveTab(id); if (id === 'news') setNewsOpen(true); scrollToRef(ref); };

  const aligned = focusThemes.filter((theme) => theme.stance === 'focus').length;
  const outflow = focusThemes.filter((theme) => theme.stance === 'outflow').length;
  const topFocus = focusThemes[0];
  const sentence = topFocus
    ? `關注分最高是${topFocus.name_zh}（${topFocus.focus_score}，${topFocus.stance_label}）；${aligned} 個題材新聞與法人同向，${outflow} 個遭法人調節。`
    : `${themes[0]?.name_zh ?? '—'} 熱度最高。`;
  const heatRank = data.momentumLatest.themes.slice().sort((a, b) => b.heat_score - a.heat_score).slice(0, 10);
  const foreignBars = focusThemes.slice().sort((a, b) => b.flow.foreign_5d - a.flow.foreign_5d)
    .map((theme) => ({ name: theme.name_zh, value: theme.flow.foreign_5d, label: formatLots(theme.flow.foreign_5d) }));
  const themeNews = data.themeRanking.themes.filter((theme) => theme.representative_news).slice(0, 6);

  const focusSection = (
    <section className="fd-section is-first" ref={focusRef} aria-label="可關注題材">
      <SectionHead title="可關注題材" note={focus ? `法人 ${focus.flow_window_days} 日，資料日 ${shortDate(focus.flow_as_of)}，單位：張` : undefined} />
      <FocusTable data={focus} onGoStock={onGoStock} limit={mobile ? 5 : 8} />
      <p className="fd-meta">關注分 = 0.5 × 新聞熱度 + 0.5 × 法人買超家數占比。只描述新聞與籌碼是否同向，不代表預測漲跌。</p>
    </section>
  );

  const latestSection = (
    <section className="fd-section momentum-latest-section" ref={latestRef} aria-label="動能排行">
      <div className="fd-head">
        <h2>動能排行</h2>
        <span className="fd-head-note">公開彙總，點代號看基本面、點「法人」看資金流向</span>
        <div className="fd-seg range-tabs" role="tablist" aria-label="動能區間">
          {(['24h', '72h', '7d'] as const).map((value) => <button className={range === value ? 'is-selected' : ''} key={value} type="button" onClick={() => setRange(value)}>{value}</button>)}
        </div>
      </div>
      <div className="momentum-table-wrap">
        <div className="momentum-table-head"><span>#</span><span>題材</span><span>相關個股</span><span>動能</span><span>熱度</span><span>階段</span></div>
        {themes.map((theme) => (
          <article className="momentum-row" key={theme.theme_id}>
            <span className="rank-num mono-num">{theme.rank}</span>
            <div className="momentum-theme-name"><strong>{theme.name_zh}</strong><span>{theme.qualification_status === 'qualified' ? '已達門檻' : '接近門檻'}</span></div>
            <ThemeStockChips theme={theme} onGoStock={onGoStock} />
            <strong className={`momentum-value mono-num ${theme.momentum_score >= 0 ? 'positive' : 'negative'}`}>{signed(theme.momentum_score)}</strong>
            <strong className="heat-value mono-num">{theme.heat_score}</strong>
            <span className="stage-value">{stageLabel(theme.lifecycle_stage)}</span>
          </article>
        ))}
      </div>
    </section>
  );

  const historySection = (
    <section className="fd-section momentum-history-section" ref={historyRef} aria-label="熱度走勢">
      <SectionHead title="熱度走勢" note={`五大題材，逐小時，${historyRangeLabel(observations)}，缺少的小時保留為斷點`} />
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
      <div className="fd-box history-box">
        <div className="history-chart-scroll">
          <div className="history-chart-wrap">
            <svg viewBox="0 0 600 140" role="img" aria-label="五題材熱度歷史折線圖" preserveAspectRatio="none">
              {[46, 92].map((y) => <line key={y} x1="0" x2="600" y1={y} y2={y} className="chart-grid-line" />)}
            {themes.map((theme, index) => {
              const values = observations.map((point) => point.themes.find((item) => item.theme_id === theme.theme_id)?.heat_score ?? null);
              const paths = segmentsFor(values, 600, CHART_HEIGHT).map((points) => <polyline key={points} points={points} fill="none" stroke={lineColors[index]} className={selectedThemeId && selectedThemeId !== theme.theme_id ? 'chart-line is-muted' : 'chart-line'} />);
              const latestValue = values[values.length - 1];
              const latestX = values.length <= 1 ? 300 : 600;
              const latestY = latestValue === null || latestValue === undefined ? 0 : chartY(latestValue, CHART_HEIGHT);
              const showPoint = selectedThemeId === theme.theme_id;
              return <g key={theme.theme_id}>{paths}{showPoint && latestValue !== null && latestValue !== undefined ? <><circle cx={latestX} cy={latestY} r="3" fill={lineColors[index]} /><text x={latestX + 7} y={latestY - 6} className="chart-value-label">{latestValue}</text></> : null}</g>;
            })}
            </svg>
          </div>
          <div className="history-axis-labels" style={{ gridTemplateColumns: `repeat(${Math.max(observations.length, 1)}, minmax(0, 1fr))` }}>{observations.map((point) => <span key={point.observed_hour}>{historyHour(point.observed_hour)}</span>)}</div>
        </div>
      </div>
      <p className="fd-meta fd-num">{observations.length} 個觀測點{mobile ? '，左右滑動可查看完整圖表' : ''}</p>
    </section>
  );

  const newsSection = (
    <section className="fd-section" ref={newsRef} aria-label="題材新聞與成分股">
      <details className="momentum-news-details" open={newsOpen} onToggle={(event) => setNewsOpen((event.target as HTMLDetailsElement).open)}>
        <summary><span className="fd-summary-title">題材新聞與完整成分股</span><span className="fd-head-note">逐題材查看代表新聞、直接提及與供應鏈個股</span></summary>
        <ThemeCarousel data={data} device={device} onGoStock={onGoStock} />
      </details>
    </section>
  );

  const rail = (
    <aside className="fd-rail" aria-label="題材概覽">
      <section className="fd-rail-block">
        <SectionHead level={3} title="熱度排行" note={`${data.momentumLatest.themes.length} 個題材`} />
        <ol className="fd-rank-list">
          {heatRank.map((theme, index) => (
            <li key={theme.theme_id}>
              <span className="fd-rank">{index + 1}</span>
              <span className="fd-rank-name">{theme.name_zh}</span>
              <span className="fd-meter"><span className="fd-meter-track"><span style={{ width: `${Math.min(100, theme.heat_score)}%` }} /></span><span className="fd-num">{theme.heat_score}</span></span>
              <span className="fd-faint fd-rank-stage">{stageLabel(theme.lifecycle_stage)}</span>
            </li>
          ))}
        </ol>
      </section>
      {foreignBars.length > 0 ? (
        <section className="fd-rail-block">
          <SectionHead level={3} title="外資流向" note={focus ? `${focus.flow_window_days} 日，張` : undefined} />
          <DivergingBars title="外資買賣超，依題材" note={shortDate(focus?.flow_as_of)} bars={foreignBars} />
        </section>
      ) : null}
      {themeNews.length > 0 ? (
        <section className="fd-rail-block">
          <SectionHead level={3} title="題材代表新聞" />
          <div className="fd-news">
            {themeNews.map((theme) => (
              <article className="fd-news-row" key={theme.theme_id}>
                <a href={theme.representative_news!.canonical_url} target="_blank" rel="noreferrer">{theme.representative_news!.title_zh}</a>
                <div className="fd-news-meta"><span>{theme.name_zh}</span><span>{theme.representative_news!.source}</span></div>
              </article>
            ))}
          </div>
        </section>
      ) : null}
    </aside>
  );

  const tabs = (
    <PageTabs label="題材動能分區" tabs={[
      { id: 'focus', label: '可關注題材', active: activeTab === 'focus', onClick: () => go('focus', focusRef) },
      { id: 'latest', label: '動能排行', active: activeTab === 'latest', onClick: () => go('latest', latestRef) },
      { id: 'history', label: '熱度走勢', active: activeTab === 'history', onClick: () => go('history', historyRef) },
      { id: 'news', label: '新聞與成分股', active: activeTab === 'news', onClick: () => go('news', newsRef) },
    ]} />
  );
  const hero = <PageHero title="題材動能" sentence={sentence} meta={focus ? `法人資料 ${shortDate(focus.flow_as_of)}，題材 ${shortDate(focus.theme_generated_at ?? focus.generated_at)}` : undefined} />;

  if (mobile) {
    return (
      <div className="page-content momentum-page fd fd-page is-mobile">
        {tabs}{hero}{focusSection}{latestSection}{rail}{historySection}{newsSection}
        <p className="disclaimer">不構成投資建議。</p>
      </div>
    );
  }
  return (
    <div className="page-content momentum-page fd fd-page">
      {tabs}
      <div className="fd-cols">
        <div className="fd-main">{hero}{focusSection}{latestSection}{historySection}{newsSection}
          <p className="disclaimer">不構成投資建議。</p>
        </div>
        {rail}
      </div>
    </div>
  );
};
