import { createPortal } from 'react-dom';
import React, { useEffect } from 'react';
import { ThemeStockEntry } from '../../lib/themeStocks';

interface ThemeStocksCanvasProps {
  themeName: string;
  stocks: ThemeStockEntry[];
  onClose: () => void;
}

export const ThemeStocksCanvas: React.FC<ThemeStocksCanvasProps> = ({ themeName, stocks, onClose }) => {
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', closeOnEscape);
    };
  }, [onClose]);

  const direct = stocks.filter((stock) => stock.kind === 'direct');
  const supply = stocks.filter((stock) => stock.kind === 'supply');
  const groups = [
    { key: 'direct', label: '直接提及', stocks: direct },
    { key: 'supply', label: '供應鏈候選', stocks: supply }
  ].filter((group) => group.stocks.length);

  return createPortal(
    <div
      className="theme-stocks-canvas-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section className="theme-stocks-canvas" role="dialog" aria-modal="true" aria-labelledby="theme-stocks-canvas-title">
        <header className="theme-stocks-canvas-header">
          <div>
            <span className="page-kicker">THEME STOCKS · 題材個股</span>
            <h2 id="theme-stocks-canvas-title">{themeName} · 題材股票</h2>
            <p>全部標的已直接展開；內容較多時可在畫布內向下捲動，不需要再進入個股頁。</p>
          </div>
          <button type="button" className="theme-stocks-canvas-close" aria-label="關閉題材股票畫布" onClick={onClose}>×</button>
        </header>
        <div className="theme-stocks-canvas-scroll">
          {groups.length ? groups.map((group) => (
            <section className="theme-stocks-canvas-group" key={group.key}>
              <div className="theme-stocks-canvas-group-heading"><strong>{group.label}</strong><span>{group.stocks.length} 檔</span></div>
              <div className="theme-stocks-canvas-list">
                {group.stocks.map(({ instrument, kind }) => (
                  <article className={`theme-stocks-canvas-item ${kind}`} key={`${kind}-${instrument.instrument_id}`}>
                    <b className="mono-num">{instrument.symbol}</b>
                    <span>{instrument.name_zh}</span>
                  </article>
                ))}
              </div>
            </section>
          )) : <p className="theme-stocks-canvas-empty">目前沒有可顯示的題材股票。</p>}
        </div>
        <footer className="theme-stocks-canvas-footer">共 {stocks.length} 檔標的 · 題材股票來自公開彙總</footer>
      </section>
    </div>,
    document.body,
  );
};
