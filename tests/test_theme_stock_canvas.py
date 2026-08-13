from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_home_theme_stocks_use_fallback_data_and_open_canvas() -> None:
    source = (ROOT / "src/components/common/ThemeCarousel.tsx").read_text()

    assert "mergeInstrumentRefs" in source
    assert "ThemeStocksCanvas" in source
    assert "setCanvasOpen(true)" in source


def test_momentum_theme_stocks_restore_ranking_symbols_and_expand() -> None:
    source = (ROOT / "src/components/momentum/ThemeMomentum.tsx").read_text()

    assert "mergeInstrumentRefs" in source
    assert 'className="more-chip mono-num"' in source
    assert "ThemeStocksCanvas" in source


def test_theme_stock_canvas_is_scrollable_and_home_preview_keeps_two_rows() -> None:
    component = (ROOT / "src/components/common/ThemeStocksCanvas.tsx").read_text()
    css = (ROOT / "src/index.css").read_text()

    assert "createPortal" in component
    assert "theme-stocks-canvas-scroll" in component
    assert ".theme-stocks-canvas-scroll" in css
    assert "min-height: 82px" in css
