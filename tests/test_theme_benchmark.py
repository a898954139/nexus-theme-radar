from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import benchmark_theme_taxonomy
from scripts.theme_relevance import score_theme_relevance

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_SOURCE = (
    ROOT / "tests" / "fixtures" / "theme_benchmark" / "v0.7" / "manifest.json"
)
REAL_SOURCE = (
    ROOT / "tests" / "fixtures" / "theme_benchmark" / "v0.7" / "real-records.json"
)
SYNTHETIC_SOURCE = (
    ROOT / "tests" / "fixtures" / "theme_benchmark" / "v0.7" / "synthetic-cases.json"
)
DIGITIMES_FIXTURE_SHA256 = (
    "c72051f04c9a00e3eda4e7823d388c77a59c05f4d1d2f6038ec575eb767d740f"
)
DIGITIMES_RSS_PATH = ROOT / "tests" / "fixtures" / "digitimes_tw_rss.xml"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raw_record(record_id: str, *, provenance: str = "real", **patches: object) -> dict[str, object]:
    record: dict[str, object] = {
        "record_id": record_id,
        "source_id": "fixture-lab",
        "endpoint": "https://example.com/api",
        "captured_at": "2026-07-27T06:00:00Z",
        "published_at": "2026-07-27T06:00:00Z",
        "canonical_url": "https://example.com/probe",
        "title": "Probe fixture",
        "description": "fixture record",
        "expected_theme_ids": ["semicon_foundry_advanced"],
        "adjudication": "positive",
        "adjudicated_by": "fixture",
        "adjudicated_at": "2026-07-27T06:01:00Z",
        "notes": "probe",
        "event_cluster_id": "probe-cluster",
        "adjudication_split": "heldout",
        "provenance": provenance,
        "raw_fixture_sha256": "probe-hash",
    }
    record.update(patches)
    return record


def _manifest_path(tmp_path: Path, *, real: list[dict], synthetic: list[dict]) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    real_path = tmp_path / "real-records.json"
    synth_path = tmp_path / "synthetic-cases.json"
    manifest_path = tmp_path / "manifest.json"

    _write_json(real_path, real)
    _write_json(synth_path, synthetic)

    manifest = json.loads(MANIFEST_SOURCE.read_text(encoding="utf-8"))
    manifest["real_records_path"] = real_path.name
    manifest["synthetic_records_path"] = synth_path.name
    manifest["fixtures"] = {
        "real_records": {"path": real_path.name, "sha256": _file_hash(real_path)},
        "synthetic_records": {
            "path": synth_path.name,
            "sha256": _file_hash(synth_path),
        },
    }
    _write_json(manifest_path, manifest)
    return manifest_path


def _load_source_payloads() -> tuple[list[dict], list[dict]]:
    return (
        json.loads(REAL_SOURCE.read_text(encoding="utf-8")),
        json.loads(SYNTHETIC_SOURCE.read_text(encoding="utf-8")),
    )


def _digitimes_entry(index: int) -> dict[str, str]:
    root = ET.fromstring(DIGITIMES_RSS_PATH.read_text(encoding="utf-8"))
    item = root.find("channel").findall("item")[index]
    return {
        "published_at": item.findtext("pubDate") or "",
        "title": (item.findtext("title") or "").strip(),
        "description": (item.findtext("description") or "").strip(),
        "canonical_url": (item.findtext("link") or "").strip(),
    }


def _utc_timestamp(value: str) -> str:
    if not value:
        return ""
    return datetime.fromisoformat(value).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def test_benchmark_rejects_bad_manifest_hash_or_missing_fixture_fields(tmp_path: Path) -> None:
    real_records, synthetic_records = _load_source_payloads()
    manifest = _manifest_path(
        tmp_path / "missing-hash",
        real=real_records,
        synthetic=synthetic_records,
    )

    with pytest.raises(ValueError, match="raw_fixture_sha256"):
        benchmark_theme_taxonomy.run_benchmark(
            _manifest_path(
                tmp_path / "missing-field",
                real=[
                    _raw_record("r01", raw_fixture_sha256=""),
                ],
                synthetic=synthetic_records,
            )
        )

    (manifest.parent / "real-records.json").write_text("[{", encoding="utf-8")
    with pytest.raises(ValueError, match="fixture sha256 mismatch"):
        # Tampered file without updating manifest checksum
        benchmark_theme_taxonomy.run_benchmark(manifest)


