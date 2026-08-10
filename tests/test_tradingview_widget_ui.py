from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "src" / "components" / "stock" / "TradingViewChart.tsx"
STOCK_DETAIL = ROOT / "src" / "components" / "stock" / "StockDetail.tsx"
APP = ROOT / "src" / "App.tsx"
TYPES = ROOT / "src" / "types.ts"


def _read(path: Path) -> str:
    assert path.exists(), f"{path.relative_to(ROOT)} is missing"
    return path.read_text(encoding="utf-8")


def test_tradingview_widget_uses_fixed_official_script_and_exact_config() -> None:
    source = _read(COMPONENT)

    assert "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js" in source
    assert "autosize: true" in source
    assert "interval: 'D'" in source
    assert "timezone: 'exchange'" in source
    assert "theme: 'dark'" in source
    assert "style: '1'" in source
    assert "allow_symbol_change: false" in source
    assert "locale: 'zh_TW'" in source
    assert "support_host: 'https://www.tradingview.com'" in source
    assert re.search(r"symbol:\s*`\$\{safeExchange\}:\$\{safeCode\}`", source)
    assert "JSON.stringify(config)" in source
    assert "dangerouslySetInnerHTML" not in source


def test_tradingview_widget_allows_only_safe_twse_tpex_symbols() -> None:
    source = _read(COMPONENT)

    assert "exchange: 'TWSE' | 'TPEX' | null" in source
    assert "exchange === 'TWSE' || exchange === 'TPEX'" in source
    assert "SAFE_SYMBOL_PATTERN" in source
    assert re.search(r"SAFE_SYMBOL_PATTERN\s*=\s*/\^\[A-Z0-9\]\{1,12\}\$/", source)
    assert "TWSE:2330" in source
    assert "TPEX:6488" in source


def test_tradingview_widget_cleans_up_bounded_lifecycle_resources() -> None:
    source = _read(COMPONENT)

    assert "setTimeout" in source
    assert "10000" in source
    assert "clearTimeout" in source
    assert "MutationObserver" in source
    assert "observer.disconnect()" in source
    assert "container.textContent = ''" in source
    assert "script.remove()" in source
    assert "setWidgetReady(false)" in source
    assert "setWidgetFailed(false)" in source


def test_stock_detail_adds_lazy_technical_tab_after_fundamentals() -> None:
    detail = _read(STOCK_DETAIL)
    app = _read(APP)
    types = _read(TYPES)

    assert "technical" in re.search(r"export type StockTab = ([^;]+);", types).group(1)
    assert "TradingViewChart" in detail
    assert "基本面分析" in detail
    assert "K 線／技術面" in detail
    assert detail.index("基本面分析") < detail.index("K 線／技術面")
    assert "tab === 'technical'" in detail
    assert "tab === 'technical' ? <TradingViewChart" in detail
    assert "stock-technical-panel" in detail
    assert "const technicalExchange = exchange === 'TWSE' || exchange === 'TPEX' ? exchange : null" in detail
    assert "params.get('tab') === 'technical' ? 'technical'" in app
    assert "route.tab === 'technical'" in app


def test_tradingview_fallback_copy_is_visible_without_blocking_other_tabs() -> None:
    source = _read(COMPONENT)
    detail = _read(STOCK_DETAIL)

    assert "TradingView 圖表暫時無法載入" in source
    assert "TWSE:2330" in source
    assert "TPEX:6488" in source
    assert "fundamentals ? <>" in detail
    assert "tab === 'flows'" in detail
    assert "tab === 'broker'" in detail
