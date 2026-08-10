import React, { useEffect, useMemo, useRef, useState } from 'react';

const TRADINGVIEW_SCRIPT_URL = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
const SAFE_SYMBOL_PATTERN = /^[A-Z0-9]{1,12}$/;

interface TradingViewChartProps {
  code: string;
  exchange: 'TWSE' | 'TPEX' | null;
  className?: string;
}

export const TradingViewChart: React.FC<TradingViewChartProps> = ({ code, exchange, className = '' }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [widgetReady, setWidgetReady] = useState(false);
  const [widgetFailed, setWidgetFailed] = useState(false);
  const safeCode = useMemo(() => code.trim().toUpperCase(), [code]);
  const safeExchange = exchange === 'TWSE' || exchange === 'TPEX' ? exchange : null;
  const isValidSymbol = safeExchange !== null && SAFE_SYMBOL_PATTERN.test(safeCode);
  const tradingViewUrl = isValidSymbol
    ? `https://www.tradingview.com/symbols/${safeExchange}-${safeCode}/`
    : 'https://www.tradingview.com/markets/stocks-taiwan/';

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    setWidgetReady(false);
    setWidgetFailed(false);
    container.textContent = '';

    if (!isValidSymbol || !safeExchange) {
      setWidgetFailed(true);
      return () => {
        container.textContent = '';
      };
    }

    const widget = document.createElement('div');
    widget.className = 'tradingview-widget-container__widget';
    container.appendChild(widget);

    let timeoutId: number | undefined;
    const observer = new MutationObserver(() => {
      if (container.querySelector('iframe')) {
        if (timeoutId !== undefined) window.clearTimeout(timeoutId);
        setWidgetReady(true);
        setWidgetFailed(false);
      }
    });
    observer.observe(container, { childList: true, subtree: true });

    const config = {
      autosize: true,
      symbol: `${safeExchange}:${safeCode}`,
      interval: 'D',
      timezone: 'exchange',
      theme: 'dark',
      style: '1',
      locale: 'zh_TW',
      allow_symbol_change: false,
      support_host: 'https://www.tradingview.com'
    };
    const script = document.createElement('script');
    script.type = 'text/javascript';
    script.async = true;
    script.src = TRADINGVIEW_SCRIPT_URL;
    script.text = JSON.stringify(config);
    container.appendChild(script);

    timeoutId = window.setTimeout(() => {
      if (!container.querySelector('iframe')) setWidgetFailed(true);
    }, 10000);

    return () => {
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
      observer.disconnect();
      script.remove();
      container.textContent = '';
    };
  }, [isValidSymbol, safeCode, safeExchange]);

  return (
    <section className={className || 'stock-technical-panel'}>
      <div className="stock-section-heading">
        <span className="page-kicker">TRADINGVIEW · K 線／技術面</span>
        <span className="section-note">日線 · {safeExchange ?? '市場缺值'}:{safeCode || '代號缺值'}</span>
      </div>
      <p className="tradingview-source-copy">圖表由 TradingView 提供；開啟本頁會連線至 TradingView。支援 TWSE:2330、TPEX:6488 格式。</p>
      <div className="tradingview-chart-shell">
        {!widgetReady && !widgetFailed ? <span className="tradingview-loading">TradingView 圖表載入中…</span> : null}
        {widgetFailed ? <div className="tradingview-fallback"><strong>TradingView 圖表暫時無法載入</strong><span>可改用下方連結查看此股票。</span></div> : null}
        <div className="tradingview-widget-container" ref={containerRef} aria-label={`${safeExchange ?? ''}:${safeCode} TradingView 圖表`} />
      </div>
      <a className="tradingview-direct-link" href={tradingViewUrl} target="_blank" rel="noopener noreferrer">前往 TradingView 查看 {safeExchange ?? ''}:{safeCode} ↗</a>
    </section>
  );
};
