from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _function_body(source: str, name: str) -> str:
    match = re.search(rf"(?:async\s+)?function\s+{name}\s*\([^)]*\)\s*\{{", source)
    assert match, f"{name} declaration missing"
    start = match.end()
    depth = 1
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index]
    raise AssertionError(f"{name} body is incomplete")


def test_page_is_public_local_and_defaults_to_72_hours() -> None:
    html = (ROOT / "theme-momentum.html").read_text(encoding="utf-8")

    assert '<html lang="zh-TW">' in html
    assert 'href="./assets/theme-momentum.css"' in html
    assert 'src="./assets/theme-momentum.js"' in html
    assert 'data-range-hours="24"' in html
    assert 'data-range-hours="72"' in html
    assert 'data-range-hours="168"' in html
    assert re.search(r'data-range-hours="72"[^>]+aria-pressed="true"', html)
    assert 'id="momentumStatus"' in html and 'aria-live="polite"' in html
    assert 'id="historyTable"' in html
    assert 'id="momentumChart"' in html
    assert "login" not in html.casefold()


def test_browser_fetches_only_the_two_public_static_payloads() -> None:
    source = (ROOT / "assets" / "theme-momentum.js").read_text(encoding="utf-8")

    assert '"./data/public-theme-momentum-latest-v0.9.json"' in source
    assert '"./data/public-theme-momentum-history-v0.9.json"' in source
    assert "fetch(url" in source
    for forbidden in (
        "supabase",
        "theme_radar.hourly_theme_heat",
        "service_role",
        "postgres://",
        "postgresql://",
        "producer_run_id",
    ):
        assert forbidden not in source.casefold()


def test_ui_preserves_producer_order_and_names_every_required_state() -> None:
    source = (ROOT / "assets" / "theme-momentum.js").read_text(encoding="utf-8")
    render_latest = _function_body(source, "renderLatest")

    assert ".sort(" not in render_latest
    for state in (
        "loading",
        "empty",
        "partial",
        "stale",
        "latest-error",
        "history-error",
        "mixed-version",
        "gap",
        "accumulating",
    ):
        assert state in source
    assert "splitSeriesAtGaps" in source
    assert "setRange" in source


def test_page_and_styles_include_accessibility_and_responsive_contracts() -> None:
    html = (ROOT / "theme-momentum.html").read_text(encoding="utf-8")
    css = (ROOT / "assets" / "theme-momentum.css").read_text(encoding="utf-8")

    assert 'class="skip-link"' in html
    assert 'role="group"' in html
    assert 'aria-label="題材動能時間範圍"' in html
    assert 'role="img"' in html
    assert "caption" in html
    assert ":focus-visible" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "@media (max-width: 640px)" in css
    assert "min-width: 320px" in css
    assert "overflow-x: auto" in css


def test_homepage_adds_only_the_approved_momentum_destination() -> None:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert html.count('href="./theme-momentum.html"') == 2
    assert re.search(
        r'class="hero-link"\s+href="\./theme-momentum\.html"',
        html,
    )
    assert re.search(
        r'class="theme-momentum-entry"[^>]+href="\./theme-momentum\.html"',
        html,
    )
    assert "題材動能" in html


def test_both_pages_accept_exactly_the_fields_the_materializer_emits() -> None:
    """Homepage and momentum page must agree with the producer on history fields.

    Both validators match keys exactly, so a field required by one and absent
    from the producer fails closed forever. app.js required observation_provenance
    while materialize_public_theme_history never selected it and theme-momentum.js
    rejected it -- a contradiction no page could satisfy at once. It stayed
    invisible because the database path was unreachable, so history was always
    empty and neither validator ever saw a populated observation.
    """

    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from materialize_public_theme_history import PUBLIC_THEME_FIELD_ORDER

    produced = set(PUBLIC_THEME_FIELD_ORDER)

    def declared_keys(source: str, marker: str) -> set[str]:
        start = source.index(marker)
        block = source[start : source.index("]", start)]
        return set(re.findall(r'"([a-z_]+)"', block))

    momentum = (ROOT / "assets" / "theme-momentum.js").read_text(encoding="utf-8")
    history_block = momentum[momentum.index("history theme fields are invalid") - 2000 :]
    momentum_keys = declared_keys(history_block, "const themeKeys = [")

    homepage = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    homepage_keys = declared_keys(
        homepage, "function validateHomepageMomentumHistoryTheme"
    )

    assert momentum_keys == produced, (
        "theme-momentum.js history fields drifted from the materializer: "
        f"extra={sorted(momentum_keys - produced)} missing={sorted(produced - momentum_keys)}"
    )
    assert homepage_keys == produced, (
        "app.js history fields drifted from the materializer: "
        f"extra={sorted(homepage_keys - produced)} missing={sorted(produced - homepage_keys)}"
    )


def test_javascript_is_syntactically_valid() -> None:
    completed = subprocess.run(
        ["node", "--check", str(ROOT / "assets" / "theme-momentum.js")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