def test_benchmark_rejects_provenance_mismatch(tmp_path: Path) -> None:
    real_records, synthetic_records = _load_source_payloads()
    mismatch = _raw_record("r01", provenance="synthetic")
    manifest_path = _manifest_path(
        tmp_path / "bad-provenance",
        real=[mismatch],
        synthetic=synthetic_records,
    )
    with pytest.raises(ValueError, match="record provenance must be real"):
        benchmark_theme_taxonomy.run_benchmark(manifest_path)


def test_benchmark_excludes_synthetic_records_from_denominator_and_is_empty_evidence_safe(
    tmp_path: Path,
) -> None:
    real_records, synthetic_records = _load_source_payloads()
    manifest_path = _manifest_path(
        tmp_path / "quality",
        real=real_records,
        synthetic=synthetic_records,
    )
    result = benchmark_theme_taxonomy.run_benchmark(manifest_path)
    foundry = result["themes"]["semicon_foundry_advanced"]
    edge_ai = result["themes"]["ic_design_edge_ai"]
    equipment = result["themes"]["semicon_equipment"]
    materials = result["themes"]["semicon_materials"]

    assert result["policy"]["provisional"] is True
    assert result["theme_count"] == 4
    assert foundry["status"] == "insufficient_evidence"
    assert edge_ai["status"] == "insufficient_evidence"
    assert equipment["status"] == "insufficient_evidence"
    assert materials["status"] == "insufficient_evidence"
    assert foundry["status_reason"] == "policy_provisional"
    assert edge_ai["status_reason"] == "policy_provisional"
    assert equipment["status_reason"] == "policy_provisional"
    assert materials["status_reason"] == "policy_provisional"
    assert foundry["fixture_hashes"] == [DIGITIMES_FIXTURE_SHA256]
    assert edge_ai["fixture_hashes"] == [DIGITIMES_FIXTURE_SHA256]
    assert equipment["fixture_hashes"] == [DIGITIMES_FIXTURE_SHA256]
    assert materials["fixture_hashes"] == [DIGITIMES_FIXTURE_SHA256]
    assert foundry["real_positive_clusters"] == 0
    assert edge_ai["real_positive_clusters"] == 0
    assert equipment["real_positive_clusters"] == 1
    assert materials["real_positive_clusters"] == 0
    assert foundry["real_negative_records"] == 1
    assert edge_ai["real_negative_records"] == 1
    assert equipment["real_negative_records"] == 0
    assert materials["real_negative_records"] == 1


def test_benchmark_real_records_trace_back_to_digitimes_snapshot_and_records_are_heldout() -> None:
    real_records = json.loads(REAL_SOURCE.read_text(encoding="utf-8"))
    index_map = {"r14": 14, "r52": 52, "r56": 56}
    assert {record["record_id"] for record in real_records} == set(index_map)

    for record in real_records:
        source_item = _digitimes_entry(index_map[record["record_id"]])
        assert record["canonical_url"] == source_item["canonical_url"]
        assert record["title"] == source_item["title"]
        assert record["description"] == source_item["description"]
        assert record["published_at"] == _utc_timestamp(source_item["published_at"])
        assert record["adjudication_split"] == "heldout"
        assert record["provenance"] == "real"


def test_benchmark_rejects_cluster_conflicts_in_heldout_real_records(tmp_path: Path) -> None:
    synthetic_records = _load_source_payloads()[1]

    base_records = [
        _raw_record(
            "r01",
            canonical_url="https://example.com/f1",
            event_cluster_id="cluster-f1",
            expected_theme_ids=["semicon_foundry_advanced"],
        ),
        _raw_record(
            "r02",
            canonical_url="https://example.com/f2",
            event_cluster_id="cluster-f2",
            expected_theme_ids=["semicon_foundry_advanced"],
        ),
    ]

    deduped = base_records + [
        _raw_record(
            "r01-dup",
            canonical_url="https://example.com/f1",
            event_cluster_id="cluster-f1",
            expected_theme_ids=["semicon_foundry_advanced"],
            adjudication="positive",
        )
    ]
    dedupe_manifest = _manifest_path(
        tmp_path / "dedupe",
        real=deduped,
        synthetic=synthetic_records,
    )
    result = benchmark_theme_taxonomy.run_benchmark(dedupe_manifest)
    assert result["themes"]["semicon_foundry_advanced"]["real_positive_clusters"] == 2

    conflicted = base_records + [
        _raw_record(
            "r01-conflict",
            canonical_url="https://example.com/f1",
            event_cluster_id="cluster-f1",
            expected_theme_ids=["ic_design_edge_ai"],
            adjudication="negative",
        )
    ]
    conflict_manifest = _manifest_path(
        tmp_path / "conflict",
        real=conflicted,
        synthetic=synthetic_records,
    )
    with pytest.raises(ValueError, match="conflicting labels or expected_theme_ids"):
        benchmark_theme_taxonomy.run_benchmark(conflict_manifest)


