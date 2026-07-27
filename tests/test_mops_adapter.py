from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from scripts.source_adapters import (
    build_official_evidence_payload,
    fetch_twse_openapi_source,
    load_dataset_catalog,
    normalize_official_date,
    normalize_twse_record,
)
from scripts.update_theme_radar import (
    active_sources,
    attach_official_evidence,
    dispatch_sources,
    run_update,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "config" / "mops_datasets.tw.json"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "mops"
SWAGGER_SHA256 = "2c2cecccb7a220ac9e263228a7659aa49b1ada5aea397650e601ad3dfcc48043"
ANCHOR = datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc)


def _source(source_id: str, fetch_method: str) -> dict[str, object]:
    source: dict[str, object] = {
        "source_id": source_id,
        "name": source_id,
        "source_class": "official_disclosure" if source_id == "mops" else "financial_media",
        "fetch_method": fetch_method,
        "status": "active",
        "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"],
    }
    if fetch_method == "rss":
        source["feed_url"] = f"https://example.com/{source_id}.xml"
    else:
        source.update(
            {
                "base_url": "https://openapi.twse.com.tw/v1",
                "catalog_path": str(CATALOG_PATH),
            }
        )
    return source


def test_registry_dispatches_rss_and_twse_openapi_adapters() -> None:
    registry = {
        "market_id": "TW_EQUITY",
        "market_scope": ["TW_EQUITY"],
        "sources": [
            _source("moneydj", "rss"),
            _source("mops", "twse_openapi"),
            {**_source("disabled", "rss"), "status": "planned"},
        ],
    }
    calls: list[tuple[str, str]] = []

    def rss_fetcher(_session, source, _fetched_at, **_kwargs):
        calls.append(("rss", source["source_id"]))
        return {"records": [], "status": {"source_id": source["source_id"], "status": "ok", "items": 0}}

    def twse_fetcher(_session, source, _fetched_at, **_kwargs):
        calls.append(("twse_openapi", source["source_id"]))
        return {"records": [], "status": {"source_id": source["source_id"], "status": "ok", "items": 0}}

    sources = active_sources(registry)
    results = dispatch_sources(
        object(),
        sources,
        ANCHOR,
        max_workers=2,
        fetchers={"rss": rss_fetcher, "twse_openapi": twse_fetcher},
    )

    assert {tuple(call) for call in calls} == {("rss", "moneydj"), ("twse_openapi", "mops")}
    assert [result["status"]["source_id"] for result in results] == ["moneydj", "mops"]


def test_dispatch_isolates_failures_and_sorts_deterministically() -> None:
    sources = [_source("zeta", "rss"), _source("alpha", "rss"), _source("mops", "twse_openapi")]

    def rss_fetcher(_session, source, _fetched_at, **_kwargs):
        if source["source_id"] == "zeta":
            raise RuntimeError("fixture failure")
        time.sleep(0.02)
        return {
            "records": [{"id": "alpha-record", "published_at": "2026-07-27T08:00:00Z"}],
            "status": {"source_id": source["source_id"], "status": "ok", "items": 1},
        }

    def twse_fetcher(_session, source, _fetched_at, **_kwargs):
        return {
            "records": [{"evidence_id": "mops-record", "published_at": "2026-07-27T08:30:00Z"}],
            "status": {"source_id": source["source_id"], "status": "ok", "items": 1},
        }

    results = dispatch_sources(
        object(),
        sources,
        ANCHOR,
        max_workers=3,
        fetchers={"rss": rss_fetcher, "twse_openapi": twse_fetcher},
    )

    assert [result["status"]["source_id"] for result in results] == ["alpha", "mops", "zeta"]
    failed = results[-1]["status"]
    assert failed["status"] == "error"
    assert failed["adapter"] == "rss"
    assert failed["items"] == 0
    assert "fixture failure" in failed["error"]


