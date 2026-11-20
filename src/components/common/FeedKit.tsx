// Page scaffolding shared by every page that follows the 訊息流 (feed) layout:
// sticky top tabs, a one-line hero, two columns (main + rail) and the
// diverging-bar data box. Styles live in ./feed.css.
import React from 'react';
import './feed.css';
import './feed-pages.css';

export interface PageTab {
  id: string;
  label: string;
  active?: boolean;
  onClick: () => void;
}

export const PageTabs: React.FC<{ tabs: PageTab[]; label: string }> = ({ tabs, label }) => (
  <nav className="fd-tabs" aria-label={label}>
    {tabs.map((tab) => (
      <button key={tab.id} type="button" className={tab.active ? 'is-active' : ''} aria-pressed={tab.active ?? false}
        onClick={tab.onClick}>{tab.label}</button>
    ))}
  </nav>
);

export const PageHero: React.FC<{ title: string; sentence?: React.ReactNode; meta?: React.ReactNode }> = ({ title, sentence, meta }) => (
  <header className="fd-hero">
    <h1>{title}</h1>
    {sentence ? <p>{sentence}</p> : null}
    {meta ? <span className="fd-faint fd-num">{meta}</span> : null}
  </header>
);

export interface DivergingBar {
  name: string;
  value: number;
  label: string;
}

/** Data box of bars around a zero axis (red right = buy / up, green left = sell / down). */
export const DivergingBars: React.FC<{ title: string; note?: string; bars: DivergingBar[]; onPick?: (name: string) => void }> =
  ({ title, note, bars, onPick }) => {
    const max = Math.max(1, ...bars.map((bar) => Math.abs(bar.value)));
    return (
      <div className="fd-box fd-bars">
        <div className="fd-box-head"><span>{title}</span>{note ? <span className="fd-num">{note}</span> : null}</div>
        {bars.map((bar) => {
          const width = (Math.abs(bar.value) / max) * 50;
          const row = (
            <>
              <span className="fd-bar-name">{bar.name}</span>
              <span className="fd-bar-track">
                <span className={`fd-bar-fill${bar.value >= 0 ? ' is-up' : ' is-down'}`}
                  style={{ width: `${Math.max(1.5, width)}%`, [bar.value >= 0 ? 'left' : 'right']: '50%' }} />
              </span>
              <span className={`fd-num${bar.value > 0 ? ' is-up' : bar.value < 0 ? ' is-down' : ''}`}>{bar.label}</span>
            </>
          );
          return onPick
            ? <button type="button" className="fd-bar-row is-button" key={bar.name} onClick={() => onPick(bar.name)}>{row}</button>
            : <div className="fd-bar-row" key={bar.name}>{row}</div>;
        })}
      </div>
    );
  };

export function scrollToRef(ref: React.RefObject<HTMLElement>) {
  ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
