import React, { useRef, useEffect, useMemo, useState } from 'react';
import { fetchInstitutionalBoard, fetchInstitutionalFlows } from '../../services/dataService';
import { formatLots, rankedFocusThemes, shortDate } from '../common/ThemeFocusBoard';
import { DivergingBars, PageHero, PageTabs, scrollToRef } from '../common/FeedKit';
import { SectionHead } from '../home/FeedBlocks';
import { ThemeFlowPanel } from './ThemeFlowPanel';
import { BrokerFlows } from './BrokerFlows';
import { DeviceType, FlowDirection, FlowMetric, FlowView, InstitutionalFlowItem, InstitutionalRankingBoard, InstitutionalRankingEntry, RadarData, StockTab, ThemeFocusData } from '../../types';

interface InstitutionalFlowsProps {
  data: RadarData;
  focus?: ThemeFocusData | null;
  device: DeviceType;
  onGoStock: (code: string, exchange?: string, tab?: StockTab) => void;
  refreshKey: number;
}

const DEFAULT_VISIBLE_ROWS = 10;

/** instrument_id -> radar theme names, from the full momentum membership. */
function themeMembership(data: RadarData): Map<string, string[]> {
  const map = new Map<string, string[]>();
  const add = (instrumentId: string, name: string) => {
    const names = map.get(instrumentId) ?? [];
    if (!names.includes(name)) names.push(name);
    map.set(instrumentId, names);
  };
  data.momentumLatest.themes.forEach((theme) => {
    [...theme.direct_symbols, ...theme.related_symbols].forEach((item) => add(item.instrument_id, theme.name_zh));
  });
  data.themeRanking.themes.forEach((theme) => {
    [...theme.direct_mentions, ...theme.supply_chain_candidates].forEach((item) => add(item.instrument_id, theme.name_zh));
  });
  return map;
}

function themeMemberIds(data: RadarData, themeId: string): Set<string> {
  const ids = new Set<string>();
  data.momentumLatest.themes.filter((theme) => theme.theme_id === themeId).forEach((theme) => {
    [...theme.direct_symbols, ...theme.related_symbols].forEach((item) => ids.add(item.instrument_id));
  });
  data.themeRanking.themes.filter((theme) => theme.theme_id === themeId).forEach((theme) => {
    [...theme.direct_mentions, ...theme.supply_chain_candidates].forEach((item) => ids.add(item.instrument_id));
  });
  return ids;
}

function boardNote(board: InstitutionalRankingBoard | null): string {
  if (!board) return '';
  const range = board.date_range ? `${shortDate(board.date_range.start)}–${shortDate(board.date_range.end)}` : '區間未提供';
  const official = (board.source ?? '').includes('官方');
  return `${official ? '官方' : '第三方'} · ${range}`;
}

