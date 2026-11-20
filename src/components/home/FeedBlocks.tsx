import React, { useState } from 'react';
import type { MacroFocus, ThemeFocus } from '../../lib/focusThemes';
import { eventDirection, FeedAnalysis, relativeTime, RiskAppetite, sparkPoints } from '../../lib/feed';
import type { CalendarData, CryptoQuote, UsQuote } from '../../services/marketExtras';
import type { FocusEvent, PreMarketData, SectorChange, ThemeFocusData, ThemeFocusTheme, WatchlistStock } from '../../types';

type GoStock = (code: string, exchange?: string) => void;

export const SectionHead: React.FC<{ title: string; note?: React.ReactNode; action?: string; onAction?: () => void; level?: 2 | 3 }> =
  ({ title, note, action, onAction, level = 2 }) => (
    <div className={`fd-head${level === 3 ? ' is-small' : ''}`}>
      {level === 2 ? <h2>{title}</h2> : <h3>{title}</h3>}
      {note ? <span className="fd-head-note">{note}</span> : null}
      {action && onAction ? <button type="button" className="fd-head-link" onClick={onAction}>{action} →</button> : null}
    </div>
  );

const LEAN_LABEL = { bull: '偏多', bear: '偏空', mixed: '多空交錯', none: '中性' } as const;

export const LeanTag: React.FC<{ lean: keyof typeof LEAN_LABEL }> = ({ lean }) => (
  <span className={`fd-lean is-${lean}`}>{LEAN_LABEL[lean]}</span>
);

function signed(value: number, digits = 2): string {
  return `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toFixed(digits)}`;
}

function tone(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return '';
  return value > 0 ? ' is-up' : ' is-down';
}

function lotsK(shares: number): string {
  const lots = shares / 1000;
  const k = lots / 1000;
  return `${lots > 0 ? '+' : lots < 0 ? '−' : ''}${Math.abs(k) >= 100 ? Math.abs(k).toFixed(0) : Math.abs(k).toFixed(1)}k`;
}

function themeLotsK(lots: number): string {
  const k = lots / 1000;
  return `${k > 0 ? '+' : k < 0 ? '−' : ''}${Math.abs(k) >= 100 ? Math.abs(k).toFixed(0) : Math.abs(k).toFixed(1)}k`;
}

/* ---------------- lead event ---------------- */

export const LeadEvent: React.FC<{ path: MacroFocus; now: number }> = ({ path, now }) => {
  const lead = path.lead;
  const bt = path.backtest;
  const rows = path.calls.length > 0
    ? path.calls.map((call) => ({ sector: call.sector, direction: call.direction as -1 | 0 | 1 }))
    : path.sectors.slice(0, 5).map((sector) => ({ sector, direction: 0 as const }));
  return (
    <article className="fd-lead">
      <div className="fd-kicker">
        <LeanTag lean={path.lean} />
        <span>{path.label}，{path.horizon === 'long' ? '長線' : '短線'}，{path.total} 則報導整理</span>
      </div>
      <h2 className="fd-lead-title"><a href={lead.url || '#'} target="_blank" rel="noreferrer">{lead.titleZh}</a></h2>
      <p className="fd-desc">傳導路徑：{lead.channel}。近 {path.total} 則中利多 {path.bull}、利空 {path.bear}，其餘尚無明確方向。</p>
      {rows.length > 0 ? (
        <div className="fd-box fd-impact">
          <div className="fd-impact-row is-head"><span>受影響的台股族群</span><span>方向</span><span>隔日命中</span></div>
          {rows.map((row) => {
            const hit = bt && bt.target === row.sector && bt.hitRate !== null ? `${Math.round(bt.hitRate * 100)}%` : '—';
            return (
              <div className="fd-impact-row" key={row.sector}>
                <span className="fd-impact-name">{row.sector}</span>
                <span className={`fd-dir${row.direction === 1 ? ' is-up' : row.direction === -1 ? ' is-down' : ''}`}>
                  {row.direction === 1 ? '▲ 偏多' : row.direction === -1 ? '▼ 偏空' : '未判斷'}
                </span>
                <span className="fd-num">{hit}</span>
              </div>
            );
          })}
        </div>
      ) : null}
      <p className="fd-meta">
        {lead.speaker}，{relativeTime(lead.publishedAt, now)}
        {bt ? `，${bt.target}樣本 ${bt.n} 次` : ''}
      </p>
    </article>
  );
};

