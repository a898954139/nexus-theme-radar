import React from 'react';
import { ThemeFocusData, ThemeFocusStance, ThemeFocusStock, ThemeFocusTheme } from '../../types';
import './focus.css';

export type GoStock = (code: string, exchange?: string, tab?: 'fundamentals' | 'flows') => void;

export const stanceTone: Record<ThemeFocusStance, string> = {
  focus: 'is-focus',
  money_first: 'is-money',
  news_only: 'is-news',
  outflow: 'is-out',
  watch: 'is-watch'
};

/** One-line reading of each stance, shown under the pill. */
const stanceHint: Record<ThemeFocusStance, string> = {
  focus: '新聞熱度與法人買盤同向，優先研究',
  money_first: '新聞還沒熱，法人已在布局',
  news_only: '話題熱但買盤不廣，等資金確認',
  outflow: '多數成分股遭法人調節，避開追價',
  watch: '訊號不足，持續觀察'
};

export function formatLots(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return `${sign}${Math.abs(value).toLocaleString('zh-TW')}`;
}

export function directionClass(value: number): string {
  if (value > 0) return 'positive';
  if (value < 0) return 'negative';
  return '';
}

export function shortDate(value: string | null | undefined): string {
  if (!value) return '—';
  const match = /^\d{4}-(\d{2})-(\d{2})/.exec(value);
  return match ? `${match[1]}/${match[2]}` : value;
}

/** Themes with at least one member the official flow data covers. */
export function rankedFocusThemes(data: ThemeFocusData | null): ThemeFocusTheme[] {
  if (!data) return [];
  return data.themes.filter((theme) => theme.flow.covered_count > 0);
}

/** Every focus theme a symbol belongs to, best focus rank first. */
export function themesForSymbol(data: ThemeFocusData | null, symbol: string): ThemeFocusTheme[] {
  if (!data) return [];
  return data.themes.filter((theme) =>
    theme.leaders.some((stock) => stock.symbol === symbol) || theme.outflows.some((stock) => stock.symbol === symbol)
  );
}

const StockChip: React.FC<{
  stock: ThemeFocusStock;
  onGoStock: GoStock;
  tone?: 'up' | 'down';
}> = ({ stock, onGoStock, tone = 'up' }) => (
  <button
    type="button"
    className={`focus-stock-chip ${tone === 'down' ? 'is-down' : ''}`}
    onClick={() => onGoStock(stock.symbol, stock.exchange, 'flows')}
    title={`${stock.symbol} ${stock.name_zh}：法人 ${stock.flow?.days ?? 5} 日 ${formatLots(stock.flow?.total_5d ?? 0)} 張${stock.flow && stock.flow.streak !== 0 ? `，連${stock.flow.streak > 0 ? '買' : '賣'} ${Math.abs(stock.flow.streak)} 日` : ''}`}
  >
    <b className="mono-num">{stock.symbol}</b>
    <span>{stock.name_zh}</span>
    {stock.relation === 'direct' ? <i>新聞點名</i> : null}
    <em className={`mono-num ${directionClass(stock.flow?.total_5d ?? 0)}`}>{formatLots(stock.flow?.total_5d ?? 0)}</em>
  </button>
);