def test_dispatch_respects_worker_bound() -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    def fetcher(_session, source, _fetched_at, **_kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return {"records": [], "status": {"source_id": source["source_id"], "status": "ok", "items": 0}}

    sources = [_source(f"source-{index}", "rss") for index in range(6)]
    results = dispatch_sources(
        object(),
        sources,
        ANCHOR,
        max_workers=2,
        fetchers={"rss": fetcher},
    )

    assert len(results) == 6
    assert peak == 2


def test_dispatch_uses_and_closes_an_independent_session_per_source() -> None:
    sessions: list[object] = []
    used_session_ids: list[int] = []

    class Session:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    def session_factory() -> Session:
        session = Session()
        sessions.append(session)
        return session

    def fetcher(session, source, _fetched_at, **_kwargs):
        used_session_ids.append(id(session))
        return {
            "records": [],
            "status": {
                "source_id": source["source_id"],
                "status": "ok",
                "items": 0,
            },
        }

    sources = [_source(f"source-{index}", "rss") for index in range(3)]
    dispatch_sources(
        None,
        sources,
        ANCHOR,
        max_workers=3,
        fetchers={"rss": fetcher},
        session_factory=session_factory,
    )

    assert len(sessions) == len(sources)
    assert len(set(used_session_ids)) == len(sources)
    assert all(session.closed for session in sessions)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda catalog: catalog["datasets"].append(dict(catalog["datasets"][0])), "duplicate"),
        (lambda catalog: catalog["datasets"][0].update(path="/api/not-opendata"), "path"),
        (lambda catalog: catalog["datasets"][0].update(refresh_class="weekly"), "refresh"),
        (lambda catalog: catalog["datasets"][0].update(status="retired"), "status"),
    ],
)
def test_dataset_catalog_rejects_invalid_entries(tmp_path: Path, mutate, message: str) -> None:
    catalog = {
        "version": "v0.5",
        "catalog_url": "https://openapi.twse.com.tw/v1/swagger.json",
        "catalog_sha256": SWAGGER_SHA256,
        "datasets": [
            {
                "dataset_id": "t187ap04_L",
                "path": "/opendata/t187ap04_L",
                "category": "material_information",
                "status": "active",
                "refresh_class": "hourly",
                "public_projection": "theme_relevant_only",
            }
        ],
    }
    mutate(catalog)
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_dataset_catalog(path)


def test_checked_in_catalog_is_explicit_and_summarizes_deferred_categories() -> None:
    catalog = load_dataset_catalog(CATALOG_PATH)
    selected_paths = {dataset["path"] for dataset in catalog["datasets"]}

    assert catalog["version"] == "v0.5"
    assert catalog["catalog_sha256"] == SWAGGER_SHA256
    assert all(dataset["path"] == f"/opendata/{dataset['dataset_id']}" for dataset in catalog["datasets"])
    assert all(dataset["public_projection"] == "theme_relevant_only" for dataset in catalog["datasets"])
    assert "excluded_datasets" not in catalog
    assert catalog["deferred_categories"]
    assert all(isinstance(category, str) for category in catalog["deferred_categories"])
    assert all(path.startswith("/opendata/t187ap") for path in selected_paths)


def test_checked_in_catalog_contains_only_approved_active_mops_datasets() -> None:
    catalog = load_dataset_catalog(CATALOG_PATH)

    expected_refresh_classes = {
        "t187ap04_L": "hourly",
        "t187ap12_L": "daily",
        "t187ap13_L": "daily",
        "t187ap16_L": "quarterly",
        "t187ap22_L": "daily",
        "t187ap23_L": "daily",
        "t187ap24_L": "daily",
        "t187ap25_L": "daily",
        "t187ap26_L": "hourly",
        "t187ap27_L": "hourly",
        "t187ap38_L": "daily",
        "t187ap45_L": "daily",
    }
    actual_refresh_classes = {
        dataset["dataset_id"]: dataset["refresh_class"]
        for dataset in catalog["datasets"]
        if dataset["status"] == "active"
    }

    assert actual_refresh_classes == expected_refresh_classes


def test_twse_adapter_rejects_nonofficial_base_url() -> None:
    source = {
        **_source("mops", "twse_openapi"),
        "base_url": "https://example.com/v1",
    }

    with pytest.raises(ValueError, match="official TWSE OpenAPI base URL"):
        fetch_twse_openapi_source(object(), source, ANCHOR)


