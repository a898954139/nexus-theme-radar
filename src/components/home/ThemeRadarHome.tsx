import React, { useEffect, useMemo, useRef, useState } from 'react';
import { buildMacroFocus, buildThemeFocus } from '../../lib/focusThemes';
import { FEED_TABS, FeedTab, feedAnalysis, feedHeadline, pathsForTab, relativeTime, riskAppetite } from '../../lib/feed';
import { CalendarData, CryptoQuote, fetchCalendar, fetchCryptoQuotes, fetchUsQuotes, UsQuote } from '../../services/marketExtras';
import { DeviceType, NewsItem, PreMarketData, RadarData, StockWatchlistData, ThemeFocusData } from '../../types';
import {
  AllEvents, AnalysisSection, CalendarList, LeadEvent, leadQuotes, MiniCards, overviewQuotes, PathList, PickTable,
  RiskBlock, SectionHead, SectorHeat, ThemeTable,
} from './FeedBlocks';
import '../common/feed.css';

interface ThemeRadarHomeProps {
  data: RadarData;
  preMarket: PreMarketData | null;
  watchlist: StockWatchlistData | null;
  focus: ThemeFocusData | null;
  device: DeviceType;
  onGoMomentum: () => void;
  onGoWatchlist: () => void;
  onGoStock: (code: string, exchange?: string, tab?: 'fundamentals' | 'flows') => void;
}

const NEWS_PAGE_SIZE = 20;
const EXTRAS_REFRESH_MS = 5 * 60 * 1000;

function toNewsItems(data: RadarData): NewsItem[] {
  const themeName = new Map(data.themeRanking.themes.map((theme) => [theme.theme_id, theme.name_zh]));
  return data.events
    .slice()
    .sort((a, b) => new Date(b.published_at).getTime() - new Date(a.published_at).getTime())
    .map((event) => ({
      id: event.id,
      title_zh: event.title_zh,
      source: event.source,
      published_at: event.published_at,
      url: event.url,
      theme_id: event.primary_theme_id,
      theme_name_zh: event.primary_theme_id ? themeName.get(event.primary_theme_id) : undefined,
      symbols: [...(event.direct_symbols ?? []), ...(event.related_symbols ?? [])]
    }));
}

function updatedLabel(iso: string | undefined): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const weekday = '日一二三四五六'[date.getDay()];
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日週${weekday} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')} 更新`;
}

