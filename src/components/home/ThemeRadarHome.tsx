import React, { useMemo, useState } from 'react';
import { DeviceType, InstrumentRef, NewsItem, RadarData, StockGroup } from '../../types';

interface ThemeRadarHomeProps {
  data: RadarData;
  device: DeviceType;
  onGoMomentum: () => void;
  onGoStock: (code: string, exchange?: string, tab?: 'fundamentals' | 'flows') => void;
}

function stageLabel(stage?: string) {
  const labels: Record<string, string> = {
    new: '加速中',
    accelerating: '加速中',
    expanding: '擴散',
    stable: '持平',
    cooling: '退燒'
  };
  return labels[stage ?? ''] ?? stage ?? '—';
}

function signedValue(value: number) {
  return `${value >= 0 ? '+' : ''}${value}`;
}

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
    .slice(0, 20)
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

function mergeThemeData(data: RadarData) {
  const momentum = new Map(data.momentumLatest.themes.map((theme) => [theme.theme_id, theme]));
  return data.themeRanking.themes.slice(0, 5).map((theme) => ({
    ...theme,
    momentum_score: momentum.get(theme.theme_id)?.momentum_score ?? 0,
    lifecycle_stage: momentum.get(theme.theme_id)?.lifecycle_stage,
    related_symbols: momentum.get(theme.theme_id)?.related_symbols ?? []
  }));
}

const InstrumentChip: React.FC<{
  instrument: InstrumentRef;
  kind: 'direct' | 'supply';
  onClick: () => void;
}> = ({ instrument, kind, onClick }) => (
  <button className={`instrument-chip ${kind}`} type="button" onClick={onClick}>
    <span className="instrument-symbol mono-num">{instrument.symbol}</span>
    <span>{instrument.name_zh}</span>
  </button>
);

