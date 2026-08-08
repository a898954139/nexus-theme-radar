"""Anti-inflation rules for the pageview Edge Function.

The site is static, so this function is the only thing standing between the
public and the counter tables. These are the checks that decide whether a write
is allowed, so they are tested directly rather than through the HTTP layer.

Follows the repo's existing convention of exercising frontend JS through
`node -e` (see test_homepage_theme_momentum_entry.py) instead of introducing a
JavaScript test runner.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIMITS_PATH = ROOT / "supabase" / "functions" / "pageview" / "limits.ts"


def _limits_as_js() -> str:
    """Strip TypeScript-only syntax so the module runs under plain node."""
    source = LIMITS_PATH.read_text(encoding="utf-8")
    source = source.replace("value: unknown): value is string", "value)")
    source = source.replace("origin: string | null): boolean", "origin)")
    source = source.replace("recentRequestCount: number): boolean", "recentRequestCount)")
    source = source.replace("export const", "const").replace("export function", "function")
    return source


def _run(expression: str) -> str:
    script = _limits_as_js() + "\n" + expression
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _evaluate(expression: str) -> object:
    return json.loads(_run(f"console.log(JSON.stringify({expression}))"))


def test_typescript_stripping_actually_produces_runnable_js() -> None:
    # Guards the harness itself: a syntax error here would make every other
    # assertion in this file vacuous.
    assert _evaluate("typeof isValidVisitorId === 'function'") is True
    assert _evaluate("typeof isAllowedOrigin === 'function'") is True
    assert _evaluate("typeof isRateLimited === 'function'") is True


def test_valid_uuid_is_accepted() -> None:
    assert _evaluate("isValidVisitorId('3f8a1c62-9d4e-4b7a-8c15-2e6f0b9d4a73')") is True


def test_malformed_visitor_ids_are_rejected() -> None:
    rejected = [
        "''",
        "'not-a-uuid'",
        "'3f8a1c62-9d4e-4b7a-8c15'",
        "'3f8a1c62-9d4e-4b7a-8c15-2e6f0b9d4a73-extra'",
        "'<script>alert(1)</script>'",
        "null",
        "undefined",
        "42",
        "{}",
        "[]",
    ]
    for candidate in rejected:
        assert _evaluate(f"isValidVisitorId({candidate})") is False, candidate


def test_uuid_check_rejects_sql_and_injection_shaped_input() -> None:
    # There are no free-text columns, but the id reaches a query builder, so the
    # shape check is the guard that matters.
    assert _evaluate("""isValidVisitorId("' OR 1=1 --")""") is False


def test_allowed_origins_are_the_published_site() -> None:
    assert _evaluate("isAllowedOrigin('https://a898954139.github.io')") is True
    assert _evaluate("isAllowedOrigin('https://news.learnprompt.pro')") is True


def test_foreign_and_missing_origins_are_rejected() -> None:
    for origin in ["'https://evil.example'", "'http://a898954139.github.io'", "null", "''"]:
        assert _evaluate(f"isAllowedOrigin({origin})") is False, origin


def test_rate_limit_triggers_at_the_documented_threshold() -> None:
    assert _evaluate("RATE_LIMIT_MAX_REQUESTS") == 20
    assert _evaluate("isRateLimited(19)") is False
    assert _evaluate("isRateLimited(20)") is True
    assert _evaluate("isRateLimited(500)") is True


def test_rate_limit_leaves_headroom_for_normal_visitors() -> None:
    # A visitor sends one view plus a heartbeat every 45s: under 3 per minute.
    # Shared IPs (offices, mobile carriers) must not trip the limit.
    assert _evaluate("isRateLimited(3)") is False


def test_windows_match_the_spec() -> None:
    assert _evaluate("DEDUP_WINDOW_MS") == 30 * 60 * 1000
    assert _evaluate("ONLINE_WINDOW_MS") == 2 * 60 * 1000
    assert _evaluate("RATE_LIMIT_WINDOW_MS") == 60 * 1000


INDEX_PATH = ROOT / "supabase" / "functions" / "pageview" / "index.ts"


def _index_source() -> str:
    return INDEX_PATH.read_text(encoding="utf-8")


def test_windows_are_applied_as_sql_intervals_not_hardcoded_numbers() -> None:
    # The windows moved into SQL. A literal there would silently drift from the
    # constants these tests pin, so the queries must reference the constants.
    source = _index_source()
    assert "intervalMs(DEDUP_WINDOW_MS)" in source
    assert "intervalMs(ONLINE_WINDOW_MS)" in source
    assert "intervalMs(RATE_LIMIT_WINDOW_MS)" in source


def test_heartbeats_never_insert_into_page_view() -> None:
    # The property that keeps a 45-second ping from inflating the total: the
    # page_view insert is unreachable unless kind === 'view'.
    source = _index_source()
    guard = source.index("if (kind !== 'view') return;")
    assert guard < source.index("insert into site_metrics.page_view")


def test_dedup_is_enforced_inside_the_insert() -> None:
    # Checking then inserting as two statements would let two simultaneous
    # requests from one visitor both pass and double-count.
    source = _index_source()
    insert_index = source.index("insert into site_metrics.page_view")
    tail = source[insert_index:]
    assert "where not exists" in tail[: tail.index("`")]


def test_site_metrics_is_reached_over_postgres_not_postgrest() -> None:
    # site_metrics is deliberately absent from PostgREST's exposed schemas, so
    # a supabase-js client cannot see it -- that mistake failed closed and made
    # every write look rate limited.
    source = _index_source()
    assert "postgresjs" in source
    assert "@supabase/supabase-js" not in source
