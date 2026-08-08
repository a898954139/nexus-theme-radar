import React, { useMemo, useState } from 'react';
import { BrokerMapData, DeviceType, FinancialQuarter, InstitutionalFlowItem, StockFundamentals, StockTab } from '../../types';
import { BrokerMap } from './BrokerMap';

interface StockDetailProps {
  code: string;
  exchange?: string;
  name?: string;
  fundamentals: StockFundamentals | null;
  flows: InstitutionalFlowItem[];
  brokerMap: BrokerMapData | null;
  brokerLoading?: boolean;
  onGoStock: (code: string, exchange?: string, tab?: StockTab) => void;
  device: DeviceType;
  initialTab: StockTab;
  onBack: () => void;
  onTabChange: (tab: StockTab) => void;
}

function pct(value: number) { return `${(value * 100).toFixed(1)}%`; }
function signedPct(value: number) { return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`; }
function signed(value: number, digits = 1) { return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`; }
function latestPeriod(fundamentals: StockFundamentals) { return fundamentals.quarters[0]?.period ?? fundamentals.fiscal_quarter; }
function statementNumber(row: Record<string, number | string | null | undefined> | undefined, key: string) { const value = row?.[key]; return typeof value === 'number' ? value : 0; }
function formatNumber(value: number) { return value.toLocaleString('en-US', { maximumFractionDigits: 2 }); }
function formatStatementValue(row: Record<string, number | string | null | undefined> | undefined, key: string) {
  const value = row?.[key];
  return typeof value === 'number' ? formatNumber(value) : value == null || value === '' ? '—' : String(value);
}
function shortPeriod(period: string) { return period.slice(2); }

const statementLabels: Record<string, string> = {
  revenue: '營業收入',
  cost_of_sales: '營業成本',
  gross_profit: '營業毛利',
  selling_expense: '推銷費用',
  admin_expense: '管理費用',
  rd_expense: '研發費用',
  expected_credit_loss: '預期信用減損',
  operating_expense: '營業費用',
  operating_income: '營業利益',
  pretax_income: '稅前淨利',
  net_income: '本期淨利',
  eps: '每股盈餘',
  cash: '現金及約當現金',
  receivables: '應收帳款',
  inventory: '存貨',
  current_assets: '流動資產',
  total_assets: '資產總額',
  current_liabilities: '流動負債',
  total_liabilities: '負債總額',
  total_equity: '權益總額',
  operating: '營業活動',
  investing: '投資活動',
  financing: '融資活動',
  depreciation: '折舊費用',
  capex: '資本支出',
  dividends_paid: '支付股利',
  ending_cash: '期末現金'
};

function statementLabel(key: string) { return statementLabels[key] ?? key; }

function points(values: Array<number | null>, width = 240, height = 82, min?: number, max?: number) {
  const actual = values.filter((value): value is number => value !== null);
  const lower = min ?? Math.min(...actual, 0);
  const upper = max ?? Math.max(...actual, 1);
  return values.map((value, index) => {
    if (value === null) return null;
    const x = values.length <= 1 ? width / 2 : 12 + index / (values.length - 1) * (width - 24);
    const y = height - 8 - ((value - lower) / Math.max(upper - lower, 1)) * (height - 16);
    return `${x},${y}`;
  });
}

interface TrendDataPoint {
  period: string;
  values: string[];
}

const ChartCard: React.FC<{ title: string; children: React.ReactNode; legend?: React.ReactNode; data?: TrendDataPoint[] }> = ({ title, children, legend, data }) => <article className="trend-card"><div className="trend-card-title"><strong>{title}</strong>{legend}</div><div className="trend-chart">{children}</div>{data ? <div className="trend-data-strip" aria-label={`${title}實際數值`}>{data.map((point) => <span className="trend-data-point" key={point.period}><b className="mono-num">{point.period}</b><span className="mono-num">{point.values.join(' · ')}</span></span>)}</div> : null}</article>;