def test_twse_adapter_isolates_dataset_failures_and_caps_attempts(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "version": "v0.5",
                "catalog_url": "https://openapi.twse.com.tw/v1/swagger.json",
                "catalog_sha256": SWAGGER_SHA256,
                "datasets": [
                    {
                        "dataset_id": dataset_id,
                        "path": f"/opendata/{dataset_id}",
                        "category": "material_information",
                        "status": "active",
                        "refresh_class": "hourly",
                        "public_projection": "theme_relevant_only",
                    }
                    for dataset_id in ("healthy", "broken")
                ],
            }
        ),
        encoding="utf-8",
    )
    calls: dict[str, int] = {"healthy": 0, "broken": 0}

    class Response:
        def __init__(self, dataset_id: str) -> None:
            self.dataset_id = dataset_id
            self.headers: dict[str, str] = {}
            self.content = json.dumps(
                [{"公司代號": "2330", "公司名稱": "台積電", "出表日期": "1150727"}]
            ).encode()

        def raise_for_status(self) -> None:
            if self.dataset_id == "broken":
                raise requests.HTTPError("503 fixture")

        def iter_content(self, chunk_size: int):
            yield self.content[:chunk_size]
            yield self.content[chunk_size:]

        def close(self) -> None:
            return None

    class Session:
        def get(self, url: str, **_kwargs):
            dataset_id = url.rsplit("/", 1)[-1]
            calls[dataset_id] += 1
            return Response(dataset_id)

    source = {
        **_source("mops", "twse_openapi"),
        "catalog_path": str(catalog_path),
        "max_attempts": 2,
    }
    result = fetch_twse_openapi_source(Session(), source, ANCHOR, full_refresh=False)

    assert result["status"]["status"] == "partial"
    assert result["status"]["datasets_ok"] == 1
    assert result["status"]["datasets_failed"] == 1
    assert result["status"]["items"] == 1
    assert [dataset["dataset_id"] for dataset in result["status"]["datasets"]] == ["broken", "healthy"]
    assert calls == {"healthy": 1, "broken": 2}


