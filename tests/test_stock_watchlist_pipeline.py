from __future__ import annotations

import json
from pathlib import Path

from scripts.stock_watchlist import validate_stock_watchlist_payload


ROOT = Path(__file__).resolve().parents[1]


def test_hourly_entrypoint_uses_dual_imports_for_watchlist_modules() -> None:
    source = (ROOT / "scripts" / "update_theme_radar.py").read_text(encoding="utf-8")

    assert "from scripts.stock_watchlist import" in source
    assert "from stock_watchlist import" in source
    assert "from scripts.day_trading_activity import" in source
    assert "from day_trading_activity import" in source


def test_watchlist_is_published_before_the_optional_history_connection_return() -> None:
    source = (ROOT / "scripts" / "update_theme_radar.py").read_text(encoding="utf-8")
    start = source.index("def run_momentum_side_paths(")
    no_connection_return = source.index("if connection is None:", start)

    assert source.index("publish_stock_watchlist(", start) < no_connection_return
    assert "PUBLIC_STOCK_WATCHLIST_FILENAME" in source


def test_hourly_workflow_stages_versioned_watchlist_and_daytrade_cache() -> None:
    workflow = (ROOT / ".github" / "workflows" / "update-theme-radar.yml").read_text(
        encoding="utf-8"
    )

    assert "git add data/" in workflow
    assert "python scripts/update_theme_radar.py" in workflow


def test_pages_deploy_copies_the_versioned_watchlist_payload() -> None:
    workflow = (ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text(
        encoding="utf-8"
    )

    assert "cp data/public-stock-watchlist-v1.json dist/data/" in workflow


def test_repository_real_watchlist_payload_is_valid_and_not_mock_data() -> None:
    path = ROOT / "data" / "public-stock-watchlist-v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    validate_stock_watchlist_payload(payload)
    assert payload["coverage"]["eligible_count"] > 0
    assert payload["short"]["count"] == payload["long"]["count"] > 0
    assert {
        row["instrument"]["instrument_id"] for row in payload["short"]["items"]
    } == {
        row["instrument"]["instrument_id"] for row in payload["long"]["items"]
    }
    assert "mock" not in path.read_text(encoding="utf-8").lower()
