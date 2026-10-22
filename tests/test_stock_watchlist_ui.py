from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "src" / "components" / "watchlist" / "StockWatchlist.tsx"
APP = ROOT / "src" / "App.tsx"
NAV = ROOT / "src" / "components" / "common" / "NavTabBar.tsx"
SERVICE = ROOT / "src" / "services" / "dataService.ts"
TYPES = ROOT / "src" / "types.ts"
CSS = ROOT / "src" / "index.css"


def _read(path: Path) -> str:
    assert path.exists(), f"{path.relative_to(ROOT)} is missing"
    return path.read_text(encoding="utf-8")


def test_component_exports_controlled_watchlist_contract() -> None:
    source = _read(COMPONENT)

    assert "export interface StockWatchlistProps" in source
    assert "payload: StockWatchlistData | null" in source
    assert "view: WatchlistView" in source
    assert "query: string" in source
    assert "onViewChange: (view: WatchlistView) => void" in source
    assert "onQueryChange: (query: string) => void" in source
    assert "onGoStock: (symbol: string, exchange: string) => void" in source
    assert "loading?: boolean" in source
    assert "error?: boolean" in source
    assert "onRetry?: () => void" in source
    assert "onGoHome?: () => void" in source
    assert "export type WatchlistView = 'short' | 'long' | 'search'" in source


def test_route_nav_and_loader_are_isolated_from_existing_radar_data() -> None:
    app = _read(APP)
    nav = _read(NAV)
    service = _read(SERVICE)
    types = _read(TYPES)

    assert "watchlist" in re.search(r"export type PageType = ([^;]+);", types).group(1)
    assert "fetchStockWatchlist" in service
    assert "./data/public-stock-watchlist-v1.json" in service
    assert "fetchStockWatchlist()" in app
    assert "setWatchlistError(true)" in app
    assert "loadRadarData()" in app
    assert "Promise.all([" not in app.partition("fetchStockWatchlist()")[0]
    assert "page: ['index', 'momentum', 'flows', 'watchlist', 'stock', 'sources']" in app
    assert "const view: WatchlistView = params.get('view') === 'long' ? 'long' : params.get('view') === 'search' ? 'search' : 'short'" in app
    assert "q: view === 'search' ? params.get('q') ?? '' : ''" in app
    assert "const exchange = params.get('exchange')" in app
    assert "exchange: exchange === 'TWSE' || exchange === 'TPEX' ? exchange : undefined" in app
    assert "updateWatchlistHash" in app
    assert "window.location.hash = params.toString()" in app
    assert "window.history.replaceState(null, '', nextHash)" in app
    assert "setRoute(readRoute())" in app
    assert "route.page !== 'watchlist' && !radarData && !loadError" in app
    assert "route.page !== 'watchlist' && (loadError" in app
    assert "{ id: 'watchlist', label: '個股雷達' }" in nav


def test_mobile_nav_keeps_the_feedback_action_visible() -> None:
    nav = _read(NAV)
    css = _read(CSS)

    assert 'className="nav-feedback-mobile"' in nav
    assert 'href="https://forms.gle/KwFAL59UjcnEBCNj6"' in nav
    assert re.search(
        r"\.main-nav \.nav-feedback-mobile\s*\{[^}]*display:\s*inline-flex;",
        css,
        re.DOTALL,
    )
    assert re.search(
        r"\.app-root\.is-mobile \.main-nav \.nav-feedback-mobile\s*\{[^}]*display:\s*inline-flex;",
        css,
        re.DOTALL,
    )


def test_stock_audit_renders_fixed_order_and_one_expandable_detail() -> None:
    source = _read(COMPONENT)

    section_order = (
        source.index('id="stock-audit-conclusion-title"'),
        source.index('id="stock-audit-forecast-title"'),
        source.index('id="stock-audit-candidates-title"'),
    )
    assert section_order == tuple(sorted(section_order))
    assert '<details className="stock-audit-card"' in source

    detail_order = (
        source.index('title="基本面分析"'),
        source.index('title="技術分析"'),
        source.index('title="操作"'),
        source.index('title="總結"'),
    )
    assert detail_order == tuple(sorted(detail_order))
    assert 'open={index === 0}' in source
    assert 'aria-labelledby' in source


