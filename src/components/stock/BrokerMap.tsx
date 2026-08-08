import React, { useEffect, useMemo, useState } from 'react';
import { BrokerMapBranch, BrokerMapData, DeviceType, StockTab } from '../../types';

interface BrokerMapProps {
  code: string;
  name: string;
  device: DeviceType;
  data: BrokerMapData | null;
  loading?: boolean;
  onGoStock: (code: string, exchange?: string, tab?: StockTab) => void;
}

interface BrokerLayout {
  branch: BrokerMapBranch;
  children: Array<[string, string, number]>;
  blockTop: number;
  blockHeight: number;
  nodeTop: number;
  childTops: number[];
  open: boolean;
}

function formatLots(value: number) {
  return `${value >= 0 ? '+' : ''}${value.toLocaleString('en-US')}`;
}

function branchMatches(branch: BrokerMapBranch, query: string) {
  if (!query.trim()) return { branch: true, childCodes: branch.stocks };
  const needle = query.trim().toLowerCase();
  const branchMatch = branch.name.toLowerCase().includes(needle);
  const childCodes = branch.stocks.filter(([code, name]) => `${code} ${name}`.toLowerCase().includes(needle));
  return { branch: branchMatch, childCodes };
}

const MapEmpty: React.FC<{ loading?: boolean }> = ({ loading }) => (
  <div className="broker-map-empty"><strong>{loading ? 'LOADING BROKER DATA' : 'NO BROKER DATA'}</strong><span>{loading ? '讀取公開券商分點彙總…' : '此標的目前沒有可用的券商分點資料。'}</span></div>
);

