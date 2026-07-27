"""Official-source adapters for the Taiwan equity theme radar."""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


SUPPORTED_REFRESH_CLASSES = {"hourly", "daily", "monthly", "quarterly"}
SUPPORTED_DATASET_STATUSES = {"active", "inactive"}
TRANSIENT_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_MAX_ATTEMPTS = 2
DEFAULT_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_DATASET_ROWS = 100_000
CONFLICT_TERMS = ("撤銷", "取消", "否認", "不實", "未通過")
TWSE_OPENAPI_BASE_URL = "https://openapi.twse.com.tw/v1"


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _first_text(row: dict[str, Any], fields: list[str] | tuple[str, ...]) -> str | None:
    for field in fields:
        value = row.get(field)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def load_dataset_catalog(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    datasets = payload.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise ValueError("dataset catalog must contain a non-empty datasets array")

    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for raw_dataset in datasets:
        if not isinstance(raw_dataset, dict):
            raise ValueError("dataset catalog entries must be objects")
        dataset = dict(raw_dataset)
        dataset_id = str(dataset.get("dataset_id") or "")
        if not dataset_id:
            raise ValueError("dataset_id is required")
        if dataset_id in seen:
            raise ValueError(f"duplicate dataset_id: {dataset_id}")
        seen.add(dataset_id)

        if dataset.get("path") != f"/opendata/{dataset_id}":
            raise ValueError(f"invalid dataset path: {dataset_id}")
        if dataset.get("refresh_class") not in SUPPORTED_REFRESH_CLASSES:
            raise ValueError(f"unsupported refresh class: {dataset_id}")
        if dataset.get("status") not in SUPPORTED_DATASET_STATUSES:
            raise ValueError(f"unsupported dataset status: {dataset_id}")
        if dataset.get("public_projection") != "theme_relevant_only":
            raise ValueError(f"invalid public projection: {dataset_id}")
        if not str(dataset.get("category") or ""):
            raise ValueError(f"dataset category is required: {dataset_id}")
        validated.append(dataset)

    return {**payload, "datasets": sorted(validated, key=lambda item: item["dataset_id"])}


def dataset_is_due(dataset: dict[str, Any], anchor: datetime, *, full_refresh: bool) -> bool:
    if dataset["status"] != "active":
        return False
    if full_refresh:
        return True
    refresh_class = dataset["refresh_class"]
    if refresh_class == "hourly":
        return True
    if refresh_class == "daily":
        return anchor.hour == 0
    if refresh_class == "monthly":
        return anchor.day == 1 and anchor.hour == 0
    return anchor.month in {1, 4, 7, 10} and anchor.day == 1 and anchor.hour == 0


def normalize_official_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    cleaned = (
        text.replace("民國", "")
        .replace("年", "/")
        .replace("月", "/")
        .replace("日", "")
        .replace(".", "/")
        .replace("-", "/")
    )
    date_part = cleaned.split(" ", 1)[0]
    parts = [part for part in date_part.split("/") if part]
    try:
        if len(parts) == 3:
            year, month, day = (int(part) for part in parts)
        else:
            digits = re.sub(r"\D", "", date_part)
            if len(digits) == 7:
                year, month, day = int(digits[:3]), int(digits[3:5]), int(digits[5:7])
            elif len(digits) == 8:
                year, month, day = int(digits[:4]), int(digits[4:6]), int(digits[6:8])
            elif len(digits) == 5:
                year, month, day = int(digits[:3]), int(digits[3:5]), 1
            elif len(digits) == 6 and int(digits[:4]) >= 1911:
                year, month, day = int(digits[:4]), int(digits[4:6]), 1
            else:
                return None
        if year < 1911:
            year += 1911
        return _utc_text(datetime(year, month, day, tzinfo=timezone.utc))
    except (TypeError, ValueError):
        return None


def _stable_record_hash(row: dict[str, Any]) -> str:
    canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_twse_record(
    row: dict[str, Any],
    dataset: dict[str, Any],
    source: dict[str, Any],
    fetched_at: datetime,
) -> dict[str, Any]:
    symbol = _first_text(row, tuple(dataset.get("symbol_fields") or ("公司代號", "公司代碼")))
    company_name = _first_text(
        row,
        tuple(dataset.get("company_name_fields") or ("公司名稱", "公司簡稱")),
    )
    title = _first_text(
        row,
        tuple(dataset.get("title_fields") or ("主旨 ", "主旨", "公司名稱", "公司簡稱")),
    )
    summary = _first_text(
        row,
        tuple(dataset.get("summary_fields") or ("說明", "備註", "事由")),
    )
    published_raw = _first_text(
        row,
        tuple(dataset.get("published_date_fields") or ("發言日期", "出表日期", "資料年月")),
    )
    effective_raw = _first_text(
        row,
        tuple(dataset.get("effective_date_fields") or ("事實發生日", "上市日期", "成立日期")),
    )
    record_hash = _stable_record_hash(row)
    natural_values = [
        str(row.get(field) or "").strip()
        for field in dataset.get("natural_key_fields", [])
        if str(row.get(field) or "").strip()
    ]
    identity = "|".join(
        natural_values
        or [value for value in (symbol, published_raw, effective_raw, title, company_name) if value]
        or [record_hash]
    )
    dataset_id = str(dataset["dataset_id"])
    evidence_hash = hashlib.sha256(f"mops|{dataset_id}|{identity}".encode("utf-8")).hexdigest()[:20]
    path = str(dataset["path"])
    base_url = str(source.get("base_url") or "https://openapi.twse.com.tw/v1").rstrip("/")
    instrument_prefix = str(dataset.get("instrument_prefix") or "TWSE")
    return {
        "evidence_id": f"mops-{dataset_id.lower()}-{evidence_hash}",
        "source_id": str(source["source_id"]),
        "source_class": str(source.get("source_class") or "official_disclosure"),
        "adapter": "twse_openapi",
        "dataset_id": dataset_id,
        "category": str(dataset["category"]),
        "market_id": str(source.get("market_id") or "TW_EQUITY"),
        "instrument_id": f"{instrument_prefix}:{symbol}" if symbol else None,
        "symbol": symbol,
        "company_name": company_name,
        "title": title,
        "summary": summary,
        "published_at": normalize_official_date(published_raw),
        "effective_at": normalize_official_date(effective_raw),
        "canonical_url": f"{base_url}{path}",
        "raw_reference": f"{path}#sha256:{record_hash}",
        "fetched_at": _utc_text(fetched_at),
    }


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError):
        response = getattr(exc, "response", None)
        return response is None or response.status_code in TRANSIENT_HTTP_STATUSES
    return False


