"""Pin and parity tests for the private ``nexus-structure-detector`` package.

The installed package must reproduce, record for record, the detector evidence
already stored in the committed Stock Audit reports (swings, BOS/CHoCH breaks,
OB/FVG zone ledger and the raw engine hash) without any NexusDashboard checkout.

The package lives in a private repository, so these tests skip (they do not
fail) when it is not installed; install it as described in docs/STOCK_AUDIT.md.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts import analyze_stock_audit_technical as mod


ROOT = Path(__file__).parents[1]
PACKAGE_DIR = mod.DETECTOR_PACKAGE_DIR
PACKAGED_SOURCE = PACKAGE_DIR / "src/nexusStructureDetector.js"
PARITY_REPORTS = ("reports/stock-audit-2026-10-21.json", "reports/stock-audit-2026-10-22.json")
NODE = shutil.which("node")
PACKAGE_INSTALLED = (PACKAGE_DIR / "package.json").exists() and PACKAGED_SOURCE.exists()
requires_package = pytest.mark.skipif(
    not PACKAGE_INSTALLED,
    reason="private nexus-structure-detector package not installed (see docs/STOCK_AUDIT.md)",
)
requires_node = pytest.mark.skipif(
    NODE is None or not PACKAGE_INSTALLED,
    reason="node and the installed nexus-structure-detector package are required",
)


@requires_package
def test_packaged_source_matches_pin_and_manifest():
    manifest = json.loads((PACKAGE_DIR / "package.json").read_text(encoding="utf-8"))
    upstream = manifest["nexusUpstream"]
    actual = mod._sha256(PACKAGED_SOURCE)
    assert actual == mod.PINNED_SOURCE_SHA256["nexus-structure"]
    assert actual == upstream["sha256"]
    assert len(upstream["commit"]) == 40


def test_default_detector_path_prefers_env_then_package_then_legacy(monkeypatch):
    monkeypatch.delenv("NEXUS_STRUCTURE_DETECTOR_PATH", raising=False)
    expected = PACKAGED_SOURCE if PACKAGED_SOURCE.exists() else mod.LEGACY_DETECTOR_PATH
    assert mod._default_detector_path() == expected
    monkeypatch.setenv("NEXUS_STRUCTURE_DETECTOR_PATH", "/opt/detector.js")
    assert mod._default_detector_path() == Path("/opt/detector.js")


@requires_package
def test_receipt_revision_is_upstream_commit_not_host_head():
    receipt = mod._source_receipt(PACKAGED_SOURCE, method_id="nexus-structure", params={})
    manifest = json.loads((PACKAGE_DIR / "package.json").read_text(encoding="utf-8"))
    assert receipt["revision"] == manifest["nexusUpstream"]["commit"]
    assert receipt["source_path"] == "nexusStructureDetector.js"


def _parity_cases():
    for report in PARITY_REPORTS:
        data = json.loads((ROOT / report).read_text(encoding="utf-8"))
        for stock in data["stocks"]:
            analysis = stock.get("technical_analysis") or {}
            if analysis.get("analysis_status") == "complete" and stock.get("technical_candles"):
                yield pytest.param(stock, id=f"{Path(report).stem}-{stock['symbol']}")


@requires_node
@pytest.mark.parametrize("stock", list(_parity_cases()))
def test_packaged_detector_reproduces_stored_stock_audit_evidence(stock):
    stored = stock["technical_analysis"]
    as_of = mod._date(stored["as_of"])
    candles = mod._validate_candles(stock["technical_candles"], as_of=as_of, minimum=mod.MIN_TECHNICAL_BARS)
    mintick = float(mod._tick(float(candles[-1]["close"])))
    weekly, _ = mod.aggregate_completed_weekly(candles, as_of, stock.get("week_completion"))
    stored_zones = {zone["id"]: zone for zone in stored["zones"]}

    for timeframe, series in (("D1", candles), ("W1", weekly)):
        engine = mod._run_detector(series, timeframe=timeframe, detector_path=PACKAGED_SOURCE, mintick=mintick, replay=True)
        expected = stored["timeframes"][timeframe]
        current_ids = {str(raw["id"]) for key in ("fvgZones", "obZones") for raw in engine["current"].get(key, [])}
        zones = [
            mod._zone_validation(raw, series, timeframe, current_engine_ids=current_ids, as_of=mod._date(series[-1]["date"]))
            for raw in engine["replay"].get("fvgZones", []) + engine["replay"].get("obZones", [])
        ]

        assert mod._pivot_candidates(engine["pivots"], series, timeframe=timeframe) == expected["pivots"]
        assert mod._normalize_breaks(engine["current"].get("structureBreaks", []), series, timeframe) == expected["breaks"]
        assert {zone["id"]: zone for zone in zones} == {
            key: zone for key, zone in stored_zones.items() if zone["timeframe"] == timeframe
        }
        assert engine["current"].get("summary") == expected["engine"]["summary"]
        assert {
            "fvg": len(engine["replay"]["fvgZones"]),
            "ob": len(engine["replay"]["obZones"]),
        } == expected["engine"]["replay_candidate_counts"]
        if "raw_engine_sha256" in expected:
            assert mod._canonical_hash(engine["current"]) == expected["raw_engine_sha256"]


@requires_node
def test_package_installs_and_runs_outside_this_repo(tmp_path: Path):
    """Clean-environment install: no NexusDashboard, no repo, only the packed tarball."""
    npm = shutil.which("npm")
    if npm is None:
        pytest.skip("npm is required for the install check")
    subprocess.run([npm, "pack", str(PACKAGE_DIR), "--silent", "--pack-destination", str(tmp_path)], check=True, capture_output=True, timeout=120)
    tarball = next(tmp_path.glob("nexus-structure-detector-*.tgz"))
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "package.json").write_text('{"name":"consumer","private":true,"type":"module"}')
    subprocess.run([npm, "install", "--silent", "--no-audit", "--no-fund", str(tarball)], cwd=consumer, check=True, capture_output=True, timeout=180)
    script = (
        "import { detectNexusStructure, detectPivots, SOURCE_SHA256, UPSTREAM } from 'nexus-structure-detector';"
        "const r = detectNexusStructure([], {});"
        "process.stdout.write(JSON.stringify({ok: SOURCE_SHA256 === UPSTREAM.sha256, fn: typeof detectPivots, breaks: r.structureBreaks.length}))"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=consumer, check=True, capture_output=True, text=True, timeout=60)
    assert json.loads(result.stdout) == {"ok": True, "fn": "function", "breaks": 0}
    installed = consumer / "node_modules/nexus-structure-detector/src/nexusStructureDetector.js"
    assert mod._sha256(installed) == mod.PINNED_SOURCE_SHA256["nexus-structure"]