/* ---------------- event list ---------------- */

export const PathList: React.FC<{ paths: MacroFocus[]; now: number }> = ({ paths, now }) => (
  <ol className="fd-paths">
    {paths.map((path) => (
      <li className="fd-path" key={path.key}>
        <div className="fd-kicker">
          <LeanTag lean={path.lean} />
          <span>{path.label}</span>
          <span className="fd-time">{relativeTime(path.latestAt, now)}</span>
        </div>
        <a className="fd-path-title" href={path.lead.url || '#'} target="_blank" rel="noreferrer">{path.lead.titleZh}</a>
        <p className="fd-desc is-clamp">近 {path.total} 則，利多 {path.bull}、利空 {path.bear}。{path.lead.channel}</p>
        {path.calls.length > 0 ? (
          <div className="fd-calls">
            {path.calls.slice(0, 4).map((call) => (
              <span key={call.sector} className={call.direction === 1 ? 'is-up' : 'is-down'}>{call.direction === 1 ? '▲' : '▼'} {call.sector}</span>
            ))}
          </div>
        ) : null}
      </li>
    ))}
  </ol>
);

export const AllEvents: React.FC<{ events: FocusEvent[]; now: number }> = ({ events, now }) => (
  <ul className="fd-events">
    {events.map((event) => {
      const dir = eventDirection(event);
      return (
        <li key={event.id}>
          <span className={`fd-event-dir${dir === 1 ? ' is-up' : dir === -1 ? ' is-down' : ''}`}>{dir === 1 ? '利多' : dir === -1 ? '利空' : '中性'}</span>
          <a href={event.url || '#'} target="_blank" rel="noreferrer">{event.titleZh}</a>
          <span className="fd-time">{event.pathLabel}，{relativeTime(event.publishedAt, now)}</span>
        </li>
      );
    })}
  </ul>
);

/* ---------------- analysis ---------------- */

export const AnalysisSection: React.FC<{ analysis: FeedAnalysis }> = ({ analysis }) => {
  const { lead, items } = analysis;
  return (
    <div className="fd-analysis">
      <article className="fd-analysis-lead">
        {lead.bars.length > 0 ? (
          <div className="fd-box fd-bars">
            <div className="fd-box-head">
              <span>外資 {lead.windowDays} 日買賣超，依題材（張）</span>
              {lead.asOf ? <span className="fd-num">截至 {lead.asOf}</span> : null}
            </div>
            {lead.bars.map((bar) => (
              <div className="fd-bar-row" key={bar.name}>
                <span className="fd-bar-name">{bar.name}</span>
                <span className="fd-bar-track">
                  <span className={`fd-bar-fill${bar.value >= 0 ? ' is-up' : ' is-down'}`} style={{ width: `${Math.max(1.5, bar.width / 2)}%`, [bar.value >= 0 ? 'left' : 'right']: '50%' }} />
                </span>
                <span className={`fd-num${tone(bar.value)}`}>{themeLotsK(bar.value)}</span>
              </div>
            ))}
          </div>
        ) : null}
        <p className="fd-meta">{lead.meta}</p>
        <h3 className="fd-analysis-title">{lead.title}</h3>
        <p className="fd-desc">{lead.body}</p>
      </article>
      <ol className="fd-analysis-list">
        {items.map((item) => (
          <li key={item.id}>
            <p className="fd-meta">{item.meta}</p>
            <h3 className="fd-analysis-item-title">{item.title}</h3>
            <p className="fd-desc is-clamp">{item.body}</p>
          </li>
        ))}
      </ol>
    </div>
  );
};

/* ---------------- themes ---------------- */

