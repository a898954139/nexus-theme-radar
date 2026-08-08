import React, { useEffect, useMemo, useState } from 'react';
import { fetchInstitutionalFlows, fetchInstitutionalRankings } from '../../services/dataService';
import { DeviceType, FlowDirection, FlowMetric, FlowView, InstitutionalFlowItem, InstitutionalRankingEntry, RadarData } from '../../types';

interface InstitutionalFlowsProps {
  data: RadarData;
  device: DeviceType;
  onGoStock: (code: string, exchange?: string, tab?: 'fundamentals' | 'flows') => void;
}

function formatValue(value: number, unit = '') {
  if (!Number.isFinite(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toLocaleString('en-US', { maximumFractionDigits: 2 })}${unit}`;
}

function metricValue(entry: InstitutionalRankingEntry, metric: FlowMetric) {
  return metric === 'net' ? entry.change : entry.three_inst_ratio;
}

const ControlGroup: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="flow-control-group"><span className="field-label">{label}</span><div className="flow-control-options">{children}</div></div>
);

const FlowControls: React.FC<{
  metric: FlowMetric;
  setMetric: (value: FlowMetric) => void;
  days: number;
  setDays: (value: number) => void;
  direction: FlowDirection;
  setDirection: (value: FlowDirection) => void;
  hideEtf: boolean;
  setHideEtf: (value: boolean) => void;
  view: FlowView;
  setView: (value: FlowView) => void;
}> = ({ metric, setMetric, days, setDays, direction, setDirection, hideEtf, setHideEtf, view, setView }) => (
  <section className="flow-controls">
    <div className="flow-controls-row">
      <ControlGroup label="統計指標"><button className={metric === 'net' ? 'is-selected' : ''} type="button" onClick={() => setMetric('net')}>資金淨流入</button><button className={metric === 'ratio' ? 'is-selected' : ''} type="button" onClick={() => setMetric('ratio')}>持股比重變化</button></ControlGroup>
      <ControlGroup label="統計天數">{[5, 10, 20, 30].map((value) => <button className={days === value ? 'is-selected' : ''} key={value} type="button" onClick={() => setDays(value)}>{value} 日</button>)}</ControlGroup>
    </div>
    <div className="flow-controls-row">
      <ControlGroup label="流向方向"><button className={direction === 'up' ? 'is-selected' : ''} type="button" onClick={() => setDirection('up')}>買超 / 增加</button><button className={direction === 'down' ? 'is-selected' : ''} type="button" onClick={() => setDirection('down')}>賣超 / 減少</button></ControlGroup>
      <label className="flow-etf-toggle"><input type="checkbox" checked={hideEtf} onChange={(event) => setHideEtf(event.target.checked)} /><span className="toggle-track" /><span>隱藏 ETF</span></label>
      <ControlGroup label="檢視方式"><button className={view === 'bars' ? 'is-selected' : ''} type="button" onClick={() => setView('bars')}>分歧橫條</button><button className={view === 'matrix' ? 'is-selected' : ''} type="button" onClick={() => setView('matrix')}>熱力圖</button><button className={view === 'table' ? 'is-selected' : ''} type="button" onClick={() => setView('table')}>明細表</button></ControlGroup>
    </div>
  </section>
);

const FlowBarsView: React.FC<{ entries: InstitutionalRankingEntry[]; metric: FlowMetric; expandedCode: string | null; setExpandedCode: (code: string | null) => void; loadBreakdown: (code: string, exchange?: string) => Promise<InstitutionalFlowItem[]>; }> = ({ entries, metric, expandedCode, setExpandedCode, loadBreakdown }) => {
  const [breakdowns, setBreakdowns] = useState<Record<string, InstitutionalFlowItem[]>>({});
  const [loadingCode, setLoadingCode] = useState<string | null>(null);
  const maxValue = Math.max(...entries.map((entry) => Math.abs(metricValue(entry, metric))), 1);
  const toggleEntry = async (entry: InstitutionalRankingEntry) => {
    if (expandedCode === entry.code) {
      setExpandedCode(null);
      return;
    }
    setExpandedCode(entry.code);
    if (breakdowns[entry.code]) return;
    setLoadingCode(entry.code);
    const flows = await loadBreakdown(entry.code, entry.exchange);
    setBreakdowns((current) => ({ ...current, [entry.code]: flows }));
    setLoadingCode((current) => current === entry.code ? null : current);
  };
  return (
    <div className="flow-board">
      <div className="flow-board-title"><span className="page-kicker">RANKINGS BOARD · {entries.length} 筆</span><span className="section-note">買超向右 · 賣超向左</span></div>
      <div className="flow-bars-head"><span>#</span><span>代號／名稱</span><span>賣超</span><span>買超</span><span>合計</span></div>
      {entries.map((entry, index) => {
        const value = metricValue(entry, metric);
        const width = `${Math.max(3, Math.abs(value) / maxValue * 100)}%`;
        const expanded = expandedCode === entry.code;
        return (
          <article className={`flow-bar-row ${expanded ? 'is-expanded' : ''}`} key={entry.instrument_id}>
            <button className="flow-bar-main" type="button" onClick={() => void toggleEntry(entry)}>
              <span className="rank-num mono-num">{String(index + 1).padStart(2, '0')}</span>
              <span className="flow-stock-label"><b className="mono-num">{entry.code}</b><span>{entry.name}</span></span>
              <span className="zero-axis"><span className={`bar-fill ${value >= 0 ? 'positive-fill' : 'negative-fill'}`} style={{ width }} /></span>
              <strong className={`flow-total mono-num ${value >= 0 ? 'positive' : 'negative'}`}>{formatValue(value, metric === 'ratio' ? ' pp' : '')}</strong>
            </button>
            {expanded ? <div className="flow-breakdown">{loadingCode === entry.code ? <span>讀取逐日拆解…</span> : (breakdowns[entry.code]?.[0] ? <><span>外資 <b className={breakdowns[entry.code][0].foreign_net >= 0 ? 'positive mono-num' : 'negative mono-num'}>{formatValue(breakdowns[entry.code][0].foreign_net)}</b></span><span>投信 <b className={breakdowns[entry.code][0].trust_net >= 0 ? 'positive mono-num' : 'negative mono-num'}>{formatValue(breakdowns[entry.code][0].trust_net)}</b></span><span>自營商 <b className={breakdowns[entry.code][0].dealer_net >= 0 ? 'positive mono-num' : 'negative mono-num'}>{formatValue(breakdowns[entry.code][0].dealer_net)}</b></span></> : <span>此標的尚無逐日拆解資料</span>)}</div> : null}
          </article>
        );
      })}
    </div>
  );
};

const FlowMatrixView: React.FC<{ symbol: string; flows: InstitutionalFlowItem[]; metric: FlowMetric }> = ({ symbol, flows, metric }) => {
  const columns: Array<[keyof InstitutionalFlowItem, string]> = [['foreign_net', '外資'], ['trust_net', '投信'], ['dealer_net', '自營商'], ['total_net', '合計']];
  const max = Math.max(...flows.flatMap((flow) => columns.map(([key]) => Math.abs(flow[key] as number))), 1);
  return (
    <div className="flow-matrix-panel">
      <div className="flow-board-title"><span className="page-kicker">{symbol || '—'} · DATE × INSTITUTION</span><span className="section-note">{metric === 'net' ? '賣超 — 買超' : '持股比重資料未提供'}</span></div>
      {metric === 'ratio' ? <p className="no-results">現有資料 contract 沒有逐日持股比重序列；此檢視保留空值，不以示意值補齊。</p> : (
        <div className="matrix-scroll"><table className="flow-matrix"><thead><tr><th>日期</th>{columns.map(([, label]) => <th key={label}>{label}</th>)}</tr></thead><tbody>{flows.slice(0, 5).map((flow) => <tr key={flow.date}><th className="mono-num">{flow.date}</th>{columns.map(([key]) => { const value = flow[key] as number; return <td className={value >= 0 ? 'matrix-positive' : 'matrix-negative'} key={key} style={{ '--cell-alpha': 0.12 + Math.min(0.76, Math.abs(value) / max * 0.76) } as React.CSSProperties}>{formatValue(value)}</td>; })}</tr>)}</tbody></table></div>
      )}
      <div className="matrix-legend"><span>賣超</span><i className="legend-negative" /><i className="legend-neutral" /><i className="legend-positive" /><span>買超</span></div>
    </div>
  );
};

const FlowTableView: React.FC<{ entries: InstitutionalRankingEntry[]; metric: FlowMetric; onGoStock: InstitutionalFlowsProps['onGoStock'] }> = ({ entries, metric, onGoStock }) => (
  <div className="flow-table-panel"><div className="flow-board-title"><span className="page-kicker">DETAIL TABLE</span><span className="section-note">所有數值來自公開彙總</span></div><div className="table-scroll"><table className="flow-detail-table"><thead><tr><th>代號</th><th>名稱</th><th>外資</th><th>投信</th><th>自營商</th><th>合計</th></tr></thead><tbody>{entries.map((entry) => <tr key={entry.instrument_id}><th><button type="button" onClick={() => onGoStock(entry.code, entry.exchange)} className="stock-code-link mono-num">{entry.code}</button></th><td>{entry.name}</td><td className="mono-num">—</td><td className="mono-num">—</td><td className="mono-num">—</td><td className={`mono-num ${entry.change >= 0 ? 'positive' : 'negative'}`}>{metric === 'net' ? formatValue(entry.change) : `${entry.three_inst_ratio.toFixed(2)}%`}</td></tr>)}</tbody></table></div></div>
);

export const InstitutionalFlows: React.FC<InstitutionalFlowsProps> = ({ data, device, onGoStock }) => {
  const defaultLookup = useMemo(() => data.themeRanking.themes.flatMap((theme) => theme.direct_mentions).find((instrument) => instrument.symbol)?.symbol ?? '', [data.themeRanking.themes]);
  const [metric, setMetric] = useState<FlowMetric>('net');
  const [days, setDays] = useState(5);
  const [direction, setDirection] = useState<FlowDirection>('up');
  const [hideEtf, setHideEtf] = useState(true);
  const [view, setView] = useState<FlowView>('bars');
  const [expandedCode, setExpandedCode] = useState<string | null>(null);
  const [entries, setEntries] = useState<InstitutionalRankingEntry[]>([]);
  const [stockFlows, setStockFlows] = useState<InstitutionalFlowItem[]>([]);
  const [lookup, setLookup] = useState(defaultLookup);

  useEffect(() => {
    let active = true;
    fetchInstitutionalRankings(days, direction).then((result) => { if (active) setEntries(result); });
    return () => { active = false; };
  }, [days, direction]);

  useEffect(() => {
    let active = true;
    if (!lookup) return () => { active = false; };
    fetchInstitutionalFlows(lookup).then((result) => { if (active) setStockFlows(result); });
    return () => { active = false; };
  }, [lookup]);

  const visibleEntries = useMemo(() => entries.filter((entry) => !hideEtf || !entry.is_etf), [entries, hideEtf]);

  return (
    <div className="page-content flows-page">
      <header className="page-intro"><span className="page-kicker">INSTITUTIONAL MONEY-FLOW RANKINGS</span><h1>三大法人資金流向排行</h1><div className="gold-rule" /><p>動態追蹤台股上市櫃的三大法人籌碼買賣超與持股比重變化。數據源自公開交易資訊彙整整理。</p></header>
      <FlowControls metric={metric} setMetric={setMetric} days={days} setDays={setDays} direction={direction} setDirection={setDirection} hideEtf={hideEtf} setHideEtf={setHideEtf} view={view} setView={setView} />
      {view === 'bars' ? <FlowBarsView entries={visibleEntries} metric={metric} expandedCode={expandedCode} setExpandedCode={setExpandedCode} loadBreakdown={fetchInstitutionalFlows} /> : null}
      {view === 'matrix' ? <FlowMatrixView symbol={lookup} flows={stockFlows} metric={metric} /> : null}
      {view === 'table' ? <FlowTableView entries={visibleEntries} metric={metric} onGoStock={onGoStock} /> : null}
      <section className="flow-lookup"><div><span className="page-kicker">STOCK FLOW LOOKUP</span><strong>查詢個股法人資金流向</strong></div><form onSubmit={(event) => { event.preventDefault(); onGoStock(lookup, undefined, 'flows'); }}><input aria-label="輸入個股代號查詢籌碼" value={lookup} onChange={(event) => setLookup(event.target.value)} /><button type="submit">查詢籌碼 →</button></form></section>
      <p className="disclaimer">本頁資訊整理自公開交易資料，僅供技術與數據呈現展示，不構成任何買賣投資建議。</p>
    </div>
  );
};
