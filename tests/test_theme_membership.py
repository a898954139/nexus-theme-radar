"""Theme membership hygiene: years are not stock codes, multi-topic articles
do not leak one theme's seed stocks into another, and curated themes absorb
their same-industry source tags."""

from __future__ import annotations

from scripts import update_theme_radar as updater
from scripts.symbol_mapping import extract_direct_symbols
from scripts.theme_relevance import load_theme_taxonomy

ALIASES = {
    "market_id": "TW_EQUITY",
    "symbols": {
        "2027": {"exchange": "TWSE", "name_zh": "大成鋼", "aliases": ["大成鋼"]},
        "2344": {"exchange": "TWSE", "name_zh": "華邦電", "aliases": ["華邦電"]},
    },
}


def _codes(text: str) -> list[str]:
    return [item["symbol"] for item in extract_direct_symbols({"title_zh": text}, ALIASES)]


def test_a_year_in_the_headline_is_not_a_stock_code() -> None:
    assert _codes("CSP 下修訂單，2027 年 NAND Flash 價格") == []
    assert _codes("台廠人形機器人零組件2027拚送樣驗證") == []


def test_a_bracketed_or_named_code_in_the_year_range_still_counts() -> None:
    assert _codes("大成鋼(2027)營收創高") == ["2027"]
    assert _codes("鋼價回升（2027）") == ["2027"]
    assert _codes("大成鋼 2027 受惠") == ["2027"]
    assert _codes("華邦電 2344 漲停") == ["2344"]


def _seed(symbol: str, theme_id: str) -> dict[str, str]:
    return {"instrument_id": f"TWSE:{symbol}", "symbol": symbol, "evidence": f"taxonomy seed: {theme_id}"}


def test_unrelated_theme_seeds_from_a_multi_topic_article_are_dropped() -> None:
    taxonomy = {"themes": [
        {"theme_id": "memory", "seed_symbols": ["2344", "2408", "8299"]},
        {"theme_id": "ssd", "seed_symbols": ["2344", "2408", "8299", "3260"]},
        {"theme_id": "robot", "seed_symbols": ["2049", "4576"]},
    ]}
    family = updater._theme_family(taxonomy)
    assert family["memory"] == {"memory", "ssd"}
    symbols = [
        _seed("2344", "memory"),
        _seed("3260", "ssd"),
        _seed("2049", "robot"),
        {"instrument_id": "TWSE:2330", "symbol": "2330", "evidence": "title_zh: 台積電"},
    ]
    kept = updater._theme_related_symbols(symbols, "memory", family)
    assert [item["symbol"] for item in kept] == ["2344", "3260", "2330"]


def test_enrich_momentum_latest_filters_only_when_given_a_taxonomy() -> None:
    momentum = {"themes": [{"theme_id": "memory", "rank": 1}]}
    candidate = {
        "id": "a", "primary_theme_id": "memory", "matched_theme_ids": ["memory", "robot"],
        "direct_symbols": [], "related_symbols": [_seed("2344", "memory"), _seed("2049", "robot")],
    }
    taxonomy = {"themes": [
        {"theme_id": "memory", "seed_symbols": ["2344"]},
        {"theme_id": "robot", "seed_symbols": ["2049"]},
    ]}
    without = updater.enrich_momentum_latest(momentum, [candidate])
    with_taxonomy = updater.enrich_momentum_latest(momentum, [candidate], taxonomy)
    if without["themes"][0]["related_symbols"]:
        assert {item["symbol"] for item in without["themes"][0]["related_symbols"]} == {"2344", "2049"}
        assert [item["symbol"] for item in with_taxonomy["themes"][0]["related_symbols"]] == ["2344"]


def test_curated_themes_absorb_their_named_source_tags() -> None:
    themes = {theme["theme_id"]: theme for theme in load_theme_taxonomy()["themes"]}
    memory = themes["memory_hbm"]
    assert {"2337", "3260", "6239"} <= set(memory["seed_symbols"])
    assert {"187", "243"} <= set(memory.get("source_tag_ids", []))
    assert "statementdog_tag_187" not in themes and "statementdog_tag_243" not in themes
    assert "2383" in themes["pcb_abf_hdi"]["seed_symbols"]
    assert "2330" not in themes["pcb_abf_hdi"]["seed_symbols"]


SHIP_ALIASES = {
    "market_id": "TW_EQUITY",
    "symbols": {
        code: {"exchange": "TWSE", "name_zh": name, "aliases": [name]}
        for code, name in {
            "2603": "長榮", "2609": "陽明", "2615": "萬海",
            "2637": "慧洋-KY", "2606": "裕民", "2618": "長榮航",
        }.items()
    },
}