def test_foundry_candidate_keeps_cowos_in_veto_boundary_for_structured_matching() -> None:
    result = score_theme_relevance(
        {
            "title": "Foundry CoWoS announcement and fab expansion",
            "description": "CoWoS roadmap was disclosed for memory packaging.",
            "source": "moneydj",
        },
        taxonomy={
            "themes": [
                {
                    "theme_id": "semicon_foundry_advanced",
                    "matcher_mode": "structured",
                    "required_any": ["foundry", "fab expansion", "advanced node"],
                    "optional": ["euv", "backside power"],
                    "excluded": ["cowos"],
                    "related_industries": ["半導體"],
                    "seed_symbols": ["2330", "3711"],
                }
            ]
        },
    )
    assert result["matched_themes"] == []


def test_benchmark_deduplicates_and_rejects_cluster_conflicts(tmp_path: Path) -> None:
    synthetic_records = _load_source_payloads()[1]

    base_records = [
        _raw_record(
            "r01",
            canonical_url="https://example.com/f1",
            event_cluster_id="cluster-f1",
            expected_theme_ids=["semicon_foundry_advanced"],
        ),
        _raw_record(
            "r02",
            canonical_url="https://example.com/f2",
            event_cluster_id="cluster-f2",
            expected_theme_ids=["semicon_foundry_advanced"],
        ),
    ]

    deduped = base_records + [
        _raw_record(
            "r01-dup",
            canonical_url="https://example.com/f1",
            event_cluster_id="cluster-f1",
            expected_theme_ids=["semicon_foundry_advanced"],
            adjudication="positive",
        )
    ]
    dedupe_manifest = _manifest_path(
        tmp_path / "dedupe",
        real=deduped,
        synthetic=synthetic_records,
    )
    result = benchmark_theme_taxonomy.run_benchmark(dedupe_manifest)
    assert result["themes"]["semicon_foundry_advanced"]["real_positive_clusters"] == 2

    conflicted = base_records + [
        _raw_record(
            "r01-conflict",
            canonical_url="https://example.com/f1",
            event_cluster_id="cluster-f1",
            expected_theme_ids=["ic_design_edge_ai"],
            adjudication="negative",
        )
    ]
    conflict_manifest = _manifest_path(
        tmp_path / "conflict",
        real=conflicted,
        synthetic=synthetic_records,
    )
    with pytest.raises(ValueError, match="conflicting labels or expected_theme_ids"):
        benchmark_theme_taxonomy.run_benchmark(conflict_manifest)


def test_benchmark_output_is_deterministic_under_input_permutation(tmp_path: Path) -> None:
    real_records, synthetic_records = _load_source_payloads()
    first = _manifest_path(
        tmp_path / "first",
        real=deepcopy(real_records),
        synthetic=deepcopy(synthetic_records),
    )
    second = _manifest_path(
        tmp_path / "second",
        real=list(reversed(real_records)),
        synthetic=list(reversed(synthetic_records)),
    )

    assert benchmark_theme_taxonomy.run_benchmark(first) == benchmark_theme_taxonomy.run_benchmark(
        second
    )


