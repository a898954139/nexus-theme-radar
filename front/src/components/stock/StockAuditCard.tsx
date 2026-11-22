// 個股健檢 (stock audit) on the stock page: the latest /api/v1/stock-audit
// report's entry for this symbol — valuation, technical levels and the
// short / mid / long operation plan. Renders nothing when the symbol is not in
// the report or the API is unavailable.
import React, { useEffect, useState } from 'react';
import { fetchStockAudit, StockAuditReport, StockAuditStock } from '../../services/stockAudit';
import './stock-audit-card.css';

/** Older than this the plan's price levels are shown collapsed, with a warning. */
export const STALE_AFTER_DAYS = 5;

let reportPromise: Promise<StockAuditReport | null> | null = null;
function loadReport(): Promise<StockAuditReport | null> {
  // One fetch per page load, shared by every stock page the user opens.
  reportPromise ??= fetchStockAudit().catch(() => {
    reportPromise = null;
    return null;
  });
  return reportPromise;
}

function taipeiToday(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
}

export function daysSince(date: string, today: string): number {
  return Math.round((Date.parse(`${today}T00:00:00Z`) - Date.parse(`${date}T00:00:00Z`)) / 86_400_000);
}

function md(date: string) { return `${Number(date.slice(5, 7))}/${Number(date.slice(8, 10))}`; }
function price(value: number) { return value.toLocaleString('en-US', { maximumFractionDigits: 2 }); }
function signedPct(value: number) { return `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toFixed(1)}%`; }

/** Price vs MA20 / MA60 on the audit date, stated as 偏多 / 偏空 directly. */
function stance(stock: StockAuditStock): { label: string; tone: 'up' | 'down' | 'flat' } {
  const { ma20, ma60 } = stock.technical;
  if (stock.price > ma20 && ma20 > ma60) return { label: '偏多（站上 MA20，均線多頭排列）', tone: 'up' };
  if (stock.price < ma20 && ma20 < ma60) return { label: '偏空（跌破 MA20，均線空頭排列）', tone: 'down' };
  return { label: '多空交錯（均線糾結）', tone: 'flat' };
}

const AuditBody: React.FC<{ stock: StockAuditStock; report: StockAuditReport }> = ({ stock, report }) => {
  const { fundamentals: f, valuation: v, technical: t, quality: q } = stock;
  const s = stance(stock);
  return <>
    <div className="daily-report-tags">
      <span className={`tag sa-${s.tone}`}>結構：{s.label}</span>
      <span className="tag">收盤 <b className="mono-num">{price(stock.price)}</b></span>
      <span className="tag">本益比 <b className="mono-num">{f.pe.toFixed(1)}</b>，{v.baseline_label} {v.baseline_pe.toFixed(1)}（{v.premium_pct >= 0 ? '溢價' : '折價'} <b className="mono-num">{signedPct(v.premium_pct)}</b>）</span>
    </div>
    <p className="daily-report-conclusion">{stock.summary}</p>
    <div className="table-scroll"><table className="sa-ops">
      <thead><tr><th>週期</th><th>停損</th><th>進場</th><th>加碼</th><th>停利</th><th>風報比</th><th>時機</th></tr></thead>
      <tbody>{stock.operations.map((op) => {
        const rr = (op.take_profit - op.entry) / (op.entry - op.stop);
        return <tr key={op.term}>
          <th>{op.term}<small>{op.horizon}</small></th>
          <td className="mono-num sa-down">{price(op.stop)}</td>
          <td className="mono-num">{price(op.entry)}</td>
          <td className="mono-num">{price(op.add)}</td>
          <td className="mono-num sa-up">{price(op.take_profit)}</td>
          <td className="mono-num">1 : {rr.toFixed(1)}</td>
          <td className="sa-timing">{op.timing}<small>加碼：{op.add_condition}</small></td>
        </tr>;
      })}</tbody>
    </table></div>
    <dl className="daily-report-body">
      <dt>技術面</dt><dd>MA20 <b className="mono-num">{price(t.ma20)}</b>・MA60 <b className="mono-num">{price(t.ma60)}</b>・20 日支撐 <b className="mono-num">{price(t.support)}</b>・壓力 <b className="mono-num">{price(t.resistance)}</b><br />{t.analysis}</dd>
      <dt>基本面</dt><dd>{f.period} 營收 {price(f.revenue)} {f.revenue_unit}，EPS {f.eps.toFixed(2)}，近四季 {f.ttm_eps.toFixed(2)}<br />{f.analysis}</dd>
      <dt>估值</dt><dd>本益比位於 {v.sample_count} 個樣本的第 {Math.round(v.percentile)} 百分位。{v.analysis}</dd>
      <dt>報酬品質</dt><dd>Sharpe <b className="mono-num">{q.sharpe.toFixed(2)}</b>・Sortino <b className="mono-num">{q.sortino.toFixed(2)}</b>・回本 {q.ttr_days} 天・{q.index_shape}<small>（{q.period}）</small></dd>
      {report.forecast ? <><dt>隔日情境</dt><dd>{report.forecast.summary}</dd></> : null}
    </dl>
    <p className="daily-report-foot">價位為條件式計畫，不是下單指令。資料 {md(report.report_date)} 收盤，產生於 {report.generated_at.slice(0, 16).replace('T', ' ')}（UTC）。</p>
  </>;
};

export const StockAuditCard: React.FC<{ code: string }> = ({ code }) => {
  const [report, setReport] = useState<StockAuditReport | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let active = true;
    loadReport().then((value) => { if (active) setReport(value); });
    return () => { active = false; };
  }, []);
  useEffect(() => { setOpen(false); }, [code]);

  const stock = report?.stocks.find((item) => item.symbol === code) ?? null;
  if (!report || !stock) return null;
  const age = daysSince(report.report_date, taipeiToday());
  const stale = age > STALE_AFTER_DAYS;
  const expanded = !stale || open;
  return <section className={`daily-report stock-audit-card${stale ? ' is-stale' : ''}`} data-testid="stock-audit-card">
    <div className="daily-report-head">
      <span className="page-kicker">STOCK AUDIT · 個股健檢</span>
      <span className="mono-num">{md(report.report_date)} 收盤資料{stale ? `，已 ${age} 天未更新` : ''}</span>
    </div>
    {stale ? <button type="button" className="sa-toggle" onClick={() => setOpen((value) => !value)}>
      <span>健檢已過期，價位可能已失效，僅供對照</span><span className="mono-num">{open ? '收合 ▲' : '展開 ▾'}</span>
    </button> : null}
    {expanded ? <AuditBody stock={stock} report={report} /> : null}
  </section>;
};
