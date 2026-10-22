import React, { useEffect, useMemo, useState } from 'react';
import { StockAuditChart } from './StockAuditChart';
import {
  StockAuditOperation,
  StockAuditReference,
  StockAuditReport,
  StockAuditStock,
  StockAuditTerm,
  fetchStockAudit
} from '../../services/stockAudit';
import { StockWatchlistData } from '../../types';
import './stock-audit.css';

export type WatchlistView = 'short' | 'long' | 'search';

export interface StockWatchlistProps {
  payload: StockWatchlistData | null;
  view: WatchlistView;
  query: string;
  onViewChange: (view: WatchlistView) => void;
  onQueryChange: (query: string) => void;
  onGoStock: (symbol: string, exchange: string) => void;
  loading?: boolean;
  error?: boolean;
  onRetry?: () => void;
  onGoHome?: () => void;
}

const TERMS: StockAuditTerm[] = ['短線', '中線', '長線'];

function formatPrice(value: number): string {
  return value.toLocaleString('zh-TW', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function formatNumber(value: number): string {
  return value.toLocaleString('zh-TW', { maximumFractionDigits: 2 });
}

function formatPercent(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`;
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat('zh-TW', {
    dateStyle: 'short',
    timeStyle: 'short',
    hour12: false,
    timeZone: 'Asia/Taipei'
  }).format(new Date(value));
}

function sourceHost(source: string): string {
  try {
    return new URL(source).hostname.replace(/^www\./, '');
  } catch {
    return source;
  }
}

function sourceLink(source: string, label = '來源'): React.ReactNode {
  return <a href={source} target="_blank" rel="noreferrer">{label} · {sourceHost(source)} ↗</a>;
}

const ReportSource: React.FC<{ source: string; asOf: string; label?: string }> = ({ source, asOf, label = '資料來源' }) => (
  <p className="stock-audit-source">
    <span>{label} · {formatTimestamp(asOf)}</span>
    {sourceLink(source)}
  </p>
);

const Metric: React.FC<{ label: string; value: React.ReactNode; note?: React.ReactNode; accent?: boolean }> = ({ label, value, note, accent = false }) => (
  <div className={`stock-audit-metric${accent ? ' is-accent' : ''}`}>
    <span>{label}</span>
    <strong>{value}</strong>
    {note ? <small>{note}</small> : null}
  </div>
);

const SectionHeader: React.FC<{ id: string; title: string; note?: string }> = ({ id, title, note }) => (
  <div className="stock-audit-section-header">
    <h3 id={id}>{title}</h3>
    {note ? <span className="mono-num">{note}</span> : null}
  </div>
);

const ForecastReference: React.FC<{ reference: StockAuditReference }> = ({ reference }) => (
  <article className="stock-audit-reference">
    <div className="stock-audit-reference-head">
      <strong>{reference.label}</strong>
      <span className={reference.change_pct >= 0 ? 'positive' : 'negative'}>{formatPercent(reference.change_pct)}</span>
    </div>
    <b className="stock-audit-reference-value mono-num">{formatNumber(reference.value)}</b>
    <small>{formatTimestamp(reference.as_of)}</small>
    {sourceLink(reference.source, '資料')}
  </article>
);

const Operations: React.FC<{ operations: StockAuditOperation[] }> = ({ operations }) => {
  const byTerm = useMemo(() => new Map(operations.map((operation) => [operation.term, operation])), [operations]);
  return (
    <div className="stock-audit-operations">
      {TERMS.map((term) => {
        const operation = byTerm.get(term);
        if (!operation) return null;
        return (
          <article className="stock-audit-operation" key={operation.term}>
            <header>
              <strong>{operation.term}</strong>
              <span>{operation.horizon}</span>
            </header>
            <dl>
              <div><dt>進場時機</dt><dd>{operation.timing}</dd></div>
              <div><dt>進場價</dt><dd className="mono-num">{formatPrice(operation.entry)}</dd></div>
              <div><dt>加碼條件</dt><dd>{operation.add_condition}</dd></div>
              <div><dt>加碼價</dt><dd className="mono-num">{formatPrice(operation.add)}</dd></div>
              <div><dt>止損價</dt><dd className="mono-num">{formatPrice(operation.stop)}</dd></div>
              <div><dt>停利價</dt><dd className="mono-num">{formatPrice(operation.take_profit)}</dd></div>
            </dl>
          </article>
        );
      })}
    </div>
  );
};

const Fundamentals: React.FC<{ stock: StockAuditStock }> = ({ stock }) => (
  <section className="stock-audit-detail-section" aria-labelledby={`${stock.symbol}-fundamentals`}>
    <SectionHeader id={`${stock.symbol}-fundamentals`} title="基本面分析" note={stock.fundamentals.period} />
    <div className="stock-audit-metric-grid">
      <Metric label="營收" value={`${formatNumber(stock.fundamentals.revenue)} ${stock.fundamentals.revenue_unit}`} note={stock.fundamentals.period} />
      <Metric label="EPS" value={formatNumber(stock.fundamentals.eps)} note={`TTM ${formatNumber(stock.fundamentals.ttm_eps)}`} />
      <Metric label="本益比 PE" value={`${formatNumber(stock.fundamentals.pe)}x`} note="最新估值" accent />
      <Metric
        label="估值相對位置"
        value={`${stock.valuation.percentile.toFixed(0)} 百分位`}
        note={`${stock.valuation.sample_count} 筆樣本 · ${stock.valuation.baseline_label}`}
      />
    </div>
    <div className="stock-audit-valuation-callout">
      <span>相對基準溢價</span>
      <strong className={stock.valuation.premium_pct > 0 ? 'status-delayed' : 'positive'}>{formatPercent(stock.valuation.premium_pct)}</strong>
      <small>基準 PE {formatNumber(stock.valuation.baseline_pe)}x · {stock.valuation.analysis}</small>
    </div>
    <p className="stock-audit-analysis">{stock.fundamentals.analysis}</p>
    <ReportSource source={stock.fundamentals.source} asOf={stock.fundamentals.as_of} label="財務資料" />
    <ReportSource source={stock.valuation.source} asOf={stock.price_as_of} label="歷史 PE" />
  </section>
);

const Technical: React.FC<{ stock: StockAuditStock }> = ({ stock }) => {
  const latestCandle = stock.technical.candles[stock.technical.candles.length - 1];
  return (
    <section className="stock-audit-detail-section" aria-labelledby={`${stock.symbol}-technical`}>
      <SectionHeader id={`${stock.symbol}-technical`} title="技術分析" note={`日線 · ${latestCandle.date}`} />
      <StockAuditChart symbol={stock.symbol} price={stock.price} technical={stock.technical} />
      <div className="stock-audit-metric-grid stock-audit-technical-metrics">
        <Metric label="現價" value={formatPrice(stock.price)} note={`報價 ${formatTimestamp(stock.price_as_of)}`} accent />
        <Metric label="MA20" value={formatPrice(stock.technical.ma20)} note="20 日均線" />
        <Metric label="MA60" value={formatPrice(stock.technical.ma60)} note="60 日均線" />
        <Metric label="支撐 / 壓力" value={`${formatPrice(stock.technical.support)} / ${formatPrice(stock.technical.resistance)}`} note="日線區間" />
      </div>
      <p className="stock-audit-analysis">{stock.technical.analysis}</p>
      <ReportSource source={stock.source} asOf={stock.price_as_of} label="行情資料" />
    </section>
  );
};

const QualitySummary: React.FC<{ stock: StockAuditStock }> = ({ stock }) => (
  <div className="stock-audit-quality">
    <div className="stock-audit-quality-heading">
      <strong>成長曲線品質檢查</strong>
      <span>選股後檢查 · 不作為基本面門檻</span>
    </div>
    <p>Sharpe、Sortino、TTR 與指數形狀只用於候選完成後的成長曲線品質檢查，不作為基本面分析的篩選條件。</p>
    <div className="stock-audit-quality-grid">
      <Metric label="Sharpe" value={stock.quality.sharpe.toFixed(2)} note={stock.quality.period} />
      <Metric label="Sortino" value={stock.quality.sortino.toFixed(2)} note={stock.quality.period} />
      <Metric label="TTR" value={`${stock.quality.ttr_days} 日`} note="回到高點所需時間" />
      <Metric label="指數形狀" value={stock.quality.index_shape} />
    </div>
    <p className="stock-audit-quality-method">計算方法 · {stock.quality.method}</p>
    <ReportSource source={stock.quality.source} asOf={stock.price_as_of} label="品質計算" />
  </div>
);

const StockAuditCard: React.FC<{ stock: StockAuditStock; index: number }> = ({ stock, index }) => (
  <details className="stock-audit-card" open={index === 0}>
    <summary>
      <span className="stock-audit-card-identity">
        <span className="stock-audit-card-index mono-num">{String(index + 1)}</span>
        <span><strong>{stock.name}</strong><small className="mono-num">{stock.symbol}</small></span>
      </span>
      <span className="stock-audit-card-price"><strong className="mono-num">{formatPrice(stock.price)}</strong><small>{formatTimestamp(stock.price_as_of)}</small></span>
    </summary>
    <div className="stock-audit-card-content">
      <div className="stock-audit-card-source">{sourceLink(stock.source, '報價來源')}</div>
      <Fundamentals stock={stock} />
      <Technical stock={stock} />
      <section className="stock-audit-detail-section" aria-labelledby={`${stock.symbol}-operations`}>
        <SectionHeader id={`${stock.symbol}-operations`} title="操作" note="條件式情境" />
        <p className="stock-audit-section-lead">短線、中線、長線分開列出進場、加碼、止損與停利價格；僅在條件成立時執行。</p>
        <Operations operations={stock.operations} />
      </section>
      <section className="stock-audit-detail-section" aria-labelledby={`${stock.symbol}-summary`}>
        <SectionHeader id={`${stock.symbol}-summary`} title="總結" />
        <p className="stock-audit-summary">{stock.summary}</p>
        <QualitySummary stock={stock} />
      </section>
    </div>
  </details>
);

const LoadingState: React.FC = () => (
  <section className="watchlist-state stock-audit-state" aria-live="polite">
    <span className="stock-audit-loading-line watchlist-skeleton-row" />
    <span className="stock-audit-loading-line watchlist-skeleton-row" />
    <p>正在載入本期報告</p>
  </section>
);

const ErrorState: React.FC<{ onRetry?: () => void; onGoHome?: () => void }> = ({ onRetry, onGoHome }) => (
  <section className="watchlist-state stock-audit-state">
    <h2>本期報告無法載入</h2>
    <p>請稍後再試。</p>
    <div>
      {onRetry ? <button type="button" onClick={onRetry}>重新載入</button> : null}
      {onGoHome ? <button type="button" onClick={onGoHome}>回題材雷達</button> : null}
    </div>
  </section>
);

export const StockWatchlist: React.FC<StockWatchlistProps> = ({ onRetry, onGoHome }) => {
  const [report, setReport] = useState<StockAuditReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [requestKey, setRequestKey] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    fetchStockAudit(requestKey > 0)
      .then((nextReport) => {
        if (active) setReport(nextReport);
      })
      .catch(() => {
        if (active) {
          setReport(null);
          setError(true);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [requestKey]);

  const handleRetry = () => {
    setRequestKey((key) => key + 1);
    onRetry?.();
  };

  return (
    <div className="page-content stock-audit-page watchlist-page watchlist-no-horizontal-scroll">
      {loading ? <LoadingState /> : null}
      {error && !loading ? <ErrorState onRetry={handleRetry} onGoHome={onGoHome} /> : null}
      {!loading && !error && report ? (
        <>
          <header className="page-intro stock-audit-intro">
            <span className="stock-audit-kicker">Stock Audit · {report.report_date}</span>
            <h1>個股稽核報告</h1>
            <div className="gold-rule" />
            <p>先看今日結論，再看明日市場參照與候選細節；本頁只呈現具備來源與時間戳的標的。</p>
            <p className="stock-audit-generated">報告時間 · {formatTimestamp(report.generated_at)}</p>
          </header>
          <main className="stock-audit-report">
            <section className="stock-audit-section stock-audit-conclusion" aria-labelledby="stock-audit-conclusion-title">
              <div className="stock-audit-section-header"><h2 id="stock-audit-conclusion-title">今日結論</h2><span className="mono-num">{report.report_date}</span></div>
              <p className="stock-audit-conclusion-copy">{report.conclusion}</p>
            </section>
            <section className="stock-audit-section stock-audit-forecast" aria-labelledby="stock-audit-forecast-title">
              <div className="stock-audit-section-header"><h2 id="stock-audit-forecast-title">明日台股預測</h2><span className="mono-num">{report.forecast ? formatTimestamp(report.forecast.as_of) : '—'}</span></div>
              {report.forecast ? (
                <>
                  <p className="stock-audit-forecast-summary">{report.forecast.summary}</p>
                  <div className="stock-audit-reference-grid">{report.forecast.references.map((reference) => <ForecastReference key={`${reference.label}-${reference.as_of}`} reference={reference} />)}</div>
                </>
              ) : <p className="stock-audit-empty">本期不提供方向預測。</p>}
            </section>
            <section className="stock-audit-section stock-audit-candidates" aria-labelledby="stock-audit-candidates-title">
              <div className="stock-audit-section-header"><h2 id="stock-audit-candidates-title">重點標的</h2><span className="mono-num">{report.stocks.length} 檔</span></div>
              {report.stocks.length > 0 ? <div className="stock-audit-card-list">{report.stocks.map((stock, index) => <StockAuditCard key={stock.symbol} stock={stock} index={index} />)}</div> : <p className="stock-audit-empty">本期沒有可列出的標的。</p>}
            </section>
          </main>
          <p className="disclaimer stock-audit-disclaimer">本報告提供資料與條件式情境，不構成投資建議。</p>
        </>
      ) : null}
    </div>
  );
};
