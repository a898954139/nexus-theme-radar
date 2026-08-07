"""Stock list and quarterly fundamentals on the theme momentum cards.

The published feed now carries per-symbol statements on each theme. These
tests pin two things: the page's exact-key validator must accept the fields
the pipeline actually publishes, and a symbol without statements must render
as having none rather than as having measured zeros.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "assets" / "theme-momentum.js"


def _run_node(assertions: str) -> subprocess.CompletedProcess:
    """Evaluate the page module's declarations, then run assertions on them."""
    source = SCRIPT.read_text(encoding="utf-8")
    script = (
        "const execute = new Function('require','document','window',"
        + json.dumps(source + "\n" + assertions)
        + "); execute(require, globalThis.__doc, globalThis.__win);"
    )
    return subprocess.run(
        ["node", "-e", _DOM_STUB + script],
        cwd=ROOT, check=False, capture_output=True, text=True,
    )


# Minimal DOM the module touches at definition time.
_DOM_STUB = r"""
class El {
  constructor(tag){ this.tagName=tag; this.children=[]; this.attributes=new Map();
    this._text=""; this.className=""; this._html=""; this.dataset={};
    this.style={}; this.hidden=false; this.classList={add(){},remove(){},toggle(){}}; }
  set textContent(v){ this._text=String(v); this.children=[]; }
  get textContent(){ return this.children.length
    ? this._text + this.children.map(c=>c.textContent).join("")
    : this._text; }
  set innerHTML(v){ this._html=String(v); }
  get innerHTML(){ return this._html; }
  setAttribute(n,v){ this.attributes.set(n,String(v)); }
  getAttribute(n){ return this.attributes.get(n) ?? null; }
  removeAttribute(n){ this.attributes.delete(n); }
  append(...kids){ this.children.push(...kids); }
  replaceChildren(...kids){ this.children=kids; }
  // innerHTML-created nodes are not modelled, so a selector lookup returns a
  // stand-in whose text is folded back into this element's own text.
  querySelector(){
    const proxy = new El("stub");
    this.children.push(proxy);
    return proxy;
  }
  querySelectorAll(){ return []; }
  get outerText(){
    const own = this._html.replace(/<[^>]*>/g," ") + " " + this._text;
    return [own, ...this.children.map(c=>c.outerText)].join(" ");
  }
}
const __registry = {};
globalThis.__doc = {
  getElementById(id){ return __registry[id] || (__registry[id] = new El("div")); },
  createElement(tag){ return new El(tag); },
  createElementNS(ns, tag){ return new El(tag); },
  querySelector(){ return new El("stub"); },
  querySelectorAll(){ return []; },
  addEventListener(){},
  documentElement: new El("html"),
  body: new El("body"),
  readyState: "complete",
};
globalThis.__win = { matchMedia: () => ({ matches:false, addEventListener(){} }) };
globalThis.document = globalThis.__doc;
globalThis.window = globalThis.__win;
globalThis.fetch = async () => ({ ok:true, status:200, json: async () => ({}) });
"""


def _theme(**overrides):
    theme = {
        "rank": 1, "theme_id": "memory_hbm", "name_zh": "記憶體與 HBM",
        "qualification_status": "qualified", "near_threshold_reason": None,
        "momentum_score": 33, "lifecycle_stage": "new", "heat_score": 65,
        "heat_change_24h": None, "source_change_24h": None,
        "event_count": 4, "source_count": 3, "tracking_candidate_count": 0,
        "taiwan_mapping_count": 3, "direct_mapping_event_count": 2,
        "single_source_concentration": 0.5,
        "latest_qualifying_event_at": "2026-07-31T08:59:21Z",
        "representative_news": None,
        "direct_symbols": [],
        "related_symbols": [],
    }
    theme.update(overrides)
    return theme


def _symbol(symbol="2344", name="華邦電", fundamentals=None):
    entry = {
        "instrument_id": f"TWSE:{symbol}", "symbol": symbol,
        "exchange": "TWSE", "name_zh": name,
    }
    if fundamentals is not None:
        entry["fundamentals"] = fundamentals
    return entry