def test_benchmark_synthetic_invariant_summary_is_reported_and_denominators_use_real_records_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_score(record: dict[str, object], *, taxonomy: dict[str, object]) -> dict[str, object]:
        theme_id = str(taxonomy["themes"][0].get("theme_id"))
        matched_by_record = {
            "r_positive": [theme_id],
            "r_negative": [],
            "s_optional_pass": [],
        }
        return {
            "matched_themes": [
                {
                    "theme_id": current_id,
                    "name_zh": current_id,
                    "score": 1.0 if current_id else 0.0,
                    "signals": ["fixture"],
                    "reason": "fixture",
                }
                for current_id in matched_by_record.get(str(record["record_id"]), [])
            ],
            "vetoed_theme_ids": [],
        }

    monkeypatch.setattr(benchmark_theme_taxonomy, "score_theme_relevance", fake_score)

    real_records = [
        _raw_record(
            "r_positive",
            adjudication="positive",
            expected_theme_ids=["semicon_foundry_advanced"],
            event_cluster_id="cluster-real-pos",
            title="fixture foundry advance",
            description="fixture foundry advance",
        ),
        _raw_record(
            "r_negative",
            adjudication="negative",
            expected_theme_ids=[],
            event_cluster_id="cluster-real-neg",
            title="irrelevant news",
            description="irrelevant",
        ),
    ]
    synthetic_records = [
        _raw_record(
            "s_optional_pass",
            provenance="synthetic",
            adjudication="positive",
            expected_theme_ids=["semicon_foundry_advanced"],
            event_cluster_id="cluster-synth-optional",
            violation_codes=["optional_only"],
            expected_match=False,
            title="fixture optional only",
            description="fixture optional only",
        ),
        _raw_record(
            "s_boundary_fail",
            provenance="synthetic",
            adjudication="boundary",
            expected_theme_ids=["semicon_foundry_advanced"],
            event_cluster_id="cluster-synth-boundary",
            violation_codes=["boundary"],
            expected_match=True,
            title="fixture boundary candidate",
            description="fixture boundary candidate",
        ),
    ]
    manifest_path = _manifest_path(
        tmp_path / "invariants",
        real=real_records,
        synthetic=synthetic_records,
    )
    result = benchmark_theme_taxonomy.run_benchmark(manifest_path)

    foundry = result["themes"]["semicon_foundry_advanced"]
    assert foundry["real_positive_clusters"] == 1
    assert foundry["real_negative_records"] == 1
    assert foundry["false_negative"] == 0
    assert foundry["false_positive"] == 0
    assert foundry["false_positive"] + foundry["false_negative"] == 0
    assert foundry["optional_only_violations"] == 0
    assert foundry["boundary_violations"] == 1
    assert foundry["synthetic_invariant_summary"] == {
        "boundary": {
            "failed_record_ids": ["cluster-synth-boundary"],
            "mismatches": 1,
            "total": 1,
        },
        "excluded_veto": {"failed_record_ids": [], "mismatches": 0, "total": 0},
        "optional_only": {"failed_record_ids": [], "mismatches": 0, "total": 1},
    }
    assert result["policy"]["provisional"] is True


def test_benchmark_synthetic_invariant_failure_rejects_theme_when_not_provisional(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        benchmark_theme_taxonomy,
        "QUALIFICATION_POLICY",
        {
            "mode": "provisional",
            "provisional": False,
            "gates": {
                "date_span_min": 1,
                "publisher_span_min": 1,
                "real_positive_cluster_min": 1,
                "real_negative_record_min": 0,
                "precision_min": 0.0,
                "recall_min": 0.0,
                "violation_max": 0,
                "seed_symbol_evidence_required": False,
                "boundary_gate_required": False,
            },
        },
    )

    def fake_score(record: dict[str, object], *, taxonomy: dict[str, object]) -> dict[str, object]:
        theme_id = str(taxonomy["themes"][0].get("theme_id"))
        matched_by_record = {
            "r_positive": [theme_id],
            "r_negative": [],
        }
        return {
            "matched_themes": [
                {
                    "theme_id": current_id,
                    "name_zh": current_id,
                    "score": 1.0 if current_id else 0.0,
                    "signals": ["fixture"],
                    "reason": "fixture",
                }
                for current_id in matched_by_record.get(str(record["record_id"]), [])
            ],
            "vetoed_theme_ids": [],
        }

    monkeypatch.setattr(benchmark_theme_taxonomy, "score_theme_relevance", fake_score)

    real_records = [
        _raw_record(
            "r_positive",
            adjudication="positive",
            expected_theme_ids=["semicon_foundry_advanced"],
            title="fixture foundry advance",
            description="fixture foundry advance",
            source_id="digitimes_tw",
            published_at="2026-07-28T06:00:00Z",
            captured_at="2026-07-28T06:00:00Z",
        ),
    ]
    synthetic_records = [
        _raw_record(
            "s_boundary_fail",
            provenance="synthetic",
            adjudication="boundary",
            expected_theme_ids=["semicon_foundry_advanced"],
            event_cluster_id="cluster-synth-boundary-fail",
            violation_codes=["boundary"],
            expected_match=True,
            title="fixture boundary candidate",
            description="fixture boundary candidate",
        )
    ]
    manifest_path = _manifest_path(
        tmp_path / "invariants_fail",
        real=real_records,
        synthetic=synthetic_records,
    )
    result = benchmark_theme_taxonomy.run_benchmark(manifest_path)

    foundry = result["themes"]["semicon_foundry_advanced"]
    assert foundry["status"] == "rejected"
    assert foundry["status_reason"] == "synthetic_invariant_fail"
    assert foundry["synthetic_invariant_summary"] == {
        "boundary": {
            "failed_record_ids": ["cluster-synth-boundary-fail"],
            "mismatches": 1,
            "total": 1,
        },
        "excluded_veto": {"failed_record_ids": [], "mismatches": 0, "total": 0},
        "optional_only": {"failed_record_ids": [], "mismatches": 0, "total": 0},
    }
