import React, { useEffect, useState } from 'react';
import { DeviceType, SourceHealthData, SourceHealthItem, SourceStatusData } from '../../types';
import { fetchSourceHealth } from '../../services/dataService';

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

export const SourceStatus: React.FC<{ data: SourceStatusData; device: DeviceType }> = ({ data }) => {
  const [health, setHealth] = useState<SourceHealthData | null>(null);
  useEffect(() => {
    let active = true;
    fetchSourceHealth().then((result) => { if (active) setHealth(result); });
    return () => { active = false; };
  }, []);
  return (
    <div className="page-content sources-page">
      <header className="page-intro"><span className="page-kicker">SOURCE STATUS</span><h1>源狀態詳情</h1><div className="gold-rule" /><p>檢查各信源採集是否正常。狀態異常的來源，其題材事件在 72 小時視窗內會被標記，不影響已採集資料。</p></header>
      <section className="source-table-panel"><div className="source-table-head"><span>來源</span><span>狀態</span></div>{data.sites.map((site) => { const ok = site.status === 'ok' || site.status === '正常'; const failed = site.status === 'failed' || site.status === '失敗'; return <div className="source-row" key={site.source_id}><strong>{site.name}</strong><span className={ok ? 'status-up' : failed ? 'status-down' : 'status-delayed'}>{ok ? '正常' : failed ? '失敗' : '延遲'}</span></div>; })}</section>
      {health && health.sources.length > 0 ? <HealthSection data={health} /> : null}
    </div>
  );
};