def read_bounded_response(response: Any, *, max_bytes: int) -> bytes:
    if max_bytes <= 0:
        raise ValueError("response byte limit must be positive")

    content_length = getattr(response, "headers", {}).get("Content-Length")
    if content_length:
        try:
            declared_length = int(content_length)
        except (TypeError, ValueError):
            declared_length = 0
        if declared_length > max_bytes:
            raise ValueError(f"response exceeds {max_bytes} bytes")

    iter_content = getattr(response, "iter_content", None)
    if not callable(iter_content):
        body = getattr(response, "content", b"")
        if not isinstance(body, bytes):
            body = str(body).encode("utf-8")
        if len(body) > max_bytes:
            raise ValueError(f"response exceeds {max_bytes} bytes")
        return body

    chunks: list[bytes] = []
    total = 0
    for chunk in iter_content(min(65_536, max_bytes + 1)):
        if not chunk:
            continue
        if not isinstance(chunk, bytes):
            chunk = str(chunk).encode("utf-8")
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"response exceeds {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _fetch_dataset(
    session: requests.Session,
    url: str,
    *,
    timeout: int,
    max_attempts: int,
    max_response_bytes: int,
    max_rows: int,
) -> list[dict[str, Any]]:
    for attempt in range(1, max_attempts + 1):
        response = None
        try:
            response = session.get(url, timeout=timeout, stream=True)
            response.raise_for_status()
            body = read_bounded_response(response, max_bytes=max_response_bytes)
            payload = json.loads(body.decode("utf-8-sig"))
            if not isinstance(payload, list):
                raise ValueError("TWSE dataset response must be a JSON array")
            if len(payload) > max_rows:
                raise ValueError(f"TWSE dataset row limit of {max_rows} exceeded")
            if not all(isinstance(item, dict) for item in payload):
                raise ValueError("TWSE dataset rows must be JSON objects")
            return payload
        except Exception as exc:
            if attempt >= max_attempts or not _is_transient(exc):
                raise
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
    raise RuntimeError("unreachable retry state")


