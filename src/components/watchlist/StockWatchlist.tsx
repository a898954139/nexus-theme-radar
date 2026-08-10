import React, { useMemo, useState } from 'react';
import {
  SearchableStock,
  StockFlag,
  StockFlagKey,
  StockWatchlistData,
  WatchlistDirection,
  WatchlistInstrument,
  WatchlistStock
} from '../../types';

export type WatchlistView = 'short' | 'long' | 'search';

export interface StockWatchlistProps {
  payload: StockWatchlistData | null;
  view: WatchlistView;
  query: string;
  onViewChange: (view: WatchlistView) => void;
  onQueryChange: (query: string) => void;
  onGoStock: (symbol: string, exchange: string) => void;
  loading?: boolean;
  error?: boolean;
  onRetry?: () => void;
  onGoHome?: () => void;
}

const SEARCH_RESULT_LIMIT = 30;
const views: Array<{ id: WatchlistView; label: string }> = [
  { id: 'short', label: '短線' },
  { id: 'long', label: '長線' },
  { id: 'search', label: '搜尋個股' }
];

const flagLabels: Record<StockFlagKey, string> = {
  heat_rising: '熱度升溫',
  multi_theme: '多題材共振',
  institutional_positive: '法人偏多',
  fundamentals_improving: '基本面改善',
  high_daytrade: '高當沖',
  overnight_risk: '隔日衝風險',
  cashflow_weak: '現金流轉弱',
  high_leverage: '高槓桿',
  data_sparse: '資料不足'
};

type SearchTier =
  | 'symbol-exact'
  | 'name-exact'
  | 'symbol-prefix'
  | 'name-prefix'
  | 'name-contains';

const searchTierOrder: Record<SearchTier, number> = {
  'symbol-exact': 0,
  'name-exact': 1,
  'symbol-prefix': 2,
  'name-prefix': 3,
  'name-contains': 4
};

function matchTier(instrument: WatchlistInstrument, query: string): SearchTier | null {
  const needle = query.trim().toLocaleLowerCase('zh-TW');
  const symbol = instrument.symbol.toLocaleLowerCase('zh-TW');
  const name = instrument.name_zh.toLocaleLowerCase('zh-TW');
  if (symbol === needle) return 'symbol-exact';
  if (name === needle) return 'name-exact';
  if (symbol.startsWith(needle)) return 'symbol-prefix';
  if (name.startsWith(needle)) return 'name-prefix';
  if (name.includes(needle)) return 'name-contains';
  return null;
}

function missingLabel(_missingReasons: string[], fallback: string): string {
  return `—（${fallback}）`;
}

function formatMaybePercent(value: number | null, missingReasons: string[], fallback: string): string {
  return value === null ? missingLabel(missingReasons, fallback) : `${(value * 100).toFixed(1)}%`;
}

function formatMaybeNumber(value: number | null, missingReasons: string[], fallback: string): string {
  return value === null ? missingLabel(missingReasons, fallback) : value.toLocaleString('zh-TW', { maximumFractionDigits: 1 });
}

function overnightMissingLabel(reason: string | null): string {
  return reason === 'no reliable overnight source' ? '隔日衝資料不足' : reason || '隔日衝資料不足';
}

function institutionalLabel(item: WatchlistStock): string {
  const labels = {
    positive: '近 5 日偏多',
    negative: '近 5 日偏空',
    flat: '近 5 日持平',
    insufficient: '資料不足'
  } as const;
  return labels[item.institutional.direction];
}

function directionArrow(direction: WatchlistDirection): string {
  if (direction === 'up') return '↑';
  if (direction === 'down') return '↓';
  if (direction === 'flat') return '→';
  return '—';
}

const FlagChips: React.FC<{ flags: StockFlag[] }> = ({ flags }) => (
  <div className="watchlist-flags">
    {flags.slice(0, 3).map((flag) => (
      <span className={`watchlist-flag is-${flag.type}`} key={flag.key}>{flagLabels[flag.key]}</span>
    ))}
  </div>
);

const Themes: React.FC<{ item: Pick<WatchlistStock, 'themes'> }> = ({ item }) => (
  <span className="watchlist-theme-names">
    {item.themes.slice(0, 2).map((theme) => theme.name_zh).join(' · ') || '—'}
  </span>
);

