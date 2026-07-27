from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TABS = [
    ("all", "全部"),
    ("ai_infrastructure", "AI 基建"),
    ("semiconductors", "半導體"),
    ("thermal_cooling", "散熱"),
    ("pcb_abf_hdi", "PCB / ABF"),
    ("memory_hbm", "記憶體"),
    ("optical_cpo", "光通訊"),
    ("power_grid", "電源 / 重電"),
    ("defense_drone", "國防 / 無人機"),
    ("robotics", "機器人"),
]

EXPECTED_THEME_COMPAT = {
    "ai_infrastructure": "ai_infrastructure",
    "ai_server": "ai_infrastructure",
    "semiconductors": "semiconductors",
    "cowos_supply_chain": "semiconductors",
    "thermal_cooling": "thermal_cooling",
    "pcb_abf_hdi": "pcb_abf_hdi",
    "memory_hbm": "memory_hbm",
    "optical_cpo": "optical_cpo",
    "power_grid": "power_grid",
    "power_supply": "power_grid",
    "energy_grid": "power_grid",
    "defense_drone": "defense_drone",
    "robotics": "robotics",
}


def _object_block(source: str, declaration: str) -> str:
    match = re.search(
        rf"const {declaration} = (?:Object\.freeze\()?\{{(?P<body>.*?)\}}\)?;",
        source,
        re.DOTALL,
    )
    assert match, f"{declaration} declaration is missing"
    return match.group("body")


