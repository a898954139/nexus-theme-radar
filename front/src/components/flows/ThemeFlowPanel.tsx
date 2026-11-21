import React from 'react';
import { ThemeFocusData } from '../../types';
import { directionClass, formatLots, rankedFocusThemes, shortDate, stanceTone } from '../common/ThemeFocusBoard';
import '../common/focus.css';

interface ThemeFlowPanelProps {
  focus: ThemeFocusData | null;
  selectedThemeId: string;
  onSelectTheme: (themeId: string) => void;
}

/**
 * Institutional money by radar theme: the flows page's answer to "which theme
 * is the money going into". Summed over each theme's member stocks from the
 * official per-symbol series. Hidden when theme-focus.json is unavailable.
 */
export const ThemeFlowPanel: React.FC<ThemeFlowPanelProps> = ({ focus, selectedThemeId, onSelectTheme }) => {
  const themes = rankedFocusThemes(focus);
  if (!focus || themes.length === 0) return null;
  return (
    <section className="theme-flow-panel" aria-label="題材資金流向">
      <div className="focus-board-head">
        <div>
          <span className="page-kicker">THEME FLOWS · 題材資金</span>
          <h2>法人資金流向哪些題材？</h2>
        </div>
        <span className="section-note">法人 {focus.flow_window_days} 日合計 · 資料日 {shortDate(focus.flow_as_of)} · 單位：張 · 點題材篩選下方排行</span>
      </div>
      <div className="theme-flow-table" role="table">
        <div className="theme-flow-row is-head" role="row">
          <span>題材</span><span>判讀</span><span>買超家數</span><span>外資</span><span>投信</span><span>合計</span><span>今日</span>
        </div>
        {themes.map((theme) => {
          const selected = selectedThemeId === theme.theme_id;
          const breadth = theme.flow.breadth === null ? null : Math.round(theme.flow.breadth * 100);
          return (
            <button
              type="button"
              role="row"
              className={`theme-flow-row ${stanceTone[theme.stance]} ${selected ? 'is-selected' : ''}`}
              key={theme.theme_id}
              aria-pressed={selected}
              onClick={() => onSelectTheme(selected ? '' : theme.theme_id)}
            >
              <strong>{theme.name_zh}</strong>
              <span className="theme-flow-stance">{theme.stance_label}</span>
              <span className="theme-flow-breadth mono-num">
                <i aria-hidden="true"><b style={{ width: `${breadth ?? 0}%` }} /></i>
                {theme.flow.positive_count}/{theme.flow.covered_count}
              </span>
              <span className={`mono-num ${directionClass(theme.flow.foreign_5d)}`}>{formatLots(theme.flow.foreign_5d)}</span>
              <span className={`mono-num ${directionClass(theme.flow.trust_5d)}`}>{formatLots(theme.flow.trust_5d)}</span>
              <span className={`mono-num ${directionClass(theme.flow.total_5d)}`}>{formatLots(theme.flow.total_5d)}</span>
              <span className={`mono-num ${directionClass(theme.flow.total_1d)}`}>{formatLots(theme.flow.total_1d)}</span>
            </button>
          );
        })}
      </div>
      <p className="focus-method">「買超家數」= 近 {focus.flow_window_days} 日法人合計買超的成分股數。合計張數容易被單一權值股主導，判讀以買超家數為主。</p>
    </section>
  );
};