def test_a_ranked_theme_with_no_named_stock_falls_back_to_its_seeds() -> None:
    """2026-11-23: 11 of 20 ranked themes published zero stocks (航空, 光電 ...),
    so they never reached the stock radar. They now carry their own seeds,
    round-robin across supply-chain stages, while a theme whose news did
    name stocks keeps exactly those."""
    taxonomy = {"themes": [
        {
            "theme_id": "shipping",
            "seed_symbols": ["2603", "2609", "2615", "2637", "2606", "2618"],
            "supply_chain": [
                {"stage": "中游", "industry": "貨櫃", "symbols": ["2603", "2609", "2615"]},
                {"stage": "中游", "industry": "散裝", "symbols": ["2637", "2606", "9999"]},
                {"stage": "下游", "industry": "航空貨運", "symbols": ["2618"]},
            ],
        },
        {"theme_id": "memory", "seed_symbols": ["2344"]},
    ]}
    momentum = {"themes": [{"theme_id": "shipping", "rank": 1}, {"theme_id": "memory", "rank": 2}]}
    candidate = {
        "id": "a", "primary_theme_id": "memory",
        "direct_symbols": [], "related_symbols": [_seed("2344", "memory")],
    }
    payload = updater.enrich_momentum_latest(momentum, [candidate], taxonomy, SHIP_ALIASES)
    shipping, memory = payload["themes"]
    assert [item["symbol"] for item in shipping["related_symbols"]] == [
        "2603", "2637", "2618", "2609", "2606", "2615",
    ]
    assert all(item["evidence"] == "taxonomy seed: shipping" for item in shipping["related_symbols"])
    assert shipping["related_symbols"][0]["instrument_id"] == "TWSE:2603"
    assert [item["symbol"] for item in memory["related_symbols"]] == ["2344"]
    # Without aliases there is nothing to resolve seeds against: no fallback.
    bare = updater.enrich_momentum_latest(momentum, [candidate], taxonomy)
    assert bare["themes"][0]["related_symbols"] == []


def test_shipping_news_maps_to_the_shipping_theme_and_its_stocks() -> None:
    themes = {theme["theme_id"]: theme for theme in load_theme_taxonomy()["themes"]}
    shipping = themes["shipping"]
    assert {"2603", "2609", "2615"} <= set(shipping["seed_symbols"])
    from scripts.theme_relevance import score_theme_relevance

    taxonomy = load_theme_taxonomy()
    for title in ("三利多撐運價 法人按讚長榮", "〈航運指數〉SCFI連3跌反映傳統淡季"):
        matched = score_theme_relevance({"title_zh": title}, taxonomy)["matched_themes"]
        assert "shipping" in {match["theme_id"] for match in matched}, title


# M026 (2026-11-23): ~120 headlines about 黃仁勳 leaving and returning as
# NVIDIA CEO were ingested over two days, but the matcher only knew sector
# words (AI 伺服器, CoWoS ...), so "黃仁勳回鍋輝達執行長" matched no theme and
# was dropped before the TW-relevance step. These are real titles from that day.
NVIDIA_HEADLINES = (
    "黃仁勳回鍋輝達執行長！董事會一致通過即刻生效",
    "川普喊話找回黃仁勳！輝達盤前飆逾7% 能終結7連跌？",
    "漲停宴變股災週！黃仁勳下台全球股市崩",
    "NVIDIA代理CEO走鋼索　能保住AI引擎、放下融資循環包袱？",
)


def test_nvidia_and_jensen_huang_news_reaches_the_tw_supply_chain() -> None:
    from scripts.theme_relevance import enrich_item_with_themes

    taxonomy = load_theme_taxonomy()
    chain = {theme["theme_id"]: theme for theme in taxonomy["themes"]}["nvidia_supply_chain"]
    assert {"2330", "2317", "2382", "3231", "6669"} <= set(chain["seed_symbols"])
    for title in NVIDIA_HEADLINES:
        item = enrich_item_with_themes({"title_zh": title}, taxonomy)
        assert "nvidia_supply_chain" in {m["theme_id"] for m in item["matched_themes"]}, title
        assert item["theme_score"] >= updater.SELECTED_THEME_SCORE_MIN, title
        assert item["decision"] == "track_watch", title
    # Naming both the person and the company is a tracking candidate on its own.
    item = enrich_item_with_themes({"title_zh": NVIDIA_HEADLINES[0]}, taxonomy)
    assert item["theme_score"] >= updater.CANDIDATE_THEME_SCORE_MIN