def test_twse_adapter_rejects_oversized_dataset_response(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "version": "v0.5",
                "catalog_url": "https://openapi.twse.com.tw/v1/swagger.json",
                "catalog_sha256": SWAGGER_SHA256,
                "datasets": [
                    {
                        "dataset_id": "oversized",
                        "path": "/opendata/oversized",
                        "category": "material_information",
                        "status": "active",
                        "refresh_class": "hourly",
                        "public_projection": "theme_relevant_only",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class Response:
        headers = {"Content-Length": "6"}

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return []

        def iter_content(self, _chunk_size: int):
            yield b"123456"

        def close(self) -> None:
            return None

    class Session:
        def get(self, *_args, **_kwargs):
            return Response()

    result = fetch_twse_openapi_source(
        Session(),
        {
            **_source("mops", "twse_openapi"),
            "catalog_path": str(catalog_path),
            "max_response_bytes": 5,
        },
        ANCHOR,
    )

    assert result["status"]["status"] == "error"
    assert "response exceeds 5 bytes" in result["status"]["datasets"][0]["error"]


def test_twse_adapter_rejects_dataset_row_overflow(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "version": "v0.5",
                "catalog_url": "https://openapi.twse.com.tw/v1/swagger.json",
                "catalog_sha256": SWAGGER_SHA256,
                "datasets": [
                    {
                        "dataset_id": "too-many-rows",
                        "path": "/opendata/too-many-rows",
                        "category": "company_master",
                        "status": "active",
                        "refresh_class": "hourly",
                        "public_projection": "theme_relevant_only",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class Response:
        headers: dict[str, str] = {}
        content = json.dumps(
            [
                {"公司代號": "1101", "公司名稱": "台泥"},
                {"公司代號": "2330", "公司名稱": "台積電"},
            ]
        ).encode()

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return json.loads(self.content)

        def iter_content(self, chunk_size: int):
            yield self.content[:chunk_size]
            yield self.content[chunk_size:]

        def close(self) -> None:
            return None

    class Session:
        def get(self, *_args, **_kwargs):
            return Response()

    result = fetch_twse_openapi_source(
        Session(),
        {
            **_source("mops", "twse_openapi"),
            "catalog_path": str(catalog_path),
            "max_dataset_rows": 1,
        },
        ANCHOR,
    )

    assert result["status"]["status"] == "error"
    assert "row limit of 1" in result["status"]["datasets"][0]["error"]


def _load_fixture(name: str) -> dict[str, object]:
    fixture = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    provenance = fixture["_provenance"]
    assert provenance["endpoint"].startswith("https://openapi.twse.com.tw/v1/opendata/")
    assert len(provenance["capture_date"]) == 10
    assert len(provenance["original_payload_sha256"]) == 64
    assert provenance["swagger_sha256"] == SWAGGER_SHA256
    assert provenance["http_status"] == 200
    assert provenance["hash_basis"].startswith("UTF-8 SHA-256")
    return fixture


@pytest.mark.parametrize(
    ("fixture_name", "expected_category"),
    [
        ("material-information.json", "material_information"),
    ],
)
def test_real_official_fixtures_normalize_representative_categories(
    fixture_name: str,
    expected_category: str,
) -> None:
    fixture = _load_fixture(fixture_name)
    dataset = fixture["dataset"]
    records = [
        normalize_twse_record(row, dataset, _source("mops", "twse_openapi"), ANCHOR)
        for row in fixture["records"]
    ]

    assert records
    assert all(record["dataset_id"] == dataset["dataset_id"] for record in records)
    assert all(record["category"] == expected_category for record in records)
    assert all(record["source_id"] == "mops" for record in records)
    assert all(record["adapter"] == "twse_openapi" for record in records)
    assert all(record["market_id"] == "TW_EQUITY" for record in records)
    assert all(record["raw_reference"].startswith(dataset["path"]) for record in records)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1150727", "2026-07-27T00:00:00Z"),
        ("115/07/27", "2026-07-27T00:00:00Z"),
        ("20260727", "2026-07-27T00:00:00Z"),
        ("2026-07-27", "2026-07-27T00:00:00Z"),
        ("", None),
    ],
)
def test_official_date_normalizes_roc_and_gregorian_values(value: str, expected: str | None) -> None:
    assert normalize_official_date(value) == expected


def test_official_evidence_payload_is_bounded_and_deterministic() -> None:
    records = [
        {
            "evidence_id": f"mops-{index}",
            "published_at": f"2026-07-{27 - index:02d}T00:00:00Z",
        }
        for index in range(5)
    ]

    payload = build_official_evidence_payload(
        list(reversed(records)),
        generated_at=ANCHOR,
        window_hours=72,
        max_items=2,
    )

    assert payload["market_id"] == "TW_EQUITY"
    assert payload["window_hours"] == 72
    assert payload["max_items"] == 2
    assert payload["total_items"] == 2
    assert payload["total_items_available"] == 3
    assert [item["evidence_id"] for item in payload["items"]] == ["mops-0", "mops-1"]


def test_matching_attaches_deterministic_confirmation_states() -> None:
    events = [
        {
            "id": "confirmed",
            "published_at": "2026-07-27T08:00:00Z",
            "title_zh": "台積電重大投資案",
            "related_symbols": [{"instrument_id": "TWSE:2330", "symbol": "2330"}],
        },
        {
            "id": "unconfirmed",
            "published_at": "2026-07-27T08:00:00Z",
            "title_zh": "廣達伺服器需求",
            "related_symbols": [{"instrument_id": "TWSE:2382", "symbol": "2382"}],
        },
        {
            "id": "not-required",
            "published_at": "2026-07-27T08:00:00Z",
            "title_zh": "產業趨勢觀察",
            "related_symbols": [],
        },
    ]
    evidence = [
        {
            "evidence_id": "mops-confirm",
            "instrument_id": "TWSE:2330",
            "symbol": "2330",
            "company_name": "台積電",
            "title": "重大投資案",
            "published_at": "2026-07-27T07:30:00Z",
        }
    ]

    attached = attach_official_evidence(events, evidence, official_available=True)

    assert [item["confirmation_status"] for item in attached] == [
        "confirmed",
        "unconfirmed",
        "not_required",
    ]
    assert attached[0]["official_evidence_ids"] == ["mops-confirm"]
    assert attached[0]["official_evidence_count"] == 1
    assert attached[1]["official_evidence_ids"] == []


def test_matching_marks_same_symbol_correction_as_conflicting() -> None:
    events = [
        {
            "id": "event",
            "published_at": "2026-07-27T08:00:00Z",
            "title_zh": "台積電重大投資案",
            "related_symbols": [{"instrument_id": "TWSE:2330", "symbol": "2330"}],
        }
    ]
    evidence = [
        {
            "evidence_id": "mops-correction",
            "instrument_id": "TWSE:2330",
            "symbol": "2330",
            "company_name": "台積電",
            "title": "更正：撤銷前次重大投資案",
            "published_at": "2026-07-27T07:30:00Z",
        }
    ]

    attached = attach_official_evidence(events, evidence, official_available=True)

    assert attached[0]["confirmation_status"] == "conflicting"
    assert attached[0]["official_evidence_ids"] == ["mops-correction"]


def test_matching_leaves_same_symbol_unrelated_evidence_unconfirmed() -> None:
    events = [
        {
            "id": "unrelated",
            "published_at": "2026-07-27T08:00:00Z",
            "title_zh": "台積電先進封裝擴產",
            "summary": "CoWoS 產能需求增加",
            "related_symbols": [{"instrument_id": "TWSE:2330", "symbol": "2330"}],
        }
    ]
    evidence = [
        {
            "evidence_id": "mops-unrelated",
            "instrument_id": "TWSE:2330",
            "symbol": "2330",
            "company_name": "台積電",
            "title": "董事會決議股利分派",
            "summary": "普通股現金股利",
            "category": "dividends_shareholder_meetings",
            "published_at": "2026-07-27T07:30:00Z",
        }
    ]

    attached = attach_official_evidence(events, evidence, official_available=True)

    assert attached[0]["confirmation_status"] == "unconfirmed"
    assert attached[0]["official_evidence_ids"] == []


def test_official_failure_marks_required_events_unavailable() -> None:
    events = [
        {
            "id": "event",
            "published_at": "2026-07-27T08:00:00Z",
            "title_zh": "台積電重大投資案",
            "related_symbols": [{"instrument_id": "TWSE:2330", "symbol": "2330"}],
        }
    ]

    attached = attach_official_evidence(events, [], official_available=False)

    assert attached[0]["confirmation_status"] == "unavailable"
    assert attached[0]["official_evidence_ids"] == []
    assert attached[0]["official_evidence_count"] == 0


def test_run_update_keeps_official_rows_out_of_public_theme_projection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "market_id": "TW_EQUITY",
                "market_scope": ["TW_EQUITY"],
                "sources": [
                    _source("moneydj", "rss"),
                    _source("mops", "twse_openapi"),
                ],
            }
        ),
        encoding="utf-8",
    )
    official_record = {
        "evidence_id": "mops-official-only",
        "source_id": "mops",
        "source_class": "official_disclosure",
        "adapter": "twse_openapi",
        "dataset_id": "t187ap04_L",
        "category": "material_information",
        "market_id": "TW_EQUITY",
        "instrument_id": "TWSE:2330",
        "symbol": "2330",
        "company_name": "台積電",
        "title": "AI 伺服器重大投資",
        "summary": None,
        "published_at": "2026-07-27T08:00:00Z",
        "effective_at": "2026-07-27T08:00:00Z",
        "canonical_url": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
        "raw_reference": "/opendata/t187ap04_L#sha256:fixture",
        "fetched_at": "2026-07-27T09:00:00Z",
    }

    def fake_dispatch(*_args, **_kwargs):
        return [
            {
                "records": [
                    {
                        "id": "rss-event",
                        "title_zh": "廣達 AI 伺服器液冷散熱需求升溫",
                        "summary": "",
                        "source": "MoneyDJ",
                        "source_id": "moneydj",
                        "published_at": "2026-07-27T08:00:00Z",
                        "url": "https://example.com/rss-event",
                    }
                ],
                "status": {
                    "source_id": "moneydj",
                    "source_class": "financial_media",
                    "adapter": "rss",
                    "status": "ok",
                    "items": 1,
                },
            },
            {
                "records": [official_record],
                "status": {
                    "source_id": "mops",
                    "source_class": "official_disclosure",
                    "adapter": "twse_openapi",
                    "status": "ok",
                    "items": 1,
                    "datasets_ok": 1,
                },
            },
        ]

    monkeypatch.setattr("scripts.update_theme_radar.now_utc", lambda: ANCHOR)
    monkeypatch.setattr("scripts.update_theme_radar.dispatch_sources", fake_dispatch)
    output_dir = tmp_path / "output"

    run_update(
        registry_path=registry_path,
        output_dir=output_dir,
        window_hours=24,
        max_events=10,
        max_candidates=10,
    )
    events = json.loads((output_dir / "theme-events.json").read_text(encoding="utf-8"))
    evidence = json.loads((output_dir / "official-evidence.json").read_text(encoding="utf-8"))

    assert [item["id"] for item in events["items"]] == ["rss-event"]
    assert all(item.get("source_id") != "mops" for item in events["items"])
    assert [item["evidence_id"] for item in evidence["items"]] == ["mops-official-only"]


def test_checked_in_official_evidence_seed_is_bounded_and_compatible() -> None:
    payload = json.loads((ROOT / "data" / "official-evidence.json").read_text(encoding="utf-8"))

    assert {
        "generated_at",
        "market_id",
        "window_hours",
        "max_items",
        "total_items",
        "total_items_available",
        "items",
    } <= payload.keys()
    assert payload["market_id"] == "TW_EQUITY"
    assert payload["total_items"] == len(payload["items"])
    assert payload["total_items"] <= payload["max_items"] <= 500
