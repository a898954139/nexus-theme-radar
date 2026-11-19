from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.build_theme_focus import (
    build_theme_focus,
    classify,
    focus_score,
    summarize_flow,
)

ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _flow(data_dir: Path, instrument_id: str, rows: list[list[object]]) -> None:
    exchange, code = instrument_id.split(":")
    _write(data_dir / "flows" / f"{exchange}-{code}.json", {
        "schema_version": 1,
        "instrument_id": instrument_id,
        "unit": "shares",
        "fields": ["date", "foreign_net", "trust_net", "dealer_net", "total_net"],
        "series": rows,
    })


def _symbol(instrument_id: str, name: str) -> dict[str, str]:
    exchange, code = instrument_id.split(":")
    return {"instrument_id": instrument_id, "symbol": code, "exchange": exchange, "name_zh": name}


def test_summarize_flow_converts_to_lots_and_counts_streak() -> None:
    rows = [
        ("2026-11-19", 2000.0, 0.0, 0.0, 2000.0),
        ("2026-11-18", 1000.0, 0.0, 0.0, 1000.0),
        ("2026-11-17", -5000.0, 0.0, 0.0, -5000.0),
    ]
    summary = summarize_flow(rows, "2026-11-19")
    assert summary == {
        "as_of": "2026-11-19",
        "days": 3,
        "total_5d": -2,
        "foreign_5d": -2,
        "trust_5d": 0,
        "total_1d": 2,
        "streak": 2,
    }


def test_symbol_whose_file_stopped_updating_is_missing_not_scored() -> None:
    rows = [("2026-11-12", 9000.0, 0.0, 0.0, 9000.0)]
    assert summarize_flow(rows, "2026-11-19") is None


def test_breadth_not_summed_lots_decides_the_money_side() -> None:
    # Broad buying, even when one mega-cap's selling makes the sum negative.
    assert classify(80, 0.6) == "focus"
    assert classify(40, 0.6) == "money_first"
    assert classify(80, 0.4) == "news_only"
    assert classify(40, 0.4) == "outflow"
    assert classify(80, 0.5) == "news_only"
    assert classify(40, 0.5) == "watch"
    assert classify(80, None) == "watch"
    assert focus_score(80, 0.6) == 70
    assert focus_score(80, None) == 40