function trendData(quarters: FinancialQuarter[], fundamentals: StockFundamentals, type: number): TrendDataPoint[] {
  const ordered = quarters.slice().reverse();
  return ordered.map((quarter) => {
    const income = fundamentals.statements.income[quarter.period];
    const balance = fundamentals.statements.balance[quarter.period];
    const cashFlow = fundamentals.statements.cash_flow[quarter.period];
    if (type === 1) return { period: shortPeriod(quarter.period), values: [`收入 ${formatNumber(quarter.revenue)}`, `毛利率 ${pct(quarter.gross_margin)}`] };
    if (type === 2) return { period: shortPeriod(quarter.period), values: [pct(quarter.gross_margin), pct(quarter.operating_margin), pct(quarter.net_margin)] };
    if (type === 3) return { period: shortPeriod(quarter.period), values: [`EPS ${formatNumber(quarter.eps)}`] };
    if (type === 4) return { period: shortPeriod(quarter.period), values: [`營業費用 ${formatStatementValue(income, 'operating_expense')}`, `研發 ${formatStatementValue(income, 'rd_expense')}`] };
    if (type === 5) return { period: shortPeriod(quarter.period), values: [`營業 ${formatStatementValue(cashFlow, 'operating')}`, `投資 ${formatStatementValue(cashFlow, 'investing')}`, `融資 ${formatStatementValue(cashFlow, 'financing')}`] };
    return { period: shortPeriod(quarter.period), values: [`資產 ${formatStatementValue(balance, 'total_assets')}`, `負債 ${formatStatementValue(balance, 'total_liabilities')}`, `權益 ${formatStatementValue(balance, 'total_equity')}`] };
  });
}

const TrendSvg: React.FC<{ quarters: FinancialQuarter[]; type: number; fundamentals: StockFundamentals }> = ({ quarters, type, fundamentals }) => {
  const ordered = quarters.slice().reverse();
  const width = 240;
  const x = (index: number) => 14 + index * ((width - 28) / Math.max(ordered.length - 1, 1));
  if (type === 1) {
    const revenueMax = Math.max(...ordered.map((q) => q.revenue), 1);
    const margins = points(ordered.map((q) => q.gross_margin), width, 92, 0, 1);
    return <svg viewBox="0 0 240 104" aria-label="營業收入與毛利率"><line x1="0" y1="94" x2="240" y2="94" className="chart-axis" />{ordered.map((q, index) => <rect key={q.period} x={x(index) - 7} y={94 - q.revenue / revenueMax * 70} width="14" height={q.revenue / revenueMax * 70} className="chart-bar-gold" rx="2" />)}<polyline points={margins.filter(Boolean).join(' ')} className="chart-polyline cyan-line" />{ordered.map((q, index) => <text key={q.period} x={x(index)} y="103" className="chart-label" textAnchor="middle">{q.period.slice(2, 6)}</text>)}</svg>;
  }
  if (type === 2) {
    const lines = [ordered.map((q) => q.gross_margin), ordered.map((q) => q.operating_margin), ordered.map((q) => q.net_margin)].map((values) => points(values, width, 92, 0, 1));
    return <svg viewBox="0 0 240 104" aria-label="三層利潤率趨勢"><line x1="0" y1="94" x2="240" y2="94" className="chart-axis" />{lines.map((line, index) => <polyline key={index} points={line.filter(Boolean).join(' ')} className={`chart-polyline ${['gold-line', 'cyan-line', 'green-line'][index]}`} />)}</svg>;
  }
  if (type === 3) {
    const epsMax = Math.max(...ordered.map((q) => q.eps), 1);
    const epsMin = Math.min(...ordered.map((q) => q.eps), 0);
    return <svg viewBox="0 0 240 104" aria-label="每股盈餘"><line x1="0" y1="94" x2="240" y2="94" className="chart-axis" />{ordered.map((q, index) => { const h = Math.abs(q.eps - epsMin) / Math.max(epsMax - epsMin, 1) * 75; return <rect key={q.period} x={x(index) - 7} y={94 - h} width="14" height={h} className={q.eps >= 0 ? 'chart-bar-green' : 'chart-bar-red'} rx="2" />; })}</svg>;
  }
  const statements = fundamentals.statements;
  if (type === 4) {
    const expenses = ordered.map((q) => statements.income[q.period]);
    const max = Math.max(...expenses.map((row) => statementNumber(row, 'operating_expense')), 1);
    return <svg viewBox="0 0 240 104" aria-label="營業費用結構"><line x1="0" y1="94" x2="240" y2="94" className="chart-axis" />{expenses.map((row, index) => { const rd = statementNumber(row, 'rd_expense') / max * 70; const sales = statementNumber(row, 'selling_expense') / max * 70; const admin = statementNumber(row, 'admin_expense') / max * 70; return <g key={ordered[index].period}><rect x={x(index) - 7} y={94 - rd} width="14" height={rd} className="chart-bar-cyan" /><rect x={x(index) - 7} y={94 - rd - sales} width="14" height={sales} className="chart-bar-purple" /><rect x={x(index) - 7} y={94 - rd - sales - admin} width="14" height={admin} className="chart-bar-muted" /></g>; })}</svg>;
  }
  if (type === 5) {
    const flows = ordered.map((q) => statements.cash_flow[q.period]);
    const max = Math.max(...flows.flatMap((row) => [Math.abs(statementNumber(row, 'operating')), Math.abs(statementNumber(row, 'investing')), Math.abs(statementNumber(row, 'financing'))]), 1);
    return <svg viewBox="0 0 240 104" aria-label="現金流量三表"><line x1="0" y1="52" x2="240" y2="52" className="chart-axis" />{flows.map((row, index) => { const vals = ['operating', 'investing', 'financing'].map((key) => statementNumber(row, key)); return <g key={ordered[index].period}>{vals.map((value, offset) => { const h = Math.abs(value) / max * 38; return <rect key={offset} x={x(index) - 8 + offset * 6} y={value >= 0 ? 52 - h : 52} width="4" height={h} className={value >= 0 ? 'chart-bar-green' : 'chart-bar-red'} rx="1" />; })}</g>; })}</svg>;
  }
  const balances = ordered.map((q) => fundamentals.statements.balance[q.period]);
  const max = Math.max(...balances.map((row) => statementNumber(row, 'total_assets')), 1);
  return <svg viewBox="0 0 240 104" aria-label="資產負債結構"><line x1="0" y1="94" x2="240" y2="94" className="chart-axis" />{balances.map((row, index) => { const equity = statementNumber(row, 'total_equity') / max * 70; const liabilities = statementNumber(row, 'total_liabilities') / max * 70; return <g key={ordered[index].period}><rect x={x(index) - 7} y={94 - equity} width="14" height={equity} className="chart-bar-green" /><rect x={x(index) - 7} y={94 - equity - liabilities} width="14" height={liabilities} className="chart-bar-muted" /></g>; })}</svg>;
};

