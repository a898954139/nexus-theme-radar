import React from 'react';
import { InstitutionalFlowItem, StockWatchlistData, ThemeFocusData } from '../../types';
import { directionClass, formatLots, stanceTone } from '../common/ThemeFocusBoard';
import '../common/focus.css';

export interface StockThemeRef {
  theme_id: string;
  name_zh: string;
  relation: 'direct' | 'related';
}

interface StockFocusStripProps {
  code: string;
  themes: StockThemeRef[];
  focus: ThemeFocusData | null;
  watchlist: StockWatchlistData | null;
  flows: InstitutionalFlowItem[];
  onGoTheme: () => void;
}

function flowSummary(flows: InstitutionalFlowItem[]) {
  const rows = flows.slice().sort((left, right) => right.date.localeCompare(left.date));
  if (!rows.length) return null;
  const window = rows.slice(0, 5);
  let streak = 0;
  for (const row of rows) {
    if (row.total_net > 0 && streak >= 0) streak += 1;
    else if (row.total_net < 0 && streak <= 0) streak -= 1;
    else break;
  }
  // institutional-flows.json is in shares; show lots like every other flows view.
  const lots = (value: number) => Math.round(value / 1000);
  return {
    asOf: rows[0].date,
    foreign: lots(window.reduce((sum, row) => sum + row.foreign_net, 0)),
    trust: lots(window.reduce((sum, row) => sum + row.trust_net, 0)),
    total: lots(window.reduce((sum, row) => sum + row.total_net, 0)),
    streak
  };
}

/**
 * Why this stock is on the radar, above the tabs: its themes with their focus
 * stance, its watch ranks, and five days of institutional flow. Each part
 * hides when its data is missing; the strip hides when all of them are.
 */
export const StockFocusStrip: React.FC<StockFocusStripProps> = ({ code, themes, focus, watchlist, flows, onGoTheme }) => {
  const short = watchlist?.short.items.find((item) => item.instrument.symbol === code);
  const long = watchlist?.long.items.find((item) => item.instrument.symbol === code);
  const flow = flowSummary(flows);
  const focusById = new Map((focus?.themes ?? []).map((theme) => [theme.theme_id, theme]));
  if (!themes.length && !short && !flow) return null;
  return (
    <section className="stock-focus-strip" aria-label="關注理由">
      {themes.length ? (
        <div className="stock-focus-block">
          <span className="focus-stocks-label">所屬題材</span>
          <div className="stock-focus-themes">
            {themes.slice(0, 4).map((theme) => {
              const stance = focusById.get(theme.theme_id);
              return (
                <button type="button" key={theme.theme_id} className={`stock-focus-theme ${stance ? stanceTone[stance.stance] : 'is-watch'}`} onClick={onGoTheme} title={stance ? `${stance.stance_label} · 關注分 ${stance.focus_score}` : undefined}>
                  <b>{theme.name_zh}</b>
                  {theme.relation === 'direct' ? <i>新聞點名</i> : null}
                  {stance ? <em>{stance.stance_label}</em> : null}
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
      {short || long ? (
        <div className="stock-focus-block">
          <span className="focus-stocks-label">個股雷達</span>
          <div className="stock-focus-kpis">
            {short ? <span>短線 <b className="mono-num">#{short.short.rank}</b><small className="mono-num">{Math.round(short.short.score)} 分</small></span> : null}
            {long ? <span>長線 <b className="mono-num">#{long.long.rank}</b><small className="mono-num">{Math.round(long.long.score)} 分</small></span> : null}
          </div>
        </div>
      ) : null}
      {flow ? (
        <div className="stock-focus-block">
          <span className="focus-stocks-label">法人 5 日 · 資料日 {flow.asOf.slice(5).replace('-', '/')}（張）</span>
          <div className="stock-focus-kpis">
            <span>外資 <b className={`mono-num ${directionClass(flow.foreign)}`}>{formatLots(flow.foreign)}</b></span>
            <span>投信 <b className={`mono-num ${directionClass(flow.trust)}`}>{formatLots(flow.trust)}</b></span>
            <span>合計 <b className={`mono-num ${directionClass(flow.total)}`}>{formatLots(flow.total)}</b></span>
            {flow.streak !== 0 ? <span className={directionClass(flow.streak)}>連{flow.streak > 0 ? '買' : '賣'} {Math.abs(flow.streak)} 日</span> : null}
          </div>
        </div>
      ) : null}
    </section>
  );
};
