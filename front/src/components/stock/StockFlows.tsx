import React, { useMemo, useState } from 'react';
import { InstitutionalFlowItem } from '../../types';
import { directionClass, formatLots } from '../common/ThemeFocusBoard';

/**
 * Three-institution flow tab of the stock page.
 *
 * The API serves daily nets in shares (institutional-flows, unit "shares");
 * everything on this tab is shown in 張 (1 張 = 1,000 股) so it matches the
 * 法人 5 日 summary above the tabs and the rest of the site.
 */

interface LotRow {
  date: string;
  foreign: number;
  trust: number;
  dealer: number;
  total: number;
  /** total from this date through the latest date, in 張 */
  sinceTotal: number;
}

const toLots = (shares: number) => Math.round(shares / 1000);
const WINDOWS = [1, 5, 10, 20, 60] as const;
const CHART_DAYS = 20;
const TABLE_DAYS = 20;

function lotRows(flows: InstitutionalFlowItem[]): LotRow[] {
  const ordered = flows.slice().sort((left, right) => right.date.localeCompare(left.date));
  let running = 0;
  return ordered.map((flow) => {
    const total = toLots(flow.total_net);
    running += total;
    return { date: flow.date, foreign: toLots(flow.foreign_net), trust: toLots(flow.trust_net), dealer: toLots(flow.dealer_net), total, sinceTotal: running };
  });
}

function streakOf(rows: LotRow[], key: 'foreign' | 'trust' | 'dealer' | 'total') {
  let streak = 0;
  for (const row of rows) {
    const value = row[key];
    if (value > 0 && streak >= 0) streak += 1;
    else if (value < 0 && streak <= 0) streak -= 1;
    else break;
  }
  return streak;
}

function streakText(streak: number) {
  if (!streak) return '—';
  return `連${streak > 0 ? '買' : '賣'} ${Math.abs(streak)} 日`;
}

const Num: React.FC<{ value: number }> = ({ value }) => <span className={`mono-num ${directionClass(value)}`}>{formatLots(value)}</span>;

const WindowTable: React.FC<{ rows: LotRow[] }> = ({ rows }) => {
  const windows = WINDOWS.filter((days) => days === 1 || rows.length >= days);
  const sum = (days: number, key: 'foreign' | 'trust' | 'dealer' | 'total') => rows.slice(0, days).reduce((total, row) => total + row[key], 0);
  const keys = [['foreign', '外資'], ['trust', '投信'], ['dealer', '自營商'], ['total', '合計']] as const;
  return (
    <table className="sf-table sf-window">
      <thead><tr><th>區間（張）</th>{keys.map(([key, label]) => <th key={key}>{label}</th>)}</tr></thead>
      <tbody>
        {windows.map((days) => {
          return <tr key={days}><th>{days === 1 ? `最新 ${rows[0].date.slice(5)}` : `近 ${days} 日`}</th>{keys.map(([key]) => <td key={key}><Num value={sum(days, key)} /></td>)}</tr>;
        })}
        <tr className="sf-streak"><th>連續買賣</th>{keys.map(([key]) => { const streak = streakOf(rows, key); return <td key={key} className={directionClass(streak)}>{streakText(streak)}</td>; })}</tr>
      </tbody>
    </table>
  );
};