function formatValue(value: number, unit = '') {
  if (!Number.isFinite(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toLocaleString('en-US', { maximumFractionDigits: 2 })}${unit}`;
}

function isFiniteNumber(value: number | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function hasRankedNetBreakdown(entry: InstitutionalRankingEntry) {
  return [entry.foreign, entry.trust, entry.dealer, entry.total].every(isFiniteNumber);
}

function metricValue(entry: InstitutionalRankingEntry, metric: FlowMetric) {
  return metric === 'net' ? entry.total ?? Number.NaN : entry.change ?? Number.NaN;
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
      <div className="flow-mobile-view"><ControlGroup label="檢視方式"><button className={view === 'bars' ? 'is-selected' : ''} type="button" onClick={() => setView('bars')}>分歧橫條</button><button className={view === 'matrix' ? 'is-selected' : ''} type="button" onClick={() => setView('matrix')}>熱力圖</button><button className={view === 'table' ? 'is-selected' : ''} type="button" onClick={() => setView('table')}>明細表</button></ControlGroup></div>
    </div>
  </section>
);

const FlowViewTabs: React.FC<{ view: FlowView; setView: (value: FlowView) => void }> = ({ view, setView }) => <div className="flow-view-tabs flow-desktop-view" role="tablist" aria-label="資金流檢視方式"><button className={view === 'bars' ? 'is-selected' : ''} type="button" onClick={() => setView('bars')}>分歧橫條</button><button className={view === 'matrix' ? 'is-selected' : ''} type="button" onClick={() => setView('matrix')}>熱力圖</button><button className={view === 'table' ? 'is-selected' : ''} type="button" onClick={() => setView('table')}>明細表</button></div>;

const FlowBoardTitle: React.FC<{ kicker: string; note: string; view: FlowView; setView: (value: FlowView) => void }> = ({ kicker, note, view, setView }) => <div className="flow-board-title"><span className="page-kicker">{kicker}</span><div className="flow-board-title-right"><span className="section-note">{note}</span><FlowViewTabs view={view} setView={setView} /></div></div>;

function aggregateFlows(flows: InstitutionalFlowItem[], days: number): InstitutionalFlowItem | null {
  const selected = flows.slice(0, days);
  if (!selected.length) return null;
  return {
    date: `${days}日合計`,
    foreign_net: selected.reduce((sum, flow) => sum + flow.foreign_net, 0),
    trust_net: selected.reduce((sum, flow) => sum + flow.trust_net, 0),
    dealer_net: selected.reduce((sum, flow) => sum + flow.dealer_net, 0),
    total_net: selected.reduce((sum, flow) => sum + flow.total_net, 0)
  };
}

const FlowBreakdown: React.FC<{ entry: InstitutionalRankingEntry; metric: FlowMetric; days: number; flows: InstitutionalFlowItem[] }> = ({ entry, metric, days, flows }) => {
  if (metric !== 'net') return <span>此資料 contract 未提供逐日持股比重拆解</span>;
  const hasRankedBreakdown = hasRankedNetBreakdown(entry);
  const aggregate = hasRankedBreakdown ? { date: `${days}日彙總`, foreign_net: entry.foreign as number, trust_net: entry.trust as number, dealer_net: entry.dealer as number, total_net: entry.total as number } : aggregateFlows(flows, days);
  if (!aggregate) return <span>此標的尚無逐法人拆解資料</span>;
  return <><span className="flow-breakdown-period">{hasRankedBreakdown ? `${days}日彙總` : aggregate.date}</span><span>外資 <b className={aggregate.foreign_net >= 0 ? 'positive mono-num' : 'negative mono-num'}>{formatValue(aggregate.foreign_net)}</b></span><span>投信 <b className={aggregate.trust_net >= 0 ? 'positive mono-num' : 'negative mono-num'}>{formatValue(aggregate.trust_net)}</b></span><span>自營商 <b className={aggregate.dealer_net >= 0 ? 'positive mono-num' : 'negative mono-num'}>{formatValue(aggregate.dealer_net)}</b></span></>;
};

const FlowBarsView: React.FC<{ entries: InstitutionalRankingEntry[]; metric: FlowMetric; days: number; view: FlowView; setView: (value: FlowView) => void; expandedCode: string | null; setExpandedCode: (code: string | null) => void; loadBreakdown: (code: string, exchange?: string) => Promise<InstitutionalFlowItem[]>; themesOf: Map<string, string[]>; note: string; onGoStock: InstitutionalFlowsProps['onGoStock']; }> = ({ entries, metric, days, view, setView, expandedCode, setExpandedCode, loadBreakdown, themesOf, note, onGoStock }) => {
  const [breakdowns, setBreakdowns] = useState<Record<string, InstitutionalFlowItem[]>>({});
  const [loadingCode, setLoadingCode] = useState<string | null>(null);
  const maxValue = Math.max(...entries.map((entry) => Math.abs(metricValue(entry, metric))), 1);
  const toggleEntry = async (entry: InstitutionalRankingEntry) => {
    if (expandedCode === entry.code) {
      setExpandedCode(null);
      return;
    }
    setExpandedCode(entry.code);
    if (breakdowns[entry.code] || metric === 'ratio' || hasRankedNetBreakdown(entry)) return;
    setLoadingCode(entry.code);
    const flows = await loadBreakdown(entry.code, entry.exchange);
    setBreakdowns((current) => ({ ...current, [entry.code]: flows }));
    setLoadingCode((current) => current === entry.code ? null : current);
  };
  return (
    <div className="flow-board">
      <FlowBoardTitle kicker={`RANKINGS BOARD · ${days}日 · ${entries.length} 筆`} note={note || '買超向右 · 賣超向左'} view={view} setView={setView} />
      <div className="flow-bars-head"><span>#</span><span>代號／名稱</span><span>賣超</span><span>買超</span><span>合計</span></div>
      {entries.map((entry, index) => {
        const value = metricValue(entry, metric);
        // Each side of the zero axis is half the track, so the largest bar is 50%.
        const width = `${Math.max(1.5, Math.abs(value) / maxValue * 50)}%`;
        const expanded = expandedCode === entry.code;
        return (
          <article className={`flow-bar-row ${expanded ? 'is-expanded' : ''}`} key={entry.instrument_id}>
            <button className="flow-bar-main" type="button" onClick={() => void toggleEntry(entry)}>
              <span className="rank-num mono-num">{String(index + 1).padStart(2, '0')}</span>
              <span className="flow-stock-label"><b className="mono-num">{entry.code}</b><span>{entry.name}</span>{themesOf.get(entry.instrument_id)?.[0] ? <i className="flow-theme-tag">{themesOf.get(entry.instrument_id)?.[0]}</i> : null}</span>
              <span className="zero-axis"><span className={`bar-fill ${value >= 0 ? 'positive-fill' : 'negative-fill'}`} style={{ width }} /></span>
              <strong className={`flow-total mono-num ${value >= 0 ? 'positive' : 'negative'}`}>{formatValue(value, metric === 'ratio' ? ' pp' : '')}</strong>
            </button>
            {expanded ? <div className="flow-breakdown">{loadingCode === entry.code ? <span>讀取逐日拆解…</span> : <FlowBreakdown entry={entry} metric={metric} days={days} flows={breakdowns[entry.code] ?? []} />}<button type="button" className="flow-breakdown-link" onClick={() => onGoStock(entry.code, entry.exchange, 'flows')}>個股籌碼 →</button></div> : null}
          </article>
        );
      })}
    </div>
  );
};

const FlowMatrixView: React.FC<{ symbol: string; flows: InstitutionalFlowItem[]; metric: FlowMetric; view: FlowView; setView: (value: FlowView) => void }> = ({ symbol, flows, metric, view, setView }) => {
  const columns: Array<[keyof InstitutionalFlowItem, string]> = [['foreign_net', '外資'], ['trust_net', '投信'], ['dealer_net', '自營商'], ['total_net', '合計']];
  const max = Math.max(...flows.flatMap((flow) => columns.map(([key]) => Math.abs(flow[key] as number))), 1);
  return (
    <div className="flow-matrix-panel">
      <FlowBoardTitle kicker={`${symbol || '—'} · DATE × INSTITUTION`} note={metric === 'net' ? '賣超 — 買超' : '持股比重資料未提供'} view={view} setView={setView} />
      {metric === 'ratio' ? <p className="no-results">現有資料 contract 沒有逐日持股比重序列；此檢視保留空值，不以示意值補齊。</p> : (
        <div className="matrix-scroll"><table className="flow-matrix"><thead><tr><th>日期</th>{columns.map(([, label]) => <th key={label}>{label}</th>)}</tr></thead><tbody>{flows.slice(0, 5).map((flow) => <tr key={flow.date}><th className="mono-num">{flow.date}</th>{columns.map(([key]) => { const value = flow[key] as number; return <td className={value >= 0 ? 'matrix-positive' : 'matrix-negative'} key={key} style={{ '--cell-alpha': 0.12 + Math.min(0.76, Math.abs(value) / max * 0.76) } as React.CSSProperties}>{formatValue(value)}</td>; })}</tr>)}</tbody></table></div>
      )}
      <div className="matrix-legend"><span>賣超</span><i className="legend-negative" /><i className="legend-neutral" /><i className="legend-positive" /><span>買超</span></div>
    </div>
  );
};

const FlowTableView: React.FC<{ entries: InstitutionalRankingEntry[]; metric: FlowMetric; view: FlowView; setView: (value: FlowView) => void; onGoStock: InstitutionalFlowsProps['onGoStock'] }> = ({ entries, metric, view, setView, onGoStock }) => {
  const valueCell = (value: number | undefined, unit = '') => <td className={`mono-num ${isFiniteNumber(value) && value >= 0 ? 'positive' : isFiniteNumber(value) ? 'negative' : ''}`} title={isFiniteNumber(value) ? undefined : '此資料 contract 未提供此欄位'}>{isFiniteNumber(value) ? formatValue(value, unit) : '—'}</td>;
  return <div className="flow-table-panel"><FlowBoardTitle kicker="DETAIL TABLE" note={metric === 'net' ? '三大法人為統計區間彙總' : '持股比重變化以 pp 顯示'} view={view} setView={setView} /><div className="table-scroll"><table className="flow-detail-table"><thead><tr><th>代號</th><th>名稱</th><th>外資</th><th>投信</th><th>自營商</th><th>合計</th></tr></thead><tbody>{entries.map((entry) => <tr key={entry.instrument_id}><th><button type="button" onClick={() => onGoStock(entry.code, entry.exchange)} className="stock-code-link mono-num">{entry.code}</button></th><td>{entry.name}</td>{metric === 'net' ? <>{valueCell(entry.foreign)}{valueCell(entry.trust)}{valueCell(entry.dealer)}{valueCell(entry.total)}</> : <>{valueCell(undefined)}{valueCell(undefined)}{valueCell(undefined)}{valueCell(entry.change, ' pp')}</>}</tr>)}</tbody></table></div></div>;
};

export const InstitutionalFlows: React.FC<InstitutionalFlowsProps> = ({ data, focus = null, device, onGoStock, refreshKey }) => {
  const defaultLookup = useMemo(() => data.themeRanking.themes.flatMap((theme) => theme.direct_mentions).find((instrument) => instrument.symbol)?.symbol ?? '', [data.themeRanking.themes]);
  const [metric, setMetric] = useState<FlowMetric>('net');
  const [days, setDays] = useState(5);
  const [direction, setDirection] = useState<FlowDirection>('up');
  const [hideEtf, setHideEtf] = useState(true);
  const [view, setView] = useState<FlowView>('bars');
  const [mode, setMode] = useState<'institutional' | 'broker'>('institutional');
  const [expandedCode, setExpandedCode] = useState<string | null>(null);
  const [board, setBoard] = useState<InstitutionalRankingBoard | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [themeFilter, setThemeFilter] = useState('');
  const themesOf = useMemo(() => themeMembership(data), [data]);
  const entries = board?.entries ?? [];
  const [stockFlows, setStockFlows] = useState<InstitutionalFlowItem[]>([]);
  const [lookup, setLookup] = useState(defaultLookup);

  useEffect(() => {
    let active = true;
    fetchInstitutionalBoard(days, direction, metric, refreshKey > 0).then((result) => { if (active) setBoard(result); });
    return () => { active = false; };
  }, [days, direction, metric, refreshKey]);

  useEffect(() => {
    let active = true;
    if (!lookup) return () => { active = false; };
    fetchInstitutionalFlows(lookup, undefined, refreshKey > 0).then((result) => { if (active) setStockFlows(result); });
    return () => { active = false; };
  }, [lookup, refreshKey]);

  const filteredEntries = useMemo(() => {
    const members = themeFilter ? themeMemberIds(data, themeFilter) : null;
    return entries.filter((entry) => (!hideEtf || !entry.is_etf) && (!members || members.has(entry.instrument_id)));
  }, [data, entries, hideEtf, themeFilter]);
  const visibleEntries = showAll || themeFilter ? filteredEntries : filteredEntries.slice(0, DEFAULT_VISIBLE_ROWS);
  const themeName = focus?.themes.find((theme) => theme.theme_id === themeFilter)?.name_zh ?? '';
  const note = boardNote(board);

  const mobile = device === 'mobile';
  const themeRef = useRef<HTMLElement>(null);
  const rankRef = useRef<HTMLElement>(null);
  const focusThemes = rankedFocusThemes(focus);
  const byForeign = focusThemes.slice().sort((x, y) => y.flow.foreign_5d - x.flow.foreign_5d);
  const topBuy = byForeign.find((theme) => theme.flow.foreign_5d > 0);
  const topSell = byForeign.slice().reverse().find((theme) => theme.flow.foreign_5d < 0);
  const broad = focusThemes.filter((theme) => (theme.flow.breadth ?? 0) >= 0.5).length;
  const heroSentence = focus
    ? [
      topBuy ? `外資 ${focus.flow_window_days} 日買超最多是${topBuy.name_zh}（${formatLots(topBuy.flow.foreign_5d)} 張）` : `外資 ${focus.flow_window_days} 日沒有題材淨買超`,
      topSell ? `賣超最多是${topSell.name_zh}（${formatLots(topSell.flow.foreign_5d)} 張）` : '',
      `${broad} 個題材法人買超家數過半`,
    ].filter(Boolean).join('；') + '。'
    : '先看法人資金流向哪些題材，再看個股排行與分點。';
  const pickTheme = (themeId: string) => { setThemeFilter(themeId); setMode('institutional'); setMetric('net'); scrollToRef(rankRef); };
  const nameToId = new Map(focusThemes.map((theme) => [theme.name_zh, theme.theme_id]));
  const bars = (key: 'foreign_5d' | 'trust_5d') => focusThemes.slice().sort((x, y) => y.flow[key] - x.flow[key])
    .map((theme) => ({ name: theme.name_zh, value: theme.flow[key], label: formatLots(theme.flow[key]) }));

  const tabs = (
    <PageTabs label="籌碼流向資料面向" tabs={[
      { id: 'theme', label: '題材資金', onClick: () => scrollToRef(themeRef) },
      { id: 'institutional', label: '三大法人排行', active: mode === 'institutional', onClick: () => { setMode('institutional'); scrollToRef(rankRef); } },
      { id: 'broker', label: '券商分點', active: mode === 'broker', onClick: () => { setMode('broker'); scrollToRef(rankRef); } },
    ]} />
  );

  const lookupForm = (
    <section className="flow-lookup" aria-label="查詢個股法人資金流向">
      <form onSubmit={(event) => { event.preventDefault(); onGoStock(lookup, undefined, 'flows'); }}><input aria-label="輸入個股代號查詢籌碼" value={lookup} onChange={(event) => setLookup(event.target.value)} /><button type="submit">查詢籌碼 →</button></form>
    </section>
  );

  const main = (
    <div className="fd-main">
      <PageHero title="資金流向" sentence={heroSentence} meta={focus ? `法人資料 ${shortDate(focus.flow_as_of)}，TWSE / TPEX 官方每日資料` : 'TWSE / TPEX 官方每日資料'} />
      <section className="fd-section is-first" ref={themeRef} aria-label="題材資金">
        <SectionHead title="法人資金流向哪些題材" note={focus ? `法人 ${focus.flow_window_days} 日合計，單位：張，點題材篩選下方排行` : undefined} />
        <ThemeFlowPanel focus={focus} selectedThemeId={themeFilter} onSelectTheme={pickTheme} />
      </section>
      <section className="fd-section" ref={rankRef} aria-label={mode === 'broker' ? '券商分點' : '三大法人排行'}>
        <SectionHead title={mode === 'broker' ? '券商分點' : '三大法人個股排行'} note={mode === 'broker' ? '分點買賣與隔日衝傾向' : note || undefined} />
        {mode === 'broker' ? <BrokerFlows onGoStock={onGoStock} refreshKey={refreshKey} /> : <>
          <FlowControls metric={metric} setMetric={setMetric} days={days} setDays={setDays} direction={direction} setDirection={setDirection} hideEtf={hideEtf} setHideEtf={setHideEtf} view={view} setView={setView} />
          {themeFilter ? <div className="flow-filter-note"><span>只顯示「{themeName || themeFilter}」成分股（{filteredEntries.length} 筆在排行內）</span><button type="button" onClick={() => setThemeFilter('')}>清除篩選 ×</button></div> : null}
          {view === 'bars' ? <FlowBarsView entries={visibleEntries} metric={metric} days={days} view={view} setView={setView} expandedCode={expandedCode} setExpandedCode={setExpandedCode} loadBreakdown={(code, exchange) => fetchInstitutionalFlows(code, exchange, refreshKey > 0)} themesOf={themesOf} note={note} onGoStock={onGoStock} /> : null}
          {view === 'matrix' ? <FlowMatrixView symbol={lookup} flows={stockFlows} metric={metric} view={view} setView={setView} /> : null}
          {view === 'table' ? <FlowTableView entries={visibleEntries} metric={metric} view={view} setView={setView} onGoStock={onGoStock} /> : null}
          {view !== 'matrix' && !themeFilter && filteredEntries.length > DEFAULT_VISIBLE_ROWS ? <div className="list-more"><button type="button" onClick={() => setShowAll((shown) => !shown)}>{showAll ? `收合至前 ${DEFAULT_VISIBLE_ROWS} 名` : `顯示全部 ${filteredEntries.length} 筆`}</button></div> : null}
        </>}
      </section>
      <p className="disclaimer">本頁資訊整理自公開交易資料，僅供技術與數據呈現展示，不構成任何買賣投資建議。</p>
    </div>
  );

  const rail = (
    <aside className="fd-rail" aria-label="資金概覽">
      {focusThemes.length > 0 ? (
        <section className="fd-rail-block">
          <SectionHead level={3} title="外資流向" note={`${focus!.flow_window_days} 日，張`} />
          <DivergingBars title="依題材，點題材篩選排行" note={shortDate(focus!.flow_as_of)} bars={bars('foreign_5d')} onPick={(name) => { const id = nameToId.get(name); if (id) pickTheme(id); }} />
        </section>
      ) : null}
      {focusThemes.length > 0 ? (
        <section className="fd-rail-block">
          <SectionHead level={3} title="投信流向" note={`${focus!.flow_window_days} 日，張`} />
          <DivergingBars title="依題材" note={shortDate(focus!.flow_as_of)} bars={bars('trust_5d')} onPick={(name) => { const id = nameToId.get(name); if (id) pickTheme(id); }} />
        </section>
      ) : null}
      <section className="fd-rail-block">
        <SectionHead level={3} title="查詢個股籌碼" />
        {lookupForm}
      </section>
    </aside>
  );

  return (
    <div className={`page-content flows-page fd fd-page${mobile ? ' is-mobile' : ''}`}>
      {tabs}
      {mobile ? <>{main}{rail}</> : <div className="fd-cols">{main}{rail}</div>}
    </div>
  );
};