def test_build_theme_focus_joins_themes_flows_and_watch_scores(tmp_path: Path) -> None:
    _write(tmp_path / "public-theme-momentum-latest-v0.9.json", {
        "generated_at": "2026-11-19T03:00:00Z",
        "themes": [
            {
                "rank": 1, "theme_id": "memory", "name_zh": "記憶體", "heat_score": 80,
                "momentum_score": 10, "lifecycle_stage": "accelerating", "event_count": 4,
                "direct_symbols": [_symbol("TWSE:2408", "南亞科")],
                "related_symbols": [_symbol("TWSE:2344", "華邦電"), _symbol("TWSE:2330", "台積電")],
                "representative_news": {"title_zh": "DRAM 漲價", "source": "MoneyDJ", "published_at": "2026-11-19T01:00:00Z", "canonical_url": "https://example.com/a"},
            },
            {
                "rank": 2, "theme_id": "empty", "name_zh": "沒有個股", "heat_score": 90,
                "momentum_score": 0, "lifecycle_stage": "new", "event_count": 1,
                "direct_symbols": [], "related_symbols": [],
            },
        ],
    })
    _write(tmp_path / "public-theme-ranking-v0.8.json", {
        "themes": [{"theme_id": "memory", "direct_mentions": [_symbol("TPEX:8299", "群聯")], "supply_chain_candidates": []}],
    })
    _write(tmp_path / "public-stock-watchlist-v1.json", {
        "short": {"items": [{"instrument": {"instrument_id": "TWSE:2344"}, "short": {"rank": 1, "score": 80.4}}]},
        "long": {"items": [{"instrument": {"instrument_id": "TWSE:2344"}, "long": {"rank": 3, "score": 61.6}}]},
    })
    _flow(tmp_path, "TWSE:2408", [["2026-11-19", 1000, 0, 0, 1000], ["2026-11-18", 1000, 0, 0, 1000]])
    _flow(tmp_path, "TWSE:2344", [["2026-11-19", 4000, 1000, 0, 5000]])
    _flow(tmp_path, "TWSE:2330", [["2026-11-19", -90000, 0, 0, -90000]])
    _flow(tmp_path, "TPEX:8299", [["2026-11-19", 2000, 0, 0, 2000]])

    payload = build_theme_focus(tmp_path, generated_at=datetime(2026, 11, 19, 9, 30, tzinfo=timezone.utc))

    assert payload["schema_version"] == "nexus_theme_focus.v1"
    assert payload["flow_as_of"] == "2026-11-19"
    memory = next(theme for theme in payload["themes"] if theme["theme_id"] == "memory")
    assert memory["flow"]["covered_count"] == 4
    assert memory["flow"]["positive_count"] == 3
    assert memory["flow"]["breadth"] == 0.75
    assert memory["flow"]["total_5d"] == -81
    # 3 of 4 members bought despite the sum being negative: the theme is focus.
    assert memory["stance"] == "focus"
    assert memory["focus_score"] == round(0.5 * 80 + 0.5 * 75)
    # Direct names weighted 3x: 南亞科 / 群聯 2 lots x3 = 6 rank above the
    # related 華邦電 at 5 lots.
    assert [stock["symbol"] for stock in memory["leaders"]] == ["2408", "8299", "2344"]
    assert memory["leaders"][2]["short_rank"] == 1 and memory["leaders"][2]["long_score"] == 62
    assert [stock["symbol"] for stock in memory["outflows"]] == ["2330"]
    assert memory["headline"]["title"] == "DRAM 漲價"

    empty = next(theme for theme in payload["themes"] if theme["theme_id"] == "empty")
    assert empty["flow"]["breadth"] is None and empty["stance"] == "watch"
    assert [theme["focus_rank"] for theme in payload["themes"]] == [1, 2]
    assert payload["themes"][0]["theme_id"] == "memory"


def test_entrypoint_runs_by_path_like_ci(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_theme_focus.py"), "--data-dir", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "theme-focus.json").exists()


def test_runtime_copy_and_workflows_publish_theme_focus() -> None:
    copy = (ROOT / "scripts" / "copy_runtime_data.sh").read_text(encoding="utf-8")
    assert "theme-focus.json" not in copy
    radar = (ROOT / ".github" / "workflows" / "update-theme-radar.yml").read_text(encoding="utf-8")
    flows = (ROOT / ".github" / "workflows" / "update-institutional-flows.yml").read_text(encoding="utf-8")
    assert "python scripts/build_theme_focus.py --data-dir data" in radar
    assert "python scripts/build_theme_focus.py --data-dir data" in flows
    assert "git add data/theme-focus.json" in flows
    assert "--dataset theme-focus" in radar and "--dataset theme-focus" in flows


def test_theme_without_news_symbols_falls_back_to_taxonomy_seeds(tmp_path: Path) -> None:
    (tmp_path / "flows").mkdir()
    (tmp_path / "public-theme-momentum-latest-v0.9.json").write_text(json.dumps({
        "themes": [{"theme_id": "pcb", "name_zh": "PCB", "rank": 1, "heat_score": 30,
                    "direct_symbols": [], "related_symbols": []}],
    }), encoding="utf-8")
    (tmp_path / "flows" / "TWSE-3037.json").write_text(json.dumps({
        "name": "欣興", "series": [["2026-11-19", 1000000, 0, 0, 1000000]],
    }), encoding="utf-8")
    payload = build_theme_focus(tmp_path, taxonomy_seeds={"pcb": ["3037", "9999"]})
    theme = payload["themes"][0]
    assert theme["flow"]["member_count"] == 1
    assert theme["leaders"][0]["instrument_id"] == "TWSE:3037"
    assert theme["leaders"][0]["name_zh"] == "欣興"
    assert build_theme_focus(tmp_path)["themes"][0]["flow"]["member_count"] == 0
