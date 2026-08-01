from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BLOCK_START = "const HOMEPAGE_MOMENTUM_CONTRACT = Object.freeze({"
BLOCK_END = "const PUBLIC_THEME_RANKING_CONTRACT = Object.freeze({"


def _homepage_momentum_source() -> str:
    source = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    assert BLOCK_START in source, "homepage momentum entry implementation block missing"
    assert BLOCK_END in source, "public theme ranking boundary missing"
    return source[source.index(BLOCK_START) : source.index(BLOCK_END)]


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


def test_homepage_has_one_primary_card_and_preserves_secondary_link() -> None:
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    assert html.count('href="./theme-momentum.html"') == 2
    assert html.count('class="theme-momentum-entry"') == 1
    assert re.search(
        r'<a\s+class="theme-momentum-entry"\s+id="themeMomentumEntry"'
        r'\s+href="\./theme-momentum\.html"\s+aria-busy="true"\s*>',
        html,
    )
    assert re.search(
        r'class="hero-link"\s+href="\./theme-momentum\.html"',
        html,
    )
    assert html.index('id="themeMomentumEntry"') < html.index(
        'id="publicThemeRankingWrap"'
    )
    assert "追蹤熱門題材走勢" in html
    assert "開啟完整動能儀表板" in html
    for element_id in (
        "themeMomentumEntryTitle",
        "themeMomentumEntryDescription",
        "themeMomentumEntryData",
        "themeMomentumEntryUpdatedAt",
        "themeMomentumEntryWindows",
    ):
        assert f'id="{element_id}"' in html


def test_card_uses_only_approved_payloads_and_has_explicit_fallback() -> None:
    source = _homepage_momentum_source()
    loader = _function_body(source, "loadHomepageMomentumSummary")
    initializer = _function_body(source, "initHomepageMomentumEntry")

    assert source.count("./data/public-theme-momentum-latest-v0.9.json") == 1
    assert source.count("./data/public-theme-momentum-history-v0.9.json") == 1
    assert "Promise.all" in loader
    assert "validateHomepageMomentumLatestPayload" in loader
    assert "validateHomepageMomentumHistoryPayload" in loader
    assert "renderHomepageMomentumFallback" in initializer
    for forbidden in (
        "supabase",
        "theme_radar.hourly_theme_heat",
        "service_role",
        "postgres://",
        "postgresql://",
        "producer_run_id",
    ):
        assert forbidden not in source.casefold()


def test_card_renders_valid_summary_and_fails_closed_on_errors() -> None:
    source = _homepage_momentum_source()
    node_assertions = r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const latest = JSON.parse(fs.readFileSync("data/public-theme-momentum-latest-v0.9.json", "utf8"));
const history = JSON.parse(fs.readFileSync("data/public-theme-momentum-history-v0.9.json", "utf8"));

function createElement(textContent = "") {
  return {
    textContent,
    hidden: false,
    dateTime: "",
    dataset: {},
    attributes: new Map(),
    setAttribute(name, value) { this.attributes.set(name, String(value)); },
    removeAttribute(name) { this.attributes.delete(name); },
  };
}

function createElements() {
  const entry = createElement();
  entry.setAttribute("aria-busy", "true");
  const data = createElement();
  data.hidden = true;
  return {
    themeMomentumEntry: entry,
    themeMomentumEntryTitle: createElement("追蹤熱門題材走勢"),
    themeMomentumEntryDescription: createElement("開啟完整動能儀表板"),
    themeMomentumEntryData: data,
    themeMomentumEntryUpdatedAt: createElement(),
    themeMomentumEntryWindows: createElement(),
  };
}

let elements = createElements();
let latestPayload = latest;
let historyPayload = history;
let shouldReject = false;
const requestedUrls = [];
const document = { getElementById(id) { return elements[id] || null; } };

function fmtTime() { return "07/31 23:29"; }

async function fetch(url) {
  requestedUrls.push(url);
  if (shouldReject) throw new Error("offline");
  const payload = url.startsWith(HOMEPAGE_MOMENTUM_CONTRACT.latestUrl)
    ? latestPayload
    : historyPayload;
  return { ok: true, status: 200, async json() { return structuredClone(payload); } };
}

