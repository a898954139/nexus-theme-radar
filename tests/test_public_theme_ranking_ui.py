from __future__ import annotations

import copy
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "public_theme_ranking"
    / "v0.8"
    / "ranking-contract.json"
)
ERROR_COPY = "題材排行暫時無法更新，請稍後再試"
PARTIAL_COPY = "部分資料來源暫時無法更新，排行門檻維持不變"
OFFICIAL_UNAVAILABLE_COPY = "官方佐證暫時無法更新"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text())


def _themes_payload(count: int) -> dict[str, object]:
    payload = _fixture()
    original = payload["themes"][0]
    themes = []
    for rank in range(1, count + 1):
        theme = copy.deepcopy(original)
        theme["rank"] = rank
        theme["theme_id"] = f"theme-{rank}"
        theme["name_zh"] = f"題材 {rank}"
        theme["representative_news"]["cluster_id"] = f"cluster-{rank}"
        theme["representative_news"]["id"] = f"event-cluster-{rank}"
        themes.append(theme)
    payload["themes"] = themes
    payload["qualified_theme_count"] = count
    payload["displayed_theme_count"] = count
    payload["threshold_note"] = (
        f"目前僅 {count} 個題材達到上榜門檻" if count < 5 else None
    )
    return payload


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


def _probe(payload: dict[str, object]) -> dict[str, object]:
    source_path = ROOT / "assets" / "app.js"
    harness = f"""
const fs = require("fs");
const vm = require("vm");

function makeElement(tagName = "div", id = "") {{
  let ownText = "";
  let ownHtml = "";
  const element = {{
    attributes: {{}},
    children: [],
    className: "",
    dataset: {{}},
    hidden: false,
    id,
    style: {{}},
    tagName: String(tagName).toUpperCase(),
    addEventListener() {{}},
    append(...children) {{
      children.forEach((child) => {{
        if (child === null || child === undefined) return;
        if (typeof child === "string") {{
          const textNode = makeElement("#text");
          textNode.textContent = child;
          this.children.push(textNode);
          return;
        }}
        if (child.tagName === "#FRAGMENT") {{
          this.children.push(...child.children);
          return;
        }}
        this.children.push(child);
      }});
    }},
    appendChild(child) {{
      this.append(child);
      return child;
    }},
    classList: {{
      add(...names) {{
        element.className = Array.from(
          new Set(`${{element.className}} ${{names.join(" ")}}`.trim().split(/\\s+/).filter(Boolean))
        ).join(" ");
      }},
      remove(...names) {{
        element.className = element.className
          .split(/\\s+/)
          .filter((name) => name && !names.includes(name))
          .join(" ");
      }},
      toggle(name, enabled) {{
        if (enabled === undefined) enabled = !element.className.split(/\\s+/).includes(name);
        if (enabled) this.add(name);
        else this.remove(name);
      }},
    }},
    getAttribute(name) {{
      return this.attributes[name];
    }},
    querySelector() {{
      return null;
    }},
    querySelectorAll() {{
      return [];
    }},
    remove() {{}},
    setAttribute(name, value) {{
      this.attributes[name] = String(value);
    }},
  }};
  Object.defineProperty(element, "innerHTML", {{
    get() {{ return ownHtml; }},
    set(value) {{
      ownHtml = String(value);
      ownText = "";
      element.children = [];
    }},
  }});
  Object.defineProperty(element, "textContent", {{
    get() {{ return ownText; }},
    set(value) {{
      ownText = String(value ?? "");
      ownHtml = "";
      element.children = [];
    }},
  }});
  return element;
}}

const elements = new Map();
function byId(id) {{
  if (!elements.has(id)) elements.set(id, makeElement("div", id));
  return elements.get(id);
}}
const localStorage = {{
  getItem() {{ return ""; }},
  removeItem() {{}},
  setItem() {{}},
}};
const document = {{
  createDocumentFragment() {{ return makeElement("#fragment"); }},
  createElement(tagName) {{ return makeElement(tagName); }},
  getElementById: byId,
  querySelector() {{ return makeElement("section"); }},
  querySelectorAll() {{ return []; }},
}};
const context = {{
  URL,
  URLSearchParams,
  clearTimeout,
  console,
  CustomEvent: function CustomEvent() {{}},
  document,
  fetch: async () => ({{ ok: true, json: async () => ({{}}) }}),
  localStorage,
  requestAnimationFrame(callback) {{ callback(); }},
  setTimeout,
  testPayload: {json.dumps(payload, ensure_ascii=False)},
  window: {{
    location: {{ href: "https://example.test/", pathname: "/", search: "" }},
    localStorage,
  }},
}};
vm.createContext(context);
const source = fs
  .readFileSync({json.dumps(str(source_path))}, "utf8")
  .replace(/\\nrenderDataSourceIndicator\\(\\);\\s*\\ninit\\(\\);\\s*$/, "\\n");
vm.runInContext(source, context);
vm.runInContext("renderPublicThemeRanking(testPayload);", context);

function text(node) {{
  return [node.textContent, ...node.children.map(text)].join("");
}}
function serialize(node) {{
  return {{
    attributes: node.attributes,
    children: node.children.map(serialize),
    className: node.className,
    hidden: node.hidden,
    href: node.href || "",
    rel: node.rel || "",
    tagName: node.tagName,
    target: node.target || "",
    text: node.textContent,
  }};
}}
function collect(node, tagName) {{
  const matches = node.tagName === tagName ? [node] : [];
  return matches.concat(...node.children.map((child) => collect(child, tagName)));
}}

const list = byId("publicThemeRankingList");
const links = collect(list, "A").map((link) => ({{
  href: link.href || "",
  rel: link.rel || "",
  target: link.target || "",
  text: text(link),
}}));
process.stdout.write(JSON.stringify({{
  cardCount: list.children.length,
  links,
  list: serialize(list),
  listText: text(list),
  noteHidden: byId("publicThemeRankingNote").hidden,
  noteText: text(byId("publicThemeRankingNote")),
  statusText: text(byId("publicThemeRankingStatus")),
}}));
"""
    completed = subprocess.run(
        ["node", "-e", harness],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _tags(node: dict[str, object]) -> list[str]:
    return [node["tagName"], *[
        tag
        for child in node["children"]
        for tag in _tags(child)
    ]]


def test_markup_copy_and_first_section_preserve_lower_homepage() -> None:
    html = (ROOT / "index.html").read_text()
    app = (ROOT / "src" / "App.tsx").read_text()
    home = (ROOT / "src" / "components" / "home" / "ThemeRadarHome.tsx").read_text()

    assert '<div id="root"></div>' in html
    assert "<ThemeRadarHome" in app
    assert "themeRanking.themes" in home
    assert "direct_mentions" in home
    assert "supply_chain_candidates" in home
    assert "theme-stage" in home
    assert "news-feed" in home
    assert "slice(0, 20)" in home
    assert 'id="publicThemeRankingWrap"' not in html

    ranking_markup = home
    prohibited_claims = (
        "歷史驗證",
        "historical validation",
        "市場動能",
        "market momentum",
        "預期報酬",
        "expected return",
        "價格預測",
        "price prediction",
    )
    assert not any(claim in ranking_markup for claim in prohibited_claims)


def test_styles_are_responsive_and_accessible_without_redesigning_the_page() -> None:
    styles = (ROOT / "assets" / "styles.css").read_text()

    assert ".public-theme-ranking" in styles
    assert ".public-theme-grid" in styles
    assert ".public-theme-card" in styles
    assert ".public-theme-evidence-grid" in styles
    assert ".public-theme-news-link:focus-visible" in styles
    mobile = styles[styles.index("@media (max-width: 720px)") :]
    assert ".public-theme-grid" in mobile
    assert ".public-theme-evidence-grid" in mobile
    assert "grid-template-columns: 1fr" in mobile


def test_payload_loader_uses_only_server_built_ranking() -> None:
    source = (ROOT / "assets" / "app.js").read_text()
    loader = _function_body(source, "loadPublicThemeRankingData")
    renderer = _function_body(source, "renderPublicThemeRanking")

    assert 'dataUrl("data/public-theme-ranking-v0.8.json")' in loader
    assert "theme-events.json" not in loader
    assert "loadPublicThemeRankingData()," in source
    assert "hotBoardEntries" not in source
    assert "renderHotBoard" not in source
    assert "buildHotRow" not in source

    assert ".sort(" not in renderer
    assert "slice(0, 5)" not in renderer
    assert "Math.round" not in renderer
    assert ".innerHTML" not in renderer
    assert "event_component" not in renderer
    assert "source_component" not in renderer
    assert "candidate_component" not in renderer
    assert "mapping_component" not in renderer
    assert "concentration_penalty" not in renderer


def test_valid_complete_empty_and_threshold_states_render_exact_notes() -> None:
    complete = _probe(_fixture())
    assert complete["cardCount"] == 1
    assert complete["noteText"] == "目前僅 1 個題材達到上榜門檻"
    assert complete["noteHidden"] is False
    assert complete["statusText"] == "資料更新完成"

    for count in range(5):
        state = _probe(_themes_payload(count))
        assert state["cardCount"] == count
        assert state["noteText"] == f"目前僅 {count} 個題材達到上榜門檻"
        assert state["noteHidden"] is False

    top_five = _probe(_themes_payload(5))
    assert top_five["cardCount"] == 5
    assert top_five["noteText"] == ""
    assert top_five["noteHidden"] is True


def test_partial_and_official_unavailable_states_keep_valid_cards() -> None:
    partial = _fixture()
    partial["generation_status"] = "partial"
    partial["failed_source_count"] = 2
    partial_state = _probe(partial)
    assert partial_state["cardCount"] == 1
    assert PARTIAL_COPY in partial_state["statusText"]

    unavailable = _fixture()
    unavailable["official_evidence_status"] = "unavailable"
    unavailable_state = _probe(unavailable)
    assert unavailable_state["cardCount"] == 1
    assert OFFICIAL_UNAVAILABLE_COPY in unavailable_state["statusText"]
    assert "近期官方佐證" not in unavailable_state["listText"]


def test_wrong_contract_forged_company_and_unsafe_news_fail_closed() -> None:
    invalid_payloads = []
    mutations = (
        ("schema_version", "wrong"),
        ("ranking_rule_version", "wrong"),
        ("company_rule_version", "wrong"),
        ("market_id", "US_EQUITY"),
        ("market_scope", ["US_EQUITY"]),
        ("window_hours", 24),
        ("max_themes", 6),
        ("displayed_theme_count", 2),
        ("qualified_theme_count", 0),
    )
    for key, value in mutations:
        payload = _fixture()
        payload[key] = value
        invalid_payloads.append(payload)

    too_many = _themes_payload(5)
    sixth = copy.deepcopy(too_many["themes"][-1])
    sixth["rank"] = 6
    sixth["theme_id"] = "theme-6"
    too_many["themes"].append(sixth)
    too_many["qualified_theme_count"] = 6
    too_many["displayed_theme_count"] = 6
    invalid_payloads.append(too_many)

    forged = _fixture()
    forged["themes"][0]["direct_mentions"][0].update(
        {
            "exchange": "NASDAQ",
            "instrument_id": "NASDAQ:AAPL",
            "symbol": "AAPL",
        }
    )
    invalid_payloads.append(forged)

    for unsafe_url in ("javascript:alert(1)", "data:text/html,bad", "", "https://"):
        unsafe = _fixture()
        unsafe["themes"][0]["representative_news"]["canonical_url"] = unsafe_url
        invalid_payloads.append(unsafe)

    for payload in invalid_payloads:
        state = _probe(payload)
        assert state["cardCount"] == 0
        assert state["noteText"] == ""
        assert state["statusText"] == ERROR_COPY


def test_cards_render_server_fields_as_safe_text_and_safe_links() -> None:
    payload = _fixture()
    theme = payload["themes"][0]
    theme["name_zh"] = "<img src=x onerror=alert(1)>"
    theme["heat_reason"]["raw_score"] = 99.999
    theme["direct_mentions"][0]["name_zh"] = "<b>廣達</b>"
    theme["supply_chain_candidates"][0]["name_zh"] = "<script>台積電</script>"
    theme["representative_news"]["title_zh"] = "<svg onload=alert(1)>代表新聞"
    theme["representative_news"]["source"] = "<em>Publisher</em>"

    state = _probe(payload)
    text = state["listText"]

    assert state["cardCount"] == 1
    assert "<img src=x onerror=alert(1)>" in text
    assert "<b>廣達</b>" in text
    assert "<script>台積電</script>" in text
    assert "<svg onload=alert(1)>代表新聞" in text
    assert "<em>Publisher</em>" in text
    assert "熱度 56 / 100" in text
    assert "題材事件2" in text
    assert "獨立來源2" in text
    assert "追蹤候選1" in text
    assert "台股映射3" in text
    assert text.count("台積電") >= 2
    assert "近期官方佐證" in text
    assert "IMG" not in _tags(state["list"])
    assert "SCRIPT" not in _tags(state["list"])
    assert state["links"] == [
        {
            "href": "https://example.com/cluster-a",
            "rel": "noopener noreferrer",
            "target": "_blank",
            "text": "<svg onload=alert(1)>代表新聞",
        }
    ]


def test_explicit_empty_company_states_render_without_merging_classes() -> None:
    payload = _fixture()
    payload["themes"][0]["direct_mentions"] = []
    payload["themes"][0]["supply_chain_candidates"] = []

    state = _probe(payload)

    assert state["cardCount"] == 1
    assert "暫無新聞直接提及" in state["listText"]
    assert "暫無題材／供應鏈候選" in state["listText"]
