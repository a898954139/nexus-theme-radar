from __future__ import annotations

import json
import re
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


def test_update_workflow_uses_v03_generator_and_has_no_legacy_ai_inputs() -> None:
    workflow = (ROOT / ".github" / "workflows" / "update-news.yml").read_text()

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
