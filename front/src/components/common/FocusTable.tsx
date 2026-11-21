// 題材 × 法人資金 as an open, rule-divided table (feed layout). Same data as
// the old ThemeFocusBoard cards; every number is from theme-focus.
import React from 'react';
import { ThemeFocusData, ThemeFocusStock } from '../../types';
import { formatLots, GoStock, rankedFocusThemes } from './ThemeFocusBoard';

function tone(value: number): string {
  return value > 0 ? ' is-up' : value < 0 ? ' is-down' : '';
}

const StockLink: React.FC<{ stock: ThemeFocusStock; onGoStock: GoStock; mark: string }> = ({ stock, onGoStock, mark }) => (
  <button type="button" onClick={() => onGoStock(stock.symbol, stock.exchange, 'flows')}>
    <em>{mark}</em><span className="fd-num">{stock.symbol}</span> {stock.name_zh}
    <span className={`fd-num${tone(stock.flow?.total_5d ?? 0)}`}> {formatLots(stock.flow?.total_5d ?? 0)}</span>
  </button>
);

interface FocusTableProps {
  data: ThemeFocusData | null;
  onGoStock: GoStock;
  limit?: number;
  selectedThemeId?: string;
  onSelectTheme?: (themeId: string) => void;
}

export const FocusTable: React.FC<FocusTableProps> = ({ data, onGoStock, limit = 8, selectedThemeId, onSelectTheme }) => {
  const themes = rankedFocusThemes(data).slice(0, limit);
  if (!data || themes.length === 0) return <p className="fd-empty fd-faint">題材 × 法人資料暫時無法取得</p>;
  return (
    <div className="fd-table fd-focus" role="table" aria-label="題材與法人資金">
      <div className="fd-tr is-head" role="row">
        <span>#</span><span>題材</span><span className="is-right">關注分</span><span>判讀</span><span>買超家數</span>
        <span className="is-right">外資 {data.flow_window_days} 日</span><span className="is-right">投信 {data.flow_window_days} 日</span><span>法人買超領先／主要賣壓</span>
      </div>
      {themes.map((theme) => {
        const breadth = theme.flow.breadth === null ? null : Math.round(theme.flow.breadth * 100);
        const selected = selectedThemeId === theme.theme_id;
        return (
          <div className={`fd-tr${selected ? ' is-selected' : ''}`} role="row" key={theme.theme_id}>
            <span className="fd-rank">{theme.focus_rank}</span>
            <span className="fd-theme-name">
              {onSelectTheme
                ? <button type="button" className="fd-theme-pick" aria-pressed={selected} onClick={() => onSelectTheme(theme.theme_id)}><strong>{theme.name_zh}</strong></button>
                : <strong>{theme.name_zh}</strong>}
              {theme.headline?.title ? (
                theme.headline.url
                  ? <a href={theme.headline.url} target="_blank" rel="noreferrer"><small>{theme.headline.title}</small></a>
                  : <small>{theme.headline.title}</small>
              ) : <small>新聞熱度 {theme.heat_score}</small>}
            </span>
            <strong className="fd-num is-right fd-score" title="關注分 = 0.5 × 新聞熱度 + 0.5 × 法人買超家數占比">{theme.focus_score}</strong>
            <span><span className={`fd-stance is-${theme.stance}`}>{theme.stance_label}</span></span>
            <span className="fd-meter">
              <span className="fd-meter-track"><span style={{ width: `${breadth ?? 0}%` }} /></span>
              <span className="fd-num">{theme.flow.positive_count}/{theme.flow.covered_count}</span>
            </span>
            <span className={`fd-num is-right${tone(theme.flow.foreign_5d)}`}>{formatLots(theme.flow.foreign_5d)}</span>
            <span className={`fd-num is-right${tone(theme.flow.trust_5d)}`}>{formatLots(theme.flow.trust_5d)}</span>
            <span className="fd-picks">
              {theme.leaders.slice(0, 2).map((stock) => <StockLink key={`l-${stock.symbol}`} stock={stock} onGoStock={onGoStock} mark="買" />)}
              {theme.outflows[0] ? <StockLink stock={theme.outflows[0]} onGoStock={onGoStock} mark="賣" /> : null}
              {theme.leaders.length === 0 && !theme.outflows[0] ? <span className="fd-faint">—</span> : null}
            </span>
          </div>
        );
      })}
    </div>
  );
};