function summaryLines(fundamentals: StockFundamentals) {
  const [current, previous] = fundamentals.quarters;
  const income = fundamentals.statements.income[current.period];
  const cash = fundamentals.statements.cash_flow[current.period];
  const revenueChange = previous ? current.revenue / previous.revenue - 1 : 0;
  const fcf = statementNumber(cash, 'operating') + statementNumber(cash, 'capex');
  const rdShare = current.revenue ? statementNumber(income, 'rd_expense') / current.revenue : 0;
  return [
    `${current.period} 營業收入 ${current.revenue.toLocaleString()} 億元，較前一季 ${signedPct(revenueChange)}。`,
    `毛利率 ${pct(current.gross_margin)}、營業利益率 ${pct(current.operating_margin)}、淨利率 ${pct(current.net_margin)}。`,
    `單季 EPS ${current.eps.toFixed(2)} 元，近四季 TTM EPS ${fundamentals.valuation.ttm_eps.toFixed(2)} 元。`,
    `自由現金流 ${fcf.toLocaleString()} 億元，營業現金流 ${statementNumber(cash, 'operating').toLocaleString()} 億元。`,
    `負債比率 ${pct(fundamentals.health.debt_ratio)}，研發費用約占營收 ${pct(rdShare)}。`
  ];
}

const Metrics: React.FC<{ fundamentals: StockFundamentals }> = ({ fundamentals }) => {
  const [current, previous] = fundamentals.quarters;
  const income = fundamentals.statements.income[current.period];
  const cash = fundamentals.statements.cash_flow[current.period];
  const fcf = statementNumber(cash, 'operating') + statementNumber(cash, 'capex');
  const metrics = [
    ['營業收入', `${current.revenue.toLocaleString()} 億`, previous ? signedPct(current.revenue / previous.revenue - 1) : '—'],
    ['每股盈餘', `${current.eps.toFixed(2)} 元`, previous ? signed(current.eps - previous.eps, 2) : '—'],
    ['毛利率', pct(current.gross_margin), previous ? signedPct(current.gross_margin - previous.gross_margin) : '—'],
    ['營業利益率', pct(current.operating_margin), previous ? signedPct(current.operating_margin - previous.operating_margin) : '—'],
    ['淨利率', pct(current.net_margin), previous ? signedPct(current.net_margin - previous.net_margin) : '—'],
    ['負債比率', pct(fundamentals.health.debt_ratio), '—'],
    ['近 4 季 TTM EPS', `${fundamentals.valuation.ttm_eps.toFixed(2)} 元`, '近四季累計'],
    ['自由現金流', `${fcf.toLocaleString()} 億`, '營業 − 資本支出']
  ];
  return <div className="metric-grid">{metrics.map(([label, value, change]) => <article className="metric-card" key={label}><span>{current.period} {label}</span><strong className="mono-num">{value}</strong><em className={change.startsWith('+') ? 'positive' : change.startsWith('-') ? 'negative' : ''}>{change}</em></article>)}</div>;
};