const WatchlistMetrics: React.FC<{ item: WatchlistStock; view: Exclude<WatchlistView, 'search'> }> = ({ item, view }) => {
  const missingReasons = item.coverage.missing;
  if (view === 'short') {
    const themeAttention = item.short.components.theme_attention.normalized;
    const heatChange = item.themes[0]?.heat_change_24h;
    const overnight = item.trading_activity.overnight_risk;
    return (
      <>
        <span><b>{formatMaybeNumber(themeAttention, missingReasons, '題材關注度資料不足')}</b><small>{heatChange === null || heatChange === undefined ? '—' : `${heatChange >= 0 ? '+' : ''}${heatChange.toFixed(1)} / 24h`}</small></span>
        <span><b>{institutionalLabel(item)}</b><small>{item.institutional.observation_count} 筆觀測</small></span>
        <span><b>{formatMaybePercent(item.trading_activity.day_trading_volume_ratio, missingReasons, '當沖比資料不足')}</b><small>{item.trading_activity.as_of ?? '日期缺值'}</small></span>
        <span><b>{overnight === null ? `—（${overnightMissingLabel(item.trading_activity.overnight_missing_reason)}）` : `${overnight.toFixed(0)} 分`}</b><small>初版不扣分</small></span>
      </>
    );
  }
  return (
    <>
      <span><b>{formatMaybeNumber(item.fundamentals.score, missingReasons, '基本面資料不足')}</b><small>{item.fundamentals.fiscal_quarter ?? '季度缺值'}</small></span>
      <span><b>營收{directionArrow(item.fundamentals.revenue_direction)} EPS{directionArrow(item.fundamentals.eps_direction)}</b><small>{item.fundamentals.comparison_basis ?? '比較基準缺值'}</small></span>
      <span><b>{formatMaybePercent(item.fundamentals.gross_margin, missingReasons, '毛利率資料不足')}</b><small>毛利率</small></span>
      <span><b>{formatMaybeNumber(item.fundamentals.operating_cash_flow, missingReasons, '現金流資料不足')}</b><small>負債比 {formatMaybePercent(item.fundamentals.debt_ratio, missingReasons, '資料不足')}</small></span>
    </>
  );
};

