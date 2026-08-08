import React, { useState } from 'react';
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

interface TrendAxis {
  leftTop: string;
  leftBottom: string;
  rightTop?: string;
  rightBottom?: string;
}

interface TrendLegendItem {
  label: string;
  color: string;
}

interface TrendModel {
  unit: string;
  axis: TrendAxis;
  legend?: TrendLegendItem[];
  revenueMax?: number;
  marginMin?: number;
  marginMax?: number;
  epsMax?: number;
  epsMin?: number;
  opexMax?: number;
  cashFlowMax?: number;
  assetMax?: number;
}

interface ChartCoordinate {
  x: number;
  y: number;
}

function axisInteger(value: number) { return Math.round(value).toLocaleString('en-US'); }
function axisDecimal(value: number) { return value.toFixed(1); }

function chartRange(values: number[]) {
  const lower = Math.min(...values);
  const upper = Math.max(...values);
  const range = (upper - lower) || Math.max(Math.abs(lower), Math.abs(upper), 1);
  const padding = Math.max(range * 0.05, 0.01);
  return { min: lower - padding, max: upper + padding };
}

function chartX(index: number, count: number, width: number) {
  return count <= 1 ? width / 2 : (index + 0.5) / count * width;
}

function chartY(value: number, height: number, min: number, max: number) {
  const range = (max - min) || 1;
  return height - 8 - ((value - min) / range) * (height - 20);
}

function chartCoordinates(values: number[], width: number, height: number, min: number, max: number): ChartCoordinate[] {
  return values.map((value, index) => ({
    x: chartX(index, values.length, width),
    y: chartY(value, height, min, max),
  }));
}

