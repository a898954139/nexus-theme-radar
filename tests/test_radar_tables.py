"""Mappers (scripts/radar_tables.py) and the publish CLI (scripts/radar_publish.py).

Pure tests run everywhere. The DB round trip lives in tests/js/datasets-db.test.mjs
(needs RADAR_TEST_DATABASE_URL); see docs/RADAR_RELATIONAL.md.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import radar_publish, radar_tables

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MIGRATION = ROOT / "supabase" / "migrations" / "20261119150000_create_radar_relational_core.sql"
RELATIONAL_MIGRATIONS = sorted((ROOT / "supabase" / "migrations").glob("2026111915*_create_radar_relational_*.sql")) + sorted(
    (ROOT / "supabase" / "migrations").glob("2026111916*_create_radar_relational_*.sql")
)


def load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def mapped():
    # broker-map/ is ~600MB of JSON: map the committed data once per module.
    return {name: loader(DATA) for name, loader in radar_tables.DATASETS.items()}


def test_every_registered_dataset_maps_committed_data(mapped):
    for name, item in mapped.items():
        assert item is not None, name
        assert item.row_count() > 0, name


def test_child_tables_and_columns_exist_in_the_migration(mapped):
    sql = "\n".join(p.read_text(encoding="utf-8") for p in RELATIONAL_MIGRATIONS)
    for name, item in mapped.items():
        tables = (
            [(item.header_table, tuple(item.header))] + [(c.table, c.columns) for c in item.children]
            if isinstance(item, radar_tables.Snapshot)
            else [(item.table, item.columns)]
        )
        for table, columns in tables:
            start = sql.index(f"create table if not exists radar.{table} (")
            body = sql[start: sql.index("\n);", start)]
            for column in columns:
                assert f"\n  {column} " in body, f"{name}: radar.{table}.{column} missing"


def test_rankings_keep_board_metadata_and_entry_metrics():
    snapshot = radar_tables.map_institutional_rankings(load("institutional-rankings.json"))
    boards, entries = snapshot.children
    assert len(boards.rows) == 16
    netbuy = [r for r in boards.rows if r[0] == "top_three_inst_netbuy_10_up"][0]
    assert netbuy[6] and netbuy[7] and netbuy[8]  # date range + source
    assert all(row[2] in snapshot.instruments for row in entries.rows)


def test_rankings_reject_code_that_disagrees_with_instrument_id():
    payload = load("institutional-rankings.json")
    board = next(iter(payload["rankings"].values()))
    board["entries"][0]["code"] = "9999"
    with pytest.raises(ValueError, match="disagree"):
        radar_tables.map_institutional_rankings(payload)


def test_instrument_ids_are_validated():
    with pytest.raises(ValueError, match="bad instrument_id"):
        radar_tables.add_instrument({}, "TWSE:../x")
    with pytest.raises(ValueError):
        radar_tables.add_instrument({}, "2330")


def test_broker_book_is_stored_once_and_is_the_union_over_symbol_files():
    stats = [{"name": "A", "buy": 1, "sell": 2, "dt": None, "ov": None, "top": [["2330", "台積電"]]}]
    coverage = {
        "generated_at": "2026-11-18T22:46:34Z", "source": "s", "requested_symbols": 2,
        "attempted_symbols": 2, "failed_symbols": 0, "successful_symbols": 2, "symbols_with_data": 2,
        "attempt_coverage": 1.0, "data_coverage": 1.0, "data_coverage_denominator": "requested_symbols",
        "status": "complete", "failed_symbol_codes": [], "no_data_symbol_codes": [], "not_attempted_symbol_codes": [],
    }
    index = {"unit": "lots", "symbols": {
        "2330": {"file": "2330.json", "name": "台積電", "broker_count": 1, "summary": {"buy": 5, "sell": 0, "net": 5}},
        "2317": {"file": "2317.json", "name": "鴻海", "broker_count": 1, "summary": {"buy": 0, "sell": 3, "net": -3}},
    }}
    files = {
        "2330.json": [{"id": "b1", "name": "B1", "net": 5, "ratio": 1.5, "stocks": [["2317", "鴻海", -3]]}],
        "2317.json": [{"id": "b1", "name": "B1", "net": -3, "ratio": 0.5, "stocks": [["2330", "台積電", 5]]}],
    }
    snapshot = radar_tables.map_broker(stats, coverage, index, files)
    book = [c for c in snapshot.children if c.table == "broker_branch_stock"][0]
    assert book.rows == [("b1", 0, "2330", "台積電", 5), ("b1", 1, "2317", "鴻海", -3)]
    assert snapshot.brokers == {"b1": "B1"}


def test_theme_focus_keeps_null_headline_and_null_stock_flow():
    payload = load("theme-focus.json")
    payload["themes"][0]["headline"] = None
    payload["themes"][0]["leaders"][0]["flow"] = None
    snapshot = radar_tables.map_theme_focus(payload)
    themes, stocks = snapshot.children
    assert themes.rows[0][-1] is False
    leader = [r for r in stocks.rows if r[0] == payload["themes"][0]["theme_id"] and r[1] == "leader"][0]
    assert leader[5] is None


def test_publish_without_credential_is_skipped_unless_required(tmp_path, caplog):
    (tmp_path / "source-status.json").write_text((DATA / "source-status.json").read_text(encoding="utf-8"), encoding="utf-8")
    assert radar_publish.run(tmp_path, ["source-status"], require=False, connect=lambda: None) == 0
    assert "radar_publish_skipped" in caplog.text
    assert radar_publish.run(tmp_path, ["source-status"], require=True, connect=lambda: None) == 1


def test_publish_reports_invalid_payload_before_connecting(tmp_path):
    (tmp_path / "theme-focus.json").write_text(json.dumps({"generated_at": "x"}), encoding="utf-8")
    calls = []

    def connect():
        calls.append(1)
        return None

    assert radar_publish.run(tmp_path, ["theme-focus"], require=True, connect=connect) == 1


def test_publish_redacts_connection_errors(tmp_path, caplog):
    def connect():
        raise RuntimeError("could not connect postgres://u:secret@db.example/postgres")

    assert radar_publish.run(tmp_path, ["source-status"], require=True, connect=connect) == 1
    assert "secret" not in caplog.text


def test_entrypoint_resolves_imports_the_way_ci_runs_it():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "radar_publish.py"), "--help"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr


def test_workflows_publish_with_the_gated_secret():
    for workflow, dataset in (
        ("update-institutional-flows.yml", "institutional-flows"),
        ("update-theme-radar.yml", "source-status"),
        ("update-theme-radar.yml", "theme-momentum-history"),
        ("update-broker-data.yml", "broker"),
    ):
        text = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        assert f"radar_publish.py --data-dir data" in text and f"--dataset {dataset}" in text
        assert "vars.THEME_RADAR_DB_HISTORY_AUTHORIZED_ENVIRONMENT == 'production'" in text


def test_purge_function_cannot_be_steered_by_the_caller():
    for path in RELATIONAL_MIGRATIONS:
        _assert_purge_locked(path.read_text(encoding="utf-8"))


def _assert_purge_locked(sql: str) -> None:
    assert "security definer" in sql and "set search_path = pg_catalog, radar" in sql
    assert "revoke all on function radar.purge_snapshots(integer) from public" in sql
    assert "grant delete" not in sql.lower()


def test_momentum_history_series_is_keyed_by_hour_and_theme(mapped):
    series = mapped["theme-momentum-history"]
    keys = [(row[0], row[1]) for row in series.rows]
    assert len(keys) == len(set(keys)) == 1321


def test_theme_events_symbols_reference_registered_instruments(mapped):
    snapshot = mapped["theme-events"]
    symbols = [c for c in snapshot.children if c.table == "theme_event_symbol"][0]
    assert symbols.rows and all(row[3] in snapshot.instruments for row in symbols.rows)