const ThemeDetail: React.FC<{
  theme: ReturnType<typeof mergeThemeData>[number];
  selectedGroup: StockGroup;
  setSelectedGroup: (group: StockGroup) => void;
  searchQuery: string;
  setSearchQuery: (query: string) => void;
  onGoMomentum: () => void;
  onGoStock: (code: string, exchange?: string) => void;
}> = ({ theme, selectedGroup, setSelectedGroup, searchQuery, setSearchQuery, onGoMomentum, onGoStock }) => {
  const direct = theme.direct_mentions.map((instrument) => ({ instrument, kind: 'direct' as const }));
  const supply = theme.supply_chain_candidates.map((instrument) => ({ instrument, kind: 'supply' as const }));
  const all = [...direct, ...supply];
  const filtered = all.filter(({ instrument, kind }) => {
    if (selectedGroup !== 'all' && kind !== selectedGroup) return false;
    const query = searchQuery.trim().toLowerCase();
    return !query || instrument.symbol.toLowerCase().includes(query) || instrument.name_zh.toLowerCase().includes(query);
  });
  const momentumClass = theme.momentum_score >= 0 ? 'positive' : 'negative';

  return (
    <div className="theme-detail">
      <div className="theme-detail-header">
        <div className="theme-detail-copy">
          <span className="page-kicker">RANK {String(theme.rank).padStart(2, '0')} · 熱度排名第 {theme.rank}</span>
          <h2>{theme.name_zh}</h2>
          <div className="gold-rule" />
          <p>{theme.representative_news?.summary ?? '目前沒有可顯示的題材摘要。'}</p>
        </div>
        <div className="theme-score">
          <span>熱度</span>
          <strong className="mono-num">{theme.heat_score}</strong>
          <em className={momentumClass}>動能 {signedValue(theme.momentum_score)}</em>
          <small>{stageLabel(theme.lifecycle_stage)}</small>
        </div>
      </div>

      <div className="stock-filter-bar">
        <div className="filter-tabs" role="tablist" aria-label="題材標的篩選">
          {([
            ['all', `全部 ${all.length}`],
            ['direct', `直接提及 ${direct.length}`],
            ['supply', `供應鏈 ${supply.length}`]
          ] as Array<[StockGroup, string]>).map(([value, label]) => (
            <button
              className={selectedGroup === value ? 'is-selected' : ''}
              key={value}
              type="button"
              onClick={() => setSelectedGroup(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <input
          aria-label="搜尋代號或名稱"
          placeholder="代號或名稱..."
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
        />
        <span className="filter-count mono-num">{filtered.length} / {all.length} 檔</span>
      </div>

      <div className="stock-chip-grid" aria-live="polite">
        {filtered.length ? filtered.map(({ instrument, kind }, index) => (
          <InstrumentChip
            key={`${kind}-${instrument.instrument_id}-${index}`}
            instrument={instrument}
            kind={kind}
            onClick={() => onGoStock(instrument.symbol, instrument.exchange)}
          />
        )) : <p className="no-results">沒有符合的標的</p>}
      </div>

      <div className="theme-detail-footer">
        <span>相關新聞 {theme.summaries?.event_count ?? 0} 則</span>
        <button type="button" onClick={onGoMomentum}>在題材動能中查看走勢 →</button>
      </div>
    </div>
  );
};

export const ThemeRadarHome: React.FC<ThemeRadarHomeProps> = ({ data, device, onGoMomentum, onGoStock }) => {
  const themes = useMemo(() => mergeThemeData(data), [data]);
  const news = useMemo(() => toNewsItems(data), [data]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [spread, setSpread] = useState(false);
  const [selectedGroup, setSelectedGroup] = useState<StockGroup>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [communityMode, setCommunityMode] = useState<'today' | '7d'>('today');
  const selectedTheme = themes[selectedIndex] ?? themes[0];

  const selectTheme = (index: number) => {
    setSelectedIndex(index);
    setSelectedGroup('all');
    setSearchQuery('');
  };
  const shiftTheme = (delta: number) => selectTheme((selectedIndex + delta + themes.length) % themes.length);

  return (
    <div className="page-content home-page">
      <header className="page-intro">
        <span className="page-kicker">TOP 5 THEMES</span>
        <h1>台股最近熱什麼</h1>
        <div className="gold-rule" />
        <p>追蹤過去 72 小時的新聞與公告，把反覆被提到的事件歸成題材，依熱度排出前五名。每個題材可以看到摘要、熱度與動能，以及新聞裡直接點名的個股與同一條供應鏈上的候選標的。</p>
      </header>

      {device === 'mobile' ? (
        <section className="mobile-theme-shell">
          <div className="mobile-theme-track">
            {themes.map((theme, index) => (
              <button
                className={`mobile-theme-card ${index === selectedIndex ? 'is-selected' : ''}`}
                key={theme.theme_id}
                type="button"
                onClick={() => selectTheme(index)}
              >
                <span className="page-kicker">RANK {String(theme.rank).padStart(2, '0')}</span>
                <strong>{theme.name_zh}</strong>
                <span><em>熱度</em> <b className="mono-num">{theme.heat_score}</b></span>
                <span className={theme.momentum_score >= 0 ? 'positive' : 'negative'}>{signedValue(theme.momentum_score)} {stageLabel(theme.lifecycle_stage)}</span>
              </button>
            ))}
          </div>
          {selectedTheme ? (
            <ThemeDetail
              theme={selectedTheme}
              selectedGroup={selectedGroup}
              setSelectedGroup={setSelectedGroup}
              searchQuery={searchQuery}
              setSearchQuery={setSearchQuery}
              onGoMomentum={onGoMomentum}
              onGoStock={onGoStock}
            />
          ) : null}
        </section>
      ) : (
        <section
          className="theme-stage"
          onMouseEnter={() => setSpread(true)}
          onMouseLeave={() => setSpread(false)}
          aria-label="熱門題材卡片舞台"
        >
          <span className="stage-label page-kicker">熱度排名，由右切換題材</span>
          <span className="stage-counter mono-num">{selectedIndex + 1} / {themes.length}</span>
          <button className="stage-arrow stage-arrow-left" type="button" aria-label="上一個題材" onClick={() => shiftTheme(-1)}>←</button>
          <button className="stage-arrow stage-arrow-right" type="button" aria-label="下一個題材" onClick={() => shiftTheme(1)}>→</button>
          {themes.map((theme, index) => {
            const distance = index - selectedIndex;
            const isSelected = index === selectedIndex;
            const translateX = spread ? (index - 2) * 150 : distance * 34;
            const scale = spread ? (isSelected ? 1 : 0.9) : (isSelected ? 1 : 0.94 - Math.abs(distance) * 0.03);
            return (
              <article
                className={`theme-stage-card ${isSelected ? 'is-selected' : ''}`}
                key={theme.theme_id}
                onClick={() => selectTheme(index)}
                style={{
                  transform: `translateX(calc(-50% + ${translateX}px)) translateY(-50%) scale(${scale})`,
                  opacity: spread ? (isSelected ? 1 : 0.92) : (isSelected ? 1 : 0.6),
                  zIndex: 20 - Math.abs(distance)
                }}
              >
                {isSelected ? (
                  <ThemeDetail
                    theme={theme}
                    selectedGroup={selectedGroup}
                    setSelectedGroup={setSelectedGroup}
                    searchQuery={searchQuery}
                    setSearchQuery={setSearchQuery}
                    onGoMomentum={onGoMomentum}
                    onGoStock={onGoStock}
                  />
                ) : (
                  <div className="collapsed-theme-card">
                    <span className="page-kicker">RANK {String(theme.rank).padStart(2, '0')}</span>
                    <h2>{theme.name_zh}</h2>
                    <div className="muted-rule gold-rule" />
                    <div className="collapsed-theme-stats">
                      <span>動能 <b className={theme.momentum_score >= 0 ? 'positive mono-num' : 'negative mono-num'}>{signedValue(theme.momentum_score)}</b></span>
                      <strong className="mono-num">{theme.heat_score}</strong>
                    </div>
                  </div>
                )}
              </article>
            );
          })}
          <div className="stage-dots" role="tablist" aria-label="題材選擇">
            {themes.map((theme, index) => (
              <button className={index === selectedIndex ? 'is-selected' : ''} key={theme.theme_id} type="button" aria-label={`選擇 ${theme.name_zh}`} onClick={() => selectTheme(index)} />
            ))}
          </div>
        </section>
      )}

      <section className="news-section">
        <div className="section-heading"><h2>最新新聞</h2><span className="mono-num">{news.length} 條</span></div>
        <div className="news-feed">
          {news.map((item, index) => {
            const published = formatDateTime(item.published_at);
            return (
              <article className="news-row" key={item.id}>
                <div className={`news-time ${index === 0 ? 'is-latest' : ''}`}><strong className="mono-num">{published.time}</strong><span className="mono-num">{published.date}</span></div>
                <div className="news-dot" />
                <div className="news-copy">
                  <a href={item.url ?? '#'} target="_blank" rel="noreferrer">{item.title_zh}</a>
                  <div className="news-meta">
                    {item.theme_name_zh ? <button type="button" onClick={() => selectTheme(themes.findIndex((theme) => theme.theme_id === item.theme_id))}>{item.theme_name_zh}</button> : null}
                    {item.symbols.map((symbol, symbolIndex) => <button key={`${item.id}-${symbol.instrument_id}-${symbolIndex}`} type="button" onClick={() => onGoStock(symbol.symbol, symbol.exchange)}>{symbol.symbol}</button>)}
                    <span>{item.source}</span>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      {selectedTheme ? (
        <section className="related-news-section">
          <div className="section-heading"><h2>{selectedTheme.name_zh} · 相關新聞事件</h2><span className="mono-num">{data.events.filter((event) => event.primary_theme_id === selectedTheme.theme_id).length} 則</span></div>
          <p>從最新採集事件中整理與目前選中題材直接相關的內容。</p>
        </section>
      ) : null}

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