export const StockWatchlist: React.FC<StockWatchlistProps> = ({
  payload,
  view,
  query,
  onViewChange,
  onQueryChange,
  onGoStock,
  loading = false,
  error = false,
  onRetry,
  onGoHome
}) => {
  const [showMethodology, setShowMethodology] = useState(false);
  const searchResults = useMemo(() => {
    if (!payload || !query.trim()) return [];
    return payload.searchable
      .map((instrument) => ({ instrument, tier: matchTier(instrument.instrument, query) }))
      .filter((match): match is { instrument: SearchableStock; tier: SearchTier } => match.tier !== null)
      .sort((left, right) => searchTierOrder[left.tier] - searchTierOrder[right.tier]
        || left.instrument.instrument.instrument_id.localeCompare(right.instrument.instrument.instrument_id))
      .map((match) => match.instrument)
      .slice(0, SEARCH_RESULT_LIMIT);
  }, [payload, query]);

  const handleTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
    event.preventDefault();
    const current = views.findIndex((candidate) => candidate.id === view);
    const offset = event.key === 'ArrowRight' ? 1 : -1;
    const next = (current + offset + views.length) % views.length;
    onViewChange(views[next].id);
    event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
  };

  const handleRowKeyDown = (event: React.KeyboardEvent, instrument: WatchlistInstrument) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onGoStock(instrument.symbol, instrument.exchange);
    }
  };

  const renderItem = (item: WatchlistStock) => {
    const rank = view === 'long' ? item.long.rank : item.short.rank;
    const score = view === 'long' ? Math.round(item.long.score) : Math.round(item.short.score);
    return (
      <React.Fragment key={item.instrument.instrument_id}>
        <div
          className="watchlist-row"
          role="link"
          tabIndex={0}
          onClick={() => onGoStock(item.instrument.symbol, item.instrument.exchange)}
          onKeyDown={(event) => handleRowKeyDown(event, item.instrument)}
        >
          <strong className="watchlist-rank mono-num">#{rank}</strong>
          <span className="watchlist-stock-name"><b>{item.instrument.name_zh}</b><small className="mono-num">{item.instrument.symbol} · {item.instrument.exchange}</small></span>
          <strong className="watchlist-score mono-num">{score}</strong>
          <WatchlistMetrics item={item} view={view === 'long' ? 'long' : 'short'} />
          <Themes item={item} />
          <FlagChips flags={item.flags} />
          <button type="button" onClick={(event) => { event.stopPropagation(); onGoStock(item.instrument.symbol, item.instrument.exchange); }}>查看分析 →</button>
        </div>
        <article
          className="watchlist-mobile-card"
          role="link"
          tabIndex={0}
          onClick={() => onGoStock(item.instrument.symbol, item.instrument.exchange)}
          onKeyDown={(event) => handleRowKeyDown(event, item.instrument)}
        >
          <header><span><b>{item.instrument.name_zh}</b><small className="mono-num">{item.instrument.symbol} · {item.instrument.exchange}</small></span><strong className="mono-num">#{rank} · {score}</strong></header>
          <div className="watchlist-metric-grid"><WatchlistMetrics item={item} view={view === 'long' ? 'long' : 'short'} /></div>
          <Themes item={item} />
          <FlagChips flags={item.flags} />
          <button type="button" onClick={(event) => { event.stopPropagation(); onGoStock(item.instrument.symbol, item.instrument.exchange); }}>查看分析 →</button>
        </article>
      </React.Fragment>
    );
  };

  const renderSearchItem = (item: SearchableStock) => (
    <React.Fragment key={item.instrument.instrument_id}>
      <div
        className="watchlist-row watchlist-search-row"
        role="link"
        tabIndex={0}
        onClick={() => onGoStock(item.instrument.symbol, item.instrument.exchange)}
        onKeyDown={(event) => handleRowKeyDown(event, item.instrument)}
      >
        <strong className="watchlist-rank mono-num">{item.selected_top50 ? `#${item.short_rank ?? '—'}` : '—'}</strong>
        <span className="watchlist-stock-name"><b>{item.instrument.name_zh}</b><small className="mono-num">{item.instrument.symbol} · {item.instrument.exchange}</small></span>
        <span className="watchlist-search-status">{item.selected_top50 ? `短 #${item.short_rank} · 長 #${item.long_rank}` : '候選池'}</span>
        <Themes item={item} />
        <FlagChips flags={item.flags} />
        <button type="button" onClick={(event) => { event.stopPropagation(); onGoStock(item.instrument.symbol, item.instrument.exchange); }}>查看分析 →</button>
      </div>
      <article className="watchlist-mobile-card" role="link" tabIndex={0} onClick={() => onGoStock(item.instrument.symbol, item.instrument.exchange)} onKeyDown={(event) => handleRowKeyDown(event, item.instrument)}>
        <header><span><b>{item.instrument.name_zh}</b><small className="mono-num">{item.instrument.symbol} · {item.instrument.exchange}</small></span><strong>{item.selected_top50 ? 'Top 50' : '候選池'}</strong></header>
        <div className="watchlist-metric-grid"><span><b>{item.short_rank ?? '—'}</b><small>短線排名</small></span><span><b>{item.long_rank ?? '—'}</b><small>長線排名</small></span></div>
        <Themes item={item} />
        <FlagChips flags={item.flags} />
        <button type="button" onClick={(event) => { event.stopPropagation(); onGoStock(item.instrument.symbol, item.instrument.exchange); }}>查看分析 →</button>
      </article>
    </React.Fragment>
  );

  const listItems = payload ? (view === 'long' ? payload.long.items : payload.short.items) : [];
  const resultCount = view === 'search' ? searchResults.length : listItems.length;

  return (
    <div className="page-content watchlist-page watchlist-no-horizontal-scroll">
      <section className="page-intro">
        <span className="page-kicker">STOCK WATCHLIST · TOP 50</span>
        <h1>個股雷達</h1>
        <div className="gold-rule" />
        <p>從題材候選池找出值得關注的股票；短線與長線共用同一批 Top 50，搜尋則涵蓋完整候選池。</p>
      </section>

      <div className="watchlist-tabs" role="tablist" aria-label="個股雷達檢視">
        {views.map((candidate) => (
          <button
            id={`watchlist-tab-${candidate.id}`}
            className={view === candidate.id ? 'is-selected' : ''}
            type="button"
            role="tab"
            aria-selected={view === candidate.id}
            tabIndex={view === candidate.id ? 0 : -1}
            onClick={() => onViewChange(candidate.id)}
            onKeyDown={handleTabKeyDown}
            key={candidate.id}
          >
            {candidate.label}
          </button>
        ))}
      </div>

      {view === 'search' ? (
        <div className="watchlist-search">
          <label htmlFor="watchlist-query">搜尋完整題材候選池</label>
          <div><input id="watchlist-query" type="search" value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="例如：2330、台積電" />{query ? <button type="button" onClick={() => onQueryChange('')} aria-label="清除搜尋">×</button> : null}</div>
        </div>
      ) : null}

      <section className="watchlist-list-heading">
        <div><strong>{view === 'long' ? '長線關注' : view === 'search' ? '搜尋結果' : '短線關注'}</strong><span>{payload?.candidate_as_of ?? '資料日期缺值'} · {resultCount} 檔</span></div>
        {view !== 'search' ? <button type="button" aria-expanded={showMethodology} onClick={() => setShowMethodology((shown) => !shown)}>評分說明 ▾</button> : null}
      </section>

      {showMethodology && view !== 'search' ? (
        <section className="watchlist-methodology">
          <strong>{view === 'short' ? '短線權重' : '長線權重'}</strong>
          <p>{view === 'short' ? '55% 題材關注度／20% 法人短期動向／15% 當沖活躍度／10% 基本面防守。' : '60% 基本面品質／20% 法人支持／15% 題材延續性／5% 交易籌碼穩定度。'}</p>
          <p>缺值會由 pipeline 重新分配有效權重，不補 0；目前無可靠隔日衝資料，因此初版顯示缺值且不扣分。</p>
        </section>
      ) : null}

      <div className="watchlist-result-count" aria-live="polite">顯示 {resultCount} 筆結果</div>

      {loading ? <div className="watchlist-skeleton" aria-label="個股雷達載入中">{Array.from({ length: 8 }, (_, index) => <div className="watchlist-skeleton-row" key={index} />)}</div> : null}
      {error && !loading ? <section className="watchlist-state"><h2>個股雷達暫時無法載入</h2><p>請稍後重試；既有題材雷達資料不受影響。</p><div>{onRetry ? <button type="button" onClick={onRetry}>重新載入</button> : null}{onGoHome ? <button type="button" onClick={onGoHome}>回題材雷達</button> : null}</div></section> : null}

      {!loading && !error && payload && view !== 'search' && listItems.length ? (
        <div className="watchlist-table">
          <div className="watchlist-table-head"><span>#</span><span>股票</span><span>關注分數</span><span>{view === 'short' ? '題材關注度' : '基本面'}</span><span>{view === 'short' ? '法人' : '成長'}</span><span>{view === 'short' ? '當沖比' : '獲利'}</span><span>{view === 'short' ? '隔日衝' : '財務'}</span><span>題材</span><span>Flags</span><span>操作</span></div>
          {listItems.map(renderItem)}
        </div>
      ) : null}

      {!loading && !error && view !== 'search' && (!payload || listItems.length === 0) ? <section className="watchlist-state"><h2>目前沒有可顯示的個股雷達資料</h2></section> : null}
      {!loading && !error && view === 'search' && !query.trim() ? <section className="watchlist-state"><h2>請輸入代號或公司名稱</h2><p>搜尋涵蓋完整題材候選池，包含未進入 Top 50 的股票。</p></section> : null}
      {!loading && !error && view === 'search' && query.trim() && searchResults.length === 0 ? <section className="watchlist-state"><h2>找不到「{query.trim()}」</h2><p>請改用股票代號或完整公司名稱。</p></section> : null}
      {!loading && !error && view === 'search' && searchResults.length ? <div className="watchlist-table watchlist-search-table">{searchResults.map(renderSearchItem)}</div> : null}

      <p className="disclaimer">關注分數衡量題材、籌碼與基本面訊號強度，不代表預測漲跌，也不構成投資建議。</p>
    </div>
  );
};