function chartPointString(coordinates: ChartCoordinate[]) {
  return coordinates.map(({ x, y }) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
}

function buildTrendModel(ordered: FinancialQuarter[], fundamentals: StockFundamentals, type: number): TrendModel {
  const income = ordered.map((quarter) => fundamentals.statements.income[quarter.period]);
  const cashFlow = ordered.map((quarter) => fundamentals.statements.cash_flow[quarter.period]);
  const balance = ordered.map((quarter) => fundamentals.statements.balance[quarter.period]);
  if (type === 1) {
    const marginRange = chartRange(ordered.map((quarter) => quarter.gross_margin));
    const marginMin = marginRange.min;
    const marginMax = marginRange.max;
    const revenueMax = Math.max(...ordered.map((quarter) => quarter.revenue), 1);
    return { unit: '億元 / %', axis: { leftTop: axisInteger(revenueMax), leftBottom: '0', rightTop: `${axisDecimal(marginMax * 100)}%`, rightBottom: `${axisDecimal(marginMin * 100)}%` }, revenueMax, marginMin, marginMax };
  }
  if (type === 2) {
    const marginRange = chartRange(ordered.flatMap((quarter) => [quarter.gross_margin, quarter.operating_margin, quarter.net_margin]));
    const marginMin = marginRange.min;
    const marginMax = marginRange.max;
    return { unit: '%', axis: { leftTop: `${axisDecimal(marginMax * 100)}%`, leftBottom: `${axisDecimal(marginMin * 100)}%` }, marginMin, marginMax, legend: [{ label: '毛利率', color: 'var(--gold)' }, { label: '營益率', color: 'var(--muted)' }, { label: '淨利率', color: 'var(--neutral)' }] };
  }
  if (type === 3) {
    const epsValues = ordered.map((quarter) => quarter.eps);
    const epsRange = chartRange([...epsValues, 0]);
    const epsMin = Math.min(epsRange.min, 0);
    const epsMax = epsRange.max;
    return { unit: '元', axis: { leftTop: axisDecimal(epsMax), leftBottom: axisDecimal(epsMin) }, epsMin, epsMax };
  }
  if (type === 4) {
    const opexMax = Math.max(...income.map((row) => statementNumber(row, 'rd_expense') + statementNumber(row, 'selling_expense') + statementNumber(row, 'admin_expense')), 1);
    return { unit: '億元', axis: { leftTop: axisInteger(opexMax), leftBottom: '0' }, opexMax, legend: [{ label: '研發', color: 'var(--gold)' }, { label: '行銷', color: 'var(--neutral)' }, { label: '管理', color: 'var(--shell-bg)' }] };
  }
  if (type === 5) {
    const cashFlowMax = Math.max(...cashFlow.flatMap((row) => ['operating', 'investing', 'financing'].map((key) => Math.abs(statementNumber(row, key)))), 1);
    return { unit: '億元', axis: { leftTop: axisInteger(cashFlowMax), leftBottom: `-${axisInteger(cashFlowMax)}` }, cashFlowMax, legend: [{ label: '營業', color: 'var(--green)' }, { label: '投資', color: 'var(--red)' }, { label: '融資', color: 'var(--neutral)' }] };
  }
  const assetMax = Math.max(...balance.map((row) => statementNumber(row, 'total_assets')), 1);
  return { unit: '億元', axis: { leftTop: axisInteger(assetMax), leftBottom: '0' }, assetMax, legend: [{ label: '股東權益', color: 'var(--gold)' }, { label: '負債', color: 'var(--neutral)' }] };
}

const TrendLegend: React.FC<{ items: TrendLegendItem[]; square?: boolean }> = ({ items, square = false }) => <div className="trend-card-legend-row">{items.map((item) => <span key={item.label}><i className={square ? 'trend-legend-square' : 'trend-legend-line'} style={{ background: item.color }} />{item.label}</span>)}</div>;

const TrendDots: React.FC<{ coordinates: ChartCoordinate[]; color: string }> = ({ coordinates, color }) => <>{coordinates.map((point, index) => <circle key={`${point.x}-${point.y}`} cx={point.x} cy={point.y} r={index === coordinates.length - 1 ? 4.5 : 3.5} fill="var(--shell-bg)" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />)}</>;

const TrendSvg: React.FC<{ quarters: FinancialQuarter[]; type: number; fundamentals: StockFundamentals; model: TrendModel }> = ({ quarters, type, fundamentals, model }) => {
  const ordered = quarters.slice().reverse();
  const width = 600;
  const barWidth = Math.min(30, width / Math.max(ordered.length, 1) * 0.48);
  const barX = (index: number) => chartX(index, ordered.length, width) - barWidth / 2;
  if (type === 1) {
    const height = 170;
    const marginValues = ordered.map((quarter) => quarter.gross_margin);
    const marginCoordinates = chartCoordinates(marginValues, width, height, model.marginMin ?? 0, model.marginMax ?? 1);
    return <svg viewBox="0 0 600 170" preserveAspectRatio="none" aria-label="營業收入與毛利率"><line x1="0" y1="85" x2="600" y2="85" className="trend-grid-axis" />{ordered.map((quarter, index) => { const heightValue = quarter.revenue / Math.max(model.revenueMax ?? 1, 1) * height; const current = index === ordered.length - 1; return <rect key={quarter.period} x={barX(index)} y={height - heightValue} width={barWidth} height={heightValue} className={current ? 'trend-bar-current' : 'trend-bar-muted'} rx="2" />; })}<polyline points={chartPointString(marginCoordinates)} className="trend-line trend-line-gold" /><TrendDots coordinates={marginCoordinates} color="var(--gold)" /></svg>;
  }
  if (type === 2) {
    const values = [ordered.map((quarter) => quarter.gross_margin), ordered.map((quarter) => quarter.operating_margin), ordered.map((quarter) => quarter.net_margin)];
    const lines = values.map((series) => chartCoordinates(series, width, 130, model.marginMin ?? 0, model.marginMax ?? 1));
    return <svg viewBox="0 0 600 130" preserveAspectRatio="none" aria-label="三層利潤率趨勢"><polyline points={chartPointString(lines[0])} className="trend-line trend-line-gold" /><polyline points={chartPointString(lines[1])} className="trend-line trend-line-neutral" /><polyline points={chartPointString(lines[2])} className="trend-line trend-line-muted" /><TrendDots coordinates={lines[0]} color="var(--gold)" /><TrendDots coordinates={lines[1]} color="var(--muted)" /><TrendDots coordinates={lines[2]} color="var(--neutral)" /></svg>;
  }
  if (type === 3) {
    const values = ordered.map((quarter) => quarter.eps);
    const epsMin = model.epsMin ?? 0;
    const epsMax = model.epsMax ?? 1;
    const coordinates = chartCoordinates(values, width, 130, epsMin, epsMax);
    const zeroY = chartY(0, 130, epsMin, epsMax);
    return <svg viewBox="0 0 600 130" preserveAspectRatio="none" aria-label="每股盈餘 EPS"><line x1="0" y1={zeroY} x2="600" y2={zeroY} className="trend-grid-axis" /><polyline points={chartPointString(coordinates)} className="trend-line trend-line-gold" /><TrendDots coordinates={coordinates} color="var(--gold)" /></svg>;
  }
  const statements = fundamentals.statements;
  if (type === 4) {
    return <svg viewBox="0 0 600 130" preserveAspectRatio="none" aria-label="營業費用結構"><line x1="0" y1="65" x2="600" y2="65" className="trend-grid-axis" />{ordered.map((quarter, index) => { const row = statements.income[quarter.period]; const rd = statementNumber(row, 'rd_expense') / Math.max(model.opexMax ?? 1, 1) * 130; const selling = statementNumber(row, 'selling_expense') / Math.max(model.opexMax ?? 1, 1) * 130; const admin = statementNumber(row, 'admin_expense') / Math.max(model.opexMax ?? 1, 1) * 130; return <g key={quarter.period}><rect x={barX(index)} y={130 - rd} width={barWidth} height={rd} className="trend-bar-gold" /><rect x={barX(index)} y={130 - rd - selling} width={barWidth} height={selling} className="trend-bar-neutral" /><rect x={barX(index)} y={130 - rd - selling - admin} width={barWidth} height={admin} className="trend-bar-muted" /></g>; })}</svg>;
  }
  if (type === 5) {
    const zero = 65;
    const max = Math.max(model.cashFlowMax ?? 1, 1);
    return <svg viewBox="0 0 600 130" preserveAspectRatio="none" aria-label="現金流量三表"><line x1="0" y1={zero} x2="600" y2={zero} className="trend-zero-axis" />{ordered.map((quarter, index) => { const row = statements.cash_flow[quarter.period]; const values = [['operating', 'trend-bar-green'], ['investing', 'trend-bar-red'], ['financing', 'trend-bar-neutral']] as const; return <g key={quarter.period}>{values.map(([key, className], offset) => { const value = statementNumber(row, key); const height = Math.abs(value) / max * 57; const x = barX(index) + offset * (barWidth / 3); return <rect key={key} x={x} y={value >= 0 ? zero - height : zero} width={Math.max(barWidth / 3 - 2, 2)} height={height} className={className} rx="1" />; })}</g>; })}</svg>;
  }
  const max = Math.max(model.assetMax ?? 1, 1);
  return <svg viewBox="0 0 600 130" preserveAspectRatio="none" aria-label="資產負債結構"><line x1="0" y1="65" x2="600" y2="65" className="trend-grid-axis" />{ordered.map((quarter, index) => { const row = statements.balance[quarter.period]; const equity = statementNumber(row, 'total_equity') / max * 130; const liabilities = statementNumber(row, 'total_liabilities') / max * 130; return <g key={quarter.period}><rect x={barX(index)} y={130 - equity} width={barWidth} height={equity} className="trend-bar-gold" /><rect x={barX(index)} y={130 - equity - liabilities} width={barWidth} height={liabilities} className="trend-bar-neutral" /></g>; })}</svg>;
};

const FinancialTrendCard: React.FC<{ title: string; type: number; quarters: FinancialQuarter[]; fundamentals: StockFundamentals }> = ({ title, type, quarters, fundamentals }) => {
  const ordered = quarters.slice().reverse();
  const model = buildTrendModel(ordered, fundamentals, type);
  return <article className="trend-card"><div className="trend-card-title"><strong>{title}</strong><span className="trend-card-unit">{model.unit}</span></div><div className="trend-chart"><div className="trend-plot-row"><div className="trend-axis"><span>{model.axis.leftTop}</span><span>{model.axis.leftBottom}</span></div><div className="trend-plot"><TrendSvg quarters={quarters} type={type} fundamentals={fundamentals} model={model} /></div>{model.axis.rightTop ? <div className="trend-axis trend-axis-right"><span>{model.axis.rightTop}</span><span>{model.axis.rightBottom}</span></div> : <div className="trend-axis-spacer" />}</div><div className="trend-x-labels">{ordered.map((quarter) => <span key={quarter.period}>{shortPeriod(quarter.period)}</span>)}</div>{model.legend ? <TrendLegend items={model.legend} square={type >= 4} /> : null}</div></article>;
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
  const charts = fundamentals ? [1, 2, 3, 4, 5, 6] : [];
  const chartTitles = ['營業收入與毛利率', '三層利潤率趨勢', '每股盈餘 EPS', '營業費用結構', '現金流量三表', '資產負債結構'];
  return <div className="page-content stock-page"><header className="stock-header"><button type="button" onClick={onBack}>← 題材雷達</button><div><strong className="mono-num">{code}</strong><h1>{title}</h1></div><span className="page-kicker">FINANCIAL ANALYSIS</span></header><div className="stock-tabs" role="tablist"><button className={tab === 'fundamentals' ? 'is-selected' : ''} type="button" onClick={() => onTabChange('fundamentals')}>基本面分析</button><button className={tab === 'flows' ? 'is-selected' : ''} type="button" onClick={() => onTabChange('flows')}>三大法人資金流向</button><button className={tab === 'broker' ? 'is-selected' : ''} type="button" onClick={() => onTabChange('broker')}>券商分點</button></div>{tab === 'flows' ? <StockFlows flows={flows} /> : tab === 'broker' ? <BrokerMap code={code} name={title} device={device} data={brokerMap} loading={brokerLoading} onGoStock={onGoStock} /> : fundamentals ? <><div className="stock-section-heading"><span className="page-kicker">FUNDAMENTALS · 基本面分析</span><span>{latestPeriod(fundamentals)} · {fundamentals.currency}</span></div><Metrics fundamentals={fundamentals} /><section className="financial-summary"><span className="page-kicker">FINANCIAL SUMMARY HIGHLIGHTS</span><ul>{summaryLines(fundamentals).map((line) => <li key={line}>{line}</li>)}</ul><p>本段依上述財報數字生成，僅描述已發生的財務事實，不構成投資建議。</p></section><section className="trend-section"><div className="section-heading"><span className="page-kicker">FINANCIAL TRENDS · PAST QUARTERS</span><span className="section-note">圖表與數值同步顯示</span></div><div className="trend-grid">{charts.map((type) => <FinancialTrendCard key={type} title={chartTitles[type - 1]} type={type} quarters={fundamentals.quarters} fundamentals={fundamentals} />)}</div></section><section className="financial-disclosure"><button type="button" onClick={() => setShowTables((value) => !value)}><span>財務報表詳細數據</span><span className="mono-num">{showTables ? '收合 ▲' : '展開 ▾'}</span></button>{showTables ? <FinancialTables fundamentals={fundamentals} /> : null}</section></> : <div className="stock-no-data">等待財務資料</div>}<p className="disclaimer">本頁數據源自公開財報彙總整理，僅供學術與技術展示，不代表任何投資建議。</p><span className="device-hint" aria-hidden="true">{device === 'mobile' ? 'mobile' : 'desktop'}</span></div>;
};
