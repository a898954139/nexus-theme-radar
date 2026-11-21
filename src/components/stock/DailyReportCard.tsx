import React, { useEffect, useState } from 'react';
import { DailyReportView, fetchDailyReport, resolveDailyReportView, taipeiToday } from '../../services/analysisReport';

const BIAS_LABEL = { bullish: '偏多', bearish: '偏空', neutral: '中性' } as const;
const ACTION_LABEL = { actionable: '可執行', wait_for_confirmation: '等待確認', no_trade: '不交易' } as const;
const LEVEL_LABEL = { support: '支撐', resistance: '壓力', trigger: '觸發', invalidation: '失效', target: '目標' } as const;

function md(date: string) { return `${Number(date.slice(5, 7))}/${Number(date.slice(8, 10))}`; }
function price(value: number) { return value.toLocaleString('en-US', { maximumFractionDigits: 2 }); }

const EMPTY_COPY: Record<Exclude<DailyReportView['kind'], 'produced'>, string> = {
  not_produced: '今日報告未產出',
  no_batch: '今日報告未產出',
  not_in_list: '本檔不在今日前 10 檔分析清單',
  unavailable: '盤前報告服務尚未啟用'
};

export const DailyReportCard: React.FC<{ code: string }> = ({ code }) => {
  const [view, setView] = useState<DailyReportView | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setView(null);
    fetchDailyReport(code, controller.signal).then((payload) => {
      if (!controller.signal.aborted) setView(resolveDailyReportView(payload, code, taipeiToday()));
    });
    return () => controller.abort();
  }, [code]);

  // Loading: reserve no space; most stocks end up with no report.
  if (view === null) return null;
  // No report to show for this stock today: one line, not a block that pushes
  // the stock's own data below the fold.
  // Service switched off: show nothing rather than a row that only says so.
  if (view.kind === 'unavailable') return null;
  if (view.kind === 'not_in_list') {
    return <section className="daily-report is-slim is-empty"><span className="page-kicker">盤前分析</span><strong>{EMPTY_COPY[view.kind]}</strong></section>;
  }
  if (view.kind !== 'produced') {
    const note = view.kind === 'not_produced' ? `${md(view.today)} 台股開盤分析尚未寫入，不顯示前一日報告。` : view.kind === 'no_batch' ? `${md(view.today)} 無待分析清單（非交易日或雲端清單未備妥）。` : null;
    return <section className="daily-report is-empty"><span className="page-kicker">PRE-MARKET REPORT · 盤前分析</span><strong>{EMPTY_COPY[view.kind]}</strong>{note ? <p>{note}</p> : null}</section>;
  }
  const { report, rank } = view;
  return <section className="daily-report">
    <div className="daily-report-head"><span className="page-kicker">PRE-MARKET REPORT · 盤前分析{rank ? ` · #${rank}` : ''}</span><span className="mono-num">{md(report.data_as_of)} 資料 → {md(report.report_date)} 台股開盤分析</span></div>
    <div className="daily-report-tags"><span className={`tag bias-${report.bias}`}>Bias：{BIAS_LABEL[report.bias]}</span><span className={`tag action-${report.actionability}`}>Actionability：{ACTION_LABEL[report.actionability]}</span><span className="tag">失效價 <b className="mono-num">{price(report.invalidation.price)}</b></span></div>
    <p className="daily-report-conclusion">{report.conclusion}</p>
    {report.no_trade_warning ? <p className="daily-report-warning">⚠ {report.no_trade_warning}</p> : null}
    <dl className="daily-report-body">
      <dt>市場結構</dt><dd>{report.market_structure}</dd>
      <dt>關鍵價位</dt><dd><ul>{report.key_levels.map((level) => <li key={`${level.kind}-${level.price}`}>{LEVEL_LABEL[level.kind]}・{level.label} <b className="mono-num">{price(level.price)}</b></li>)}</ul></dd>
      <dt>主劇本</dt><dd>{report.primary_scenario.summary}<br /><small>觸發：{report.primary_scenario.trigger}{report.primary_scenario.entry_zone ? `｜進場區 ${price(report.primary_scenario.entry_zone[0])}–${price(report.primary_scenario.entry_zone[1])}` : ''}{report.primary_scenario.targets.length ? `｜目標 ${report.primary_scenario.targets.map(price).join(' / ')}` : ''}</small></dd>
      <dt>替代劇本</dt><dd>{report.alternative_scenario.summary}<br /><small>觸發：{report.alternative_scenario.trigger}</small></dd>
      <dt>確認</dt><dd>{report.confirmation}</dd>
      <dt>失效</dt><dd>{report.invalidation.condition}（<b className="mono-num">{price(report.invalidation.price)}</b>）</dd>
      {report.news_context ? <><dt>新聞脈絡</dt><dd>{report.news_context}</dd></> : null}
    </dl>
    <p className="daily-report-foot">框架 {report.framework_version}・新聞只是輸入之一，方向以價格結構確認為準。條件式價位不是下單指令。</p>
  </section>;
};
