import React, { useEffect, useState } from 'react';
import { DeviceType, InstitutionalRankingBoard, PreMarketData, RadarData, SourceHealthData, SourceHealthItem, SourceSite, SourceStatusData, StockWatchlistData, ThemeFocusData, BrokerCoverageData } from '../../types';
import { fetchBrokerCoverage, fetchInstitutionalBoard, fetchSourceHealth } from '../../services/dataService';
import { daysBetween, watchlistSourceDates } from '../../lib/freshness';
import '../common/focus.css';

export interface FreshnessInputs {
  radar: RadarData;
  watchlist: StockWatchlistData | null;
  focus: ThemeFocusData | null;
  preMarket: PreMarketData | null;
}

interface FreshnessRow {
  name: string;
  source: string;
  asOf: string | null;
  display: string;
  /** Max age before the row reads as delayed: hours for intraday feeds, days for daily data. */
  limit: { hours: number } | { days: number };
}

function taipeiToday(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei' }).format(new Date());
}

function rowState(row: FreshnessRow): 'ok' | 'stale' | 'missing' {
  if (!row.asOf) return 'missing';
  if ('hours' in row.limit) {
    const age = (Date.now() - new Date(row.asOf).getTime()) / 3_600_000;
    return Number.isFinite(age) && age <= row.limit.hours ? 'ok' : 'stale';
  }
  const gap = daysBetween(row.asOf, taipeiToday());
  return gap !== null && gap <= row.limit.days ? 'ok' : 'stale';
}

const FreshnessSection: React.FC<{ inputs: FreshnessInputs }> = ({ inputs }) => {
  const [board, setBoard] = useState<InstitutionalRankingBoard | null>(null);
  const [broker, setBroker] = useState<BrokerCoverageData | null>(null);
  useEffect(() => {
    let active = true;
    fetchInstitutionalBoard(5, 'up', 'net').then((result) => { if (active) setBoard(result); }).catch(() => undefined);
    fetchBrokerCoverage().then((result) => { if (active) setBroker(result); }).catch(() => undefined);
    return () => { active = false; };
  }, []);
  const watch = watchlistSourceDates(inputs.watchlist);
  const quarters = (() => {
    const fundamentals = inputs.watchlist?.sources.fundamentals as { fiscal_quarters?: string[] } | undefined;
    const list = Array.isArray(fundamentals?.fiscal_quarters) ? fundamentals!.fiscal_quarters! : [];
    return list[list.length - 1] ?? null;
  })();
  const rankingOfficial = (board?.source ?? '').includes('官方');
  const rows: FreshnessRow[] = [
    { name: '新聞題材雷達', source: 'RSS / MOPS（GitHub Actions 每小時）', asOf: inputs.radar.themeRanking.generated_at, display: formatTaipei(inputs.radar.themeRanking.generated_at), limit: { hours: 8 } },
    { name: '盤前焦點', source: '全球快訊 + TWSE / TAIFEX', asOf: inputs.preMarket?.generated_at ?? null, display: formatTaipei(inputs.preMarket?.generated_at ?? null), limit: { hours: 8 } },
    { name: '三大法人買賣超', source: 'TWSE T86 / TPEX（官方）', asOf: inputs.focus?.flow_as_of ?? null, display: inputs.focus?.flow_as_of ?? '—', limit: { days: 4 } },
    { name: '法人排行（淨買賣超）', source: rankingOfficial ? 'TWSE T86 / TPEX（官方）' : '第三方 tw-institutional-stocker', asOf: board?.date_range?.end ?? null, display: board?.date_range ? `${board.date_range.start} – ${board.date_range.end}` : '—', limit: { days: 4 } },
    { name: '題材 × 法人關注', source: 'theme-focus（雷達 + 官方法人）', asOf: inputs.focus?.generated_at ?? null, display: formatTaipei(inputs.focus?.generated_at ?? null), limit: { hours: 30 } },
    { name: '個股雷達 · 法人', source: '個股雷達評分所用法人資料', asOf: watch.institutional, display: watch.institutional ?? '—', limit: { days: 4 } },
    { name: '個股雷達 · 當沖', source: 'TWSE / TPEX 當沖統計（T+2）', asOf: watch.dayTrading, display: watch.dayTrading ?? '—', limit: { days: 6 } },
    { name: '券商分點', source: '富邦 DJ 分點進出', asOf: broker?.source_updated ?? null, display: broker?.source_updated ?? '—', limit: { days: 4 } },
    { name: '財報基本面', source: 'Goodinfo 季報', asOf: null, display: quarters ?? '—', limit: { days: 9999 } }
  ];
  return (
    <section className="source-table-panel source-freshness-panel">
      <div className="source-table-head"><span>資料新鮮度 · 每頁所用資料的最新日期</span><span>狀態</span></div>
      {rows.map((row) => {
        const state = row.name === '財報基本面' ? (quarters ? 'ok' : 'missing') : rowState(row);
        return (
          <div className="source-row" key={row.name}>
            <strong>{row.name}<small className="source-row-detail">{row.source} · <span className="mono-num">{row.display}</span></small></strong>
            <span className={state === 'ok' ? 'status-up' : state === 'stale' ? 'status-delayed' : 'status-down'}>{state === 'ok' ? '最新' : state === 'stale' ? '延遲' : '缺資料'}</span>
          </div>
        );
      })}
    </section>
  );
};

