"""The visitor counter must not blink out when a single poll fails.

Regression test for the counter appearing intermittently: every heartbeat
result was applied to state unconditionally, so one failed or timed-out request
set the counts to null and StatusBar -- which renders only when counts is
truthy -- dropped the numbers until the next success 45 seconds later.

Exercises the real reducer through node, following the repo convention of
testing frontend JS via subprocess rather than adding a JS test runner.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COUNTS_PATH = ROOT / "src" / "lib" / "counts.ts"
HOOK_PATH = ROOT / "src" / "hooks" / "useSiteMetrics.ts"
STATUS_BAR_PATH = ROOT / "src" / "components" / "common" / "StatusBar.tsx"


def _counts_as_js() -> str:
    """Strip the import and type annotations so the reducer runs under node."""
    source = COUNTS_PATH.read_text(encoding="utf-8")
    source = "\n".join(
        line for line in source.splitlines() if not line.startswith("import ")
    )
    source = source.replace(
        "nextCounts(current: SiteCounts | null, incoming: SiteCounts | null): SiteCounts | null",
        "nextCounts(current, incoming)",
    )
    return source.replace("export function", "function")


def _evaluate(expression: str) -> object:
    script = _counts_as_js() + f"\nconsole.log(JSON.stringify({expression}))"
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout.strip())


def test_reducer_module_is_runnable() -> None:
    assert _evaluate("typeof nextCounts === 'function'") is True


def test_a_failed_poll_keeps_the_numbers_already_on_screen() -> None:
    # The bug: this returned null and the counter vanished mid-session.
    assert _evaluate("nextCounts({total: 27, online: 3}, null)") == {"total": 27, "online": 3}


def test_a_successful_poll_replaces_the_previous_values() -> None:
    assert _evaluate("nextCounts({total: 27, online: 3}, {total: 28, online: 4})") == {
        "total": 28,
        "online": 4,
    }


def test_counter_stays_visible_across_a_flapping_connection() -> None:
    # One dropped heartbeat between successes must not blank the display.
    sequence = _evaluate(
        """(() => {
          const polls = [{total: 27, online: 3}, null, null, {total: 29, online: 5}, null];
          let counts = null;
          const seen = [];
          for (const poll of polls) {
            counts = nextCounts(counts, poll);
            seen.push(counts === null ? 'hidden' : 'visible');
          }
          return seen;
        })()"""
    )
    assert sequence == ["visible", "visible", "visible", "visible", "visible"]


def test_counter_stays_hidden_until_the_first_success() -> None:
    # Before any data arrives there is nothing to show, so the placeholder is
    # correct -- the fix must not invent a zero.
    assert _evaluate("nextCounts(null, null)") is None


def test_hook_routes_poll_results_through_the_reducer() -> None:
    # Guards the wiring: the reducer only helps if the hook actually uses it.
    hook = HOOK_PATH.read_text(encoding="utf-8")
    assert "nextCounts" in hook
    assert "setCounts(next)" not in hook


def test_status_bar_still_hides_the_block_when_there_is_no_data() -> None:
    status_bar = STATUS_BAR_PATH.read_text(encoding="utf-8")
    assert "{counts ? (" in status_bar


def test_request_timeout_clears_measured_endpoint_latency() -> None:
    # The endpoint answers in ~2.5-3s because the database is in ap-southeast-2.
    # A timeout near that figure aborts healthy requests on slower connections,
    # which is what made the counter flicker.
    service = (ROOT / "src" / "services" / "metricsService.ts").read_text(encoding="utf-8")
    line = next(
        one for one in service.splitlines() if one.startswith("const REQUEST_TIMEOUT_MS")
    )
    timeout_ms = int(line.split("=")[1].strip().rstrip(";"))
    assert timeout_ms >= 10_000