/** Optional third-party extras for the rail, refreshed with the rest of the page. */
function useMarketExtras() {
  const [calendar, setCalendar] = useState<CalendarData | null>(null);
  const [crypto, setCrypto] = useState<CryptoQuote[]>([]);
  const [us, setUs] = useState<UsQuote[]>([]);
  useEffect(() => {
    let active = true;
    const load = () => {
      fetchCalendar().then((value) => { if (active && value) setCalendar(value); });
      fetchCryptoQuotes().then((value) => { if (active && value.length > 0) setCrypto(value); });
      fetchUsQuotes().then((value) => { if (active && value.length > 0) setUs(value); });
    };
    load();
    const timer = window.setInterval(load, EXTRAS_REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);
  return { calendar, crypto, us };
}

export const ThemeRadarHome: React.FC<ThemeRadarHomeProps> = ({ data, preMarket, watchlist, focus, device, onGoMomentum, onGoWatchlist, onGoStock }) => {
  const mobile = device === 'mobile';
  const news = useMemo(() => toNewsItems(data), [data]);
  const [visibleNewsCount, setVisibleNewsCount] = useState(NEWS_PAGE_SIZE);
  const newsFeedRef = useRef<HTMLDivElement>(null);
  const newsLoadMoreRef = useRef<HTMLButtonElement>(null);
  const visibleNews = news.slice(0, visibleNewsCount);
  const hasMoreNews = visibleNewsCount < news.length;
  const [tab, setTab] = useState<FeedTab>('hot');
  const [showAllEvents, setShowAllEvents] = useState(false);
  const extras = useMarketExtras();
  const analysisRef = useRef<HTMLElement>(null);

  const now = preMarket ? Date.parse(preMarket.generated_at) || Date.now() : Date.now();
  const macro = useMemo(() => (preMarket ? buildMacroFocus(preMarket, now) : []), [preMarket, now]);
  const themes = useMemo(() => buildThemeFocus(data, watchlist, macro), [data, watchlist, macro]);
  const risk = useMemo(() => riskAppetite(preMarket), [preMarket]);
  const headline = useMemo(() => feedHeadline(preMarket, macro), [preMarket, macro]);
  const analysis = useMemo(() => feedAnalysis(preMarket, focus, macro), [preMarket, focus, macro]);
  const tabPaths = useMemo(() => pathsForTab(macro, tab), [macro, tab]);
  const tabEvents = useMemo(() => {
    const keys = new Set(tabPaths.flatMap((path) => path.events.map((event) => event.id)));
    return (preMarket?.events ?? []).filter((event) => keys.has(event.id))
      .sort((a, b) => Date.parse(b.publishedAt) - Date.parse(a.publishedAt));
  }, [preMarket, tabPaths]);
  const [lead, ...restPaths] = tabPaths;
  const leads = useMemo(() => leadQuotes(preMarket, extras.us), [preMarket, extras.us]);
  const overview = useMemo(() => overviewQuotes(preMarket, extras.us, extras.crypto), [preMarket, extras.us, extras.crypto]);
  const leadsDown = leads.filter((quote) => quote.change !== null && quote.change < 0).length;
  const leadsUp = leads.filter((quote) => quote.change !== null && quote.change > 0).length;

  useEffect(() => {
    setVisibleNewsCount(NEWS_PAGE_SIZE);
  }, [news]);

  useEffect(() => {
    setShowAllEvents(false);
  }, [tab]);

  useEffect(() => {
    const root = newsFeedRef.current;
    const target = newsLoadMoreRef.current;
    if (!hasMoreNews || !root || !target || typeof IntersectionObserver === 'undefined') return;

    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      setVisibleNewsCount((count) => Math.min(count + NEWS_PAGE_SIZE, news.length));
    }, { root, rootMargin: '0px 0px 120px' });
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasMoreNews, news.length]);

  const tabs = (
    <nav className="fd-tabs" aria-label="消息分類">
      {FEED_TABS.map((item) => (
        <button key={item.id} type="button" className={tab === item.id ? 'is-active' : ''} aria-pressed={tab === item.id}
          onClick={() => setTab(item.id)}>{item.label}</button>
      ))}
      <button type="button" onClick={() => analysisRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>分析與觀點</button>
    </nav>
  );

  const header = (
    <header className="fd-hero">
      <h1>{headline.stance}</h1>
      <p>{headline.sentence}</p>
      <span className="fd-faint fd-num">{updatedLabel(preMarket?.generated_at ?? data.themeRanking.generated_at)}</span>
    </header>
  );

  const eventsBlock = (
    <section className="fd-section fd-intl" aria-label="國際局勢">
      {lead ? (
        <div className="fd-intl-grid">
          <LeadEvent path={lead} now={now} />
          {restPaths.length > 0 ? <PathList paths={restPaths.slice(0, mobile ? 4 : 5)} now={now} /> : null}
        </div>
      ) : (
        <p className="fd-empty fd-faint">{preMarket ? `近 ${preMarket.window_hours} 小時這個分類沒有消息` : '盤前資料暫時無法取得'}</p>
      )}
      {tabEvents.length > 0 ? (
        <>
          <button type="button" className="fd-more" aria-expanded={showAllEvents} onClick={() => setShowAllEvents((value) => !value)}>
            {showAllEvents ? '收合完整清單' : `完整清單 ${tabEvents.length} 則（含中性）`}
          </button>
          {showAllEvents ? <AllEvents events={tabEvents} now={now} /> : null}
        </>
      ) : null}
    </section>
  );

  const analysisBlock = analysis ? (
    <section className="fd-section" ref={analysisRef} aria-label="分析與觀點">
      <SectionHead title="分析與觀點" note="由新聞、回測與法人資料自動整理" />
      <AnalysisSection analysis={analysis} />
    </section>
  ) : null;

  const shortItems = (watchlist?.short.items ?? []).slice(0, 7);
  const longItems = (watchlist?.long.items ?? []).slice(0, 7);
  const themesBlock = (
    <section className="fd-section" aria-label="系統判斷的族群">
      <SectionHead title="系統判斷的族群" action={`全部 ${themes.length} 個題材`} onAction={onGoMomentum} />
      {themes.length > 0 ? <ThemeTable themes={themes.slice(0, mobile ? 5 : 7)} focus={focus} onGoStock={onGoStock} /> : <p className="fd-empty fd-faint">目前沒有達門檻的題材</p>}
      {shortItems.length + longItems.length > 0 ? (
        <div className="fd-two">
          <div>
            <SectionHead level={3} title="短線" note="1 到 5 日" action="個股雷達" onAction={onGoWatchlist} />
            <PickTable kind="short" items={shortItems} onGoStock={onGoStock} />
          </div>
          <div>
            <SectionHead level={3} title="長線" note="3 到 12 月" />
            <PickTable kind="long" items={longItems} onGoStock={onGoStock} />
          </div>
        </div>
      ) : null}
    </section>
  );

  const sectorsBlock = preMarket && preMarket.sectors.length > 0 ? (
    <section className="fd-section" aria-label="類股漲跌">
      <SectionHead title="類股漲跌" note={`${preMarket.market?.sectors_as_of ?? ''} 收盤，${preMarket.sectors.length} 類`} />
      <SectorHeat sectors={preMarket.sectors} />
    </section>
  ) : null;

  const riskBlock = risk ? (
    <section className="fd-rail-block" aria-label="新聞多空">
      <SectionHead level={3} title="新聞多空" note={`近 ${risk.windowHours} 小時`} />
      <RiskBlock risk={risk} marketLean={preMarket?.market?.market.lean ?? null} />
    </section>
  ) : null;

  const leadsBlock = (
    <section className="fd-rail-block" aria-label="開盤前導">
      <SectionHead level={3} title="開盤前導" note={leadsUp + leadsDown > 0 ? `${leadsDown} 跌 ${leadsUp} 漲` : '台指夜盤與美股'} />
      <MiniCards quotes={leads} />
    </section>
  );

  const overviewBlock = overview.length > 0 ? (
    <section className="fd-rail-block" aria-label="市場概覽">
      <SectionHead level={3} title="市場概覽" note="台股、匯率、加密、黃金" />
      <MiniCards quotes={overview} />
    </section>
  ) : null;

  const newsBlock = (
    <section className="fd-rail-block news-section" aria-label="最新資訊">
      <SectionHead level={3} title="最新資訊" note={`${news.length} 則原始新聞`} />
      <div className="news-feed fd-news" ref={newsFeedRef}>
        {visibleNews.map((item) => {
          const symbols = item.symbols.filter((symbol, index, all) => all.findIndex((candidate) => candidate.instrument_id === symbol.instrument_id) === index).slice(0, 2);
          return (
            <article className="fd-news-row" key={item.id}>
              <a href={item.url ?? '#'} target="_blank" rel="noreferrer">{item.title_zh}</a>
              <div className="fd-news-meta">
                <span className="fd-num">{relativeTime(item.published_at, Date.now())}</span>
                <span>{item.source}</span>
                {item.theme_name_zh ? <button type="button" onClick={onGoMomentum}>{item.theme_name_zh}</button> : null}
                {symbols.map((symbol) => <button key={`${item.id}-${symbol.instrument_id}`} type="button" onClick={() => onGoStock(symbol.symbol, symbol.exchange)}>{symbol.symbol}</button>)}
              </div>
            </article>
          );
        })}
        {hasMoreNews ? (
          <button className="fd-more news-load-more" ref={newsLoadMoreRef} type="button"
            onClick={() => setVisibleNewsCount((count) => Math.min(count + NEWS_PAGE_SIZE, news.length))}>
            向下捲動載入更多，已顯示 {visibleNews.length} / {news.length} 則
          </button>
        ) : null}
      </div>
    </section>
  );

  const calendarBlock = (
    <section className="fd-rail-block" aria-label="經濟日曆">
      <SectionHead level={3} title="經濟日曆" note={extras.calendar ? `台北時間，${extras.calendar.source}` : undefined} />
      {extras.calendar ? <CalendarList data={extras.calendar} limit={mobile ? 4 : 6} /> : <p className="fd-empty fd-faint">經濟日曆暫時無法取得</p>}
    </section>
  );

  if (mobile) {
    return (
      <div className="page-content home-page fd is-mobile">
        {tabs}
        {header}
        {riskBlock}
        {eventsBlock}
        {leadsBlock}
        {analysisBlock}
        {calendarBlock}
        {themesBlock}
        {overviewBlock}
        {sectorsBlock}
        {newsBlock}
      </div>
    );
  }

  return (
    <div className="page-content home-page fd">
      {tabs}
      <div className="fd-cols">
        <div className="fd-main">
          {header}
          {eventsBlock}
          {analysisBlock}
          {themesBlock}
          {sectorsBlock}
        </div>
        <aside className="fd-rail" aria-label="市場與日程">
          {riskBlock}
          {leadsBlock}
          {overviewBlock}
          {newsBlock}
          {calendarBlock}
        </aside>
      </div>
    </div>
  );
};