def _fundamentals(period="2026Q1", eps=2.25, gross_margin=0.534):
    quarter = {"period": period, "revenue": 382.5}
    if eps is not None:
        quarter["eps"] = eps
    if gross_margin is not None:
        quarter["gross_margin"] = gross_margin
    return {"quarters": [quarter], "valuation": {"ttm_eps": 3.37},
            "fiscal_quarter": period}


# ─── validator ──────────────────────────────────────────────────────────────


def test_validator_accepts_the_fields_the_pipeline_publishes() -> None:
    """validateLatest compares theme keys by exact count, so undeclared fields
    make the whole page throw and render nothing."""
    payload = {
        "schema_version": "nexus_public_theme_momentum_latest.v0.9",
        "ranking_rule_version": "public_theme_momentum_v0.9",
        "inclusion_rule_version": "public_theme_momentum_inclusion_v0.9",
        "heat_rule_version": "public_theme_heat_v0.8",
        "generated_at": "2026-08-06T10:00:01Z",
        "observed_hour": "2026-08-06T10:00:00Z",
        "market_id": "TW_EQUITY", "market_scope": ["TW_EQUITY"],
        "window_hours": 72, "freshness_status": "current",
        "theme_count": 1, "themes": [_theme()],
    }
    result = _run_node(
        "const assert = require('node:assert/strict');\n"
        f"const payload = {json.dumps(payload)};\n"
        "assert.doesNotThrow(() => validateLatest(payload));\n"
    )
    assert result.returncode == 0, result.stderr


def test_validator_accepts_the_real_published_feed() -> None:
    result = _run_node(
        "const assert = require('node:assert/strict');\n"
        "const fs = require('node:fs');\n"
        "const live = JSON.parse(fs.readFileSync("
        "'data/public-theme-momentum-latest-v0.9.json','utf8'));\n"
        "assert.doesNotThrow(() => validateLatest(live));\n"
    )
    assert result.returncode == 0, result.stderr


# ─── rendering ──────────────────────────────────────────────────────────────


def _render(themes):
    payload = {"observed_hour": "2026-08-06T10:00:00Z", "themes": themes}
    return _run_node(
        "const assert = require('node:assert/strict');\n"
        f"renderLatest({json.dumps(payload)});\n"
        "const text = document.getElementById('latestThemes').outerText;\n"
        "console.log(JSON.stringify(text));\n"
    )


def test_a_stock_with_statements_shows_period_eps_and_margin() -> None:
    result = _render([_theme(related_symbols=[_symbol(fundamentals=_fundamentals())])])
    assert result.returncode == 0, result.stderr
    text = json.loads(result.stdout.strip().splitlines()[-1])

    assert "2344" in text
    assert "華邦電" in text
    assert "2026Q1" in text
    assert "2.25" in text
    assert "53.4%" in text


def test_a_stock_without_statements_gets_no_placeholder() -> None:
    """A dash or a zero would read as a measurement that was never taken."""
    result = _render([_theme(related_symbols=[_symbol()])])
    assert result.returncode == 0, result.stderr
    text = json.loads(result.stdout.strip().splitlines()[-1])

    assert "2344" in text
    assert "—" not in text
    assert "N/A" not in text
    assert "0.0%" not in text


def test_a_margin_above_one_is_not_reinterpreted() -> None:
    """102% gross margin is an anomaly worth surfacing. A "looks like a
    percentage already" heuristic would render it as 1.0% and hide it."""
    result = _render([
        _theme(related_symbols=[_symbol(fundamentals=_fundamentals(gross_margin=1.02))]),
    ])
    assert result.returncode == 0, result.stderr
    text = json.loads(result.stdout.strip().splitlines()[-1])

    assert "102.0%" in text
    assert "1.0%" not in text


def test_a_missing_metric_omits_only_that_metric() -> None:
    result = _render([
        _theme(related_symbols=[_symbol(fundamentals=_fundamentals(eps=None))]),
    ])
    assert result.returncode == 0, result.stderr
    text = json.loads(result.stdout.strip().splitlines()[-1])

    assert "53.4%" in text
    assert "EPS" not in text


def test_direct_and_related_symbols_are_merged_without_duplicates() -> None:
    shared = _symbol(fundamentals=_fundamentals())
    result = _render([_theme(direct_symbols=[shared], related_symbols=[shared])])
    assert result.returncode == 0, result.stderr
    text = json.loads(result.stdout.strip().splitlines()[-1])

    assert text.count("華邦電") == 1


