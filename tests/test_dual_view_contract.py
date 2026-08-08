"""Regression checks for the mobile/classic data and safety contract."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_FILES = (
    "latest-24h.json",
    "latest-24h-all.json",
    "waytoagi-7d.json",
    "source-status.json",
    "daily-brief.json",
    "stories-merged.json",
)


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_both_views_share_data_source_override_contract():
    for path in ("assets/app.js", "classic/assets/app.js"):
        source = read(path)
        assert 'get("data")' in source
        assert 'localStorage.getItem("dataBaseUrl")' in source
        assert "function dataUrl(path)" in source
        for filename in DATA_FILES:
            assert filename in source


def test_view_router_preserves_data_parameter_between_surfaces():
    source = read("assets/view-mode.js")
    assert 'passthrough.delete("view")' in source
    assert 'passthrough.delete("data")' not in source


def test_both_views_apply_same_last_mile_content_safety_gate():
    for path in ("assets/app.js", "classic/assets/app.js"):
        source = read(path)
        assert "UNSAFE_HARD_PATTERNS" in source
        assert "UNSAFE_PROMO_PATTERNS" in source
        assert "function safeItems(items)" in source
        assert "function isUnsafeStory(story)" in source


def test_react_entrypoint_exposes_the_responsive_app_shell():
    source = read("index.html")

    assert '<html lang="zh-TW">' in source
    assert '<div id="root"></div>' in source
    assert '<script type="module" src="/src/main.tsx"></script>' in source
    assert 'data-radar-view-target=' not in source
    assert "assets/view-mode.js" not in source


def test_runtime_header_owns_status_and_navigation_content():
    app = read("src/App.tsx")

    assert "<NavTabBar" in app
    assert "<StatusBar" in app
    assert "generatedAt={radarData?.themeRanking.generated_at}" in app
    assert "sourceStatusOk={radarData ? radarData.sourceStatus.failed_count === 0 : true}" in app
    assert "showLoader = !radarData && !loadError" in app


def test_responsive_shell_keeps_the_nexus_identity_and_mobile_breakpoint():
    html = read("index.html")
    css = read("src/index.css")

    assert "NEXUS 台股題材雷達" in html
    assert "@media (max-width: 720px)" in css
    assert "mobile-bottom-nav" in css
    assert "min-width: 44px" in css


def test_classic_header_does_not_animate_the_view_switch_container():
    source = read("classic/assets/motion.js")

    assert 'addFrom(".hero-headline"' not in source
    assert 'addFrom(".hero-meta"' not in source


def test_mobile_is_the_versioned_default_view():
    source = read("assets/view-mode.js")

    assert 'const STORAGE_KEY = "aiNewsRadarViewV2"' in source
    assert 'const LEGACY_STORAGE_KEY = "aiNewsRadarView"' in source
    assert 'const MOBILE_OVERRIDE_KEY = "aiNewsRadarMobileViewOnce"' in source
    assert 'const MOBILE_BREAKPOINT = "(max-width: 760px)"' in source
    assert "const isMobileViewport = window.matchMedia(MOBILE_BREAKPOINT).matches" in source
    assert 'const mobileOverride = isMobileViewport ? readMobileOverride() : ""' in source
    assert "const preference = isMobileViewport" in source
    assert "? mobileOverride" in source
    assert 'const deviceDefault = "mobile"' in source


def test_mobile_classic_choice_is_one_navigation_only():
    source = read("assets/view-mode.js")

    assert "function readMobileOverride()" in source
    assert "window.sessionStorage.removeItem(MOBILE_OVERRIDE_KEY)" in source
    assert "function writeMobileOverride(view)" in source
    assert "writeMobileOverride(view)" in source
