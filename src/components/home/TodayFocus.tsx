import React, { useMemo, useState } from 'react';
import { buildMacroFocus, buildThemeFocus, Lean, MacroFocus, SectorCall, StockPick, ThemeFocus } from '../../lib/focusThemes';
import { DeviceType, FocusEvent, PreMarketData, RadarData, StockWatchlistData } from '../../types';
import './focus.css';

const THEME_LIMIT = { desktop: 5, mobile: 3 };
const MACRO_LIMIT = { desktop: 4, mobile: 3 };
const MACRO_EVENT_PREVIEW = 4;

const LEAN_LABEL: Record<Lean, string> = { bull: '偏多', bear: '偏空', mixed: '多空交錯', none: '方向未明' };
const STAGE_LABEL: Record<string, string> = { new: '新題材', accelerating: '加速中', expanding: '擴散', stable: '持平', cooling: '退燒' };

function relTime(iso: string, now: number): string {
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return '';
  const hours = Math.max(0, (now - at) / 3_600_000);
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} 分前`;
  if (hours < 24) return `${Math.round(hours)} 小時前`;
  return `${Math.round(hours / 24)} 天前`;
}

const LeanTag: React.FC<{ lean: Lean; prefix?: string }> = ({ lean, prefix }) => (
  <span className={`tf-lean is-${lean}`}>{prefix ?? ''}{LEAN_LABEL[lean]}</span>
);

const CallChips: React.FC<{ calls: SectorCall[]; limit: number }> = ({ calls, limit }) => (
  <>
    {calls.slice(0, limit).map((call) => (
      <span key={call.sector} className={`tf-call ${call.direction === 1 ? 'is-up' : 'is-down'}`}>
        {call.direction === 1 ? '▲' : '▼'} {call.sector}
      </span>
    ))}
  </>
);

const PickButton: React.FC<{ label: string; pick: StockPick; onGoStock: (code: string, exchange?: string) => void }> =
  ({ label, pick, onGoStock }) => (
    <button type="button" className="tf-pick" onClick={(event) => { event.stopPropagation(); onGoStock(pick.symbol, pick.exchange); }}
      title={pick.rank ? `${label}觀察清單第 ${pick.rank} 名` : undefined}>
      <span className="tf-pick-label">{label}</span>
      <span className="mono-num">{pick.symbol}</span> {pick.name}
      {pick.rank ? <span className="tf-pick-rank mono-num">#{pick.rank}</span> : null}
    </button>
  );

const ThemeRow: React.FC<{
  theme: ThemeFocus;
  index: number;
  open: boolean;
  onToggle: () => void;
  onGoStock: (code: string, exchange?: string) => void;
}> = ({ theme, index, open, onToggle, onGoStock }) => (
  <li className={`tf-row${open ? ' is-open' : ''}`}>
    <div className="tf-row-main" role="button" tabIndex={0} aria-expanded={open} onClick={onToggle}
      onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onToggle(); } }}>
      <span className={`tf-rank mono-num${index === 0 ? ' is-first' : ''}`}>{index + 1}</span>
      <div className="tf-body">
        <div className="tf-title-line">
          <strong className="tf-name">{theme.name}</strong>
          {theme.macroLean === 'bull' || theme.macroLean === 'bear' ? <LeanTag lean={theme.macroLean} prefix="國際面 " /> : null}
          {STAGE_LABEL[theme.stage] ? <span className="tf-tag">{STAGE_LABEL[theme.stage]}</span> : null}
          <span className="tf-heat" title="題材熱度（0–100）">
            <span className="tf-heat-bar"><span style={{ width: `${Math.min(100, theme.heat)}%` }} /></span>
            <span className="mono-num">{theme.heat}</span>
          </span>
        </div>
        <div className="tf-picks">
          {theme.shortPick ? <PickButton label="短線" pick={theme.shortPick} onGoStock={onGoStock} /> : null}
          {theme.longPick ? <PickButton label="長線" pick={theme.longPick} onGoStock={onGoStock} /> : null}
          {!theme.shortPick && !theme.longPick && theme.stocks[0] ? <PickButton label="相關" pick={theme.stocks[0]} onGoStock={onGoStock} /> : null}
        </div>
        {theme.news ? <p className="tf-why">{theme.news.title_zh}</p> : null}
      </div>
      <span className="tf-chevron" aria-hidden="true">{open ? '−' : '+'}</span>
    </div>
    {open ? (
      <div className="tf-detail">
        {theme.news?.summary ? (
          <p className="tf-detail-summary">{theme.news.summary.replace(/&#10;/g, ' ')}</p>
        ) : null}
        {theme.news ? (
          <a className="tf-detail-link" href={theme.news.canonical_url} target="_blank" rel="noreferrer">
            {theme.news.source} · 原文 ↗
          </a>
        ) : null}
        {theme.macroCalls.length > 0 ? (
          <div className="tf-detail-line"><span className="tf-detail-label">國際消息</span><CallChips calls={theme.macroCalls} limit={4} /></div>
        ) : null}
        {theme.stocks.length > 0 ? (
          <div className="tf-detail-line">
            <span className="tf-detail-label">其他相關</span>
            {theme.stocks.map((stock) => (
              <button type="button" className="tf-stock" key={stock.symbol} onClick={() => onGoStock(stock.symbol, stock.exchange)}>
                <span className="mono-num">{stock.symbol}</span> {stock.name}
              </button>
            ))}
          </div>
        ) : null}
        <div className="tf-detail-meta mono-num">
          {theme.eventCount !== null ? `${theme.eventCount} 則新聞` : ''}
          {theme.sourceCount !== null ? ` · ${theme.sourceCount} 個來源` : ''}
          {theme.momentum !== null ? ` · 動能 ${theme.momentum}` : ''}
        </div>
      </div>
    ) : null}
  </li>
);

const EventLine: React.FC<{ event: FocusEvent; now: number }> = ({ event, now }) => {
  const dir = event.direction === 1 || event.direction === -1 ? event.direction : 0;
  return (
    <li className="tf-event">
      <span className={`tf-event-dir is-${dir === 1 ? 'up' : dir === -1 ? 'down' : 'flat'}`}>
        {dir === 1 ? '利多' : dir === -1 ? '利空' : '中性'}
      </span>
      <a href={event.url || '#'} target="_blank" rel="noreferrer">{event.titleZh}</a>
      <span className="tf-event-time mono-num">{relTime(event.publishedAt, now)}</span>
    </li>
  );
};

const MacroRow: React.FC<{ path: MacroFocus; index: number; open: boolean; onToggle: () => void; now: number }> =
  ({ path, index, open, onToggle, now }) => {
    const [showAll, setShowAll] = useState(false);
    const directional = path.events.filter((event) => event.direction === 1 || event.direction === -1);
    const preview = showAll ? path.events : [...directional, ...path.events.filter((event) => !directional.includes(event))].slice(0, MACRO_EVENT_PREVIEW);
    const bt = path.backtest;
    return (
      <li className={`tf-row${open ? ' is-open' : ''}`}>
        <div className="tf-row-main" role="button" tabIndex={0} aria-expanded={open} onClick={onToggle}
          onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onToggle(); } }}>
          <span className={`tf-rank mono-num${index === 0 ? ' is-first' : ''}`}>{index + 1}</span>
          <div className="tf-body">
            <div className="tf-title-line">
              <strong className="tf-name">{path.label}</strong>
              <LeanTag lean={path.lean} />
              {path.horizon ? <span className="tf-tag">{path.horizon === 'long' ? '長線' : '短線'}</span> : null}
              {path.hasCritical ? <span className="tf-tag is-critical">重大</span> : null}
              {bt && bt.hitRate !== null ? (
                <span className="tf-hit mono-num" title={`回測 ${bt.window[0]}~${bt.window[1]}：${bt.target} T+1 超額報酬與事件方向同號的比例`}>
                  命中 {Math.round(bt.hitRate * 100)}%<small>（{bt.n}）</small>
                </span>
              ) : null}
            </div>
            <div className="tf-picks">
              {path.calls.length > 0
                ? <CallChips calls={path.calls} limit={4} />
                : path.sectors.slice(0, 4).map((sector) => <span className="tf-call" key={sector}>{sector}</span>)}
            </div>
            <p className="tf-why">{path.lead.titleZh}</p>
          </div>
          <span className="tf-chevron" aria-hidden="true">{open ? '−' : '+'}</span>
        </div>
        {open ? (
          <div className="tf-detail">
            <div className="tf-detail-line">
              <span className="tf-detail-label">傳導</span>
              <span className="tf-chain">{path.lead.channel}</span>
            </div>
            <div className="tf-detail-meta mono-num">
              {path.total} 則 · 利多 {path.bull} / 利空 {path.bear}
              {bt && bt.avgForeignT1 !== null ? ` · 歷史 T+1 外資 ${bt.target} 平均 ${bt.avgForeignT1 > 0 ? '+' : ''}${Math.round(bt.avgForeignT1).toLocaleString('zh-TW')} 張` : ''}
            </div>
            <ul className="tf-events">
              {preview.map((event) => <EventLine event={event} now={now} key={event.id} />)}
            </ul>
            {path.events.length > MACRO_EVENT_PREVIEW ? (
              <button type="button" className="tf-more" onClick={() => setShowAll((value) => !value)}>
                {showAll ? '收合' : `顯示全部 ${path.events.length} 則`}
              </button>
            ) : null}
          </div>
        ) : null}
      </li>
    );
  };

interface TodayFocusProps {
  preMarket: PreMarketData | null;
  radar: RadarData;
  watchlist: StockWatchlistData | null;
  device: DeviceType;
  onGoStock: (code: string, exchange?: string) => void;
  onGoMomentum: () => void;
}

/** The first screen of the site: which 題材 to watch today, ranked, one line of
 *  "why" each, and the stocks to open. Everything else is one click deeper. */
export const TodayFocus: React.FC<TodayFocusProps> = ({ preMarket, radar, watchlist, device, onGoStock, onGoMomentum }) => {
  const now = preMarket ? Date.parse(preMarket.generated_at) || Date.now() : Date.now();
  const macro = useMemo(() => (preMarket ? buildMacroFocus(preMarket, now) : []), [preMarket, now]);
  const themes = useMemo(() => buildThemeFocus(radar, watchlist, macro), [radar, watchlist, macro]);
  const [openTheme, setOpenTheme] = useState<string | null>(null);
  const [openMacro, setOpenMacro] = useState<string | null>(null);
  const shownThemes = themes.slice(0, THEME_LIMIT[device]);
  const shownMacro = macro.slice(0, MACRO_LIMIT[device]);

  return (
    <section className="tf" aria-label="今日關注">
      <div className="tf-col">
        <div className="tf-col-head">
          <h2>今日關注題材</h2>
          <span className="tf-col-note">依熱度排序 · 點個股看詳情</span>
          <button type="button" className="tf-col-link" onClick={onGoMomentum}>動能 →</button>
        </div>
        {shownThemes.length > 0 ? (
          <ol className="tf-list">
            {shownThemes.map((theme, index) => (
              <ThemeRow key={theme.themeId} theme={theme} index={index} onGoStock={onGoStock}
                open={openTheme === theme.themeId}
                onToggle={() => setOpenTheme((current) => (current === theme.themeId ? null : theme.themeId))} />
            ))}
          </ol>
        ) : <div className="tf-empty">目前沒有達門檻的題材</div>}
      </div>

      <div className="tf-col">
        <div className="tf-col-head">
          <h2>國際消息 → 台股族群</h2>
          <span className="tf-col-note">近 {preMarket?.window_hours ?? 72} 小時 · 越新權重越高</span>
        </div>
        {shownMacro.length > 0 ? (
          <ol className="tf-list">
            {shownMacro.map((path, index) => (
              <MacroRow key={path.key} path={path} index={index} now={now}
                open={openMacro === path.key}
                onToggle={() => setOpenMacro((current) => (current === path.key ? null : path.key))} />
            ))}
          </ol>
        ) : <div className="tf-empty">{preMarket ? '近期國際消息面平靜' : '盤前資料暫時無法取得'}</div>}
      </div>
    </section>
  );
};