export const ThemeFocusCard: React.FC<{
  theme: ThemeFocusTheme;
  onGoStock: GoStock;
  selected?: boolean;
  onSelect?: (themeId: string) => void;
  leaderCount?: number;
  showHeadline?: boolean;
}> = ({ theme, onGoStock, selected = false, onSelect, leaderCount = 3, showHeadline = false }) => {
  const breadthPct = theme.flow.breadth === null ? null : Math.round(theme.flow.breadth * 100);
  return (
    <article className={`focus-card ${stanceTone[theme.stance]} ${selected ? 'is-selected' : ''}`}>
      <header>
        <span className="focus-rank mono-num">{String(theme.focus_rank).padStart(2, '0')}</span>
        {onSelect ? (
          <button type="button" className="focus-name" onClick={() => onSelect(theme.theme_id)} aria-pressed={selected}>
            {theme.name_zh}
          </button>
        ) : <strong className="focus-name">{theme.name_zh}</strong>}
        <span className="focus-score mono-num" title="關注分 = 0.5 × 新聞熱度 + 0.5 × 法人買超家數占比">{theme.focus_score}</span>
      </header>
      <div className="focus-stance">
        <span className="focus-pill">{theme.stance_label}</span>
        <small>{stanceHint[theme.stance]}</small>
      </div>
      {showHeadline && theme.headline?.title ? (
        theme.headline.url
          ? <a className="focus-headline" href={theme.headline.url} target="_blank" rel="noreferrer" title={theme.headline.title}>{theme.headline.title}</a>
          : <span className="focus-headline" title={theme.headline.title}>{theme.headline.title}</span>
      ) : null}
      <dl className="focus-metrics">
        <div><dt>新聞熱度</dt><dd className="mono-num">{theme.heat_score}</dd></div>
        <div>
          <dt>法人買超家數</dt>
          <dd className="mono-num">{theme.flow.positive_count}/{theme.flow.covered_count}<small>{breadthPct === null ? '' : ` · ${breadthPct}%`}</small></dd>
        </div>
        <div><dt>外資 5 日</dt><dd className={`mono-num ${directionClass(theme.flow.foreign_5d)}`}>{formatLots(theme.flow.foreign_5d)}</dd></div>
        <div><dt>投信 5 日</dt><dd className={`mono-num ${directionClass(theme.flow.trust_5d)}`}>{formatLots(theme.flow.trust_5d)}</dd></div>
      </dl>
      {breadthPct !== null ? (
        <div className="focus-breadth" aria-hidden="true"><span style={{ width: `${breadthPct}%` }} /></div>
      ) : null}
      <div className="focus-stocks">
        <span className="focus-stocks-label">法人買超領先</span>
        {theme.leaders.length
          ? theme.leaders.slice(0, leaderCount).map((stock) => <StockChip key={stock.instrument_id} stock={stock} onGoStock={onGoStock} />)
          : <span className="focus-empty">近 5 日無成分股獲法人買超</span>}
      </div>
      {theme.outflows[0] ? (
        <div className="focus-stocks is-outflow">
          <span className="focus-stocks-label">主要賣壓</span>
          <StockChip stock={theme.outflows[0]} onGoStock={onGoStock} tone="down" />
        </div>
      ) : null}
    </article>
  );
};

interface ThemeFocusBoardProps {
  data: ThemeFocusData | null;
  onGoStock: GoStock;
  limit?: number;
  title?: string;
  selectedThemeId?: string;
  onSelectTheme?: (themeId: string) => void;
  showHeadline?: boolean;
}

/**
 * "Which themes can I focus on": news heat joined with official 5-day
 * institutional flows across each theme's member stocks. Renders nothing when
 * theme-focus.json is absent, so it is safe on every page.
 */
export const ThemeFocusBoard: React.FC<ThemeFocusBoardProps> = ({
  data,
  onGoStock,
  limit = 5,
  title = '今日可關注題材',
  selectedThemeId,
  onSelectTheme,
  showHeadline = false
}) => {
  const themes = rankedFocusThemes(data).slice(0, limit);
  if (!data || themes.length === 0) return null;
  return (
    <section className="focus-board" aria-label={title}>
      <div className="focus-board-head">
        <div>
          <span className="page-kicker">FOCUS · 題材 × 法人資金</span>
          <h2>{title}</h2>
        </div>
        <span className="section-note">法人 {data.flow_window_days} 日 · 資料日 {shortDate(data.flow_as_of)} · 單位：張</span>
      </div>
      <div className="focus-grid">
        {themes.map((theme) => (
          <ThemeFocusCard
            key={theme.theme_id}
            theme={theme}
            onGoStock={onGoStock}
            selected={selectedThemeId === theme.theme_id}
            onSelect={onSelectTheme}
            showHeadline={showHeadline}
          />
        ))}
      </div>
      <p className="focus-method">關注分 = 0.5 × 新聞熱度 + 0.5 × 法人買超家數占比。只描述新聞與籌碼是否同向，不代表預測漲跌。</p>
    </section>
  );
};