def fetch_twse_openapi_source(
    session: requests.Session,
    source: dict[str, Any],
    fetched_at: datetime,
    *,
    full_refresh: bool = False,
) -> dict[str, Any]:
    started = time.monotonic()
    catalog_path = Path(str(source["catalog_path"]))
    catalog = load_dataset_catalog(catalog_path)
    base_url = str(source["base_url"])
    if base_url != TWSE_OPENAPI_BASE_URL:
        raise ValueError(f"base_url must be the official TWSE OpenAPI base URL: {TWSE_OPENAPI_BASE_URL}")
    timeout = int(source.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
    max_attempts = min(
        DEFAULT_MAX_ATTEMPTS,
        max(1, int(source.get("max_attempts") or DEFAULT_MAX_ATTEMPTS)),
    )
    max_response_bytes = max(
        1,
        int(source.get("max_response_bytes") or DEFAULT_MAX_RESPONSE_BYTES),
    )
    max_dataset_rows = max(
        1,
        int(source.get("max_dataset_rows") or DEFAULT_MAX_DATASET_ROWS),
    )
    due = [
        dataset
        for dataset in catalog["datasets"]
        if dataset_is_due(dataset, fetched_at, full_refresh=full_refresh)
    ]
    records: list[dict[str, Any]] = []
    dataset_statuses: list[dict[str, Any]] = []

    for dataset in due:
        dataset_started = time.monotonic()
        path = str(dataset["path"])
        try:
            rows = _fetch_dataset(
                session,
                f"{base_url}{path}",
                timeout=timeout,
                max_attempts=max_attempts,
                max_response_bytes=max_response_bytes,
                max_rows=max_dataset_rows,
            )
            normalized = [
                normalize_twse_record(row, dataset, source, fetched_at)
                for row in rows
            ]
            records.extend(normalized)
            dataset_statuses.append(
                {
                    "dataset_id": dataset["dataset_id"],
                    "path": path,
                    "category": dataset["category"],
                    "refresh_class": dataset["refresh_class"],
                    "status": "ok",
                    "items": len(normalized),
                    "error": None,
                    "elapsed_ms": round((time.monotonic() - dataset_started) * 1000),
                }
            )
        except Exception as exc:  # noqa: BLE001 - dataset isolation requires a status envelope
            dataset_statuses.append(
                {
                    "dataset_id": dataset["dataset_id"],
                    "path": path,
                    "category": dataset["category"],
                    "refresh_class": dataset["refresh_class"],
                    "status": "error",
                    "items": 0,
                    "error": str(exc),
                    "elapsed_ms": round((time.monotonic() - dataset_started) * 1000),
                }
            )

    ordered_statuses = sorted(dataset_statuses, key=lambda item: item["dataset_id"])
    failed = sum(item["status"] != "ok" for item in ordered_statuses)
    succeeded = len(ordered_statuses) - failed
    if failed and succeeded:
        source_state = "partial"
    elif failed:
        source_state = "error"
    else:
        source_state = "ok"
    errors = [
        f"{item['dataset_id']}: {item['error']}"
        for item in ordered_statuses
        if item["status"] == "error"
    ]
    ordered_records = sorted(
        records,
        key=lambda item: (
            item.get("published_at") or item.get("effective_at") or item["fetched_at"],
            item["evidence_id"],
        ),
        reverse=True,
    )
    return {
        "records": ordered_records,
        "status": {
            "source_id": source["source_id"],
            "name": source.get("name") or source["source_id"],
            "source_class": source.get("source_class"),
            "adapter": "twse_openapi",
            "fetch_method": "twse_openapi",
            "endpoint": base_url,
            "catalog_path": str(catalog_path),
            "catalog_sha256": catalog.get("catalog_sha256"),
            "status": source_state,
            "items": len(ordered_records),
            "datasets_due": len(due),
            "datasets_ok": succeeded,
            "datasets_failed": failed,
            "datasets_skipped": len(catalog["datasets"]) - len(due),
            "datasets": ordered_statuses,
            "error": "; ".join(errors) or None,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        },
    }


def build_official_evidence_payload(
    records: list[dict[str, Any]],
    *,
    generated_at: datetime,
    window_hours: int,
    max_items: int,
) -> dict[str, Any]:
    if window_hours <= 0 or max_items <= 0:
        raise ValueError("official evidence bounds must be positive")
    cutoff = generated_at - timedelta(hours=window_hours)
    deduped: dict[str, dict[str, Any]] = {}
    for record in records:
        timestamp_text = (
            record.get("published_at")
            or record.get("effective_at")
            or record.get("fetched_at")
        )
        if not timestamp_text:
            continue
        timestamp = datetime.fromisoformat(str(timestamp_text).replace("Z", "+00:00"))
        if cutoff <= timestamp <= generated_at:
            deduped.setdefault(str(record["evidence_id"]), record)
    ordered = sorted(
        deduped.values(),
        key=lambda item: (
            item.get("published_at") or item.get("effective_at") or item.get("fetched_at") or "",
            item["evidence_id"],
        ),
        reverse=True,
    )
    items = ordered[:max_items]
    return {
        "generated_at": _utc_text(generated_at),
        "market_id": "TW_EQUITY",
        "window_hours": window_hours,
        "max_items": max_items,
        "total_items": len(items),
        "total_items_available": len(ordered),
        "items": items,
    }