def test_stock_audit_fields_and_quality_semantics_are_visible() -> None:
    source = _read(COMPONENT)
    chart = _read(ROOT / "src" / "components" / "watchlist" / "StockAuditChart.tsx")

    for marker in (
        '現價', '資料來源', '營收', 'EPS', '本益比 PE', '估值相對位置',
        '相對基準溢價', '進場時機', '加碼條件', '止損價', '停利價',
        'Sharpe', 'Sortino', 'TTR', '指數形狀',
        '不作為基本面門檻',
    ):
        assert marker in source
    for marker in ('OHLCV', 'MA20', 'MA60', '支撐', '壓力', '成交量', 'viewBox'):
        assert marker in chart
    assert '本期不提供方向預測。' in source
    assert 'pending verification' not in source.lower()
    assert 'incomplete' not in source.lower()
    assert '未完成' not in source


def test_stock_audit_fetch_and_contract_fail_closed_at_browser_boundary() -> None:
    service = _read(ROOT / "src" / "services" / "stockAudit.ts")

    for marker in (
        "STOCK_AUDIT_DATA_PATH = './data/stock-audit-latest.json'",
        'STOCK_AUDIT_SCHEMA_VERSION',
        'validateStockAuditReport',
        'isStockAuditStock',
        '.filter(isStockAuditStock)',
        "cache: 'no-store'",
        'REQUIRED_REFERENCE_GROUPS',
        'source_receipts',
        'operationsOrdered',
        'Math.abs(value.valuation.premium_pct - premium)',
        'Math.abs(value.technical.ma20 - ma20)',
        'Math.abs(value.technical.ma60 - ma60)',
    ):
        assert marker in service


def test_stock_audit_screen_is_mobile_first_and_touch_safe() -> None:
    source = _read(COMPONENT)
    css = _read(ROOT / "src" / "components" / "watchlist" / "stock-audit.css")

    assert 'className="page-content stock-audit-page' in source
    assert 'className="stock-audit-card"' in source
    assert 'className="watchlist-mobile-card"' not in source
    assert 'className="watchlist-table"' not in source
    assert 'min-height: 44px' in css
    assert 'grid-template-columns: repeat(2, minmax(0, 1fr))' in css
    assert '@media (min-width: 721px)' in css
    assert 'linear-gradient' not in css
    assert 'overflow-x: hidden' in css


def test_frontend_guard_checks_nested_exact_contract_and_rank_invariants() -> None:
    service = _read(SERVICE)

    for marker in (
        "WATCHLIST_SEARCHABLE_KEYS",
        "WATCHLIST_INSTRUMENT_KEYS",
        "WATCHLIST_THEME_KEYS",
        "WATCHLIST_SCORE_COMPONENT_KEYS",
        "WATCHLIST_FLAG_KEYS",
        "WATCHLIST_LIST_KEYS",
        "WATCHLIST_TOP_COVERAGE_KEYS",
        "WATCHLIST_RISK_ADJUSTMENT_KEYS",
        "WATCHLIST_RISK_ENTRY_KEYS",
        "WATCHLIST_SOURCES_KEYS",
        "WATCHLIST_METHODOLOGY_KEYS",
        "WATCHLIST_DAY_TRADING_SOURCE_KEYS",
        "WATCHLIST_SHORT_COMPONENT_KEYS",
        "WATCHLIST_LONG_COMPONENT_KEYS",
        "WATCHLIST_FLAG_NAMES",
    ):
        assert marker in service
    assert "hasExactKeys(item, WATCHLIST_SEARCHABLE_KEYS)" in service
    assert "hasExactKeys(value, WATCHLIST_INSTRUMENT_KEYS)" in service
    assert "hasExactKeys(value, WATCHLIST_THEME_KEYS)" in service
    assert "hasExactKeys(value, WATCHLIST_SCORE_COMPONENT_KEYS)" in service
    assert "hasExactKeys(value, WATCHLIST_FLAG_KEYS)" in service
    assert "hasExactKeys(value.short, WATCHLIST_LIST_KEYS)" in service
    assert "hasExactKeys(value.long, WATCHLIST_LIST_KEYS)" in service
    assert "hasExactKeys(value.coverage, WATCHLIST_TOP_COVERAGE_KEYS)" in service
    assert "hasExactKeys(value.sources, WATCHLIST_SOURCES_KEYS)" in service
    assert "hasExactKeys(value.methodology, WATCHLIST_METHODOLOGY_KEYS)" in service
    assert "hasExactKeys(value.components, expectedComponents)" in service
    assert "isScoreSummary(item.short, true)" in service
    assert "isScoreSummary(item.long, false)" in service
    assert "hasExactKeys(value, WATCHLIST_RISK_ADJUSTMENT_KEYS)" in service
    assert "hasExactKeys(entry, WATCHLIST_RISK_ENTRY_KEYS)" in service
    assert "shortIds" in service
    assert "longIds" in service
    assert "index + 1" in service
