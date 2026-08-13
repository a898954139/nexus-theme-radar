import React, { useEffect, useMemo, useState } from 'react';
import { ThemeStocksCanvas } from './ThemeStocksCanvas';
import { buildThemeStockEntries, mergeInstrumentRefs } from '../../lib/themeStocks';
import { DeviceType, InstrumentRef, RadarData, StockGroup } from '../../types';

/** The five-theme carousel. Lives here rather than on the homepage because the
 *  homepage is now a news-side board: "what is moving" belongs with the
 *  momentum tables that quantify it, not above the pre-market focus feed. */
interface ThemeCarouselProps {
  data: RadarData;
  device: DeviceType;
  onGoStock: (code: string, exchange?: string, tab?: 'fundamentals' | 'flows') => void;
  /** Omitted on the momentum page, where a link to it would go nowhere. */
  onGoMomentum?: () => void;
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

function mergeThemeData(data: RadarData) {
  const momentum = new Map(data.momentumLatest.themes.map((theme) => [theme.theme_id, theme]));
  const momentumByName = new Map(data.momentumLatest.themes.map((theme) => [theme.name_zh, theme]));
  return data.themeRanking.themes.slice(0, 5).map((theme) => {
    const latest = momentum.get(theme.theme_id) ?? momentumByName.get(theme.name_zh);
    return {
      ...theme,
      direct_mentions: mergeInstrumentRefs(theme.direct_mentions, latest?.direct_symbols ?? []),
      supply_chain_candidates: mergeInstrumentRefs(theme.supply_chain_candidates, latest?.related_symbols ?? []),
      momentum_score: latest?.momentum_score ?? 0,
      lifecycle_stage: latest?.lifecycle_stage
    };
  });
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
  onGoMomentum?: () => void;
  onGoStock: ThemeCarouselProps['onGoStock'];
}> = ({ theme, selectedGroup, setSelectedGroup, searchQuery, setSearchQuery, onGoMomentum, onGoStock }) => {
  const [canvasOpen, setCanvasOpen] = useState(false);
  const all = buildThemeStockEntries(theme.direct_mentions, theme.supply_chain_candidates);
  const direct = all.filter(({ kind }) => kind === 'direct');
  const supply = all.filter(({ kind }) => kind === 'supply');
  const filtered = all.filter(({ instrument, kind }) => {
    if (selectedGroup !== 'all' && kind !== selectedGroup) return false;
    const query = searchQuery.trim().toLowerCase();
    return !query || instrument.symbol.toLowerCase().includes(query) || instrument.name_zh.toLowerCase().includes(query);
  });
  const momentumClass = theme.momentum_score >= 0 ? 'positive' : 'negative';

  useEffect(() => {
    setCanvasOpen(false);
  }, [theme.theme_id]);

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
            onClick={() => onGoStock(instrument.symbol, instrument.exchange, 'fundamentals')}
          />
        )) : <p className="no-results">沒有符合的標的</p>}
      </div>

      {filtered.length ? <button className="stock-list-expand" type="button" onClick={() => setCanvasOpen(true)}>展開全部 {filtered.length} 檔題材股票 →</button> : null}

      {canvasOpen ? <ThemeStocksCanvas themeName={theme.name_zh} stocks={filtered} onClose={() => setCanvasOpen(false)} onGoStock={onGoStock} /> : null}

      <div className="theme-detail-footer">
        <span>相關新聞 {theme.summaries?.event_count ?? 0} 則</span>
        {onGoMomentum ? <button type="button" onClick={onGoMomentum}>在題材動能中查看走勢 →</button> : null}
      </div>
    </div>
  );
};

export const ThemeCarousel: React.FC<ThemeCarouselProps> = ({ data, device, onGoStock, onGoMomentum }) => {
  const themes = useMemo(() => mergeThemeData(data), [data]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [spread, setSpread] = useState(false);
  const [selectedGroup, setSelectedGroup] = useState<StockGroup>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const selectedTheme = themes[selectedIndex] ?? themes[0];

  const selectTheme = (index: number) => {
    setSelectedIndex(index);
    setSelectedGroup('all');
    setSearchQuery('');
  };
  const shiftTheme = (delta: number) => selectTheme((selectedIndex + delta + themes.length) % themes.length);

  if (themes.length === 0) return null;

  return (
    <>
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
    </>
  );
};