export const ThemeTable: React.FC<{ themes: ThemeFocus[]; focus: ThemeFocusData | null; onGoStock: GoStock }> = ({ themes, focus, onGoStock }) => {
  const byId = new Map<string, ThemeFocusTheme>((focus?.themes ?? []).map((theme) => [theme.theme_id, theme]));
  return (
    <div className="fd-table fd-themes" role="table" aria-label="系統判斷的族群">
      <div className="fd-tr is-head" role="row">
        <span>#</span><span>題材</span><span>新聞熱度</span><span>判讀</span><span className="is-right">法人 5 日</span><span>買超廣度</span><span>標的</span>
      </div>
      {themes.map((theme, index) => {
        const joined = byId.get(theme.themeId);
        const breadth = joined?.flow.breadth ?? null;
        return (
          <div className="fd-tr" role="row" key={theme.themeId}>
            <span className="fd-rank">{index + 1}</span>
            <span className="fd-theme-name">
              <strong>{theme.name}</strong>
              {theme.news ? <small>{theme.news.title_zh}</small> : null}
            </span>
            <span className="fd-meter"><span className="fd-meter-track"><span style={{ width: `${Math.min(100, theme.heat)}%` }} /></span><span className="fd-num">{Math.round(theme.heat)}</span></span>
            <span>{joined ? <span className={`fd-stance is-${joined.stance}`}>{joined.stance_label}</span> : <span className="fd-faint">—</span>}</span>
            <span className={`fd-num is-right${tone(joined?.flow.total_5d)}`}>{joined ? themeLotsK(joined.flow.total_5d) : '—'}</span>
            <span className="fd-meter">{breadth !== null ? <><span className="fd-meter-track"><span style={{ width: `${Math.round(breadth * 100)}%` }} /></span><span className="fd-num">{Math.round(breadth * 100)}%</span></> : <span className="fd-faint">—</span>}</span>
            <span className="fd-picks">
              {theme.shortPick ? <button type="button" onClick={() => onGoStock(theme.shortPick!.symbol, theme.shortPick!.exchange)}><em>短</em><span className="fd-num">{theme.shortPick.symbol}</span> {theme.shortPick.name}</button> : null}
              {theme.longPick ? <button type="button" onClick={() => onGoStock(theme.longPick!.symbol, theme.longPick!.exchange)}><em>長</em><span className="fd-num">{theme.longPick.symbol}</span> {theme.longPick.name}</button> : null}
              {!theme.shortPick && !theme.longPick && theme.stocks[0] ? <button type="button" onClick={() => onGoStock(theme.stocks[0].symbol, theme.stocks[0].exchange)}><em>相關</em><span className="fd-num">{theme.stocks[0].symbol}</span> {theme.stocks[0].name}</button> : null}
            </span>
          </div>
        );
      })}
    </div>
  );
};