def _probe_primary_mode_pools(
    theme_events: list[dict[str, object]],
    legacy_stories: list[dict[str, object]],
) -> dict[str, object]:
    source_path = ROOT / "assets" / "app.js"
    harness = f"""
const fs = require("fs");
const vm = require("vm");

function element() {{
  return {{
    addEventListener() {{}},
    append() {{}},
    appendChild() {{}},
    classList: {{ add() {{}}, remove() {{}}, toggle() {{}} }},
    dataset: {{}},
    hidden: false,
    innerHTML: "",
    querySelector() {{ return null; }},
    querySelectorAll() {{ return []; }},
    setAttribute() {{}},
    style: {{}},
    textContent: "",
    value: "",
  }};
}}

const localStorage = {{
  getItem() {{ return ""; }},
  removeItem() {{}},
  setItem() {{}},
}};
const context = {{
  URLSearchParams,
  clearTimeout,
  console,
  CustomEvent: function CustomEvent() {{}},
  document: {{
    createDocumentFragment: element,
    createElement: element,
    getElementById: element,
    querySelector: element,
    querySelectorAll() {{ return []; }},
  }},
  fetch: async () => ({{ ok: true, json: async () => ({{}}) }}),
  localStorage,
  requestAnimationFrame(callback) {{ callback(); }},
  setTimeout,
  window: {{
    location: {{ pathname: "/", search: "" }},
    localStorage,
  }},
}};
vm.createContext(context);

const source = fs.readFileSync({json.dumps(str(source_path))}, "utf8")
  .replace(/\\nrenderDataSourceIndicator\\(\\);\\s*\\ninit\\(\\);\\s*$/, "\\n");
vm.runInContext(source, context);

const result = vm.runInContext(`
  state.itemsAll = ${{JSON.stringify({json.dumps(theme_events)})}};
  state.itemsAllRaw = state.itemsAll;
  state.storiesMerged = {{ stories: ${{JSON.stringify({json.dumps(legacy_stories)})}} }};
  state.dailyBrief = {{ items: state.storiesMerged.stories }};
  state.top3Personas = {{
    items: state.storiesMerged.stories.map((story, index) => ({{
      rank: index + 1,
      story_id: story.story_id,
    }})),
  }};
  state.allDedup = true;
  state.authorFilter = "";

  function visibleIds(mode, query = "", siteFilter = "", activeSection = "all") {{
    state.mode = mode;
    state.query = query;
    state.siteFilter = siteFilter;
    state.activeSection = activeSection;
    return mainListEntries().map((entry) => entry.row.item.id);
  }}

  ({{
    allIds: visibleIds("all"),
    selectedIds: visibleIds("selected"),
    allSearchIds: visibleIds("all", "低分"),
    selectedSearchIds: visibleIds("selected", "高分"),
    allSiteIds: visibleIds("all", "", "fixture-b"),
    selectedSiteIds: visibleIds("selected", "", "fixture-b"),
    allSectionIds: visibleIds("all", "", "", "robotics"),
    selectedSectionIds: visibleIds("selected", "", "", "semiconductors"),
    selectedPanel: (() => {{
      state.mode = "selected";
      state.query = "";
      state.siteFilter = "";
      state.activeSection = "all";
      const primaryIds = mainListEntries().map((entry) => entry.row.item.id);
      const hotBoardIds = hotBoardEntries().map((row) => row.item.id);
      const top3BoardIds = top3BoardEntries().map((row) => row.item.id);
      renderHotBoard();
      return {{
        primaryIds,
        hotBoardIds,
        top3BoardIds,
        hotBoardHidden: hotBoardWrapEl.hidden,
        top3BoardHidden: top3BoardWrapEl.hidden,
      }};
    }})(),
  }});
`, context);
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "-e", harness],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_ui_tabs_use_v03_market_theme_taxonomy() -> None:
    source = (ROOT / "assets" / "app.js").read_text()
    section_block = source.split("const SECTION_DEFS = [", 1)[1].split("];", 1)[0]
    tabs = re.findall(r'\{\s*id: "([^"]+)",\s*label: "([^"]+)"', section_block)

    assert tabs == EXPECTED_TABS


def test_current_payload_theme_ids_are_covered_by_ui_compatibility_map() -> None:
    source = (ROOT / "assets" / "app.js").read_text()
    compat_block = _object_block(source, "THEME_SECTION_COMPAT")
    compat = dict(re.findall(r'([a-z0-9_]+): "([a-z0-9_]+)"', compat_block))

    assert compat == EXPECTED_THEME_COMPAT

    for filename in ("theme-events.json", "tracking-candidates.json"):
        payload = json.loads((ROOT / "data" / filename).read_text())
        for item in payload["items"]:
            theme_ids = [item.get("primary_theme_id")]
            theme_ids.extend(
                theme.get("theme_id")
                for theme in item.get("matched_themes", [])
                if isinstance(theme, dict)
            )
            mapped_sections = {compat[theme_id] for theme_id in theme_ids if theme_id}
            assert mapped_sections


def test_primary_mode_pools_share_theme_events_and_exclude_legacy_stories() -> None:
    theme_events = [
        {
            "id": "selected-at-threshold",
            "title": "門檻事件",
            "published_at": "2026-07-27T03:00:00Z",
            "primary_theme_id": "semiconductors",
            "related_symbols": [{"instrument_id": "TWSE:2330"}],
            "site_id": "fixture-a",
            "site_name": "測試來源 A",
            "theme_score": "0.3",
        },
        {
            "id": "selected-above-threshold",
            "title": "高分事件",
            "published_at": "2026-07-27T02:00:00Z",
            "primary_theme_id": "ai_infrastructure",
            "related_symbols": ["TWSE:2382"],
            "site_id": "fixture-b",
            "site_name": "測試來源 B",
            "theme_score": 0.8,
        },
        {
            "id": "rejected-low-score",
            "title": "低分事件",
            "published_at": "2026-07-27T01:00:00Z",
            "primary_theme_id": "thermal_cooling",
            "related_symbols": [{"instrument_id": "TWSE:3017"}],
            "site_id": "fixture-a",
            "site_name": "測試來源 A",
            "theme_score": 0.29,
        },
        {
            "id": "rejected-empty-symbols",
            "title": "無關聯標的事件",
            "published_at": "2026-07-27T00:00:00Z",
            "primary_theme_id": "robotics",
            "related_symbols": [],
            "site_id": "fixture-b",
            "site_name": "測試來源 B",
            "theme_score": 0.9,
        },
    ]
    legacy_stories = [
        {
            "story_id": "legacy-ai-story",
            "latest_at": "2026-07-27T04:00:00Z",
            "primary_item": {
                "id": "legacy-ai-item",
                "title": "Legacy AI News Radar",
                "site_id": "legacy",
                "site_name": "Legacy",
            },
        }
    ]

    pools = _probe_primary_mode_pools(theme_events, legacy_stories)

    assert set(pools["allIds"]) == {event["id"] for event in theme_events}
    assert set(pools["selectedIds"]) == {
        "selected-at-threshold",
        "selected-above-threshold",
    }
    assert "legacy-ai-item" not in pools["selectedIds"]
    assert pools["allSearchIds"] == ["rejected-low-score"]
    assert pools["selectedSearchIds"] == ["selected-above-threshold"]
    assert set(pools["allSiteIds"]) == {
        "selected-above-threshold",
        "rejected-empty-symbols",
    }
    assert pools["selectedSiteIds"] == ["selected-above-threshold"]
    assert pools["allSectionIds"] == ["rejected-empty-symbols"]
    assert pools["selectedSectionIds"] == ["selected-at-threshold"]


def test_selected_primary_ui_hides_all_legacy_story_panels() -> None:
    theme_events = [
        {
            "id": "selected-theme-event",
            "title": "台灣題材事件",
            "published_at": "2026-07-27T03:00:00Z",
            "primary_theme_id": "semiconductors",
            "related_symbols": [{"instrument_id": "TWSE:2330"}],
            "site_id": "fixture-a",
            "site_name": "測試來源 A",
            "theme_score": 0.8,
        }
    ]
    legacy_stories = [
        {
            "story_id": "legacy-ai-story",
            "duplicate_count": 2,
            "latest_at": "2026-07-27T04:00:00Z",
            "primary_item": {
                "id": "legacy-ai-item",
                "title": "Legacy Debian ESP32 Claude Story",
                "site_id": "legacy",
                "site_name": "Legacy AI News Radar",
            },
        }
    ]

    panel = _probe_primary_mode_pools(theme_events, legacy_stories)["selectedPanel"]
    visible_entry_ids = (
        panel["primaryIds"] + panel["hotBoardIds"] + panel["top3BoardIds"]
    )

    assert visible_entry_ids == ["selected-theme-event"]
    assert panel["hotBoardHidden"] is True
    assert panel["top3BoardHidden"] is True


def test_update_workflow_uses_v03_generator_and_has_no_legacy_ai_inputs() -> None:
    workflow = (ROOT / ".github" / "workflows" / "update-theme-radar.yml").read_text()

    assert workflow.startswith("name: Nexus/Taiwan Theme Radar\n")
    assert (
        "python scripts/update_theme_radar.py --output-dir data --window-hours 72 "
        "--max-events 500 --max-candidates 200"
    ) in workflow
    assert "git add data/" in workflow
    assert "theme-events.json" in workflow
    assert "tracking-candidates.json" in workflow
    assert "source-status.json" in workflow
    assert "tikhub" not in workflow.lower()
    assert "force_tikhub" not in workflow.lower()
    assert "ai news radar" not in workflow.lower()