const FinancialTables: React.FC<{ fundamentals: StockFundamentals }> = ({ fundamentals }) => {
  const groups = [
    ['損益表', fundamentals.statements.income],
    ['資產負債表摘要', fundamentals.statements.balance],
    ['現金流量摘要', fundamentals.statements.cash_flow]
  ] as const;
  return <div className="financial-tables">{groups.map(([title, rows]) => {
    const fields = Array.from(new Set(fundamentals.quarters.flatMap((quarter) => Object.keys(rows[quarter.period] ?? {}))));
    return <section key={title}><h3>{title}<span>單位：{fundamentals.currency}</span></h3><div className="table-scroll"><table><thead><tr><th>季度</th>{fields.map((key) => <th key={key}>{statementLabel(key)}</th>)}</tr></thead><tbody>{fundamentals.quarters.map((quarter) => <tr key={quarter.period}><th className="mono-num">{quarter.period}</th>{fields.map((key) => <td className="mono-num" key={key}>{formatStatementValue(rows[quarter.period], key)}</td>)}</tr>)}</tbody></table></div></section>;
  })}</div>;
};

const StockFlows: React.FC<{ flows: InstitutionalFlowItem[] }> = ({ flows }) => {
  const max = Math.max(...flows.map((flow) => Math.abs(flow.total_net)), 1);
  const chartFlows = flows.slice(0, 12).slice().reverse();
  const cumulative = chartFlows.reduce<number[]>((values, flow) => [...values, (values[values.length - 1] ?? 0) + flow.total_net], []);
  const cumulativeMin = Math.min(...cumulative, 0);
  const cumulativeMax = Math.max(...cumulative, 0);
  const cumulativeY = (value: number) => 20 + (1 - (value - cumulativeMin) / Math.max(cumulativeMax - cumulativeMin, 1)) * 94;
  const cumulativePoints = cumulative.map((value, index) => {
    const x = chartFlows.length <= 1 ? 300 : index / (chartFlows.length - 1) * 570 + 15;
    return `${x},${cumulativeY(value)}`;
  }).join(' ');
  return <div className="stock-flow-tab"><article className="stock-flow-chart"><div className="section-heading"><span className="page-kicker">INSTITUTIONAL FLOW · DAILY NET</span><span className="flow-chart-legend"><span><i className="flow-legend-bar" />日淨額</span><span><i className="flow-legend-line" />累計淨額</span><b>張</b></span></div><div className="stock-chart-scroll"><svg viewBox="0 0 600 160" role="img" aria-label="個股三大法人每日淨額與累計淨額" preserveAspectRatio="none"><line x1="0" x2="600" y1="80" y2="80" className="chart-axis" />{chartFlows.map((flow, index, values) => { const x = values.length <= 1 ? 300 : index / (values.length - 1) * 570 + 15; const h = Math.abs(flow.total_net) / max * 62; return <g key={flow.date}><rect x={x - 10} y={flow.total_net >= 0 ? 80 - h : 80} width="20" height={h} className={flow.total_net >= 0 ? 'chart-bar-green' : 'chart-bar-red'} rx="2"><title>{`${flow.date} 日淨額 ${flow.total_net.toLocaleString()} 張`}</title></rect><text x={x} y="155" className="chart-label" textAnchor="middle">{flow.date.slice(5)}</text></g>; })}<polyline points={cumulativePoints} className="flow-cumulative-line" />{cumulative.map((value, index) => { const x = chartFlows.length <= 1 ? 300 : index / (chartFlows.length - 1) * 570 + 15; return <circle key={`${chartFlows[index]?.date}-cumulative`} cx={x} cy={cumulativeY(value)} r="2.5" className="flow-cumulative-dot"><title>{`${chartFlows[index]?.date} 累計 ${value.toLocaleString()} 張`}</title></circle>; })}</svg></div></article><div className="table-scroll"><table className="flow-detail-table"><thead><tr><th>日期</th><th>外資</th><th>投信</th><th>自營商</th><th>合計</th></tr></thead><tbody>{flows.map((flow) => <tr key={flow.date}><th className="mono-num">{flow.date}</th><td className={flow.foreign_net >= 0 ? 'positive mono-num' : 'negative mono-num'}>{flow.foreign_net.toLocaleString()}</td><td className={flow.trust_net >= 0 ? 'positive mono-num' : 'negative mono-num'}>{flow.trust_net.toLocaleString()}</td><td className={flow.dealer_net >= 0 ? 'positive mono-num' : 'negative mono-num'}>{flow.dealer_net.toLocaleString()}</td><td className={flow.total_net >= 0 ? 'positive mono-num' : 'negative mono-num'}>{flow.total_net.toLocaleString()}</td></tr>)}</tbody></table></div></div>;
};