function pct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${signed(value, digits)}%`;
}

export const PickTable: React.FC<{ kind: 'short' | 'long'; items: WatchlistStock[]; onGoStock: GoStock }> = ({ kind, items, onGoStock }) => (
  <div className={`fd-table fd-picks-table is-${kind}`} role="table" aria-label={kind === 'short' ? '短線' : '長線'}>
    <div className="fd-tr is-head" role="row">
      <span>標的</span>
      {kind === 'short' ? <><span className="is-right">法人 5 日</span><span className="is-right">當沖比</span></> : <><span className="is-right">營收年增</span><span className="is-right">EPS 年增</span></>}
      <span className="is-right">分數</span>
    </div>
    {items.map((item) => {
      const theme = item.themes[0]?.name_zh;
      const net = item.institutional.five_day_net;
      const ratio = item.trading_activity.day_trading_volume_ratio;
      return (
        <button type="button" className="fd-tr" role="row" key={`${kind}-${item.instrument.symbol}`} onClick={() => onGoStock(item.instrument.symbol, item.instrument.exchange)}>
          <span className="fd-stock"><span className="fd-num fd-faint">{item.instrument.symbol}</span><strong>{item.instrument.name_zh}</strong>{theme ? <small>{theme}</small> : null}</span>
          {kind === 'short' ? (
            <>
              <span className={`fd-num is-right${tone(net)}`}>{net === null || net === undefined ? '—' : lotsK(net)}</span>
              <span className="fd-num is-right">{ratio === null || ratio === undefined ? '—' : `${Math.round(ratio * 100)}%`}</span>
            </>
          ) : (
            <>
              <span className={`fd-num is-right${tone(item.fundamentals.revenue_growth)}`}>{pct(item.fundamentals.revenue_growth)}</span>
              <span className={`fd-num is-right${tone(item.fundamentals.eps_growth)}`}>{pct(item.fundamentals.eps_growth)}</span>
            </>
          )}
          <strong className="fd-num is-right">{(kind === 'short' ? item.short.score : item.long.score) ?? '—'}</strong>
        </button>
      );
    })}
  </div>
);

/* ---------------- sectors ---------------- */

export const SectorHeat: React.FC<{ sectors: SectorChange[] }> = ({ sectors }) => {
  const max = Math.max(0.5, ...sectors.map((sector) => Math.abs(sector.chg)));
  const sorted = sectors.slice().sort((a, b) => b.chg - a.chg);
  return (
    <div className="fd-heat">
      {sorted.map((sector) => {
        const strength = Math.round(18 + (Math.abs(sector.chg) / max) * 62);
        const color = sector.chg >= 0 ? 'var(--up)' : 'var(--down)';
        return (
          <div className="fd-heat-cell" key={sector.name}
            style={{ background: `color-mix(in srgb, ${color} ${strength}%, var(--fd-sf))` }}>
            <span>{sector.name}</span>
            <span className="fd-num">{signed(sector.chg)}%</span>
          </div>
        );
      })}
    </div>
  );
};

/* ---------------- right rail ---------------- */

export const RiskBlock: React.FC<{ risk: RiskAppetite; marketLean: string | null }> = ({ risk, marketLean }) => {
  const total = Math.max(1, risk.bull + risk.bear);
  return (
    <div className="fd-risk">
      <div className="fd-risk-score">
        <strong className="fd-num">{risk.score}</strong><span className="fd-faint">/ 10</span>
        <span className="fd-risk-label">{risk.label}</span>
      </div>
      <div className="fd-risk-bar" aria-hidden="true">
        <span className="is-up" style={{ width: `${(risk.bull / total) * 100}%` }} />
        <span className="is-down" style={{ width: `${(risk.bear / total) * 100}%` }} />
      </div>
      <p className="fd-risk-legend">
        <span>利多 <b className="is-up">{risk.bull}</b></span>
        <span>利空 <b className="is-down">{risk.bear}</b></span>
        <span>中性 {risk.neutral}</span>
        {marketLean ? <span>盤勢 {marketLean}</span> : null}
      </p>
    </div>
  );
};

export interface MiniQuote {
  id: string;
  label: string;
  value: string;
  change: number | null;
  changeText?: string;
  series: number[];
  note?: string;
  missing?: boolean;
}

function fmt(value: number, digits = 2): string {
  return value.toLocaleString('zh-TW', { maximumFractionDigits: digits, minimumFractionDigits: value >= 1000 ? 0 : Math.min(digits, 2) });
}

export function leadQuotes(pre: PreMarketData | null, us: UsQuote[]): MiniQuote[] {
  const byUs = new Map(us.map((quote) => [quote.id, quote]));
  const indicators = new Map((pre?.market?.indicators ?? []).map((item) => [item.id, item]));
  const night = indicators.get('tx_night');
  const cards: MiniQuote[] = [];
  cards.push(night && !night.missing && night.value !== undefined
    ? { id: 'tx_night', label: '台指夜盤', value: fmt(night.value, 0), change: night.change_pct ?? null, series: [], note: night.session }
    : { id: 'tx_night', label: '台指夜盤', value: '—', change: null, series: [], missing: true });
  for (const id of ['sox', 'nasdaq', 'spx', 'tsm_adr', 'nvda']) {
    const quote = byUs.get(id);
    const indicator = indicators.get(id);
    if (quote) cards.push({ id, label: quote.label, value: fmt(quote.value), change: quote.change_pct, series: quote.series });
    else if (indicator && !indicator.missing && indicator.value !== undefined) cards.push({ id, label: indicator.label, value: fmt(indicator.value), change: indicator.change_pct ?? null, series: [] });
    else cards.push({ id, label: { sox: '費半', nasdaq: 'Nasdaq', spx: 'S&P 500', tsm_adr: 'TSM ADR', nvda: 'NVDA' }[id] ?? id, value: '—', change: null, series: [], missing: true });
  }
  return cards;
}

export function overviewQuotes(pre: PreMarketData | null, us: UsQuote[], crypto: CryptoQuote[]): MiniQuote[] {
  const indicators = new Map((pre?.market?.indicators ?? []).map((item) => [item.id, item]));
  const cards: MiniQuote[] = [];
  const taiex = indicators.get('taiex');
  if (taiex && !taiex.missing && taiex.value !== undefined) cards.push({ id: 'taiex', label: '加權', value: fmt(taiex.value), change: taiex.change_pct ?? null, series: [] });
  const foreign = indicators.get('foreign_net');
  if (foreign && !foreign.missing && foreign.value !== undefined) {
    cards.push({ id: 'foreign_net', label: '外資', value: `${signed(foreign.value, 1)} 億`, change: foreign.value, changeText: foreign.as_of ?? '', series: [] });
  }
  const twd = us.find((quote) => quote.id === 'usdtwd');
  if (twd) cards.push({ id: 'usdtwd', label: '美元/台幣', value: fmt(twd.value, 3), change: twd.change_pct, series: twd.series });
  for (const quote of crypto) {
    cards.push({ id: quote.id, label: quote.symbol === 'PAXGUSDT' ? 'XAU（PAXG）' : quote.label, value: fmt(quote.value, quote.value >= 1000 ? 0 : 2), change: quote.changePct, series: quote.series });
  }
  if (!crypto.some((quote) => quote.id === 'xau')) {
    const gold = us.find((quote) => quote.id === 'gold');
    if (gold) cards.push({ id: 'gold', label: gold.label, value: fmt(gold.value, 1), change: gold.change_pct, series: gold.series });
  }
  return cards;
}

export const MiniCards: React.FC<{ quotes: MiniQuote[] }> = ({ quotes }) => (
  <div className="fd-mini-grid">
    {quotes.map((quote) => {
      const points = sparkPoints(quote.series);
      return (
        <div className={`fd-box fd-mini${quote.missing ? ' is-missing' : ''}`} key={quote.id}>
          <div className="fd-mini-head">
            <span>{quote.label}</span>
            <span className={`fd-num${tone(quote.change)}`}>
              {quote.changeText ?? (quote.change === null ? '' : `${signed(quote.change)}%`)}
            </span>
          </div>
          <strong className="fd-num">{quote.value}</strong>
          {points ? (
            <svg className={`fd-mini-spark${tone(quote.change)}`} viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true" focusable="false">
              <polyline points={points} fill="none" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
            </svg>
          ) : <span className="fd-mini-spark is-empty" aria-hidden="true" />}
        </div>
      );
    })}
  </div>
);

const IMPACT_LABEL = { high: '影響 高', medium: '影響 中', low: '影響 低', holiday: '休市' } as const;

export const CalendarList: React.FC<{ data: CalendarData; limit: number }> = ({ data, limit }) => {
  const [showAll, setShowAll] = useState(false);
  const upcoming = data.items.filter((item) => item.day >= data.today && item.impact !== 'holiday');
  const today = upcoming.filter((item) => item.day === data.today && item.impact !== 'low');
  const base = today.length > 0 ? today : upcoming.filter((item) => item.impact !== 'low');
  const shown = showAll ? upcoming : base.slice(0, limit);
  if (shown.length === 0) return <p className="fd-faint fd-empty">本週已無待公布的經濟數據</p>;
  return (
    <>
      <div className="fd-cal">
        {shown.map((item) => (
          <div className="fd-box fd-cal-card" key={`${item.at}-${item.title}`}>
            <div className="fd-cal-head">
              <span className="fd-num">{item.day === data.today ? item.time : `${item.day.slice(5).replace('-', '/')} ${item.time}`}</span>
              <span className="fd-faint">{item.region}</span>
              <span className={`fd-cal-impact is-${item.impact}`}>{IMPACT_LABEL[item.impact]}</span>
            </div>
            <strong className="fd-cal-title">{item.title}</strong>
            <div className="fd-cal-vals">
              <span><small>實際</small><b className="fd-num">{item.actual ?? '—'}</b></span>
              <span><small>預測</small><b className="fd-num">{item.forecast ?? '—'}</b></span>
              <span><small>前值</small><b className="fd-num">{item.previous ?? '—'}</b></span>
            </div>
          </div>
        ))}
      </div>
      {upcoming.length > shown.length || showAll ? (
        <button type="button" className="fd-more" onClick={() => setShowAll((value) => !value)}>
          {showAll ? '只看重要數據' : `本週全部 ${upcoming.length} 項`}
        </button>
      ) : null}
    </>
  );
};
