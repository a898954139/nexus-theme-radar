import { createPortal } from 'react-dom';
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
  nodeTop: number;
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
  const [canvasSelection, setCanvasSelection] = useState<string | 'all' | null>(null);
  useEffect(() => {
    setQuery('');
    setCanvasSelection(null);
  }, [code]);
  useEffect(() => {
    if (!canvasSelection) return undefined;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setCanvasSelection(null);
    };
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', closeOnEscape);
    };
  }, [canvasSelection]);
  const isMobile = device === 'mobile';
  const rootWidth = isMobile ? 150 : 190;
  const branchWidth = isMobile ? 180 : 216;
  const horizontalGap = isMobile ? 70 : 110;
  const x0 = 20;
  const x1 = x0 + rootWidth + horizontalGap;
  const canvasWidth = x1 + branchWidth + 20;

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
    const items: BrokerLayout[] = visibleBranches.map(({ branch }) => {
      const nodeTop = cursor;
      const item = {
        branch,
        nodeTop,
      };
      cursor += 62 + 12;
      return item;
    });
    return {
      items,
      height: Math.max(isMobile ? 460 : 520, cursor + 20),
    };
  }, [isMobile, visibleBranches]);

  const summary = data?.summary ?? {
    buy: 0,
    sell: 0,
    net: data?.brokers.reduce((sum, branch) => sum + branch.net, 0) ?? 0,
    broker_count: data?.brokers.length ?? 0,
  };
  const rootY = layout.height / 2 - 63;
  const canvasBranches = useMemo(() => {
    if (!data || !canvasSelection) return [];
    if (canvasSelection === 'all') return visibleBranches.map(({ branch, children }) => ({ ...branch, stocks: children }));
    const branch = data.brokers.find((item) => item.id === canvasSelection);
    if (!branch) return [];
    const match = branchMatches(branch, query);
    return [{ ...branch, stocks: match.branch || !query.trim() ? branch.stocks : match.childCodes }];
  }, [canvasSelection, data, query, visibleBranches]);

  const openCanvas = (selection: string | 'all') => setCanvasSelection(selection);
  const goToStock = (childCode: string) => {
    setCanvasSelection(null);
    onGoStock(childCode, undefined, 'broker');
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
        <div className="broker-map-actions"><button type="button" onClick={() => openCanvas('all')}>全部展開</button><button type="button" onClick={() => setCanvasSelection(null)}>全部收合</button></div>
        <span className="broker-map-count">{visibleBranches.length} / {data.brokers.length} 家分點 · <b className="positive">買超 {data.brokers.filter((branch) => branch.net > 0).length}</b> · <b className="negative">賣超 {data.brokers.filter((branch) => branch.net < 0).length}</b></span>
      </div>
      <div className="broker-map-scroll">
        <div className="broker-map-canvas" style={{ height: layout.height, width: canvasWidth }}>
        <svg className="broker-map-links" width={canvasWidth} height={layout.height} aria-hidden="true">
          {layout.items.map((item) => {
            const branchY = item.nodeTop + 31;
            const rootPath = `M ${x0 + rootWidth} ${rootY + 63} C ${x0 + rootWidth + 55} ${rootY + 63}, ${x1 - 55} ${branchY}, ${x1} ${branchY}`;
            return <g key={item.branch.id}><path d={rootPath} className={item.branch.net >= 0 ? 'broker-link-positive' : 'broker-link-negative'} /></g>;
          })}
        </svg>
        <div className="broker-map-node broker-map-root" style={{ left: x0, top: rootY, width: rootWidth }}>
          <span className="page-kicker">STOCK</span><strong className="mono-num">{code} <em>{name}</em></strong><i /><span>分點合計 <b className={summary.net >= 0 ? 'positive' : 'negative'}>{formatLots(summary.net)}</b></span><small>分點家數 {summary.broker_count}</small>
        </div>
        {layout.items.map((item) => <React.Fragment key={item.branch.id}>
          <button type="button" aria-expanded={canvasSelection === item.branch.id} className={`broker-map-node broker-map-branch ${canvasSelection === item.branch.id ? 'is-open' : ''}`} style={{ left: x1, top: item.nodeTop, width: branchWidth }} onClick={() => openCanvas(item.branch.id)}>
            <span><b>{item.branch.name}</b><small>{canvasSelection === item.branch.id ? '−' : '+'}</small></span><strong className={item.branch.net >= 0 ? 'positive' : 'negative'}>{formatLots(item.branch.net)}</strong><em>占比 {item.branch.ratio.toFixed(1)}% · 查看標的</em>
          </button>
        </React.Fragment>)}
        </div>
      </div>
      {canvasSelection ? createPortal(
        <div className="broker-child-canvas-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setCanvasSelection(null); }}>
          <section className={`broker-child-canvas ${canvasSelection === 'all' ? 'is-all' : ''}`} role="dialog" aria-modal="true" aria-labelledby="broker-child-canvas-title">
            <header className="broker-child-canvas-header">
              <div>
                <span className="page-kicker">BROKER STOCKS · 同時進出標的</span>
                <h2 id="broker-child-canvas-title">{canvasSelection === 'all' ? '全部分點的主攻標的' : `${canvasBranches[0]?.name ?? '券商分點'} · 買賣標的`}</h2>
                <p>內容數量較多，請在此畫布內向下捲動；點擊標的可直接查看個股券商分點。</p>
              </div>
              <button type="button" className="broker-child-canvas-close" aria-label="關閉主攻標的畫布" onClick={() => setCanvasSelection(null)}>×</button>
            </header>
            <div className="broker-child-canvas-scroll">
              {canvasBranches.map((branch) => <article className="broker-child-canvas-group" key={branch.id}>
                {canvasSelection === 'all' ? <div className="broker-child-canvas-group-heading"><strong>{branch.name}</strong><span className={branch.net >= 0 ? 'positive' : 'negative'}>{formatLots(branch.net)} · {branch.stocks.length} 檔</span></div> : null}
                <div className="broker-child-canvas-list">
                  {branch.stocks.length ? branch.stocks.map(([childCode, childName, childNet]) => <button type="button" className={`broker-child-canvas-item ${childNet >= 0 ? 'is-positive' : 'is-negative'}`} key={`${branch.id}-${childCode}`} onClick={() => goToStock(childCode)}><b className="mono-num">{childCode}</b><span>{childName}</span><strong className="mono-num">{formatLots(childNet)}</strong></button>) : <span className="muted">此分點沒有其他標的資料。</span>}
                </div>
              </article>)}
            </div>
            <footer className="broker-child-canvas-footer">共 {canvasBranches.reduce((sum, branch) => sum + branch.stocks.length, 0)} 檔標的 · 分點資料源自公開彙總</footer>
          </section>
        </div>,
        document.body,
      ) : null}
      <p className="broker-source-note">分點資料源自公開券商分點進出彙總，僅供技術展示。搜尋只過濾分點層與其子標的。</p>
    </section>
  );
};