def test_a_theme_without_stocks_renders_no_stock_section() -> None:
    result = _render([_theme()])
    assert result.returncode == 0, result.stderr
    text = json.loads(result.stdout.strip().splitlines()[-1])

    assert "記憶體與 HBM" in text
    assert "檔" not in text


def test_an_overflowing_list_reports_what_it_dropped() -> None:
    """Silent truncation reads as 'this is the whole list'."""
    symbols = [_symbol(symbol=f"200{i}", name=f"公司{i}") for i in range(9)]
    result = _render([_theme(related_symbols=symbols)])
    assert result.returncode == 0, result.stderr
    text = json.loads(result.stdout.strip().splitlines()[-1])

    assert "+3" in text


# ─── linking through to the per-stock detail page ───────────────────────────


def test_stock_entry_links_to_its_detail_page() -> None:
    """The statements are published per symbol but the card has room for one
    line; the link is how a reader reaches the rest."""
    theme = _theme(direct_symbols=[_symbol()])
    result = _run_node(
        """
        const list = buildThemeStockList(THEME);
        const link = list.children[0].children[0];
        if (link.tagName !== "a") throw new Error("expected an anchor, got " + link.tagName);
        if (link.href !== "./stock.html?code=2344") throw new Error("href was " + link.href);
        console.log("OK");
        """.replace("THEME", json.dumps(theme)),
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_link_uses_the_bare_ticker_not_the_instrument_id() -> None:
    """stock.html resolves a 4-digit code; handing it TPEX:8299 lands on
    "查無此標的" even though the symbol is in the cache."""
    theme = _theme(direct_symbols=[{
        "instrument_id": "TPEX:8299", "symbol": "8299",
        "exchange": "TPEX", "name_zh": "群聯",
    }])
    result = _run_node(
        """
        const link = buildThemeStockList(THEME).children[0].children[0];
        if (link.href !== "./stock.html?code=8299") throw new Error("href was " + link.href);
        console.log("OK");
        """.replace("THEME", json.dumps(theme)),
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_instrument_id_alone_still_yields_a_usable_link() -> None:
    """`symbol` is not guaranteed; the exchange prefix must be stripped rather
    than passed through."""
    theme = _theme(direct_symbols=[{
        "instrument_id": "TWSE:2330", "exchange": "TWSE", "name_zh": "台積電",
    }])
    result = _run_node(
        """
        const link = buildThemeStockList(THEME).children[0].children[0];
        if (link.href !== "./stock.html?code=2330") throw new Error("href was " + link.href);
        console.log("OK");
        """.replace("THEME", json.dumps(theme)),
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_symbol_without_a_resolvable_code_is_not_a_link() -> None:
    """A link to stock.html with no usable code lands the reader on an error
    page. Rendering plain text is the honest outcome.

    The symbol carries an id (one without any is dropped upstream by
    ``themeStocks``) but not a 4-digit ticker -- an index or a foreign listing
    reaching the feed would look like this.
    """
    theme = _theme(direct_symbols=[{
        "instrument_id": "TWSE:TAIEX", "exchange": "TWSE", "name_zh": "加權指數",
    }])
    result = _run_node(
        """
        const body = buildThemeStockList(THEME).children[0].children[0];
        if (body.tagName === "a") throw new Error("linked a symbol with no code");
        console.log("OK");
        """.replace("THEME", json.dumps(theme)),
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_the_financial_line_survives_the_link_wrapper() -> None:
    """Regression: wrapping the name in an anchor must not drop the metrics
    that already render beside it."""
    theme = _theme(direct_symbols=[_symbol(fundamentals=_fundamentals())])
    result = _run_node(
        """
        const item = buildThemeStockList(THEME).children[0];
        const text = item.outerText;
        if (!text.includes("2026Q1")) throw new Error("lost the period: " + text);
        if (!text.includes("EPS")) throw new Error("lost the EPS: " + text);
        if (!text.includes("華邦電")) throw new Error("lost the name: " + text);
        console.log("OK");
        """.replace("THEME", json.dumps(theme)),
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
