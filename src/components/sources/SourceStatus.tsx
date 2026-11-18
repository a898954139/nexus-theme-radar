import React from 'react';
import { DeviceType, SourceSite, SourceStatusData } from '../../types';

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

export const SourceStatus: React.FC<{ data: SourceStatusData; device: DeviceType }> = ({ data }) => (
  <div className="page-content sources-page">
    <header className="page-intro"><span className="page-kicker">SOURCE STATUS</span><h1>源狀態詳情</h1><div className="gold-rule" /><p>檢查各信源採集是否正常。狀態異常的來源，其題材事件在 72 小時視窗內會被標記，不影響已採集資料。標示「試行」的來源只做抓取與重複率評估，尚未進入題材排行。</p></header>
    <section className="source-table-panel"><div className="source-table-head"><span>來源</span><span>狀態</span></div>{data.sites.map((site) => { const ok = site.status === 'ok' || site.status === '正常'; const failed = site.status === 'failed' || site.status === '失敗' || site.status === 'error'; const detail = siteDetail(site); return <div className="source-row" key={site.source_id}><strong>{site.name}{site.trial ? <span className="source-trial-tag"> 試行</span> : null}{detail ? <small className="source-row-detail">{detail}</small> : null}</strong><span className={ok ? 'status-up' : failed ? 'status-down' : 'status-delayed'}>{ok ? '正常' : failed ? '失敗' : '延遲'}</span></div>; })}</section>
  </div>
);
