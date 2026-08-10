import React, { useEffect, useMemo, useState } from 'react';
import { fetchBrokerCoverage, fetchBrokerStats } from '../../services/dataService';
import { BrokerCoverageData, BrokerStat, BrokerStatsData, StockTab } from '../../types';

interface BrokerFlowsProps {
  onGoStock: (code: string, exchange?: string, tab?: StockTab) => void;
  refreshKey: number;
}

type BrokerSort = 'net' | 'volume' | 'dt' | 'ov';

const WATCH_KEY = 'nexus-broker-watch';

function formatLots(value: number) {
  return value.toLocaleString('en-US', { maximumFractionDigits: 0 });
}

function formatMetric(value: number | null) {
  return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(0)}%`;
}

function readWatchList(): Record<string, true> {
  try {
    const value = JSON.parse(window.localStorage.getItem(WATCH_KEY) ?? '{}');
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    return Object.fromEntries(
      Object.entries(value).filter(([, watched]) => watched === true),
    ) as Record<string, true>;
  } catch {
    return {};
  }
}

function matchesQuery(stat: BrokerStat, query: string) {
  if (!query.trim()) return true;
  const normalized = query.trim().toLowerCase();
  return stat.name.toLowerCase().includes(normalized)
    || stat.top.some(([code, name]) => `${code} ${name}`.toLowerCase().includes(normalized));
}

function sortValue(stat: BrokerStat, sort: BrokerSort) {
  if (sort === 'volume') return stat.buy + stat.sell;
  if (sort === 'dt') return stat.dt ?? -1;
  if (sort === 'ov') return stat.ov ?? -1;
  return Math.abs(stat.buy - stat.sell);
}

const BrokerKpi: React.FC<{ label: string; value: string; note: string; tone?: 'positive' | 'negative' | 'muted' }> = ({ label, value, note, tone = 'muted' }) => (
  <article className="broker-kpi">
    <span className="field-label">{label}</span>
    <strong className={`mono-num ${tone}`}>{value}</strong>
    <small>{note}</small>
  </article>
);

const BrokerBars: React.FC<{ stat: BrokerStat; maxVolume: number }> = ({ stat, maxVolume }) => (
  <div className="broker-volume-bars">
    <div className="broker-volume-bar"><i className="broker-buy-fill" style={{ width: `${Math.max(2, stat.buy / Math.max(maxVolume, 1) * 100)}%` }} /></div>
    <div className="broker-volume-bar"><i className="broker-sell-fill" style={{ width: `${Math.max(2, stat.sell / Math.max(maxVolume, 1) * 100)}%` }} /></div>
    <div className="broker-volume-values mono-num"><span>{formatLots(stat.buy)}</span><span>{formatLots(stat.sell)}</span></div>
  </div>
);

const OvernightBadge: React.FC<{ value: number | null }> = ({ value }) => {
  const tone = value == null ? 'is-unavailable' : value >= 80 ? 'is-high' : value >= 60 ? 'is-medium' : 'is-low';
  return <span className={`broker-overnight-badge ${tone}`} aria-label={value == null ? '隔日衝指數無資料' : `隔日衝指數 ${value.toFixed(0)}`}>{value == null ? '—' : value.toFixed(0)}</span>;
};

const BrokerStatRow: React.FC<{
  stat: BrokerStat;
  index: number;
  maxVolume: number;
  onGoStock: BrokerFlowsProps['onGoStock'];
}> = ({ stat, index, maxVolume, onGoStock }) => {
  const net = stat.buy - stat.sell;
  return (
    <article className="broker-stat-row">
      <div className="broker-stat-main">
        <span className="broker-rank mono-num">{String(index + 1).padStart(2, '0')}</span>
        <strong>{stat.name}</strong>
      </div>
      <BrokerBars stat={stat} maxVolume={maxVolume} />
      <div className="broker-stat-metrics">
        <span><small>淨額</small><b className={`mono-num ${net >= 0 ? 'positive' : 'negative'}`}>{net >= 0 ? '+' : ''}{formatLots(net)}</b></span>
        <span><small>當沖比</small><b className={`mono-num ${stat.dt != null && stat.dt >= 60 ? 'broker-metric-gold' : 'muted'}`}>{formatMetric(stat.dt)}</b></span>
        <span><small>隔日衝</small><OvernightBadge value={stat.ov} /></span>
      </div>
      <div className="broker-top-stocks" aria-label={`${stat.name}主攻標的`}>
        {stat.top.length ? stat.top.map(([code, name]) => (
          <button className="broker-stock-chip" type="button" key={`${stat.name}-${code}`} onClick={() => onGoStock(code, undefined, 'broker')}>
            <b className="mono-num">{code}</b><span>{name}</span>
          </button>
        )) : <span className="muted">—</span>}
      </div>
    </article>
  );
};

export const BrokerFlows: React.FC<BrokerFlowsProps> = ({ onGoStock, refreshKey }) => {
  const [data, setData] = useState<BrokerStatsData | null>(null);
  const [coverage, setCoverage] = useState<BrokerCoverageData | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<BrokerSort>('net');
  const [onlyOvernight, setOnlyOvernight] = useState(false);
  const [watch, setWatch] = useState<Record<string, true>>({});
  const [watchQuery, setWatchQuery] = useState('');
  const [watchOpen, setWatchOpen] = useState(false);

  useEffect(() => {
    setWatch(readWatchList());
    let active = true;
    Promise.all([fetchBrokerStats(refreshKey > 0), fetchBrokerCoverage(refreshKey > 0).catch(() => null)])
      .then(([stats, currentCoverage]) => {
        if (!active) return;
        setData(stats);
        setCoverage(currentCoverage);
        setLoadError(false);
      })
      .catch(() => {
        if (active) setLoadError(true);
      });
    return () => { active = false; };
  }, [refreshKey]);

  const allStats = data ?? [];
  const hasOvernightMetric = allStats.some((stat) => stat.ov != null);
  const hasWatch = Object.keys(watch).length > 0;
  const visibleStats = useMemo(() => {
    const filtered = allStats.filter((stat) => {
      if (hasWatch && !watch[stat.name]) return false;
      if (onlyOvernight && (stat.ov == null || stat.ov < 70)) return false;
      return matchesQuery(stat, query);
    });
    return filtered.sort((left, right) => sortValue(right, sort) - sortValue(left, sort));
  }, [allStats, hasWatch, onlyOvernight, query, sort, watch]);

  const totals = useMemo(() => {
    const buy = visibleStats.reduce((sum, stat) => sum + stat.buy, 0);
    const sell = visibleStats.reduce((sum, stat) => sum + stat.sell, 0);
    const volume = buy + sell;
    const largest = visibleStats.reduce<BrokerStat | null>((current, stat) => {
      if (!current || stat.buy + stat.sell > current.buy + current.sell) return stat;
      return current;
    }, null);
    return { buy, sell, volume, net: buy - sell, largest, concentration: largest && volume ? (largest.buy + largest.sell) / volume * 100 : 0 };
  }, [visibleStats]);

  const maxVolume = Math.max(...visibleStats.map((stat) => stat.buy + stat.sell), 1);
  const overnightCount = visibleStats.filter((stat) => stat.ov != null && stat.ov >= 70).length;
  const watchOptions = allStats.filter((stat) => stat.name.toLowerCase().includes(watchQuery.toLowerCase()));

  const updateWatch = (next: Record<string, true>) => {
    setWatch(next);
    window.localStorage.setItem(WATCH_KEY, JSON.stringify(next));
  };

  if (loadError) return <section className="broker-empty"><strong>NO BROKER DATA</strong><span>券商分點資料目前無法讀取。</span></section>;
  if (!data) return <section className="broker-loading"><span className="data-skeleton skeleton-wide" /><span className="data-skeleton skeleton-wide" /><span className="data-skeleton skeleton-row" /></section>;

  return (
    <section className="broker-flows-panel">
      <div className="broker-kpi-grid">
        <BrokerKpi label="篩選後分點" value={formatLots(visibleStats.length)} note={`共 ${formatLots(allStats.length)} 家`} />
        <BrokerKpi label="淨買賣超合計" value={`${totals.net >= 0 ? '+' : ''}${formatLots(totals.net)}`} note={`買 ${formatLots(totals.buy)} · 賣 ${formatLots(totals.sell)}`} tone={totals.net >= 0 ? 'positive' : 'negative'} />
        <BrokerKpi label="隔日衝型分點" value={hasOvernightMetric ? formatLots(overnightCount) : '—'} note={hasOvernightMetric ? '隔日衝指數 ≥ 70' : '來源未提供隔日衝指數'} />
        <BrokerKpi label="最大分點集中度" value={totals.concentration ? `${totals.concentration.toFixed(1)}%` : '—'} note="單一分點占成交量" />
      </div>

      <div className="broker-filter-row">
        <label className="broker-search"><span className="sr-only">搜尋券商或股票</span><input name="broker-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜尋券商或標的…" /></label>
        <label className="broker-toggle"><input name="broker-overnight" type="checkbox" disabled={!hasOvernightMetric} checked={onlyOvernight} onChange={(event) => setOnlyOvernight(event.target.checked)} /><span className="toggle-track" /><span>{hasOvernightMetric ? '只看隔日衝型' : '隔日衝指數待資料'}</span></label>
        <div className="broker-sort" role="group" aria-label="排序方式"><span>排序</span><div className="broker-sort-options">{([['net', '淨額'], ['volume', '成交量'], ['dt', '當沖比'], ['ov', '隔日衝指數']] as const).map(([value, label]) => <button key={value} type="button" className={sort === value ? 'is-selected' : ''} aria-pressed={sort === value} onClick={() => setSort(value)}>{label}</button>)}</div></div>
      </div>

      <div className="broker-watch-bar">
        <button type="button" onClick={() => setWatchOpen((value) => !value)}><span>分點追蹤</span><b>{hasWatch ? `追蹤中 ${Object.keys(watch).length} 家` : '全部分點'}</b><span>{watchOpen ? '收合 ▲' : '管理追蹤 ▾'}</span></button>
        <small>{hasWatch ? '只顯示追蹤中的分點 · 已記住你的選擇' : '目前顯示全部分點 · 選擇後只顯示追蹤中的'}</small>
      </div>
      {watchOpen ? <div className="broker-watch-panel"><div className="broker-watch-actions"><input name="broker-watch-search" aria-label="搜尋追蹤券商" value={watchQuery} onChange={(event) => setWatchQuery(event.target.value)} placeholder="搜尋分點…" /><button type="button" onClick={() => updateWatch(Object.fromEntries(allStats.map((stat) => [stat.name, true])))}>全部追蹤</button><button type="button" onClick={() => updateWatch({})}>清除追蹤</button></div><div className="broker-watch-chips">{watchOptions.map((stat) => <button key={stat.name} type="button" className={watch[stat.name] ? 'is-watched' : ''} onClick={() => { const next = { ...watch }; if (next[stat.name]) delete next[stat.name]; else next[stat.name] = true; updateWatch(next); }}>{watch[stat.name] ? '✓' : '+'} {stat.name}</button>)}</div></div> : null}

      <div className="broker-stat-table">
        <div className="broker-stat-head"><span>#</span><span>券商分點</span><span>買進 / 賣出（張）</span><span>淨額</span><span>當沖比</span><span>隔日衝</span><span>主攻標的</span></div>
        {visibleStats.length ? visibleStats.map((stat, index) => <BrokerStatRow key={stat.name} stat={stat} index={index} maxVolume={maxVolume} onGoStock={onGoStock} />) : <div className="broker-empty broker-empty-inline"><strong>NO MATCHING BROKER</strong><span>沒有符合目前篩選條件的分點。</span></div>}
      </div>
      <p className="broker-source-note">隔日衝指數由該分點的當沖比、進出頻率與持有天數推估，數值越高代表短線進出傾向越強。資料源自公開券商分點進出彙總，僅供技術展示，不構成投資建議。{coverage ? `本次已嘗試 ${coverage.attempted_symbols.toLocaleString()} 檔，取得分點資料 ${coverage.symbols_with_data.toLocaleString()} 檔。` : ''}</p>
    </section>
  );
};