export const BrokerMap: React.FC<BrokerMapProps> = ({ code, name, device, data, loading = false, onGoStock }) => {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState<Set<string>>(new Set());
  useEffect(() => {
    setQuery('');
    setOpen(new Set());
  }, [code]);
  const isMobile = device === 'mobile';
  const rootWidth = isMobile ? 150 : 190;
  const branchWidth = isMobile ? 180 : 216;
  const childWidth = isMobile ? 170 : 200;
  const horizontalGap = isMobile ? 70 : 110;
  const x0 = 20;
  const x1 = x0 + rootWidth + horizontalGap;
  const x2 = x1 + branchWidth + horizontalGap;
  const canvasWidth = x2 + childWidth + 20;

  const visibleBranches = useMemo(() => {
    if (!data) return [];
    return data.brokers.flatMap((branch) => {
      const match = branchMatches(branch, query);
      if (!match.branch && !match.childCodes.length) return [];
      return [{ branch, children: match.branch || !query.trim() ? branch.stocks : match.childCodes }];
    });
  }, [data, query]);

  const layout = useMemo(() => {
    let cursor = 20;
    const items: BrokerLayout[] = visibleBranches.map(({ branch, children }) => {
      const isSearchOpen = Boolean(query.trim() && children.length && branchMatches(branch, query).childCodes.length);
      const isOpen = open.has(branch.id) || isSearchOpen;
      const childHeight = children.length * 46 + Math.max(0, children.length - 1) * 12;
      const blockHeight = isOpen ? Math.max(62, childHeight) : 62;
      const nodeTop = cursor + (blockHeight - 62) / 2;
      const childStart = cursor + (blockHeight - childHeight) / 2;
      const item = {
        branch,
        children: isOpen ? children : [],
        blockTop: cursor,
        blockHeight,
        nodeTop,
        childTops: isOpen ? children.map((_, index) => childStart + index * 58) : [],
        open: isOpen,
      };
      cursor += blockHeight + (isOpen ? 18 : 12);
      return item;
    });
    return {
      items,
      height: Math.max(isMobile ? 460 : 520, cursor + 20),
    };
  }, [isMobile, open, query, visibleBranches]);

  const summary = data?.summary ?? {
    buy: 0,
    sell: 0,
    net: data?.brokers.reduce((sum, branch) => sum + branch.net, 0) ?? 0,
    broker_count: data?.brokers.length ?? 0,
  };
  const rootY = layout.height / 2 - 63;
  const toggleAll = (value: boolean) => setOpen(value ? new Set(visibleBranches.map(({ branch }) => branch.id)) : new Set());

  if (loading || !data || !data.brokers.length) return <MapEmpty loading={loading} />;

  return (
    <section className="broker-map-section">
      <div className="broker-map-heading">
        <div><span className="page-kicker">BROKER MAP · 券商分點</span><p>從這檔股票反查背後的券商分點：展開分點查看它同時進出的其他標的。</p></div>
        <span className="broker-map-unit">單位：張</span>
      </div>
      <div className="broker-map-toolbar">
        <label><span className="sr-only">搜尋券商或標的</span><input name="broker-map-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜尋分點或標的…" /></label>
        <div className="broker-map-actions"><button type="button" onClick={() => toggleAll(true)}>全部展開</button><button type="button" onClick={() => toggleAll(false)}>全部收合</button></div>
        <span className="broker-map-count">{visibleBranches.length} / {data.brokers.length} 家分點 · <b className="positive">買超 {data.brokers.filter((branch) => branch.net > 0).length}</b> · <b className="negative">賣超 {data.brokers.filter((branch) => branch.net < 0).length}</b></span>
      </div>
      <div className="broker-map-scroll">
        <div className="broker-map-canvas" style={{ height: layout.height, width: canvasWidth }}>
        <svg className="broker-map-links" width={canvasWidth} height={layout.height} aria-hidden="true">
          {layout.items.map((item) => {
            const branchY = item.nodeTop + 31;
            const rootPath = `M ${x0 + rootWidth} ${rootY + 63} C ${x0 + rootWidth + 55} ${rootY + 63}, ${x1 - 55} ${branchY}, ${x1} ${branchY}`;
            return <g key={item.branch.id}><path d={rootPath} className={item.branch.net >= 0 ? 'broker-link-positive' : 'broker-link-negative'} />{item.open ? item.childTops.map((top, index) => { const childY = top + 23; const childPath = `M ${x1 + branchWidth} ${branchY} C ${x1 + branchWidth + 55} ${branchY}, ${x2 - 55} ${childY}, ${x2} ${childY}`; return <path key={`${item.branch.id}-${index}`} d={childPath} className={item.children[index][2] >= 0 ? 'broker-link-positive broker-link-child' : 'broker-link-negative broker-link-child'} />; }) : null}</g>;
          })}
        </svg>
        <div className="broker-map-node broker-map-root" style={{ left: x0, top: rootY, width: rootWidth }}>
          <span className="page-kicker">STOCK</span><strong className="mono-num">{code} <em>{name}</em></strong><i /><span>分點合計 <b className={summary.net >= 0 ? 'positive' : 'negative'}>{formatLots(summary.net)}</b></span><small>分點家數 {summary.broker_count}</small>
        </div>
        {layout.items.map((item) => <React.Fragment key={item.branch.id}>
          <button type="button" className={`broker-map-node broker-map-branch ${item.open ? 'is-open' : ''}`} style={{ left: x1, top: item.nodeTop, width: branchWidth }} onClick={() => setOpen((current) => { const next = new Set(current); if (next.has(item.branch.id)) next.delete(item.branch.id); else next.add(item.branch.id); return next; })}>
            <span><b>{item.branch.name}</b><small>{item.open ? '−' : '+'}</small></span><strong className={item.branch.net >= 0 ? 'positive' : 'negative'}>{formatLots(item.branch.net)}</strong><em>占比 {item.branch.ratio.toFixed(1)}%</em>
          </button>
          {item.open ? item.children.map(([childCode, childName, childNet], index) => <button type="button" className={`broker-map-node broker-map-child ${childNet >= 0 ? 'is-positive' : 'is-negative'}`} style={{ left: x2, top: item.childTops[index], width: childWidth }} key={`${item.branch.id}-${childCode}`} onClick={() => onGoStock(childCode, undefined, 'broker')}><b className="mono-num">{childCode}</b><span>{childName}</span><strong className="mono-num">{formatLots(childNet)}</strong></button>) : null}
        </React.Fragment>)}
        </div>
      </div>
      <p className="broker-source-note">分點資料源自公開券商分點進出彙總，僅供技術展示。搜尋只過濾分點層與其子標的。</p>
    </section>
  );
};