(async () => {
  await initHomepageMomentumEntry();
  assert.equal(elements.themeMomentumEntry.dataset.state, "ready");
  assert.equal(
    elements.themeMomentumEntryTitle.textContent,
    `目前最熱：${latest.themes[0].name_zh}`,
  );
  assert.equal(elements.themeMomentumEntryUpdatedAt.textContent, "更新 07/31 23:29");
  assert.equal(elements.themeMomentumEntryUpdatedAt.dateTime, latest.generated_at);
  assert.equal(elements.themeMomentumEntryWindows.textContent, "24h / 72h / 7d");
  assert.equal(elements.themeMomentumEntryData.hidden, false);
  assert.equal(elements.themeMomentumEntry.attributes.has("aria-busy"), false);
  assert.deepEqual(
    requestedUrls.map((url) => url.split("?")[0]),
    [
      "./data/public-theme-momentum-latest-v0.9.json",
      "./data/public-theme-momentum-history-v0.9.json",
    ],
  );

  elements = createElements();
  historyPayload = { ...history, schema_version: "unexpected" };
  await initHomepageMomentumEntry();
  assert.equal(elements.themeMomentumEntry.dataset.state, "fallback");
  assert.equal(elements.themeMomentumEntryTitle.textContent, "追蹤熱門題材走勢");
  assert.equal(elements.themeMomentumEntryDescription.textContent, "開啟完整動能儀表板");
  assert.equal(elements.themeMomentumEntryData.hidden, true);
  assert.equal(elements.themeMomentumEntry.attributes.has("aria-busy"), false);

  elements = createElements();
  historyPayload = history;
  shouldReject = true;
  await initHomepageMomentumEntry();
  assert.equal(elements.themeMomentumEntry.dataset.state, "fallback");
  assert.equal(elements.themeMomentumEntryTitle.textContent, "追蹤熱門題材走勢");
  assert.equal(elements.themeMomentumEntryData.hidden, true);
  assert.equal(elements.themeMomentumEntry.attributes.has("aria-busy"), false);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
'''
    node_script = (
        "const execute = new Function('require', "
        + json.dumps(source + node_assertions)
        + "); execute(require);"
    )
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_card_falls_back_when_latest_payload_is_stale() -> None:
    source = _homepage_momentum_source()
    node_assertions = r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const latest = JSON.parse(fs.readFileSync("data/public-theme-momentum-latest-v0.9.json", "utf8"));
const history = JSON.parse(fs.readFileSync("data/public-theme-momentum-history-v0.9.json", "utf8"));

function createElement(textContent = "") {
  return {
    textContent,
    hidden: false,
    dateTime: "",
    dataset: {},
    attributes: new Map(),
    setAttribute(name, value) { this.attributes.set(name, String(value)); },
    removeAttribute(name) { this.attributes.delete(name); },
  };
}

const entry = createElement();
entry.setAttribute("aria-busy", "true");
const data = createElement();
data.hidden = true;
const elements = {
  themeMomentumEntry: entry,
  themeMomentumEntryTitle: createElement("追蹤熱門題材走勢"),
  themeMomentumEntryDescription: createElement("開啟完整動能儀表板"),
  themeMomentumEntryData: data,
  themeMomentumEntryUpdatedAt: createElement(),
  themeMomentumEntryWindows: createElement(),
};
const document = { getElementById(id) { return elements[id] || null; } };

function fmtTime() { return "08/01 14:41"; }

async function fetch(url) {
  const payload = url.startsWith(HOMEPAGE_MOMENTUM_CONTRACT.latestUrl)
    ? { ...latest, freshness_status: "stale" }
    : history;
  return { ok: true, status: 200, async json() { return structuredClone(payload); } };
}

(async () => {
  await initHomepageMomentumEntry();
  assert.equal(elements.themeMomentumEntry.dataset.state, "fallback");
  assert.equal(elements.themeMomentumEntryTitle.textContent, "追蹤熱門題材走勢");
  assert.equal(elements.themeMomentumEntryDescription.textContent, "開啟完整動能儀表板");
  assert.equal(elements.themeMomentumEntryData.hidden, true);
  assert.equal(elements.themeMomentumEntryUpdatedAt.textContent, "");
  assert.equal(elements.themeMomentumEntryWindows.textContent, "");
  assert.equal(elements.themeMomentumEntry.attributes.has("aria-busy"), false);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
'''
    node_script = (
        "const execute = new Function('require', "
        + json.dumps(source + node_assertions)
        + "); execute(require);"
    )
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_card_styles_cover_focus_responsive_layout_and_reduced_motion() -> None:
    css = (ROOT / "assets" / "styles.css").read_text(encoding="utf-8")

    assert ".theme-momentum-entry:focus-visible" in css
    assert "outline-offset" in css
    assert ".theme-momentum-entry" in css and "max-width: 100%" in css
    mobile = css[css.index("@media (max-width: 720px)") :]
    assert ".theme-momentum-entry" in mobile
    assert "grid-template-columns: 1fr" in mobile
    reduced_motion = css[css.index("@media (prefers-reduced-motion: reduce)") :]
    assert ".theme-momentum-entry" in reduced_motion
    assert "transition: none" in reduced_motion
