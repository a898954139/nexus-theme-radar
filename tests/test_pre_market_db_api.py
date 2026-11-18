"""Issue #5: pre-market page served from the DB via /api/pre-market.

The behavioural contract of the API itself lives in
tests/js/pre-market-api.test.mjs (`npm run test:api`). These tests pin the
pieces around it that would fail silently: the snapshot writer, the workflow
credential gate, and that no database credential can reach the client build.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from radar_store import (  # noqa: E402
    PRE_MARKET_UPSERT_SQL,
    map_pre_market_snapshot,
    write_pre_market_snapshot,
)
from update_pre_market import run_pre_market_dual_write  # noqa: E402

PAYLOAD_PATH = ROOT / "data" / "pre-market-latest.json"
MIGRATION = ROOT / "supabase" / "migrations" / "20261118090000_create_radar_pre_market_snapshot.sql"


def _payload() -> dict:
    return json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))


class _Scope:
    def __init__(self, target):
        self.target = target

    def __enter__(self):
        return self.target

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, fail: bool = False) -> None:
        self.executed: list[tuple[str, dict]] = []
        self.fail = fail
        self.closed = False

    def transaction(self):
        return _Scope(self)

    def cursor(self):
        return _Scope(self)

    def execute(self, sql, params):
        if self.fail:
            raise RuntimeError("boom postgresql://u:secret@db.example/x password=secret")
        self.executed.append((sql, params))

    def close(self):
        self.closed = True


# --- writer ----------------------------------------------------------------


def test_snapshot_row_stores_the_payload_verbatim() -> None:
    payload = _payload()
    row = map_pre_market_snapshot(payload)
    assert json.loads(row["payload"]) == payload
    assert row["event_count"] == len(payload["events"])
    assert row["schema_version"] == payload["schema_version"]
    assert row["generated_at"].tzinfo is not None


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(extra=1),
    lambda p: p.pop("flows"),
    lambda p: p.update(events={}),
    lambda p: p.update(generated_at="not-a-time"),
])
def test_snapshot_rejects_contract_drift(mutate) -> None:
    payload = _payload()
    mutate(payload)
    with pytest.raises(ValueError):
        map_pre_market_snapshot(payload)


def test_snapshot_accepts_direction_rule_version_from_issue_9() -> None:
    payload = {**_payload(), "direction_rule_version": "direction-v1"}
    assert json.loads(map_pre_market_snapshot(payload)["payload"]) == payload


def test_snapshot_upsert_is_idempotent_on_generated_at() -> None:
    connection = FakeConnection()
    write_pre_market_snapshot(connection, _payload())
    assert connection.executed[0][0] == PRE_MARKET_UPSERT_SQL
    assert "on conflict (generated_at) do update" in PRE_MARKET_UPSERT_SQL.lower()


def test_dual_write_fails_closed_and_redacts(caplog) -> None:
    assert run_pre_market_dual_write(None, _payload()) == "skipped"
    connection = FakeConnection(fail=True)
    assert run_pre_market_dual_write(lambda: connection, _payload()) == "failed"
    assert connection.closed is True
    assert "secret" not in caplog.text
    ok = FakeConnection()
    assert run_pre_market_dual_write(lambda: ok, _payload()) == "written"
    assert ok.closed is True


# --- migration ---------------------------------------------------------------


def test_migration_is_rerunnable_and_least_privilege() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "create table if not exists radar.pre_market_snapshot (" in sql
    assert "generated_at timestamptz primary key" in sql
    assert "grant select, insert, update on radar.pre_market_snapshot to radar_writer" in sql
    assert "grant select on radar.pre_market_snapshot to radar_reader" in sql
    assert "delete" not in sql
    assert "to anon" not in sql and "to authenticated" not in sql


# --- workflow gate -----------------------------------------------------------


def test_pre_market_workflow_gates_the_credential_to_master_production() -> None:
    spec = yaml.safe_load((ROOT / ".github/workflows/update-pre-market.yml").read_text(encoding="utf-8"))
    steps = spec["jobs"]["update"]["steps"]
    build = next(step for step in steps if step.get("name") == "Build pre-market board")
    expr = build["env"]["THEME_RADAR_DATABASE_URL"]
    assert "github.ref_name == 'master'" in expr
    assert "vars.THEME_RADAR_DB_HISTORY_AUTHORIZED_ENVIRONMENT == 'production'" in expr
    assert expr.strip().endswith("&& secrets.THEME_RADAR_DATABASE_URL || '' }}")
    # Only the build step sees the secret; the commit step must not.
    others = [step for step in steps if step is not build]
    assert all("THEME_RADAR_DATABASE_URL" not in json.dumps(step) for step in others)


# --- client cannot carry credentials ----------------------------------------

FORBIDDEN = ("service_role", "postgres://", "postgresql://", "radar_api_database",
             "theme_radar_database_url", "sslmode=")


def _client_sources() -> list[Path]:
    return [p for p in (ROOT / "src").rglob("*") if p.suffix in {".ts", ".tsx", ".js"}]


def test_client_sources_never_reference_db_credentials_or_driver() -> None:
    for path in _client_sources():
        text = path.read_text(encoding="utf-8").casefold()
        for token in FORBIDDEN:
            assert token not in text, f"{token} in {path}"
        assert not re.search(r"from ['\"]pg['\"]", text), path
        assert "process.env" not in text, path


def test_only_the_public_flag_is_vite_prefixed() -> None:
    vite_vars = set()
    for path in [*_client_sources(), ROOT / "vercel.json", ROOT / "vite.config.ts"]:
        vite_vars |= set(re.findall(r"VITE_[A-Z0-9_]+", path.read_text(encoding="utf-8")))
    assert vite_vars == {"VITE_PRE_MARKET_SOURCE"}


def test_api_reads_credentials_from_server_env_only() -> None:
    api = (ROOT / "api" / "pre-market.js").read_text(encoding="utf-8")
    assert "process.env.RADAR_API_DATABASE_URL" in api
    for token in ("postgres://", "postgresql://", "service_role", "process.env.VITE_"):
        assert token not in api


@pytest.mark.skipif(not (ROOT / "dist").is_dir(), reason="run `npm run build` first")
def test_built_assets_contain_no_credentials() -> None:
    assets = [p for p in (ROOT / "dist").rglob("*") if p.suffix in {".js", ".html", ".css", ".map"}]
    assert assets, "dist has no built assets"
    for path in assets:
        text = path.read_text(encoding="utf-8", errors="ignore").casefold()
        for token in FORBIDDEN:
            assert token not in text, f"{token} in {path}"


# --- Vercel config -----------------------------------------------------------


def test_vercel_builds_the_app_and_publishes_the_same_data_as_pages() -> None:
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert config["outputDirectory"] == "dist"
    assert "sh scripts/copy_runtime_data.sh dist" in config["buildCommand"]
    assert "api/pre-market.js" in config["functions"]
    pages = (ROOT / ".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
    assert "sh scripts/copy_runtime_data.sh dist" in pages
