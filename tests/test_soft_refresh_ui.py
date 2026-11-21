from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_app_refreshes_runtime_data_every_five_minutes_without_navigation_reload() -> None:
    source = (ROOT / "front/src" / "App.tsx").read_text(encoding="utf-8")

    assert "const DATA_REFRESH_INTERVAL_MS = 5 * 60 * 1000;" in source
    assert "window.setInterval(refresh, DATA_REFRESH_INTERVAL_MS)" in source
    assert "loadRadarData(true)" in source
    assert "fetchStockWatchlist(true)" in source
    assert "window.location.reload" not in source


def test_runtime_data_service_can_bypass_static_payload_cache() -> None:
    source = (ROOT / "front/src" / "services" / "dataService.ts").read_text(encoding="utf-8")

    assert "cacheBust = false" in source
    assert "cache: cacheBust ? 'no-store' : 'default'" in source
    assert "search.set('refresh', String(Date.now()))" in source