export const StockDetail: React.FC<StockDetailProps> = ({ code, exchange, name, fundamentals, flows, brokerMap, brokerLoading, onGoStock, device, initialTab, onBack, onTabChange }) => {
  const [showTables, setShowTables] = useState(false);
  const tab = initialTab;
  const title = name ?? '個股';
  const charts = useMemo(() => fundamentals ? [1, 2, 3, 4, 5, 6] : [], [fundamentals]);
  const chartTitles = ['營業收入與毛利率', '三層利潤率趨勢', '每股盈餘', '營業費用結構', '現金流量三表', '資產負債結構'];
  const chartLegends = ['收入 / 毛利率', '毛利 / 營業 / 淨利率', 'EPS', '研發 / 推銷 / 管理', '營業 / 投資 / 融資', '權益 / 負債'];
  return <div className="page-content stock-page"><header className="stock-header"><button type="button" onClick={onBack}>← 題材雷達</button><div><strong className="mono-num">{code}</strong><h1>{title}</h1></div><span className="page-kicker">FINANCIAL ANALYSIS</span></header><div className="stock-tabs" role="tablist"><button className={tab === 'fundamentals' ? 'is-selected' : ''} type="button" onClick={() => onTabChange('fundamentals')}>基本面分析</button><button className={tab === 'flows' ? 'is-selected' : ''} type="button" onClick={() => onTabChange('flows')}>三大法人資金流向</button><button className={tab === 'broker' ? 'is-selected' : ''} type="button" onClick={() => onTabChange('broker')}>券商分點</button></div>{tab === 'flows' ? <StockFlows flows={flows} /> : tab === 'broker' ? <BrokerMap code={code} name={title} device={device} data={brokerMap} loading={brokerLoading} onGoStock={onGoStock} /> : fundamentals ? <><div className="stock-section-heading"><span className="page-kicker">FUNDAMENTALS · 基本面分析</span><span>{latestPeriod(fundamentals)} · {fundamentals.currency}</span></div><Metrics fundamentals={fundamentals} /><section className="financial-summary"><span className="page-kicker">FINANCIAL SUMMARY HIGHLIGHTS</span><ul>{summaryLines(fundamentals).map((line) => <li key={line}>{line}</li>)}</ul><p>本段依上述財報數字生成，僅描述已發生的財務事實，不構成投資建議。</p></section><section className="trend-section"><div className="section-heading"><span className="page-kicker">FINANCIAL TRENDS · PAST QUARTERS</span><span className="section-note">圖表與數值同步顯示</span></div><div className="trend-grid">{charts.map((type) => <ChartCard key={type} title={chartTitles[type - 1]} legend={<span className="trend-card-legend">{chartLegends[type - 1]}</span>} data={trendData(fundamentals.quarters, fundamentals, type)}><TrendSvg quarters={fundamentals.quarters} type={type} fundamentals={fundamentals} /></ChartCard>)}</div></section><section className="financial-disclosure"><button type="button" onClick={() => setShowTables((value) => !value)}><span>財務報表詳細數據</span><span className="mono-num">{showTables ? '收合 ▲' : '展開 ▾'}</span></button>{showTables ? <FinancialTables fundamentals={fundamentals} /> : null}</section></> : <div className="stock-no-data">等待財務資料</div>}<p className="disclaimer">本頁數據源自公開財報彙總整理，僅供學術與技術展示，不代表任何投資建議。</p><span className="device-hint" aria-hidden="true">{device === 'mobile' ? 'mobile' : 'desktop'}</span></div>;
};
