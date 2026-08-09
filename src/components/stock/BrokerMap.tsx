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

interface VisibleBranch {
  branch: BrokerMapBranch;
  children: BrokerMapBranch['stocks'];
}

interface BrokerLayout extends VisibleBranch {
  branchTop: number;
  childTops: number[];
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
  const [openBranches, setOpenBranches] = useState<Set<string>>(new Set());
  const isMobile = device === 'mobile';
  const rootWidth = isMobile ? 150 : 190;
  const branchWidth = isMobile ? 180 : 216;
  const childWidth = isMobile ? 170 : 200;
  const horizontalGap = isMobile ? 70 : 110;
  const x0 = 20;
  const x1 = x0 + rootWidth + horizontalGap;
  const x2 = x1 + branchWidth + horizontalGap;
  const canvasWidth = x2 + childWidth + 20;

  useEffect(() => {
    setQuery('');
    setOpenBranches(new Set());
  }, [code]);

  const visibleBranches = useMemo<VisibleBranch[]>(() => {
    if (!data) return [];
    return data.brokers.flatMap((branch) => {
      const match = branchMatches(branch, query);
      if (!match.branch && !match.childCodes.length) return [];
      return [{ branch, children: match.branch || !query.trim() ? branch.stocks : match.childCodes }];
    });
  }, [data, query]);

  const layout = useMemo(() => {
    const branchHeight = 62;
    const childHeight = 46;
    const childGap = 12;
    let cursor = 20;
    const items: BrokerLayout[] = visibleBranches.map((item) => {
      const isOpen = openBranches.has(item.branch.id) && item.children.length > 0;
      const childBlockHeight = item.children.length * childHeight + Math.max(0, item.children.length - 1) * childGap;
      const blockHeight = isOpen ? branchHeight + childGap + childBlockHeight : branchHeight;
      const branchTop = cursor;
      const childStart = cursor + branchHeight + childGap;
      const childTops = isOpen ? item.children.map((_, index) => childStart + index * (childHeight + childGap)) : [];
      cursor += blockHeight + (isOpen ? 6 : 12);
      return { ...item, branchTop, childTops };
    });
    return {
      items,
      height: Math.max(isMobile ? 460 : 520, cursor + 20),
    };
  }, [isMobile, openBranches, visibleBranches]);

  const summary = data?.summary ?? {
    buy: 0,
    sell: 0,
    net: data?.brokers.reduce((sum, branch) => sum + branch.net, 0) ?? 0,
    broker_count: data?.brokers.length ?? 0,
  };
  const rootY = layout.height / 2 - 63;

  const toggleBranch = (branchId: string) => {
    setOpenBranches((current) => {
      const next = new Set(current);
      if (next.has(branchId)) next.delete(branchId);
      else next.add(branchId);
      return next;
    });
  };

  if (loading || !data || !data.brokers.length) return <MapEmpty loading={loading} />;

  return (
    <section className="broker-map-section">
      <div className="broker-map-heading">
        <div><span className="page-kicker">BROKER MAP · 券商分點</span><p>從這檔股票反查背後的券商分點：點分點查看它同時進出的其他標的。</p></div>
        <span className="broker-map-unit">單位：張</span>
      </div>
      <div className="broker-map-toolbar">
        <label><span className="sr-only">搜尋券商或標的</span><input name="broker-map-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜尋分點或標的…" /></label>
        <div className="broker-map-actions">
          <button type="button" onClick={() => setOpenBranches(new Set(visibleBranches.map(({ branch }) => branch.id)))}>全部展開</button>
          <button type="button" onClick={() => setOpenBranches(new Set())}>全部收合</button>
        </div>
        <span className="broker-map-count">{visibleBranches.length} / {data.brokers.length} 家分點 · <b className="positive">買超 {data.brokers.filter((branch) => branch.net > 0).length}</b> · <b className="negative">賣超 {data.brokers.filter((branch) => branch.net < 0).length}</b></span>
      </div>
      <div className="broker-map-scroll">
        <div className="broker-map-canvas" style={{ height: layout.height, width: canvasWidth }}>
          <svg className="broker-map-links" width={canvasWidth} height={layout.height} aria-hidden="true">
            {layout.items.map((item) => {
              const branchY = item.branchTop + 31;
              const rootPath = `M ${x0 + rootWidth} ${rootY + 63} C ${x0 + rootWidth + 55} ${rootY + 63}, ${x1 - 55} ${branchY}, ${x1} ${branchY}`;
              return (
                <g key={item.branch.id}>
                  <path d={rootPath} className={item.branch.net >= 0 ? 'broker-link-positive' : 'broker-link-negative'} />
                  {item.childTops.map((childTop, index) => {
                    const childY = childTop + 23;
                    const childPath = `M ${x1 + branchWidth} ${branchY} C ${x1 + branchWidth + 55} ${branchY}, ${x2 - 55} ${childY}, ${x2} ${childY}`;
                    return <path key={`${item.branch.id}-${item.children[index][0]}`} d={childPath} className={item.children[index][2] >= 0 ? 'broker-link-positive' : 'broker-link-negative'} />;
                  })}
                </g>
              );
            })}
          </svg>
          <div className="broker-map-node broker-map-root" style={{ left: x0, top: rootY, width: rootWidth }}>
            <span className="page-kicker">STOCK</span><strong className="mono-num">{code} <em>{name}</em></strong><i /><span>分點合計 <b className={summary.net >= 0 ? 'positive' : 'negative'}>{formatLots(summary.net)}</b></span><small>分點家數 {summary.broker_count}</small>
          </div>
          {layout.items.map((item) => {
            const isOpen = openBranches.has(item.branch.id) && item.children.length > 0;
            return (
              <React.Fragment key={item.branch.id}>
                <button type="button" aria-expanded={isOpen} className={`broker-map-node broker-map-branch ${isOpen ? 'is-open' : ''}`} style={{ left: x1, top: item.branchTop, width: branchWidth }} onClick={() => toggleBranch(item.branch.id)}>
                  <span><b>{item.branch.name}</b><small>{isOpen ? '−' : '+'}</small></span><strong className={item.branch.net >= 0 ? 'positive' : 'negative'}>{formatLots(item.branch.net)}</strong><em>占比 {item.branch.ratio.toFixed(1)}% · {isOpen ? '收合標的' : '查看標的'}</em>
                </button>
                {isOpen ? item.children.map(([childCode, childName, childNet], index) => (
                  <button type="button" className={`broker-map-node broker-map-child ${childNet >= 0 ? 'is-positive' : 'is-negative'}`} style={{ left: x2, top: item.childTops[index], width: childWidth }} key={`${item.branch.id}-${childCode}`} onClick={() => onGoStock(childCode, undefined, 'broker')}>
                    <b className="mono-num">{childCode}</b><span>{childName}</span><strong className="mono-num">{formatLots(childNet)}</strong>
                  </button>
                )) : null}
              </React.Fragment>
            );
          })}
        </div>
      </div>
      <p className="broker-source-note">分點資料源自公開券商分點進出彙總，僅供技術展示。搜尋只過濾分點層與其子標的。</p>
    </section>
  );
};
