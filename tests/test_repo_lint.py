"""lint/repo_lint.py: each past mistake (docs/MISTAKES.md) has a sample that must fail.

Add a case here whenever a rule is added or widened (skills/mistake-to-lint).
Stdlib + pytest only, so CI runs it without the job venv.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("repo_lint", ROOT / "lint" / "repo_lint.py")
lint = importlib.util.module_from_spec(_spec)
sys.modules["repo_lint"] = lint
_spec.loader.exec_module(lint)

# Fake credentials are assembled at runtime so this file never contains one.
PW = "Zq" + "8vT2mKp4LxW9"


def rules(path: str, text: str) -> set[str]:
    return {f.rule for f in lint.lint_text(path, text)}


BAD = [
    # M001 pipeline dual import
    ("job/scripts/new_job.py", "from scripts.radar_store import redact_error\n", "job-dual-import"),
    # M004 colours
    ("front/src/index.css", ":root { --up: var(--green); }\n", "color-convention"),
    ("front/src/index.css", ".fd .is-up { color: var(--green); }\n", "color-convention"),
    ("front/src/components/stock/Chart.tsx", "series({ upColor: '#16a34a', downColor: '#dc2626' })\n", "color-convention"),
    ("front/src/components/stock/Tv.tsx", "s.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'\n", "color-convention"),
    # M005 wording
    ("front/src/components/home/Lean.tsx", "const label = '偏防守';\n", "wording-euphemism"),
    ("job/scripts/build_theme_focus.py", "summary = '外資偏保守'\n", "wording-euphemism"),
    ("front/src/components/home/News.tsx", "<h2>最新信息</h2>\n", "wording-taiwan"),
    ("front/src/components/home/News.tsx", "<h2>美聯儲利率決議</h2>\n", "wording-taiwan"),
    ("front/src/components/home/News.tsx", "<h2>题材热度</h2>\n", "wording-taiwan"),
    # M008 retired project / M009 direct host
    ("front/src/services/metricsService.ts", "const u = 'https://abtdxucfppnjdqkwqiqh.supabase.co/functions/v1/x'\n", "supabase-project-ref"),
    ("docs/SETUP.md", "host: db.xdixmdglgzaiugvfxmuw.supabase.co\n", "supabase-direct-host"),
    ("job/mac/cutover.sh", "echo 'paste postgresql://u:p@db.<ref>.supabase.co:5432/postgres'\n", "supabase-direct-host"),
    # M010 role names
    ("job/mac/cutover.sh", 'ask THEME_RADAR_DATABASE_URL "radar_writer 連線字串" 1\n', "db-role-registry"),
    ("docs/SETUP.md", "postgresql://radar_writer.xdixmdglgzaiugvfxmuw:<pw>@host:5432/postgres\n", "db-role-registry"),
    ("docs/SETUP.md", "grant radar_reader to radar_reader_login;\n", "db-role-registry"),
    ("docs/SETUP.md", "postgresql://postgres.xdixmdglgzaiugvfxmuw:" + PW + "@h:5432/postgres\n", "db-role-registry"),
    # M013 one scheduler
    (".github/workflows/x.yml", "on:\n  schedule:\n    - cron: '17 * * * *'\n", "no-github-schedule"),
    ("db/supabase/migrations/20990101000000_x.sql", "select cron.schedule('x', '* * * * *', $$select 1$$);\n", "no-pg-cron"),
    # M017 front reads only the API
    ("front/src/services/dataService.ts", "const r = await fetch('./data/public-theme-momentum-latest.json');\n", "front-api-only"),
    # M022 secrets
    ("job/config/x.py", "URL = 'postgresql://theme_radar_app.ref:" + PW + "@host:5432/postgres'\n", "secrets"),
    ("job/config/x.py", "KEY = 'sk-" + "ant-" + "a" * 30 + "'\n", "secrets"),
    ("job/.env", "X=1\n", "secrets"),
]


@pytest.mark.parametrize("path,text,rule", BAD, ids=[f"{r}:{p}" for p, _, r in BAD])
def test_past_mistake_is_caught(path, text, rule):
    assert rule in rules(path, text)


GOOD = [
    ("job/scripts/ok_job.py", "try:\n    from scripts.radar_store import redact_error\nexcept ModuleNotFoundError:\n    from radar_store import redact_error\n"),
    ("front/src/index.css", ":root { --up: var(--red); --down: var(--green); }\n.fd .is-up { color: var(--up); }\n"),
    ("front/src/components/home/Lean.tsx", "const label = '偏空';\n"),
    ("front/src/components/home/News.tsx", "<h2>最新資訊</h2> {/* 信息 lint-ok: wording-taiwan quoted source term */}\n"),
    ("docs/SETUP.md", "postgresql://theme_radar_app.xdixmdglgzaiugvfxmuw:<password>@aws-1-ap-southeast-2.pooler.supabase.com:5432/postgres\n"),
    ("front/src/services/dataService.ts", "const r = await fetch(`${API}/api/v1/theme-focus`);\n"),
    ("tests/test_x.py", "url = 'postgresql://u:p@h/db'\n"),
]


@pytest.mark.parametrize("path,text", GOOD)
def test_correct_code_passes(path, text):
    assert rules(path, text) == set()


def test_repo_is_clean_against_its_baseline():
    findings = lint.run(lint.tracked_files())
    new, _, stale = lint.split_baseline(findings)
    assert not new, "\n".join(f.render() for f in new)
    assert not stale, f"remove fixed entries from lint/baseline.json: {stale}"


def test_every_baseline_entry_has_a_reason():
    baseline = json.loads((ROOT / "lint" / "baseline.json").read_text(encoding="utf-8"))
    for rule, entries in baseline.items():
        if rule.startswith("_"):
            continue
        assert rule in {r.id for r in lint.FILE_RULES} | {r.id for r in lint.REPO_RULES}, rule
        for key, reason in entries.items():
            assert len(reason) > 20, f"{rule}/{key} needs a real reason"


def test_duplicate_migration_versions_are_caught(tmp_path, monkeypatch):
    mig = tmp_path / "db" / "supabase" / "migrations"
    mig.mkdir(parents=True)
    for name in ("20261118090000_a.sql", "20261118090000_b.sql"):
        (mig / name).write_text("select 1;\n")
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    assert [f.key for f in lint.rule_migration_versions()] == ["20261118090000"]


def test_facts_counts_jobs_from_jobs_conf():
    facts = lint.facts()
    conf = (ROOT / "job" / "mac" / "jobs.conf").read_text(encoding="utf-8")
    assert facts["mac_jobs"]["count"] == len(facts["mac_jobs"]["names"]) > 0
    assert all(f"\n{name} |" in conf for name in facts["mac_jobs"]["names"])


def _hook(kind: str, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "lint" / "repo_lint.py"), "hook", kind],
        input=json.dumps(payload), capture_output=True, text=True, cwd=ROOT,
    )


def test_claude_post_hook_blocks_a_bad_edit(tmp_path):
    bad = ROOT / "front" / "src" / "__lint_probe__.ts"
    bad.write_text("export const lean = '偏防守';\n", encoding="utf-8")
    try:
        result = _hook("claude-post", {"tool_name": "Write", "tool_input": {"file_path": str(bad)}})
    finally:
        bad.unlink()
    assert result.returncode == 2
    assert "wording-euphemism" in result.stderr


def test_claude_hooks_ignore_unrelated_calls():
    assert _hook("claude-post", {"tool_input": {"file_path": "/tmp/elsewhere.ts"}}).returncode == 0
    assert _hook("claude-bash", {"tool_input": {"command": "ls -la"}}).returncode == 0
