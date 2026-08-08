import React from 'react';
import { DeviceType, SourceStatusData } from '../../types';

export const SourceStatus: React.FC<{ data: SourceStatusData; device: DeviceType }> = ({ data }) => (
  <div className="page-content sources-page">
    <header className="page-intro"><span className="page-kicker">SOURCE STATUS</span><h1>源狀態詳情</h1><div className="gold-rule" /><p>檢查各信源採集是否正常。狀態異常的來源，其題材事件在 72 小時視窗內會被標記，不影響已採集資料。</p></header>
    <section className="source-table-panel"><div className="source-table-head"><span>來源</span><span>狀態</span></div>{data.sites.map((site) => { const ok = site.status === 'ok' || site.status === '正常'; const failed = site.status === 'failed' || site.status === '失敗'; return <div className="source-row" key={site.source_id}><strong>{site.name}</strong><span className={ok ? 'status-up' : failed ? 'status-down' : 'status-delayed'}>{ok ? '正常' : failed ? '失敗' : '延遲'}</span></div>; })}</section>
  </div>
);
