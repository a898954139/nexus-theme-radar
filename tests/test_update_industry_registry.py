from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.update_industry_registry import (
    build_catalog_markdown,
    build_symbol_registry,
    parse_supply_chain_page,
    validate_snapshots,
)


ROOT = Path(__file__).resolve().parents[1]


def _company(
    symbol: str,
    name: str,
    market: str,
    benefit: str,
    *,
    linked: bool = True,
) -> str:
    link = f'<a href="/analysis/{symbol}">查看公司更多題材</a>' if linked else ""
    return f"""
      <div class="benefit-company">
        <label class="benefit-company-row">
          <div class="row-info"><div>{market} {symbol}</div><div>{name}</div><div>{benefit}</div></div>
        </label>
        {link}
      </div>
    """


def test_parse_supply_chain_page_keeps_public_structure_and_market_membership() -> None:
    html = f"""
      <html><head><title>測試產業</title></head><body>
        <h1>測試產業概念股</h1>
        <section class="benefit-master-detail">
          <nav>
            <label class="benefit-topic-label"><span>上游</span><span>材料</span></label>
            <label class="benefit-topic-label"><span>下游</span><span>系統</span></label>
          </nav>
          <article class="benefit-topic-detail">
            {_company("2330", "台積電", "台股", "受惠最高")}
            {_company("NVDA", "輝達", "美股", "受惠高")}
            {_company("688981", "中芯國際", "陸股", "受惠中", linked=False)}
          </article>
          <article class="benefit-topic-detail">
            {_company("2382", "廣達", "台股", "受惠中")}
          </article>
        </section>
      </body></html>
    """

    industry = parse_supply_chain_page(html, "https://statementdog.com/tags/123")

    assert industry is not None
    assert industry["industry_id"] == "statementdog:123"
    assert industry["name_zh"] == "測試產業"
    assert industry["taiwan_symbols"] == ["2330", "2382"]
    assert industry["segments"][0] == {
        "stage": "上游",
        "name_zh": "材料",
        "companies": [
            {
                "symbol": "2330",
                "name_zh": "台積電",
                "benefit_level_zh": "受惠最高",
                "source_rank": 1,
            },
        ],
    }


def test_parse_supply_chain_page_ignores_news_only_tag() -> None:
    assert (
        parse_supply_chain_page(
            "<html><body><h1>量產新聞</h1><article>news</article></body></html>",
            "https://statementdog.com/tags/999",
        )
        is None
    )


def test_parse_supply_chain_page_ignores_non_chain_benefit_grouping() -> None:
    html = f"""
      <h1>晶圓代工概念股</h1>
      <section class="benefit-master-detail">
        <label class="benefit-topic-label"><span>直接受惠</span><span>龍頭</span></label>
        <article class="benefit-topic-detail">
          {_company("2330", "台積電", "台股", "受惠最高")}
        </article>
      </section>
    """
    assert (
        parse_supply_chain_page(html, "https://statementdog.com/tags/101")
        is None
    )


def test_parse_supply_chain_page_rejects_partial_master_detail() -> None:
    html = """
      <h1>錯誤概念股</h1>
      <section class="benefit-master-detail">
        <label class="benefit-topic-label"><span>上游</span><span>材料</span></label>
      </section>
    """
    with pytest.raises(ValueError, match="label/article mismatch"):
        parse_supply_chain_page(html, "https://statementdog.com/tags/123")


def test_parse_supply_chain_page_keeps_source_segment_without_company_assignment() -> None:
    html = """
      <h1>甜點概念股</h1>
      <section class="benefit-master-detail">
        <label class="benefit-topic-label"><span>上游</span><span>糖與原料</span></label>
        <article class="benefit-topic-detail"></article>
      </section>
    """
    industry = parse_supply_chain_page(html, "https://statementdog.com/tags/929")
    assert industry is not None
    assert industry["segments"] == [
        {"stage": "上游", "name_zh": "糖與原料", "companies": []}
    ]


def test_build_symbol_registry_joins_only_current_official_symbols() -> None:
    industries = [
        {
            "industry_id": "statementdog:123",
            "name_zh": "測試產業",
            "segments": [
                {
                    "stage": "上游",
                    "name_zh": "材料",
                    "companies": [
                        {
                            "symbol": "2330",
                            "name_zh": "台積電",
                            "benefit_level_zh": "受惠最高",
                            "source_rank": 1,
                        },
                        {
                            "symbol": "9999",
                            "name_zh": "已下市",
                            "benefit_level_zh": "受惠低",
                            "source_rank": 2,
                        },
                    ],
                }
            ],
        }
    ]
    official = [
        {
            "symbol": "2330",
            "instrument_id": "TWSE:2330",
            "exchange": "TWSE",
            "name_zh": "台積電",
            "company_name_zh": "台灣積體電路製造股份有限公司",
            "industry_code": "24",
            "industry_name_zh": "半導體業",
            "listed_at": "19940905",
        }
    ]

    registry, source_only = build_symbol_registry(
        official,
        industries,
        generated_at="2026-08-08T00:00:00Z",
        official_sources=[],
    )

    assert source_only == ["9999"]
    assert registry["supply_chain_mapped_symbol_count"] == 1
    assert registry["symbols"][0]["supply_chain_memberships"][0]["segment_name_zh"] == "材料"


def test_catalog_lists_every_supply_chain_with_stage_counts() -> None:
    payload = {
        "generated_at": "2026-08-08T00:00:00Z",
        "industries": [
            {
                "source_tag_id": "123",
                "source_url": "https://statementdog.com/tags/123",
                "name_zh": "測試產業",
                "taiwan_symbol_count": 2,
                "segments": [
                    {"stage": "上游"},
                    {"stage": "中游"},
                    {"stage": "中游"},
                    {"stage": "下游"},
                ],
            }
        ],
    }
    catalog = build_catalog_markdown(payload)
    assert "[123](https://statementdog.com/tags/123)" in catalog
    assert "| 測試產業 | 1 | 2 | 1 | 2 |" in catalog


def test_checked_in_industry_and_symbol_snapshots_are_complete_and_joinable() -> None:
    industry_path = ROOT / "config" / "industry_supply_chains.tw.json"
    symbol_path = ROOT / "config" / "symbol_registry.tw.json"
    catalog_path = ROOT / "docs" / "INDUSTRY_SUPPLY_CHAIN_CATALOG.md"
    if not industry_path.exists() or not symbol_path.exists() or not catalog_path.exists():
        pytest.skip("generated industry snapshots have not been built yet")
    industries = json.loads(industry_path.read_text(encoding="utf-8"))
    symbols = json.loads(symbol_path.read_text(encoding="utf-8"))

    validate_snapshots(industries, symbols)
    assert industries["source"]["failed_page_count"] == 0
    assert industries["source"]["tag_pages_discovered"] >= 1_900
    assert industries["industry_count"] == len(industries["industries"])
    assert symbols["official_symbol_count"] == len(symbols["symbols"])
    assert symbols["official_symbol_count"] >= 2_300
    assert symbols["supply_chain_mapped_symbol_count"] >= 700
    assert catalog_path.read_text(encoding="utf-8").count("statementdog.com/tags/") == industries["industry_count"]