const siteDetail = (site: SourceSite): string => {
  const parts: string[] = [];
  if (typeof site.items === 'number') parts.push(`${site.items} 則`);
  if (site.not_modified) parts.push('未更新 (304)');
  if (typeof site.success_rate_7d === 'number') {
    parts.push(`7 日成功率 ${Math.round(site.success_rate_7d * 100)}%（${site.runs_7d ?? 0} 次）`);
  }
  if (site.error) parts.push(site.error);
  return parts.join(' · ');
};

const TAIPEI_TIME = new Intl.DateTimeFormat('zh-TW', {
  timeZone: 'Asia/Taipei',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false
});

function formatTaipei(value: string | null): string {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '—' : TAIPEI_TIME.format(parsed);
}

function healthClass(item: SourceHealthItem): string {
  if (item.last_status === 'ok') return 'status-up';
  if (item.last_status === null) return 'status-delayed';
  return 'status-down';
}

function healthLabel(item: SourceHealthItem): string {
  if (item.last_status === 'ok') return '正常';
  if (item.last_status === null) return '尚無紀錄';
  return '失敗';
}

const HealthSection: React.FC<{ data: SourceHealthData }> = ({ data }) => (
  <section className="source-table-panel source-health-panel">
    <div className="source-table-head"><span>高頻抓取（每 5 分鐘）· 最近一次 / 24h 成功率</span><span>狀態</span></div>
    {data.sources.map((item) => {
      const rate = item.runs_24h > 0 ? `${Math.round((item.ok_24h / item.runs_24h) * 100)}%` : '—';
      return (
        <div className="source-row" key={item.source_id} title={item.last_error ?? undefined}>
          <strong>
            {item.name}
            <small className="source-health-meta"> {formatTaipei(item.last_started_at)} · 24h {rate}{item.last_status !== 'ok' && item.last_ok_at ? ` · 上次成功 ${formatTaipei(item.last_ok_at)}` : ''}</small>
          </strong>
          <span className={healthClass(item)}>{healthLabel(item)}</span>
        </div>
      );
    })}
  </section>
);

export const SourceStatus: React.FC<{ data: SourceStatusData; device: DeviceType; freshness?: FreshnessInputs }> = ({ data, freshness }) => {
  const [health, setHealth] = useState<SourceHealthData | null>(null);
  useEffect(() => {
    let active = true;
    fetchSourceHealth().then((result) => { if (active) setHealth(result); });
    return () => { active = false; };
  }, []);
  return (
    <div className="page-content sources-page">
      <header className="page-intro is-compact"><div><span className="page-kicker">SOURCE STATUS · 源狀態</span><h1>源狀態詳情</h1></div><p>先看每頁資料是否最新，再看各新聞源採集狀態。「試行」來源只做抓取與重複率評估，尚未進入題材排行。</p></header>
      {freshness ? <FreshnessSection inputs={freshness} /> : null}
      <section className="source-table-panel"><div className="source-table-head"><span>新聞來源</span><span>狀態</span></div>{data.sites.map((site) => { const ok = site.status === 'ok' || site.status === '正常'; const failed = site.status === 'failed' || site.status === '失敗' || site.status === 'error'; const detail = siteDetail(site); return <div className="source-row" key={site.source_id}><strong>{site.name}{site.trial ? <span className="source-trial-tag"> 試行</span> : null}{detail ? <small className="source-row-detail">{detail}</small> : null}</strong><span className={ok ? 'status-up' : failed ? 'status-down' : 'status-delayed'}>{ok ? '正常' : failed ? '失敗' : '延遲'}</span></div>; })}</section>
      {health && health.sources.length > 0 ? <HealthSection data={health} /> : null}
    </div>
  );
};
