from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import pytest


@pytest.fixture(autouse=True)
def _no_live_monthly_revenue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep run_update() off the live TWSE/TPEx monthly revenue endpoints.

    Tests that exercise scripts/monthly_revenue.py inject a row fetcher and
    re-enable it explicitly.
    """
    monkeypatch.setenv("THEME_RADAR_MONTHLY_REVENUE", "0")
