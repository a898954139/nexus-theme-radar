"""Cross-layer tests: pipeline code lives in job/, so `import scripts.x` resolves there.

These tests stay at the repository root because many of them pin contracts
between layers (job writes a dataset, backend serves it, front renders it).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOB = ROOT / "job"
for path in (ROOT, JOB):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


import pytest


@pytest.fixture(autouse=True)
def _no_live_monthly_revenue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep run_update() off the live TWSE/TPEx monthly revenue endpoints.

    Tests that exercise scripts/monthly_revenue.py inject a row fetcher and
    re-enable it explicitly.
    """
    monkeypatch.setenv("THEME_RADAR_MONTHLY_REVENUE", "0")
