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


def test_search_priority_is_five_tier_deterministic_and_bounded() -> None:
    source = _read(COMPONENT)

    for tier in (
        "symbol-exact",
        "name-exact",
        "symbol-prefix",
        "name-prefix",
        "name-contains",
    ):
        assert tier in source
    assert "SEARCH_RESULT_LIMIT = 30" in source
    assert ".slice(0, SEARCH_RESULT_LIMIT)" in source
    assert "localeCompare" in source
    assert "instrument.instrument_id" in source
    assert "selected_top50" in source


def test_short_and_long_render_payload_order_without_score_recalculation() -> None:
    source = _read(COMPONENT)

    assert "payload.short.items" in source
    assert "payload.long.items" in source
    assert not re.search(r"(short|long)\.items\.sort|sort\([^)]*score", source)
    assert "short.score *" not in source
    assert "long.score *" not in source
    assert "Math.round(item.short.score)" in source
    assert "Math.round(item.long.score)" in source
    assert "rank" in source


def test_short_heat_metric_uses_pipeline_theme_attention_component() -> None:
    source = _read(COMPONENT)

    assert "item.short.components.theme_attention.normalized" in source
    assert "題材關注度資料不足" in source
    assert "item.themes[0]?.heat_score" not in source


def test_missing_values_flags_and_failure_states_are_visible() -> None:
    source = _read(COMPONENT)

    assert "formatMaybePercent" in source
    assert "missingReasons" in source
    assert "overnight_missing_reason" in source
    assert "隔日衝資料不足" in source
    assert "reason === 'no reliable overnight source' ? '隔日衝資料不足'" in source
    assert "—" in source
    assert "missingReasons[0]" not in source

    for flag in (
        "heat_rising",
        "multi_theme",
        "institutional_positive",
        "fundamentals_improving",
        "high_daytrade",
        "overnight_risk",
        "cashflow_weak",
        "high_leverage",
        "data_sparse",
    ):
        assert flag in source

    assert "watchlist-skeleton-row" in source
    assert "個股雷達暫時無法載入" in source
    assert "重新載入" in source
    assert "回題材雷達" in source
    assert "請輸入代號或公司名稱" in source
    assert "找不到「" in source
    assert "目前沒有可顯示的個股雷達資料" in source


def test_accessibility_and_responsive_markers_exist() -> None:
    source = _read(COMPONENT)
    css = _read(CSS)

    assert 'role="tablist"' in source
    assert 'role="tab"' in source
    assert "aria-selected" in source
    assert 'aria-live="polite"' in source
    assert "onKeyDown={handleTabKeyDown}" in source
    assert "ArrowRight" in source
    assert "ArrowLeft" in source
    assert "tabIndex={0}" in source
    assert "onKeyDown={(event) => handleRowKeyDown(event, item.instrument)}" in source
    assert 'className="watchlist-mobile-card"\n          role="link"' in source
    assert "onClick={() => onGoStock(item.instrument.symbol, item.instrument.exchange)}" in source

    for class_name in (
        "watchlist-page",
        "watchlist-tabs",
        "watchlist-table",
        "watchlist-row",
        "watchlist-mobile-card",
        "watchlist-metric-grid",
        "watchlist-no-horizontal-scroll",
    ):
        assert class_name in source
        assert class_name in css


def test_disclaimer_and_stock_navigation_contract() -> None:
    source = _read(COMPONENT)

    assert "關注分數衡量題材、籌碼與基本面訊號強度" in source
    assert "不構成投資建議" in source
    assert "查看分析" in source
    assert "onGoStock(item.instrument.symbol, item.instrument.exchange)" in source


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
