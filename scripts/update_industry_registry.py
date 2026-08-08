"""Build the Taiwan symbol and public supply-chain reference snapshots.

This is a manual research/update command.  It is intentionally not imported by
the hourly theme-radar pipeline because StatementDog is a browser-oriented
third-party site.  Only public taxonomy labels and company memberships are
retained; subscriber-only benefit explanations are never copied.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import json
import random
import re
import ssl
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDUSTRY_OUTPUT = ROOT / "config" / "industry_supply_chains.tw.json"
DEFAULT_SYMBOL_OUTPUT = ROOT / "config" / "symbol_registry.tw.json"
DEFAULT_CATALOG_OUTPUT = ROOT / "docs" / "INDUSTRY_SUPPLY_CHAIN_CATALOG.md"
STATEMENTDOG_SITEMAP_URL = "https://statementdog.com/sitemap.xml.gz"
STATEMENTDOG_TAG_PATTERN = re.compile(r"https://statementdog\.com/tags/(?P<tag_id>\d+)$")
STATEMENTDOG_COMPANY_PATTERN = re.compile(r"^/analysis/(?P<symbol>[0-9A-Za-z.-]+)$")
SUPPLY_CHAIN_STAGES = {"上游", "中游", "下游"}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0.0.0 Safari/537.36"
)

OFFICIAL_COMPANY_SOURCES = (
    {
        "exchange": "TWSE",
        "url": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
        "symbol_key": "公司代號",
        "name_key": "公司簡稱",
        "company_name_key": "公司名稱",
        "industry_key": "產業別",
        "listed_at_key": "上市日期",
    },
    {
        "exchange": "TPEX",
        "url": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
        "symbol_key": "SecuritiesCompanyCode",
        "name_key": "CompanyAbbreviation",
        "company_name_key": "CompanyName",
        "industry_key": "SecuritiesIndustryCode",
        "listed_at_key": "DateOfListing",
    },
    {
        "exchange": "ESB",
        "url": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_R",
        "symbol_key": "SecuritiesCompanyCode",
        "name_key": "CompanyAbbreviation",
        "company_name_key": "CompanyName",
        "industry_key": "SecuritiesIndustryCode",
        "listed_at_key": "DateOfListing",
    },
)

# The code values come from the official MOPS company-profile datasets above.
# Keeping the small lookup local makes the checked-in registry readable and
# avoids a second scraped source for labels that change very rarely.
INDUSTRY_NAMES_ZH = {
    "01": "水泥工業",
    "02": "食品工業",
    "03": "塑膠工業",
    "04": "紡織纖維",
    "05": "電機機械",
    "06": "電器電纜",
    "08": "玻璃陶瓷",
    "09": "造紙工業",
    "10": "鋼鐵工業",
    "11": "橡膠工業",
    "12": "汽車工業",
    "14": "建材營造",
    "15": "航運業",
    "16": "觀光餐旅",
    "17": "金融保險",
    "18": "貿易百貨",
    "20": "其他",
    "21": "化學工業",
    "22": "生技醫療業",
    "23": "油電燃氣業",
    "24": "半導體業",
    "25": "電腦及週邊設備業",
    "26": "光電業",
    "27": "通信網路業",
    "28": "電子零組件業",
    "29": "電子通路業",
    "30": "資訊服務業",
    "31": "其他電子業",
    "32": "文化創意業",
    "33": "農業科技業",
    "35": "綠能環保",
    "36": "數位雲端",
    "37": "運動休閒",
    "38": "居家生活",
    "91": "存託憑證",
}


class CompatibleTLSAdapter(HTTPAdapter):
    """Retain certificate verification while relaxing Python 3.14 strict mode.

    TPEX currently serves an otherwise trusted certificate chain whose leaf
    certificate lacks the Subject Key Identifier required by OpenSSL strict
    verification.  Browsers and older Python versions accept the same chain.
    """

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        context = ssl.create_default_context()
        strict = getattr(ssl, "VERIFY_X509_STRICT", 0)
        if strict:
            context.verify_flags &= ~strict
        kwargs["ssl_context"] = context
        super().init_poolmanager(*args, **kwargs)


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        }
    )
    session.mount("https://www.tpex.org.tw", CompatibleTLSAdapter())
    return session


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _fetch_text(
    session: requests.Session,
    url: str,
    *,
    timeout_seconds: float,
    attempts: int = 5,
) -> str:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.get(url, timeout=timeout_seconds)
            if response.status_code == 200 and len(response.content) > 100:
                return response.text
            raise RuntimeError(
                f"unexpected response status={response.status_code} bytes={len(response.content)}"
            )
        except (requests.RequestException, RuntimeError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep((2**attempt) + random.uniform(0.1, 0.8))
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def fetch_statementdog_sitemap(
    session: requests.Session,
    *,
    timeout_seconds: float,
) -> tuple[list[str], set[str], str]:
    response = session.get(STATEMENTDOG_SITEMAP_URL, timeout=timeout_seconds)
    response.raise_for_status()
    body = gzip.decompress(response.content).decode("utf-8")
    urls = sorted(
        {
            url
            for url in re.findall(r"<loc>(.*?)</loc>", body)
            if STATEMENTDOG_TAG_PATTERN.fullmatch(url)
        },
        key=lambda value: int(value.rsplit("/", 1)[-1]),
    )
    if not urls:
        raise ValueError("StatementDog sitemap contained no numeric tag pages")
    company_symbols = {
        match.group(1)
        for url in re.findall(r"<loc>(.*?)</loc>", body)
        if (match := re.fullmatch(r"https://statementdog\.com/analysis/(\d{4})", url))
    }
    return urls, company_symbols, hashlib.sha256(response.content).hexdigest()


def _normalized_tag_name(soup: BeautifulSoup) -> str:
    heading = soup.find("h1")
    if heading is None:
        return ""
    name = " ".join(heading.get_text(" ", strip=True).split())
    return re.sub(r"概念股$", "", name).strip()


def _parse_company(company: Any, rank: int) -> dict[str, Any] | None:
    row = company.select_one(".benefit-company-row .row-info")
    if row is None:
        return None
    values = [" ".join(value.split()) for value in row.stripped_strings]
    if len(values) < 2:
        return None
    market_parts = values[0].split(maxsplit=1)
    if len(market_parts) != 2:
        return None
    market_label, row_symbol = market_parts
    if market_label != "台股":
        return None
    link = company.select_one('a[href^="/analysis/"]')
    match = (
        STATEMENTDOG_COMPANY_PATTERN.fullmatch(str(link.get("href") or ""))
        if link is not None
        else None
    )
    symbol = match.group("symbol").strip() if match else row_symbol.strip()
    if not re.fullmatch(r"\d{4}", symbol):
        return None
    name_zh = values[1]
    benefit_level_zh = next((value for value in values[2:] if value.startswith("受惠")), "")
    return {
        "symbol": symbol,
        "name_zh": name_zh,
        "benefit_level_zh": benefit_level_zh,
        "source_rank": rank,
    }


def parse_supply_chain_page(html: str, url: str) -> dict[str, Any] | None:
    """Return public stage/segment/company structure, or None for a news-only tag."""

    soup = BeautifulSoup(html, "html.parser")
    labels = soup.select("section.benefit-master-detail label.benefit-topic-label")
    articles = soup.select("section.benefit-master-detail article.benefit-topic-detail")
    if not labels and not articles:
        return None
    if len(labels) != len(articles):
        raise ValueError(f"topic label/article mismatch at {url}")

    segments: list[dict[str, Any]] = []
    for label, article in zip(labels, articles, strict=True):
        values = [" ".join(value.split()) for value in label.stripped_strings]
        if len(values) < 2:
            raise ValueError(f"invalid supply-chain label at {url}: {values!r}")
        # StatementDog uses the same master/detail markup for other benefit
        # groupings such as "直接受惠". Those are valid concept pages but are
        # not upstream/midstream/downstream supply-chain taxonomies.
        if values[0] not in SUPPLY_CHAIN_STAGES:
            return None
        companies = [
            parsed
            for rank, company in enumerate(article.select(".benefit-company"), start=1)
            if (parsed := _parse_company(company, rank)) is not None
        ]
        segments.append(
            {
                "stage": values[0],
                "name_zh": values[1],
                "companies": companies,
            }
        )

    tag_match = STATEMENTDOG_TAG_PATTERN.fullmatch(url)
    if tag_match is None:
        raise ValueError(f"invalid StatementDog tag URL: {url}")
    name_zh = _normalized_tag_name(soup)
    if not name_zh:
        raise ValueError(f"missing tag heading at {url}")

    taiwan_symbols = sorted(
        {
            company["symbol"]
            for segment in segments
            for company in segment["companies"]
        }
    )
    return {
        "industry_id": f"statementdog:{tag_match.group('tag_id')}",
        "source_tag_id": tag_match.group("tag_id"),
        "name_zh": name_zh,
        "source_url": url,
        "taiwan_symbol_count": len(taiwan_symbols),
        "taiwan_symbols": taiwan_symbols,
        "segments": segments,
    }


class _TagFetcher:
    def __init__(self, *, delay_seconds: float, timeout_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.timeout_seconds = timeout_seconds
        self.local = threading.local()

    def _worker_session(self) -> requests.Session:
        session = getattr(self.local, "session", None)
        if session is None:
            session = _session()
            session.get("https://statementdog.com/", timeout=self.timeout_seconds)
            self.local.session = session
        return session

    def __call__(self, url: str) -> dict[str, Any]:
        session = self._worker_session()
        try:
            html = _fetch_text(session, url, timeout_seconds=self.timeout_seconds)
            industry = parse_supply_chain_page(html, url)
            return {"url": url, "status": "supply_chain" if industry else "not_supply_chain", "industry": industry}
        except Exception as exc:  # noqa: BLE001 - preserve URL-level failure for a complete audit
            return {"url": url, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
        finally:
            if self.delay_seconds:
                time.sleep(self.delay_seconds)


def _normalize_taiwan_industry(industry: dict[str, Any]) -> dict[str, Any]:
    """Normalize older checkpoints into the Taiwan-only public snapshot."""

    segments: list[dict[str, Any]] = []
    symbols: set[str] = set()
    for segment in industry["segments"]:
        companies: list[dict[str, Any]] = []
        for company in segment["companies"]:
            symbol = str(company.get("symbol") or "")
            market = company.get("market")
            if not re.fullmatch(r"\d{4}", symbol) or market not in {None, "TW"}:
                continue
            symbols.add(symbol)
            companies.append(
                {
                    "symbol": symbol,
                    "name_zh": str(company.get("name_zh") or ""),
                    "benefit_level_zh": str(company.get("benefit_level_zh") or ""),
                    "source_rank": int(company.get("source_rank") or 0),
                }
            )
        segments.append(
            {
                "stage": segment["stage"],
                "name_zh": segment["name_zh"],
                "companies": companies,
            }
        )
    return {
        "industry_id": industry["industry_id"],
        "source_tag_id": industry["source_tag_id"],
        "name_zh": industry["name_zh"],
        "source_url": industry["source_url"],
        "taiwan_symbol_count": len(symbols),
        "taiwan_symbols": sorted(symbols),
        "segments": segments,
    }


def crawl_statementdog_supply_chains(
    urls: Iterable[str],
    *,
    workers: int,
    delay_seconds: float,
    timeout_seconds: float,
    checkpoint_path: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], int]:
    requested = list(urls)
    completed: dict[str, dict[str, Any]] = {}
    if checkpoint_path and checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        for row in checkpoint.get("results", []):
            if row.get("status") != "error" and row.get("url") in requested:
                completed[row["url"]] = row

    pending = [url for url in requested if url not in completed]
    fetcher = _TagFetcher(delay_seconds=delay_seconds, timeout_seconds=timeout_seconds)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetcher, url): url for url in pending}
        for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            row = future.result()
            completed[row["url"]] = row
            if index % 25 == 0 or index == len(pending):
                supply_count = sum(value.get("status") == "supply_chain" for value in completed.values())
                error_count = sum(value.get("status") == "error" for value in completed.values())
                print(
                    f"statementdog progress {len(completed)}/{len(requested)} "
                    f"supply_chains={supply_count} errors={error_count}",
                    flush=True,
                )
                if checkpoint_path:
                    _atomic_write_json(
                        checkpoint_path,
                        {"schema_version": "1.0", "results": list(completed.values())},
                    )

    industries = sorted(
        [
            _normalize_taiwan_industry(row["industry"])
            for row in completed.values()
            if row.get("status") == "supply_chain"
        ],
        key=lambda row: int(row["source_tag_id"]),
    )
    errors = sorted(
        [
            {"url": row["url"], "error": str(row.get("error") or "unknown error")}
            for row in completed.values()
            if row.get("status") == "error"
        ],
        key=lambda row: row["url"],
    )
    not_supply_chain_count = sum(
        row.get("status") == "not_supply_chain" for row in completed.values()
    )
    return industries, errors, not_supply_chain_count


def fetch_official_companies(
    session: requests.Session,
    *,
    timeout_seconds: float,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    symbols: list[dict[str, str]] = []
    source_status: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in OFFICIAL_COMPANY_SOURCES:
        response = session.get(source["url"], timeout=timeout_seconds)
        response.raise_for_status()
        rows = response.json()
        accepted = 0
        for row in rows:
            symbol = str(row.get(source["symbol_key"]) or "").strip()
            if not re.fullmatch(r"\d{4}", symbol):
                continue
            if symbol in seen:
                raise ValueError(f"official company symbol appears in multiple markets: {symbol}")
            seen.add(symbol)
            industry_code = str(row.get(source["industry_key"]) or "").strip()
            if industry_code not in INDUSTRY_NAMES_ZH:
                raise ValueError(
                    f"unknown official industry code {industry_code!r} for {source['exchange']}:{symbol}"
                )
            name_zh = str(row.get(source["name_key"]) or "").strip()
            company_name_zh = str(row.get(source["company_name_key"]) or "").strip()
            if not name_zh or not company_name_zh:
                raise ValueError(f"official company row is missing a name: {source['exchange']}:{symbol}")
            symbols.append(
                {
                    "symbol": symbol,
                    "instrument_id": f"{source['exchange']}:{symbol}",
                    "exchange": source["exchange"],
                    "name_zh": name_zh,
                    "company_name_zh": company_name_zh,
                    "industry_code": industry_code,
                    "industry_name_zh": INDUSTRY_NAMES_ZH[industry_code],
                    "listed_at": str(row.get(source["listed_at_key"]) or "").strip(),
                }
            )
            accepted += 1
        source_status.append(
            {
                "exchange": source["exchange"],
                "url": source["url"],
                "rows_received": len(rows),
                "symbols_accepted": accepted,
            }
        )
    return sorted(symbols, key=lambda row: row["symbol"]), source_status


def build_symbol_registry(
    official_symbols: list[dict[str, str]],
    industries: list[dict[str, Any]],
    *,
    generated_at: str,
    official_sources: list[dict[str, Any]],
    statementdog_company_symbols: set[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    memberships: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for industry in industries:
        for segment in industry["segments"]:
            for company in segment["companies"]:
                symbol = company["symbol"]
                if not re.fullmatch(r"\d{4}", symbol):
                    continue
                memberships[symbol].append(
                    {
                        "industry_id": industry["industry_id"],
                        "industry_name_zh": industry["name_zh"],
                        "stage": segment["stage"],
                        "segment_name_zh": segment["name_zh"],
                        "benefit_level_zh": company["benefit_level_zh"],
                        "source_rank": company["source_rank"],
                    }
                )

    official_set = {row["symbol"] for row in official_symbols}
    source_only_symbols = sorted(set(memberships) - official_set)
    registry_symbols: list[dict[str, Any]] = []
    for row in official_symbols:
        symbol_memberships = sorted(
            memberships.get(row["symbol"], []),
            key=lambda value: (
                int(value["industry_id"].split(":", 1)[1]),
                value["stage"],
                value["source_rank"],
            ),
        )
        registry_symbols.append(
            {
                **row,
                "statementdog_company_url": (
                    f"https://statementdog.com/analysis/{row['symbol']}"
                    if statementdog_company_symbols is None
                    or row["symbol"] in statementdog_company_symbols
                    else None
                ),
                "supply_chain_memberships": symbol_memberships,
            }
        )

    registry = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "market_id": "TW_EQUITY",
        "official_sources": official_sources,
        "official_symbol_count": len(registry_symbols),
        "supply_chain_mapped_symbol_count": sum(
            bool(row["supply_chain_memberships"]) for row in registry_symbols
        ),
        "symbols": registry_symbols,
    }
    return registry, source_only_symbols


def validate_snapshots(
    industries_payload: dict[str, Any],
    symbol_registry: dict[str, Any],
) -> None:
    industries = industries_payload.get("industries")
    symbols = symbol_registry.get("symbols")
    if not isinstance(industries, list) or not industries:
        raise ValueError("industry snapshot must contain supply-chain industries")
    if not isinstance(symbols, list) or len(symbols) < 2_000:
        raise ValueError("symbol registry must contain the full official Taiwan universe")
    industry_ids = [row["industry_id"] for row in industries]
    if len(industry_ids) != len(set(industry_ids)):
        raise ValueError("industry snapshot contains duplicate industry IDs")
    symbol_codes = [row["symbol"] for row in symbols]
    if len(symbol_codes) != len(set(symbol_codes)):
        raise ValueError("symbol registry contains duplicate symbols")
    known_industries = set(industry_ids)
    industry_memberships: set[tuple[str, str, str, str]] = set()
    source_symbols: set[str] = set()
    for industry in industries:
        flattened_symbols = {
            company["symbol"]
            for segment in industry["segments"]
            for company in segment["companies"]
        }
        if flattened_symbols != set(industry["taiwan_symbols"]):
            raise ValueError("industry taiwan_symbols do not match segment memberships")
        if industry["taiwan_symbol_count"] != len(flattened_symbols):
            raise ValueError("industry taiwan_symbol_count is inconsistent")
        source_symbols.update(flattened_symbols)
        for segment in industry["segments"]:
            if segment["stage"] not in SUPPLY_CHAIN_STAGES:
                raise ValueError("industry segment uses an invalid supply-chain stage")
            for company in segment["companies"]:
                if not re.fullmatch(r"\d{4}", company["symbol"]):
                    raise ValueError("industry snapshot must contain Taiwan symbols only")
                industry_memberships.add(
                    (
                        company["symbol"],
                        industry["industry_id"],
                        segment["stage"],
                        segment["name_zh"],
                    )
                )

    registry_memberships: set[tuple[str, str, str, str]] = set()
    for row in symbols:
        for membership in row["supply_chain_memberships"]:
            if membership["industry_id"] not in known_industries:
                raise ValueError("symbol registry membership points to an unknown industry")
            registry_memberships.add(
                (
                    row["symbol"],
                    membership["industry_id"],
                    membership["stage"],
                    membership["segment_name_zh"],
                )
            )

    official_symbols = set(symbol_codes)
    if registry_memberships != {
        membership
        for membership in industry_memberships
        if membership[0] in official_symbols
    }:
        raise ValueError("symbol registry memberships do not match the industry snapshot")
    if symbol_registry.get("official_symbol_count") != len(symbols):
        raise ValueError("official_symbol_count is inconsistent")
    mapped_count = sum(bool(row["supply_chain_memberships"]) for row in symbols)
    if symbol_registry.get("supply_chain_mapped_symbol_count") != mapped_count:
        raise ValueError("supply_chain_mapped_symbol_count is inconsistent")
    expected_source_only = sorted(source_symbols - official_symbols)
    if (
        industries_payload.get("source", {}).get(
            "taiwan_symbols_missing_from_official_registry"
        )
        != expected_source_only
    ):
        raise ValueError("source-only Taiwan symbol list is inconsistent")
    source = industries_payload.get("source", {})
    if source.get("tag_pages_fetched", 0) + source.get("failed_page_count", 0) != source.get(
        "tag_pages_discovered"
    ):
        raise ValueError("StatementDog page-count audit is inconsistent")


def build_catalog_markdown(industries_payload: dict[str, Any]) -> str:
    lines = [
        "# Taiwan supply-chain catalog",
        "",
        (
            "Generated from the public StatementDog tag pages recorded in "
            "`config/industry_supply_chains.tw.json`. Company counts include "
            "Taiwan symbols only."
        ),
        "",
        f"Snapshot generated: `{industries_payload['generated_at']}`",
        "",
        "| Tag | Supply chain | Upstream segments | Midstream segments | Downstream segments | Taiwan symbols |",
        "| ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for industry in industries_payload["industries"]:
        stage_counts = {stage: 0 for stage in SUPPLY_CHAIN_STAGES}
        for segment in industry["segments"]:
            stage_counts[segment["stage"]] += 1
        name = str(industry["name_zh"]).replace("|", "\\|")
        lines.append(
            "| "
            f"[{industry['source_tag_id']}]({industry['source_url']}) | {name} | "
            f"{stage_counts['上游']} | {stage_counts['中游']} | {stage_counts['下游']} | "
            f"{industry['taiwan_symbol_count']} |"
        )
    lines.extend(
        [
            "",
            "See `docs/INDUSTRY_SUPPLY_CHAIN_DATA.md` for methodology, sources, and limitations.",
            "",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--industry-output", type=Path, default=DEFAULT_INDUSTRY_OUTPUT)
    parser.add_argument("--symbol-output", type=Path, default=DEFAULT_SYMBOL_OUTPUT)
    parser.add_argument("--catalog-output", type=Path, default=DEFAULT_CATALOG_OUTPUT)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--delay-seconds", type=float, default=0.75)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--limit", type=int, help="development-only cap over sitemap tag pages")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="write snapshots even when one or more tag pages failed",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.workers < 1 or args.delay_seconds < 0 or args.timeout_seconds <= 0:
        raise ValueError("workers, delay, and timeout values are invalid")

    session = _session()
    tag_urls, statementdog_company_symbols, sitemap_sha256 = fetch_statementdog_sitemap(
        session,
        timeout_seconds=args.timeout_seconds,
    )
    if args.limit is not None:
        tag_urls = tag_urls[: args.limit]

    industries, errors, not_supply_chain_count = crawl_statementdog_supply_chains(
        tag_urls,
        workers=args.workers,
        delay_seconds=args.delay_seconds,
        timeout_seconds=args.timeout_seconds,
        checkpoint_path=args.checkpoint,
    )
    if errors and not args.allow_partial:
        sample = "; ".join(f"{row['url']}: {row['error']}" for row in errors[:5])
        raise RuntimeError(f"refusing to write partial crawl with {len(errors)} errors: {sample}")

    official_symbols, official_sources = fetch_official_companies(
        session,
        timeout_seconds=args.timeout_seconds,
    )
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    industry_payload = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "market_id": "TW_EQUITY",
        "source": {
            "name": "StatementDog",
            "sitemap_url": STATEMENTDOG_SITEMAP_URL,
            "sitemap_sha256": sitemap_sha256,
            "tag_pages_discovered": len(tag_urls),
            "numeric_company_pages_discovered": len(statementdog_company_symbols),
            "tag_pages_fetched": len(tag_urls) - len(errors),
            "supply_chain_page_count": len(industries),
            "non_supply_chain_page_count": not_supply_chain_count,
            "failed_page_count": len(errors),
            "failed_pages": errors,
            "scope_note": (
                "Public industry names, upstream/midstream/downstream segment labels, "
                "Taiwan company memberships, and displayed benefit levels only; subscriber-only "
                "benefit explanations are excluded."
            ),
        },
        "industry_count": len(industries),
        "industries": industries,
    }
    symbol_registry, source_only_symbols = build_symbol_registry(
        official_symbols,
        industries,
        generated_at=generated_at,
        official_sources=official_sources,
        statementdog_company_symbols=statementdog_company_symbols,
    )
    industry_payload["source"]["taiwan_symbols_missing_from_official_registry"] = source_only_symbols
    validate_snapshots(industry_payload, symbol_registry)
    _atomic_write_json(args.industry_output, industry_payload)
    _atomic_write_json(args.symbol_output, symbol_registry)
    _atomic_write_text(args.catalog_output, build_catalog_markdown(industry_payload))
    if not errors and args.checkpoint and args.checkpoint.exists():
        args.checkpoint.unlink()

    print(
        json.dumps(
            {
                "industry_output": str(args.industry_output),
                "symbol_output": str(args.symbol_output),
                "catalog_output": str(args.catalog_output),
                "tag_pages": len(tag_urls),
                "supply_chain_pages": len(industries),
                "official_symbols": len(official_symbols),
                "mapped_symbols": symbol_registry["supply_chain_mapped_symbol_count"],
                "source_only_symbols": source_only_symbols,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
