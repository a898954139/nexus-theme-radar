"""Taxonomy benchmark harness v0.7 matcher qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

try:
    from scripts.theme_relevance import MATCHER_MODE_STRUCTURED, score_theme_relevance
except ModuleNotFoundError:  # pragma: no cover - fallback execution
    sys.path.insert(0, str(ROOT))
    from theme_relevance import MATCHER_MODE_STRUCTURED, score_theme_relevance

QUALIFICATION_POLICY = {
    "mode": "provisional",
    "provisional": True,
    "gates": {
        "date_span_min": 2,
        "publisher_span_min": 2,
        "real_positive_cluster_min": 5,
        "real_negative_record_min": 10,
        "precision_min": 0.85,
        "recall_min": 0.70,
        "violation_max": 0,
        "seed_symbol_evidence_required": True,
        "boundary_gate_required": True,
    },
}

MANDATORY_MANIFEST_FIELDS = {
    "benchmark_version",
    "themes",
    "real_records_path",
    "synthetic_records_path",
    "fixtures",
}

MANDATORY_RECORD_FIELDS = {
    "record_id",
    "source_id",
    "endpoint",
    "captured_at",
    "published_at",
    "canonical_url",
    "title",
    "description",
    "raw_fixture_sha256",
    "expected_theme_ids",
    "adjudication",
    "adjudicated_by",
    "adjudicated_at",
    "notes",
    "event_cluster_id",
    "adjudication_split",
    "provenance",
}

MANDATORY_FIXTURE_FIELDS = {"path", "sha256"}
MANDATORY_FIXTURE_KEYS = {
    "real_records",
    "synthetic_records",
}

VALID_ADJUDICATION = {"positive", "negative", "unadjudicated", "boundary"}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_path(manifest_dir: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else manifest_dir / candidate


def _hash_payload(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_cluster_id(record: dict[str, Any]) -> str:
    return str(
        record.get("event_cluster_id")
        or record.get("record_id")
        or record.get("canonical_url")
        or record.get("title")
        or ""
    ).strip()


def _record_sort_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record.get("published_at") or ""),
        str(record.get("captured_at") or ""),
        str(record.get("record_id") or ""),
    )


def _extract_expected_match(record: dict[str, Any]) -> bool | None:
    value = record.get("expected_match")
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError("expected_match must be boolean when provided")


def _matcher_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        **record,
        "summary": record.get("summary") or record.get("description", ""),
    }


def _matches_theme(
    record: dict[str, Any],
    theme: dict[str, Any],
    *,
    theme_id: str,
) -> bool:
    score = score_theme_relevance(
        _matcher_record(record),
        taxonomy={"themes": [theme], "theme_id": theme_id},
    )
    return theme_id in {match["theme_id"] for match in score["matched_themes"]}


def _violation_category(record: dict[str, Any]) -> str | None:
    codes = {
        str(code).strip().casefold()
        for code in (record.get("violation_codes") or [])
        if str(code).strip()
    }
    if "optional_only" in codes:
        return "optional_only"
    if "excluded_veto" in codes:
        return "excluded_veto"
    if "boundary" in codes:
        return "boundary"
    return None


def _normalized_expected_theme_ids(record: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(value).strip()
                for value in (record.get("expected_theme_ids") or [])
                if str(value).strip()
            }
        )
    )


def _validate_manifest(manifest: dict[str, Any], manifest_dir: Path) -> None:
    manifest_path_values = {
        "real_records": manifest.get("real_records_path"),
        "synthetic_records": manifest.get("synthetic_records_path"),
    }

    for key, path_value in manifest_path_values.items():
        fixture_record = manifest["fixtures"].get(key)
        if not isinstance(fixture_record, dict):
            raise ValueError(f"fixture manifest entry missing object: {key}")

        missing = sorted(MANDATORY_FIXTURE_FIELDS.difference(fixture_record.keys()))
        if missing:
            raise ValueError(f"fixture manifest entry {key} missing keys: {', '.join(missing)}")

        if fixture_record["path"] != path_value:
            raise ValueError(f"fixture manifest path mismatch for {key}")

        if not isinstance(path_value, str) or not fixture_record["path"]:
            raise ValueError(f"invalid {key} path in manifest")

        resolved = _resolve_path(manifest_dir, path_value)
        actual_sha = _hash_file(resolved)
        expected_sha = str(fixture_record["sha256"])
        if not expected_sha:
            raise ValueError(f"fixture manifest missing sha256 for {key}")
        if actual_sha != expected_sha:
            raise ValueError(f"fixture sha256 mismatch for {key}")

        if not fixture_record["sha256"]:
            raise ValueError(f"fixture manifest missing sha256 for {key}")


def _validate_records(records: list[dict[str, Any]], *, provenance: str) -> None:
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("each record must be a JSON object")

        if record.get("provenance") != provenance:
            raise ValueError(f"record provenance must be {provenance}")

        missing = sorted(MANDATORY_RECORD_FIELDS.difference(record.keys()))
        if missing:
            raise ValueError(f"record missing required keys: {', '.join(missing)}")

        if not str(record.get("raw_fixture_sha256") or ""):
            raise ValueError("record raw_fixture_sha256 must be present")

        adjudication = str(record.get("adjudication") or "").strip().lower()
        if adjudication not in VALID_ADJUDICATION:
            raise ValueError("adjudication must be positive negative unadjudicated boundary")

        adjudication_split = str(record.get("adjudication_split") or "").strip().lower()
        if adjudication_split not in {"heldout", "train"}:
            raise ValueError("adjudication_split must be heldout or train")
        if "expected_match" in record and not isinstance(record["expected_match"], bool):
            raise ValueError("expected_match must be boolean")


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}

    for record in sorted(records, key=_record_sort_key, reverse=True):
        cluster_key = _canonical_cluster_id(record)
        if not cluster_key:
            continue

        existing = seen.get(cluster_key)
        if existing is None:
            seen[cluster_key] = record
            ordered.append(record)
            continue

        expected_labels = (
            str(existing.get("adjudication") or "").strip().lower(),
            _normalized_expected_theme_ids(existing),
        )
        current_labels = (
            str(record.get("adjudication") or "").strip().lower(),
            _normalized_expected_theme_ids(record),
        )

        if expected_labels != current_labels:
            raise ValueError(
                f"conflicting labels or expected_theme_ids for event_cluster_id {cluster_key}"
            )

    return ordered


def _evaluate_theme(
    theme: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    synthetic_records: list[dict[str, Any]],
    expected_count: int,
) -> dict[str, Any]:
    theme_id = str(theme["theme_id"])
    theme_taxonomy = {"themes": [theme], "theme_id": theme_id}

    heldout_records = [
        record
        for record in records
        if str(record.get("adjudication_split") or "heldout").strip().lower() == "heldout"
    ]

    positives: set[str] = set()
    negatives: set[str] = set()
    true_positive = 0
    false_positive = 0
    true_negative = 0
    false_negative = 0
    synthetic_invariant_summary = {
        "optional_only": {"total": 0, "mismatches": 0, "failed_record_ids": []},
        "excluded_veto": {"total": 0, "mismatches": 0, "failed_record_ids": []},
        "boundary": {"total": 0, "mismatches": 0, "failed_record_ids": []},
    }
    fixture_hashes: set[str] = set()

    date_values: set[str] = set()
    publisher_values: set[str] = set()

    for record in heldout_records:
        adjudication = str(record.get("adjudication") or "").strip().lower()
        if adjudication not in {"positive", "negative"}:
            continue

        expected_theme_ids = {
            str(value).strip()
            for value in (record.get("expected_theme_ids") or [])
            if str(value).strip()
        }
        predicted_theme_ids = {
            match["theme_id"]
            for match in score_theme_relevance(
                _matcher_record(record),
                taxonomy=theme_taxonomy,
            )["matched_themes"]
        }
        predicted = theme_id in predicted_theme_ids
        cluster_id = _canonical_cluster_id(record)

        fixture_hashes.add(str(record["raw_fixture_sha256"]))
        date_values.add(str(record.get("published_at") or ""))
        publisher_values.add(str(record.get("source_id") or "").strip())

        is_positive = adjudication == "positive" and theme_id in expected_theme_ids
        if is_positive:
            positives.add(cluster_id)
            if predicted:
                true_positive += 1
            else:
                false_negative += 1
            continue

        negatives.add(cluster_id)
        if predicted:
            false_positive += 1
        else:
            true_negative += 1

    for record in synthetic_records:
        heldout = str(record.get("adjudication_split") or "heldout").strip().lower() == "heldout"
        if not heldout:
            continue
        category = _violation_category(record)
        if category is None:
            continue
        expected_match = _extract_expected_match(record)
        if expected_match is None:
            continue
        expected_theme_ids = {
            str(value).strip()
            for value in (record.get("expected_theme_ids") or [])
            if str(value).strip()
        }
        if theme_id not in expected_theme_ids:
            continue
        predicted = _matches_theme(record, theme, theme_id=theme_id)
        summary = synthetic_invariant_summary[category]
        summary["total"] += 1
        if expected_match != predicted:
            summary["mismatches"] += 1
            summary["failed_record_ids"].append(_canonical_cluster_id(record))

    positive_total = true_positive + false_negative
    negative_total = false_positive + true_negative
    precision = (
        round(true_positive / (true_positive + false_positive), 3)
        if (true_positive + false_positive)
        else 0.0
    )
    recall = (
        round(true_positive / (true_positive + false_negative), 3)
        if (true_positive + false_negative)
        else 0.0
    )

    date_span = len({
        value[:10] for value in date_values if value
    })
    publisher_span = len({value for value in publisher_values if value})
    seed_symbol_evidence = bool(theme.get("seed_symbols"))
    synthetic_invariant_failures = sum(
        category["mismatches"] for category in synthetic_invariant_summary.values()
    )
    optional_only_violations = synthetic_invariant_summary["optional_only"]["mismatches"]
    excluded_veto_violations = synthetic_invariant_summary["excluded_veto"]["mismatches"]
    boundary_violations = synthetic_invariant_summary["boundary"]["mismatches"]

    policy = QUALIFICATION_POLICY
    if expected_count == 0:
        status = "insufficient_evidence"
        status_reason = "no_real_records"
    elif policy.get("provisional"):
        status = "insufficient_evidence"
        status_reason = "policy_provisional"
    elif date_span < policy["gates"]["date_span_min"]:
        status = "insufficient_evidence"
        status_reason = "date_span_min"
    elif publisher_span < policy["gates"]["publisher_span_min"]:
        status = "insufficient_evidence"
        status_reason = "publisher_span_min"
    elif len(positives) < policy["gates"]["real_positive_cluster_min"]:
        status = "insufficient_evidence"
        status_reason = "positive_cluster_min"
    elif negative_total < policy["gates"]["real_negative_record_min"]:
        status = "insufficient_evidence"
        status_reason = "negative_record_min"
    elif synthetic_invariant_failures > 0:
        status = "rejected"
        status_reason = "synthetic_invariant_fail"
    elif boundary_violations > policy["gates"]["violation_max"]:
        status = "rejected"
        status_reason = "violation_max"
    elif policy["gates"]["seed_symbol_evidence_required"] and not seed_symbol_evidence:
        status = "rejected"
        status_reason = "seed_symbol_evidence"
    elif precision < policy["gates"]["precision_min"]:
        status = "rejected"
        status_reason = "precision_min"
    elif recall < policy["gates"]["recall_min"]:
        status = "rejected"
        status_reason = "recall_min"
    else:
        status = "qualified"
        status_reason = "passed"

    return {
        "theme_id": theme_id,
        "status": status,
        "status_reason": status_reason,
        "fixture_count": expected_count,
        "real_positive_clusters": len(positives),
        "real_negative_records": negative_total,
        "date_span": date_span,
        "publisher_span": publisher_span,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "true_negative": true_negative,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "synthetic_invariant_summary": {
            key: {
                "total": value["total"],
                "mismatches": value["mismatches"],
                "failed_record_ids": sorted(value["failed_record_ids"]),
            }
            for key, value in sorted(synthetic_invariant_summary.items())
        },
        "optional_only_violations": optional_only_violations,
        "excluded_veto_violations": excluded_veto_violations,
        "boundary_violations": boundary_violations,
        "fixture_hashes": sorted(fixture_hashes),
        "seed_symbol_evidence": seed_symbol_evidence,
    }


def _validate_theme_entry(theme: dict[str, Any]) -> None:
    if theme.get("matcher_mode") != MATCHER_MODE_STRUCTURED:
        raise ValueError("benchmark fixtures expect structured taxonomy candidates")

    if not str(theme.get("theme_id") or ""):
        raise ValueError("theme_id required")


def run_benchmark(manifest_path: str | Path) -> dict[str, Any]:
    manifest_file = Path(manifest_path)
    payload = _read_json(manifest_file)
    if not isinstance(payload, dict):
        raise ValueError("manifest must be a JSON object")

    missing = sorted(MANDATORY_MANIFEST_FIELDS.difference(payload.keys()))
    if missing:
        raise ValueError(f"manifest missing keys: {', '.join(missing)}")

    missing_fixtures = sorted(
        MANDATORY_FIXTURE_KEYS.difference(payload.get("fixtures", {}).keys())
    )
    if missing_fixtures:
        raise ValueError(f"fixtures missing keys: {', '.join(missing_fixtures)}")

    if not isinstance(payload["fixtures"], dict):
        raise ValueError("fixtures must be an object")

    manifest_dir = manifest_file.parent
    _validate_manifest(payload, manifest_dir)

    real_records = _read_json(_resolve_path(manifest_dir, payload["real_records_path"]))
    synthetic_records = _read_json(
        _resolve_path(manifest_dir, payload["synthetic_records_path"])
    )

    if not isinstance(real_records, list):
        raise ValueError("real records must be an array")
    if not isinstance(synthetic_records, list):
        raise ValueError("synthetic records must be an array")

    _validate_records(real_records, provenance="real")
    _validate_records(synthetic_records, provenance="synthetic")

    real_records = [
        dict(record)
        for record in _dedupe_records(real_records)
        if record.get("provenance") == "real"
    ]
    synthetic_records = [
        dict(record)
        for record in _dedupe_records(synthetic_records)
        if record.get("provenance") == "synthetic"
    ]

    themes = payload["themes"]
    if not isinstance(themes, list) or not themes:
        raise ValueError("themes must be a non-empty array")

    for theme in themes:
        if not isinstance(theme, dict):
            raise ValueError("each theme entry must be an object")
        _validate_theme_entry(theme)

    theme_results: dict[str, Any] = {}
    for theme in sorted(themes, key=lambda value: str(value.get("theme_id"))):
        theme_results[str(theme["theme_id"])] = _evaluate_theme(
            theme,
            real_records,
            synthetic_records=synthetic_records,
            expected_count=len(real_records),
        )

    return {
        "benchmark_version": payload["benchmark_version"],
        "taxonomy_version": payload.get("taxonomy_version", "v0.7"),
        "theme_count": len(themes),
        "policy": QUALIFICATION_POLICY,
        "themes": theme_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    result = run_benchmark(args.manifest)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
