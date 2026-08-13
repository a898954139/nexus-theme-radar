import React, { useEffect, useMemo, useRef, useState } from 'react';
import { DeviceType, NewsItem, PreMarketData, RadarData } from '../../types';
import { PreMarketFocus } from './PreMarketFocus';

interface ThemeRadarHomeProps {
  data: RadarData;
  preMarket: PreMarketData | null;
  device: DeviceType;
  onGoMomentum: () => void;
  onGoStock: (code: string, exchange?: string, tab?: 'fundamentals' | 'flows') => void;
}

const NEWS_PAGE_SIZE = 20;

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return { date: '—', time: '—' };
  return {
    date: `${String(date.getMonth() + 1).padStart(2, '0')}/${String(date.getDate()).padStart(2, '0')}`,
    time: `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
  };
}

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




export const ThemeRadarHome: React.FC<ThemeRadarHomeProps> = ({ data, preMarket, device, onGoMomentum, onGoStock }) => {
  const news = useMemo(() => toNewsItems(data), [data]);
  const [communityMode, setCommunityMode] = useState<'today' | '7d'>('today');
  const [visibleNewsCount, setVisibleNewsCount] = useState(NEWS_PAGE_SIZE);
  const newsFeedRef = useRef<HTMLDivElement>(null);
  const newsLoadMoreRef = useRef<HTMLButtonElement>(null);
  const visibleNews = news.slice(0, visibleNewsCount);
  const hasMoreNews = visibleNewsCount < news.length;

  useEffect(() => {
    setVisibleNewsCount(NEWS_PAGE_SIZE);
  }, [news]);

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


  return (
    <div className="page-content home-page">
      {preMarket ? <PreMarketFocus data={preMarket} device={device} /> : null}



      <section className="news-section">
        <div className="section-heading"><h2>最新新聞</h2><span className="mono-num">{news.length} 條</span></div>
        <div className="news-feed" ref={newsFeedRef}>
          {visibleNews.map((item, index) => {
            const published = formatDateTime(item.published_at);
            const symbols = item.symbols.filter((symbol, symbolIndex, allSymbols) => allSymbols.findIndex((candidate) => candidate.instrument_id === symbol.instrument_id) === symbolIndex);
            const visibleSymbols = symbols.slice(0, 3);
            const hiddenSymbolCount = symbols.length - visibleSymbols.length;
            return (
              <article className="news-row" key={item.id}>
                <div className={`news-time ${index === 0 ? 'is-latest' : ''}`}><strong className="mono-num">{published.time}</strong><span className="mono-num">{published.date}</span></div>
                <div className="news-dot" />
                <div className="news-copy">
                  <a href={item.url ?? '#'} target="_blank" rel="noreferrer">{item.title_zh}</a>
                  <div className="news-meta">
                    {item.theme_name_zh ? <button type="button" onClick={onGoMomentum}>{item.theme_name_zh}</button> : null}
                    {visibleSymbols.map((symbol, symbolIndex) => <button key={`${item.id}-${symbol.instrument_id}-${symbolIndex}`} type="button" onClick={() => onGoStock(symbol.symbol, symbol.exchange)}>{symbol.symbol}</button>)}
                    {hiddenSymbolCount > 0 ? <span className="news-symbol-overflow mono-num">+{hiddenSymbolCount}</span> : null}
                    <span>{item.source}</span>
                  </div>
                </div>
              </article>
            );
          })}
          {hasMoreNews ? (
            <button
              className="stock-list-expand news-load-more"
              ref={newsLoadMoreRef}
              type="button"
              onClick={() => setVisibleNewsCount((count) => Math.min(count + NEWS_PAGE_SIZE, news.length))}
            >
              向下捲動載入更多 · 已顯示 {visibleNews.length} / {news.length} 條
            </button>
          ) : null}
        </div>
      </section>


      <section className="home-guides">
        <button type="button" onClick={onGoMomentum} className="guide-panel guide-momentum">
          <span className="page-kicker">MOMENTUM</span>
          <strong>查看五題材同框動能走勢 →</strong>
          <span>比較不同期間的熱度變化與階段推移</span>
        </button>
        <div className="guide-panel guide-community">
          <div className="section-heading"><span className="page-kicker">COMMUNITY · WAYTOAGI</span><div className="filter-tabs"><button type="button" className={communityMode === 'today' ? 'is-selected' : ''} onClick={() => setCommunityMode('today')}>最近更新日</button><button type="button" className={communityMode === '7d' ? 'is-selected' : ''} onClick={() => setCommunityMode('7d')}>近 7 日</button></div></div>
          <span>{data.waytoagi.latest_date} · {communityMode === 'today' ? data.waytoagi.count_today : data.waytoagi.count_7d} 則更新</span>
        </div>
      </section>
    </div>
  );
};