const FlowChart: React.FC<{ rows: LotRow[] }> = ({ rows }) => {
  const chart = rows.slice(0, CHART_DAYS).slice().reverse();
  const width = 600;
  const top = 12;
  const bottom = 128;
  const max = Math.max(...chart.map((row) => Math.abs(row.total)), 1);
  const cumulative = chart.reduce<number[]>((values, row) => [...values, (values[values.length - 1] ?? 0) + row.total], []);
  const cMin = Math.min(...cumulative, 0);
  const cMax = Math.max(...cumulative, 0);
  const zero = (top + bottom) / 2;
  const step = width / Math.max(chart.length, 1);
  const x = (index: number) => step * (index + 0.5);
  const barWidth = Math.min(18, step * 0.62);
  const cy = (value: number) => top + (1 - (value - cMin) / Math.max(cMax - cMin, 1)) * (bottom - top);
  const points = cumulative.map((value, index) => `${x(index).toFixed(1)},${cy(value).toFixed(1)}`).join(' ');
  const labelEvery = Math.ceil(chart.length / 10);
  const last = cumulative[cumulative.length - 1] ?? 0;
  return (
    <div className="sf-chart">
      <div className="sf-chart-head">
        <span>近 {chart.length} 日合計淨額（張）</span>
        <span className="sf-legend"><span><i className="sf-legend-up" />買超</span><span><i className="sf-legend-down" />賣超</span><span><i className="sf-legend-line" />區間累計 <b className={directionClass(last)}>{formatLots(last)}</b></span></span>
      </div>
      <svg viewBox={`0 0 ${width} 150`} role="img" aria-label="三大法人每日合計淨額與區間累計" preserveAspectRatio="none">
        <line x1="0" x2={width} y1={zero} y2={zero} className="chart-axis" />
        {chart.map((row, index) => {
          const h = Math.abs(row.total) / max * (zero - top);
          return <g key={row.date}>
            <rect x={x(index) - barWidth / 2} y={row.total >= 0 ? zero - h : zero} width={barWidth} height={Math.max(h, 1)} className={row.total >= 0 ? 'chart-bar-up' : 'chart-bar-down'} rx="1.5"><title>{`${row.date} 合計 ${formatLots(row.total)} 張（外資 ${formatLots(row.foreign)}／投信 ${formatLots(row.trust)}／自營商 ${formatLots(row.dealer)}）`}</title></rect>
            {index % labelEvery === 0 || index === chart.length - 1 ? <text x={x(index)} y="146" className="chart-label" textAnchor="middle">{row.date.slice(5)}</text> : null}
          </g>;
        })}
        <polyline points={points} className="flow-cumulative-line" />
        {cumulative.map((value, index) => <circle key={chart[index].date} cx={x(index)} cy={cy(value)} r="2.2" className="flow-cumulative-dot"><title>{`${chart[index].date} 區間累計 ${formatLots(value)} 張`}</title></circle>)}
      </svg>
    </div>
  );
};

const DailyTable: React.FC<{ rows: LotRow[] }> = ({ rows }) => {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? rows : rows.slice(0, TABLE_DAYS);
  const max = Math.max(...visible.map((row) => Math.abs(row.total)), 1);
  return (
    <div className="sf-daily">
      <table className="sf-table">
        <thead><tr><th>日期</th><th>外資</th><th>投信</th><th>自營商</th><th>合計</th><th className="sf-bar-col" aria-label="合計長條" /><th title="從該日到最新一日的合計累計">自該日累計</th></tr></thead>
        <tbody>
          {visible.map((row) => {
            const width = Math.abs(row.total) / max * 50;
            return <tr key={row.date}>
              <th className="mono-num">{row.date.slice(5)}</th>
              <td><Num value={row.foreign} /></td>
              <td><Num value={row.trust} /></td>
              <td><Num value={row.dealer} /></td>
              <td className="sf-total"><Num value={row.total} /></td>
              <td className="sf-bar-col"><span className="sf-bar"><i className={row.total >= 0 ? 'up' : 'down'} style={row.total >= 0 ? { left: '50%', width: `${width}%` } : { right: '50%', width: `${width}%` }} /></span></td>
              <td><Num value={row.sinceTotal} /></td>
            </tr>;
          })}
        </tbody>
      </table>
      {rows.length > TABLE_DAYS ? <button type="button" className="sf-more" onClick={() => setShowAll((value) => !value)}>{showAll ? `收合，只看近 ${TABLE_DAYS} 日` : `顯示全部 ${rows.length} 日`}</button> : null}
    </div>
  );
};

export const StockFlows: React.FC<{ flows: InstitutionalFlowItem[] }> = ({ flows }) => {
  const rows = useMemo(() => lotRows(flows), [flows]);
  if (!rows.length) return <div className="stock-no-data">尚無三大法人買賣超資料</div>;
  return (
    <div className="sf">
      <div className="sf-head">
        <span className="page-kicker">三大法人買賣超</span>
        <span className="sf-unit">單位：張（1 張 = 1,000 股）・資料日 {rows[0].date}</span>
      </div>
      <div className="sf-grid">
        <div className="sf-left">
          <WindowTable rows={rows} />
          <FlowChart rows={rows} />
        </div>
        <DailyTable rows={rows} />
      </div>
    </div>
  );
};
