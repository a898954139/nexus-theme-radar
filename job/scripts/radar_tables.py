"""Map published pipeline payloads to normalized rows of the `radar` schema.

Target architecture (2026-11-19): every dataset the site shows lives in typed
relational tables and the site reads it only through the Vercel API
(api/v1/[dataset].js). This module is the single place that decides how a
payload becomes rows; scripts/radar_publish.py writes them.

Each ``map_*`` function is pure (payload in, rows out) so it can be tested
without a database, and validates as it goes: a payload that does not fit the
tables raises ``ValueError`` before any transaction opens.

Two shapes come out:

* ``Snapshot``: one header row (keyed by its unique ``generated_at``) plus
  child tables. Child rows never carry ``snapshot_id``; the writer prepends it.
* ``Series``: rows upserted by natural key (institutional flow per day).

Both may carry dimension rows (instruments, brokers) that are upserted first so
the foreign keys hold.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_EXCHANGE = re.compile(r"^[A-Z]{2,8}$")
_SYMBOL = re.compile(r"^[A-Za-z0-9]{1,10}$")


@dataclass
class ChildTable:
    table: str
    columns: tuple[str, ...]
    rows: list[tuple[Any, ...]] = field(default_factory=list)


@dataclass
class Snapshot:
    dataset: str
    header_table: str
    header: dict[str, Any]
    children: list[ChildTable]
    instruments: dict[str, dict[str, Any]] = field(default_factory=dict)
    brokers: dict[str, str] = field(default_factory=dict)

    @property
    def generated_at(self) -> str:
        return str(self.header["generated_at"])

    def row_count(self) -> int:
        return sum(len(child.rows) for child in self.children)


@dataclass
class Series:
    dataset: str
    table: str
    key_columns: tuple[str, ...]
    columns: tuple[str, ...]
    rows: list[tuple[Any, ...]]
    instruments: dict[str, dict[str, Any]] = field(default_factory=dict)

    def row_count(self) -> int:
        return len(self.rows)


@dataclass
class Versioned:
    """One current row per key (header) plus children stamped with its version.

    The header is upserted; children are inserted with the header's version
    column and never updated, and rows of superseded versions are removed by
    radar.purge_snapshots() (radar.versioned_child).
    """

    dataset: str
    header_table: str
    key_column: str
    version_column: str
    headers: list[dict[str, Any]]
    children: list[ChildTable]
    instruments: dict[str, dict[str, Any]] = field(default_factory=dict)

    def row_count(self) -> int:
        return len(self.headers) + sum(len(child.rows) for child in self.children)


# ------------------------------------------------------------------ helpers


def _require(mapping: Mapping[str, Any], key: str, label: str) -> Any:
    if key not in mapping:
        raise ValueError(f"{label}: missing {key!r}")
    return mapping[key]


def _str(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}: expected non-empty string, got {value!r}")
    return value


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}: expected number, got {value!r}")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{label}: expected integer, got {value!r}")
    return int(value)


def _opt_int(value: Any, label: str) -> int | None:
    return None if value is None else _int(value, label)


def _num(value: Any, label: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}: expected number, got {value!r}")
    return value


def _opt_num(value: Any, label: str) -> float | int | None:
    return None if value is None else _num(value, label)


def _opt_bool(value: Any, label: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{label}: expected boolean, got {value!r}")
    return value


def _bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label}: expected boolean, got {value!r}")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label}: expected list")
    return value


def _dict(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label}: expected object")
    return value


def add_instrument(
    instruments: dict[str, dict[str, Any]],
    instrument_id: Any,
    name: Any = None,
    *,
    is_etf: bool | None = None,
    label: str = "instrument",
) -> str:
    """Register a TWSE/TPEX instrument dimension row and return its id."""

    iid = _str(instrument_id, label)
    exchange, sep, symbol = iid.partition(":")
    if not sep or not _EXCHANGE.match(exchange) or not _SYMBOL.match(symbol):
        raise ValueError(f"{label}: bad instrument_id {iid!r}")
    row = instruments.setdefault(
        iid, {"instrument_id": iid, "symbol": symbol, "exchange": exchange, "name_zh": "", "is_etf": None}
    )
    if isinstance(name, str) and name.strip():
        row["name_zh"] = name.strip()
    if is_etf is not None:
        row["is_etf"] = bool(is_etf)
    return iid


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


# ------------------------------------------------- institutional rankings

RANKING_ENTRY_COLUMNS = (
    "board_key", "position", "instrument_id", "in_universe", "ratio_out_of_range",
    "three_inst_ratio", "change", "rank", "foreign_net", "trust_net", "dealer_net",
    "total_net", "days",
)


def map_institutional_rankings(payload: Mapping[str, Any]) -> Snapshot:
    label = "institutional-rankings"
    generated_at = _str(_require(payload, "generated_at", label), f"{label}.generated_at")
    rankings = _dict(_require(payload, "rankings", label), f"{label}.rankings")
    instruments: dict[str, dict[str, Any]] = {}
    boards = ChildTable(
        "institutional_ranking_board",
        ("board_key", "metric", "window_days", "side", "unit", "updated_at", "date_start",
         "date_end", "source", "source_rows"),
    )
    entries = ChildTable("institutional_ranking_entry", RANKING_ENTRY_COLUMNS)
    for board_key, board in rankings.items():
        blabel = f"{label}.{board_key}"
        board = _dict(board, blabel)
        date_range = board.get("date_range")
        if date_range is not None:
            date_range = _dict(date_range, f"{blabel}.date_range")
        boards.rows.append((
            _str(board_key, blabel),
            _str(_require(board, "metric", blabel), f"{blabel}.metric"),
            _int(_require(board, "window", blabel), f"{blabel}.window"),
            _str(_require(board, "side", blabel), f"{blabel}.side"),
            _opt_str(board.get("unit")),
            _opt_str(board.get("updated")),
            None if date_range is None else _str(date_range.get("start"), f"{blabel}.start"),
            None if date_range is None else _str(date_range.get("end"), f"{blabel}.end"),
            _opt_str(board.get("source")),
            _opt_int(board.get("source_rows"), f"{blabel}.source_rows"),
        ))
        for position, entry in enumerate(_list(_require(board, "entries", blabel), blabel)):
            elabel = f"{blabel}[{position}]"
            entry = _dict(entry, elabel)
            iid = add_instrument(
                instruments, _require(entry, "instrument_id", elabel), entry.get("name"),
                is_etf=_bool(_require(entry, "is_etf", elabel), f"{elabel}.is_etf"), label=elabel,
            )
            if entry.get("code") != iid.partition(":")[2] or entry.get("exchange") != iid.partition(":")[0]:
                raise ValueError(f"{elabel}: code/exchange disagree with instrument_id")
            entries.rows.append((
                board_key, position, iid,
                _bool(_require(entry, "in_universe", elabel), f"{elabel}.in_universe"),
                _opt_bool(entry.get("ratio_out_of_range"), f"{elabel}.ratio_out_of_range"),
                _opt_num(entry.get("three_inst_ratio"), f"{elabel}.three_inst_ratio"),
                _opt_num(entry.get("change"), f"{elabel}.change"),
                _opt_int(entry.get("rank"), f"{elabel}.rank"),
                _opt_int(entry.get("foreign"), f"{elabel}.foreign"),
                _opt_int(entry.get("trust"), f"{elabel}.trust"),
                _opt_int(entry.get("dealer"), f"{elabel}.dealer"),
                _opt_int(entry.get("total"), f"{elabel}.total"),
                _opt_int(entry.get("days"), f"{elabel}.days"),
            ))
    return Snapshot(
        dataset="institutional-rankings",
        header_table="institutional_ranking_snapshot",
        header={"generated_at": generated_at, "source": _opt_str(payload.get("source"))},
        children=[boards, entries],
        instruments=instruments,
    )


# ------------------------------------------------- institutional flows

FLOW_FIELDS = ("date", "foreign_net", "trust_net", "dealer_net", "total_net")
FLOW_SOURCE = "TWSE T86 / TPEX dailyTrade (official)"


def map_institutional_flows(flow_files: Iterable[Mapping[str, Any]], *, source: str = FLOW_SOURCE) -> Series:
    """Whole-market per-symbol daily flows (data/flows/<EXCHANGE>-<code>.json)."""

    instruments: dict[str, dict[str, Any]] = {}
    rows: dict[tuple[str, str], tuple[Any, ...]] = {}
    for document in flow_files:
        label = f"flows.{document.get('instrument_id')}"
        iid = add_instrument(instruments, _require(document, "instrument_id", label), document.get("name"), label=label)
        fields = tuple(_list(_require(document, "fields", label), label))
        if fields != FLOW_FIELDS:
            raise ValueError(f"{label}: unexpected field order {fields!r}")
        for point in _list(_require(document, "series", label), label):
            if not isinstance(point, list) or len(point) != len(FLOW_FIELDS):
                raise ValueError(f"{label}: malformed row {point!r}")
            trade_date = _str(point[0], f"{label}.date")
            rows[(iid, trade_date)] = (
                iid, trade_date,
                _int(point[1], f"{label}.foreign_net"),
                _int(point[2], f"{label}.trust_net"),
                _int(point[3], f"{label}.dealer_net"),
                _int(point[4], f"{label}.total_net"),
                source,
            )
    return Series(
        dataset="institutional-flows",
        table="institutional_flow",
        key_columns=("instrument_id", "trade_date"),
        columns=("instrument_id", "trade_date", "foreign_net", "trust_net", "dealer_net", "total_net", "source"),
        rows=list(rows.values()),
        instruments=instruments,
    )


def read_flow_files(data_dir: Path) -> list[dict[str, Any]]:
    directory = data_dir / "flows"
    if not directory.is_dir():
        return []
    return [load_json(path) for path in sorted(directory.glob("*.json")) if path.name != "index.json"]


# ------------------------------------------------------------- broker data


def map_broker(
    stats: Sequence[Mapping[str, Any]],
    coverage: Mapping[str, Any],
    map_index: Mapping[str, Any],
    map_files: Mapping[str, Sequence[Mapping[str, Any]]],
) -> Snapshot:
    """broker-stats.json + broker-coverage.json + broker-map/ as one snapshot.

    ``map_files`` maps each index entry's ``file`` name to its parsed branch
    list. A branch's ``stocks`` book repeats (minus the file's own symbol) in
    every symbol file it appears in; it is stored once per branch
    (broker_branch_stock).
    """

    label = "broker"
    generated_at = _str(_require(coverage, "generated_at", f"{label}.coverage"), f"{label}.generated_at")
    brokers: dict[str, str] = {}

    stat_rows = ChildTable("broker_stat", ("position", "broker_name", "buy", "sell", "day_trade", "overnight"))
    top_rows = ChildTable("broker_stat_top", ("stat_position", "position", "stock_code", "stock_name"))
    for position, stat in enumerate(stats):
        slabel = f"{label}.stats[{position}]"
        stat = _dict(stat, slabel)
        stat_rows.rows.append((
            position,
            _str(_require(stat, "name", slabel), f"{slabel}.name"),
            _int(_require(stat, "buy", slabel), f"{slabel}.buy"),
            _int(_require(stat, "sell", slabel), f"{slabel}.sell"),
            _opt_int(stat.get("dt"), f"{slabel}.dt"),
            _opt_int(stat.get("ov"), f"{slabel}.ov"),
        ))
        for top_position, pair in enumerate(_list(stat.get("top") or [], f"{slabel}.top")):
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError(f"{slabel}.top: malformed {pair!r}")
            top_rows.rows.append((position, top_position, str(pair[0]), str(pair[1])))

    codes = ChildTable("broker_coverage_code", ("kind", "stock_code"))
    for kind, key in (("failed", "failed_symbol_codes"), ("no_data", "no_data_symbol_codes"),
                      ("not_attempted", "not_attempted_symbol_codes")):
        for code in dict.fromkeys(_list(coverage.get(key) or [], f"{label}.{key}")):
            codes.rows.append((kind, str(code)))

    symbols = ChildTable("broker_symbol", ("stock_code", "stock_name", "broker_count", "buy", "sell", "net"))
    branches = ChildTable("broker_symbol_branch", ("stock_code", "position", "broker_id", "net", "ratio"))
    book_rows = ChildTable("broker_branch_stock", ("broker_id", "position", "stock_code", "stock_name", "net"))
    books: dict[str, dict[str, tuple[str, int]]] = {}
    index_symbols = _dict(map_index.get("symbols") or {}, f"{label}.map_index.symbols")
    for code, meta in index_symbols.items():
        mlabel = f"{label}.map[{code}]"
        meta = _dict(meta, mlabel)
        branch_list = map_files.get(str(meta.get("file")))
        if branch_list is None:
            continue
        summary = meta.get("summary")
        if summary is None:
            summary = {
                "buy": sum(max(int(b["net"]), 0) for b in branch_list),
                "sell": sum(max(-int(b["net"]), 0) for b in branch_list),
                "net": sum(int(b["net"]) for b in branch_list),
            }
        summary = _dict(summary, f"{mlabel}.summary")
        symbols.rows.append((
            str(code),
            str(meta.get("name") or ""),
            _int(meta.get("broker_count", len(branch_list)), f"{mlabel}.broker_count"),
            _int(_require(summary, "buy", mlabel), f"{mlabel}.buy"),
            _int(_require(summary, "sell", mlabel), f"{mlabel}.sell"),
            _int(_require(summary, "net", mlabel), f"{mlabel}.net"),
        ))
        for position, branch in enumerate(branch_list):
            blabel = f"{mlabel}[{position}]"
            branch = _dict(branch, blabel)
            broker_id = _str(_require(branch, "id", blabel), f"{blabel}.id")
            brokers[broker_id] = str(branch.get("name") or broker_id)
            branches.rows.append((
                str(code), position, broker_id,
                _int(_require(branch, "net", blabel), f"{blabel}.net"),
                _num(_require(branch, "ratio", blabel), f"{blabel}.ratio"),
            ))
            book = books.setdefault(broker_id, {})
            for item in _list(branch.get("stocks") or [], f"{blabel}.stocks"):
                if not isinstance(item, list) or len(item) != 3:
                    raise ValueError(f"{blabel}.stocks: malformed {item!r}")
                book[str(item[0])] = (str(item[1]), _int(item[2], f"{blabel}.stocks.net"))
    # Each symbol file carries the branch's book minus that symbol, so the
    # union over files is the whole book; the API drops the requested symbol.
    # Order matches scripts/broker_data.py: by |net| desc, then code.
    for broker_id, book in books.items():
        ordered = sorted(book.items(), key=lambda kv: (-abs(kv[1][1]), kv[0]))
        for stock_position, (stock_code, (stock_name, net)) in enumerate(ordered):
            book_rows.rows.append((broker_id, stock_position, stock_code, stock_name, net))

    header = {
        "generated_at": generated_at,
        "source": _str(_require(coverage, "source", label), f"{label}.source"),
        "source_scope": _opt_str(coverage.get("source_scope")),
        "source_updated": _opt_str(coverage.get("source_updated")),
        "map_source": _opt_str(map_index.get("source")),
        "unit": str(map_index.get("unit") or "lots"),
        "requested_symbols": _int(_require(coverage, "requested_symbols", label), "requested_symbols"),
        "attempted_symbols": _int(_require(coverage, "attempted_symbols", label), "attempted_symbols"),
        "failed_symbols": _int(_require(coverage, "failed_symbols", label), "failed_symbols"),
        "successful_symbols": _int(_require(coverage, "successful_symbols", label), "successful_symbols"),
        "symbols_with_data": _int(_require(coverage, "symbols_with_data", label), "symbols_with_data"),
        "attempt_coverage": _num(_require(coverage, "attempt_coverage", label), "attempt_coverage"),
        "data_coverage": _num(_require(coverage, "data_coverage", label), "data_coverage"),
        "data_coverage_denominator": _str(_require(coverage, "data_coverage_denominator", label), "denominator"),
        "status": _str(_require(coverage, "status", label), "status"),
    }
    # Parents before children: the writer COPYs in this order.
    return Snapshot(
        dataset="broker",
        header_table="broker_snapshot",
        header=header,
        children=[codes, stat_rows, top_rows, symbols, branches, book_rows],
        brokers=brokers,
    )


def read_broker_inputs(data_dir: Path) -> tuple[Any, Any, Any, dict[str, Any]] | None:
    stats_path = data_dir / "broker-stats.json"
    coverage_path = data_dir / "broker-coverage.json"
    index_path = data_dir / "broker-map" / "index.json"
    if not (stats_path.is_file() and coverage_path.is_file() and index_path.is_file()):
        return None
    index = load_json(index_path)
    files: dict[str, Any] = {}
    for meta in (index.get("symbols") or {}).values():
        name = str(meta.get("file") or "")
        path = data_dir / "broker-map" / name
        if name and "/" not in name and path.is_file():
            files[name] = load_json(path)
    return load_json(stats_path), load_json(coverage_path), index, files


# ------------------------------------------------------------- theme focus

FOCUS_STOCK_COLUMNS = (
    "theme_id", "role", "position", "instrument_id", "relation", "flow_as_of", "flow_days",
    "total_5d", "foreign_5d", "trust_5d", "total_1d", "streak", "short_rank", "short_score",
    "long_rank", "long_score",
)


def map_theme_focus(payload: Mapping[str, Any]) -> Snapshot:
    label = "theme-focus"
    method = _dict(_require(payload, "method", label), f"{label}.method")
    instruments: dict[str, dict[str, Any]] = {}
    themes = ChildTable(
        "theme_focus_theme",
        ("theme_id", "position", "name_zh", "rank", "focus_rank", "heat_score", "momentum_score",
         "lifecycle_stage", "event_count", "stance", "stance_label", "focus_score", "member_count",
         "covered_count", "positive_count", "breadth", "total_5d", "foreign_5d", "trust_5d",
         "total_1d", "headline_title", "headline_source", "headline_published_at", "headline_url",
         "has_headline"),
    )
    stocks = ChildTable("theme_focus_stock", FOCUS_STOCK_COLUMNS)
    for position, theme in enumerate(_list(_require(payload, "themes", label), label)):
        tlabel = f"{label}.themes[{position}]"
        theme = _dict(theme, tlabel)
        theme_id = _str(_require(theme, "theme_id", tlabel), f"{tlabel}.theme_id")
        flow = _dict(_require(theme, "flow", tlabel), f"{tlabel}.flow")
        headline = theme.get("headline")
        headline = _dict(headline, f"{tlabel}.headline") if headline is not None else None
        themes.rows.append((
            theme_id, position,
            _str(_require(theme, "name_zh", tlabel), f"{tlabel}.name_zh"),
            _opt_int(theme.get("rank"), f"{tlabel}.rank"),
            _int(_require(theme, "focus_rank", tlabel), f"{tlabel}.focus_rank"),
            _num(_require(theme, "heat_score", tlabel), f"{tlabel}.heat_score"),
            _opt_num(theme.get("momentum_score"), f"{tlabel}.momentum_score"),
            _opt_str(theme.get("lifecycle_stage")),
            _opt_int(theme.get("event_count"), f"{tlabel}.event_count"),
            _str(_require(theme, "stance", tlabel), f"{tlabel}.stance"),
            _str(_require(theme, "stance_label", tlabel), f"{tlabel}.stance_label"),
            _num(_require(theme, "focus_score", tlabel), f"{tlabel}.focus_score"),
            _int(_require(flow, "member_count", tlabel), "member_count"),
            _int(_require(flow, "covered_count", tlabel), "covered_count"),
            _int(_require(flow, "positive_count", tlabel), "positive_count"),
            _opt_num(flow.get("breadth"), "breadth"),
            _int(_require(flow, "total_5d", tlabel), "total_5d"),
            _int(_require(flow, "foreign_5d", tlabel), "foreign_5d"),
            _int(_require(flow, "trust_5d", tlabel), "trust_5d"),
            _int(_require(flow, "total_1d", tlabel), "total_1d"),
            None if headline is None else _opt_str(headline.get("title")),
            None if headline is None else _opt_str(headline.get("source")),
            None if headline is None else _opt_str(headline.get("published_at")),
            None if headline is None else _opt_str(headline.get("url")),
            headline is not None,
        ))
        for role, key in (("leader", "leaders"), ("outflow", "outflows")):
            for stock_position, stock in enumerate(_list(theme.get(key) or [], f"{tlabel}.{key}")):
                slabel = f"{tlabel}.{key}[{stock_position}]"
                stock = _dict(stock, slabel)
                iid = add_instrument(instruments, _require(stock, "instrument_id", slabel), stock.get("name_zh"), label=slabel)
                sflow = stock.get("flow")
                sflow = _dict(sflow, f"{slabel}.flow") if sflow is not None else None
                if sflow is not None and not sflow.get("as_of"):
                    raise ValueError(f"{slabel}.flow: as_of is required")
                stocks.rows.append((
                    theme_id, role, stock_position, iid,
                    _str(_require(stock, "relation", slabel), f"{slabel}.relation"),
                    None if sflow is None else str(sflow["as_of"]),
                    None if sflow is None else _int(_require(sflow, "days", slabel), "days"),
                    None if sflow is None else _int(_require(sflow, "total_5d", slabel), "total_5d"),
                    None if sflow is None else _int(_require(sflow, "foreign_5d", slabel), "foreign_5d"),
                    None if sflow is None else _int(_require(sflow, "trust_5d", slabel), "trust_5d"),
                    None if sflow is None else _int(_require(sflow, "total_1d", slabel), "total_1d"),
                    None if sflow is None else _int(_require(sflow, "streak", slabel), "streak"),
                    _opt_int(stock.get("short_rank"), f"{slabel}.short_rank"),
                    _opt_num(stock.get("short_score"), f"{slabel}.short_score"),
                    _opt_int(stock.get("long_rank"), f"{slabel}.long_rank"),
                    _opt_num(stock.get("long_score"), f"{slabel}.long_score"),
                ))
    header = {
        "generated_at": _str(_require(payload, "generated_at", label), f"{label}.generated_at"),
        "schema_version": _str(_require(payload, "schema_version", label), f"{label}.schema_version"),
        "theme_generated_at": _opt_str(payload.get("theme_generated_at")),
        "flow_as_of": _opt_str(payload.get("flow_as_of")),
        "flow_window_days": _int(_require(payload, "flow_window_days", label), "flow_window_days"),
        "unit": _str(_require(payload, "unit", label), "unit"),
        "flow_source": _str(_require(payload, "flow_source", label), "flow_source"),
        "method_focus_score": _str(_require(method, "focus_score", label), "method.focus_score"),
        "method_hot_heat": _num(_require(method, "hot_heat", label), "method.hot_heat"),
        "method_broad_breadth": _num(_require(method, "broad_breadth", label), "method.broad_breadth"),
        "method_weak_breadth": _num(_require(method, "weak_breadth", label), "method.weak_breadth"),
    }
    return Snapshot(
        dataset="theme-focus",
        header_table="theme_focus_snapshot",
        header=header,
        children=[themes, stocks],
        instruments=instruments,
    )


# ----------------------------------------------------------- source status


def map_source_status(payload: Mapping[str, Any]) -> Snapshot:
    label = "source-status"
    sites = ChildTable(
        "source_status_site",
        ("position", "source_id", "name", "source_class", "adapter", "fetch_method", "status", "items",
         "error", "trial", "not_modified", "runs_7d", "success_rate_7d", "elapsed_ms"),
    )
    for position, site in enumerate(_list(_require(payload, "sites", label), label)):
        slabel = f"{label}.sites[{position}]"
        site = _dict(site, slabel)
        sites.rows.append((
            position,
            _str(_require(site, "source_id", slabel), f"{slabel}.source_id"),
            _str(_require(site, "name", slabel), f"{slabel}.name"),
            _opt_str(site.get("source_class")),
            _opt_str(site.get("adapter")),
            _opt_str(site.get("fetch_method")),
            _str(_require(site, "status", slabel), f"{slabel}.status"),
            _opt_int(site.get("items"), f"{slabel}.items"),
            _opt_str(site.get("error")),
            _opt_bool(site.get("trial"), f"{slabel}.trial"),
            _opt_bool(site.get("not_modified"), f"{slabel}.not_modified"),
            _opt_int(site.get("runs_7d"), f"{slabel}.runs_7d"),
            _opt_num(site.get("success_rate_7d"), f"{slabel}.success_rate_7d"),
            _opt_int(site.get("elapsed_ms"), f"{slabel}.elapsed_ms"),
        ))
    header = {
        "generated_at": _str(_require(payload, "generated_at", label), f"{label}.generated_at"),
        "fetched_raw_items": _opt_int(payload.get("fetched_raw_items"), "fetched_raw_items"),
        "items_before_topic_filter": _opt_int(payload.get("items_before_topic_filter"), "items_before_topic_filter"),
        "successful_sites": _int(_require(payload, "successful_sites", label), "successful_sites"),
        "failed_count": _int(_require(payload, "failed_count", label), "failed_count"),
    }
    return Snapshot(
        dataset="source-status",
        header_table="source_status_snapshot",
        header=header,
        children=[sites],
    )


# ------------------------------------------------------------ theme events


def _news_columns(news: Any, label: str, *, with_cluster: bool) -> tuple[Any, ...]:
    if news is None:
        return (None,) * (8 if with_cluster else 7)
    news = _dict(news, label)
    cols = (
        _str(_require(news, "id", label), f"{label}.id"),
        *((_opt_str(news.get("cluster_id")),) if with_cluster else ()),
        _opt_str(news.get("title_zh")),
        _opt_str(news.get("summary")),
        _opt_str(news.get("source_id")),
        _opt_str(news.get("source")),
        _opt_str(news.get("published_at")),
        _opt_str(news.get("canonical_url")),
    )
    return cols


def map_theme_events(payload: Mapping[str, Any]) -> Snapshot:
    label = "theme-events"
    instruments: dict[str, dict[str, Any]] = {}
    items = ChildTable(
        "theme_event_item",
        ("position", "article_id", "cluster_id", "title_zh", "summary", "source", "source_id", "source_class",
         "published_at", "url", "extraction_method", "fetched_at", "primary_theme_id", "theme_score", "decision",
         "tw_relevance_status", "tw_relevance_reason", "confirmation_status", "cluster_size",
         "official_evidence_count"),
    )
    themes = ChildTable("theme_event_theme", ("event_position", "position", "theme_id", "name_zh", "score", "reason"))
    symbols = ChildTable("theme_event_symbol", ("event_position", "role", "position", "instrument_id", "evidence", "reason"))
    sources = ChildTable("theme_event_source", ("event_position", "position", "source_id", "source", "title", "url", "published_at"))
    for position, item in enumerate(_list(_require(payload, "items", label), label)):
        ilabel = f"{label}.items[{position}]"
        item = _dict(item, ilabel)
        items.rows.append((
            position,
            _str(_require(item, "id", ilabel), f"{ilabel}.id"),
            _opt_str(item.get("cluster_id")),
            str(_require(item, "title_zh", ilabel)),
            str(item.get("summary") or ""),
            str(_require(item, "source", ilabel)),
            _str(_require(item, "source_id", ilabel), f"{ilabel}.source_id"),
            _opt_str(item.get("source_class")),
            _str(_require(item, "published_at", ilabel), f"{ilabel}.published_at"),
            _opt_str(item.get("url")),
            _opt_str(item.get("extraction_method")),
            _opt_str(item.get("fetched_at")),
            _opt_str(item.get("primary_theme_id")),
            _opt_num(item.get("theme_score"), f"{ilabel}.theme_score"),
            _opt_str(item.get("decision")),
            _opt_str(item.get("tw_relevance_status")),
            _opt_str(item.get("tw_relevance_reason")),
            _opt_str(item.get("confirmation_status")),
            _opt_int(item.get("cluster_size"), f"{ilabel}.cluster_size"),
            _opt_int(item.get("official_evidence_count"), f"{ilabel}.official_evidence_count"),
        ))
        for tpos, theme in enumerate(_list(item.get("matched_themes") or [], f"{ilabel}.matched_themes")):
            theme = _dict(theme, f"{ilabel}.matched_themes[{tpos}]")
            themes.rows.append((
                position, tpos,
                _str(_require(theme, "theme_id", ilabel), f"{ilabel}.theme_id"),
                str(theme.get("name_zh") or ""),
                _opt_num(theme.get("score"), f"{ilabel}.score"),
                _opt_str(theme.get("reason")),
            ))
        for role, key in (("direct", "direct_symbols"), ("related", "related_symbols")):
            for spos, sym in enumerate(_list(item.get(key) or [], f"{ilabel}.{key}")):
                slabel = f"{ilabel}.{key}[{spos}]"
                sym = _dict(sym, slabel)
                iid = add_instrument(instruments, _require(sym, "instrument_id", slabel), sym.get("name_zh"), label=slabel)
                symbols.rows.append((position, role, spos, iid, _opt_str(sym.get("evidence")), _opt_str(sym.get("reason"))))
        for cpos, src in enumerate(_list(item.get("cluster_sources") or [], f"{ilabel}.cluster_sources")):
            src = _dict(src, f"{ilabel}.cluster_sources[{cpos}]")
            sources.rows.append((
                position, cpos,
                _str(_require(src, "source_id", ilabel), f"{ilabel}.cluster_source_id"),
                str(src.get("source") or ""),
                str(src.get("title") or ""),
                _opt_str(src.get("url")),
                _opt_str(src.get("published_at")),
            ))
    header = {
        "generated_at": _str(_require(payload, "generated_at", label), f"{label}.generated_at"),
        "market_id": _str(_require(payload, "market_id", label), "market_id"),
        "window_hours": _int(_require(payload, "window_hours", label), "window_hours"),
        "max_items": _opt_int(payload.get("max_items"), "max_items"),
        "total_items": _int(_require(payload, "total_items", label), "total_items"),
        "total_items_available": _opt_int(payload.get("total_items_available"), "total_items_available"),
        "taxonomy_version": _opt_str(payload.get("taxonomy_version")),
    }
    return Snapshot(
        dataset="theme-events",
        header_table="theme_event_snapshot",
        header=header,
        children=[items, themes, symbols, sources],
        instruments=instruments,
    )


# ----------------------------------------------------------- theme ranking


def map_theme_ranking(payload: Mapping[str, Any]) -> Snapshot:
    label = "theme-ranking"
    instruments: dict[str, dict[str, Any]] = {}
    themes = ChildTable(
        "theme_ranking_theme",
        ("theme_id", "rank", "name_zh", "heat_score", "event_count", "source_count", "tracking_candidate_count",
         "taiwan_mapping_count", "news_id", "news_cluster_id", "news_title_zh", "news_summary", "news_source_id",
         "news_source", "news_published_at", "news_url"),
    )
    symbols = ChildTable(
        "theme_ranking_symbol",
        ("theme_id", "role", "position", "instrument_id", "direct_event_count", "official_evidence_count",
         "company_rank_score", "latest_mentioned_at", "latest_official_at"),
    )
    for tpos, theme in enumerate(_list(_require(payload, "themes", label), label)):
        tlabel = f"{label}.themes[{tpos}]"
        theme = _dict(theme, tlabel)
        theme_id = _str(_require(theme, "theme_id", tlabel), f"{tlabel}.theme_id")
        summaries = theme.get("summaries") or {}
        summaries = _dict(summaries, f"{tlabel}.summaries")
        themes.rows.append((
            theme_id,
            _int(_require(theme, "rank", tlabel), f"{tlabel}.rank"),
            _str(_require(theme, "name_zh", tlabel), f"{tlabel}.name_zh"),
            _num(_require(theme, "heat_score", tlabel), f"{tlabel}.heat_score"),
            _opt_int(summaries.get("event_count"), "event_count"),
            _opt_int(summaries.get("source_count"), "source_count"),
            _opt_int(summaries.get("tracking_candidate_count"), "tracking_candidate_count"),
            _opt_int(summaries.get("taiwan_mapping_count"), "taiwan_mapping_count"),
            *_news_columns(theme.get("representative_news"), f"{tlabel}.representative_news", with_cluster=True),
        ))
        for role, key in (("direct", "direct_mentions"), ("supply_chain", "supply_chain_candidates")):
            for spos, sym in enumerate(_list(theme.get(key) or [], f"{tlabel}.{key}")):
                slabel = f"{tlabel}.{key}[{spos}]"
                sym = _dict(sym, slabel)
                iid = add_instrument(instruments, _require(sym, "instrument_id", slabel), sym.get("name_zh"), label=slabel)
                symbols.rows.append((
                    theme_id, role, spos, iid,
                    _opt_int(sym.get("direct_event_count"), f"{slabel}.direct_event_count"),
                    _opt_int(sym.get("official_evidence_count"), f"{slabel}.official_evidence_count"),
                    _opt_num(sym.get("company_rank_score"), f"{slabel}.company_rank_score"),
                    _opt_str(sym.get("latest_mentioned_at")),
                    _opt_str(sym.get("latest_official_at")),
                ))
    header = {
        "generated_at": _str(_require(payload, "generated_at", label), f"{label}.generated_at"),
        "schema_version": _str(_require(payload, "schema_version", label), "schema_version"),
        "ranking_rule_version": _str(_require(payload, "ranking_rule_version", label), "ranking_rule_version"),
        "company_rule_version": _opt_str(payload.get("company_rule_version")),
        "market_id": _str(_require(payload, "market_id", label), "market_id"),
        "window_hours": _int(_require(payload, "window_hours", label), "window_hours"),
        "max_themes": _opt_int(payload.get("max_themes"), "max_themes"),
        "qualified_theme_count": _opt_int(payload.get("qualified_theme_count"), "qualified_theme_count"),
        "displayed_theme_count": _opt_int(payload.get("displayed_theme_count"), "displayed_theme_count"),
        "threshold_note": _opt_str(payload.get("threshold_note")),
        "generation_status": _opt_str(payload.get("generation_status")),
        "failed_source_count": _opt_int(payload.get("failed_source_count"), "failed_source_count"),
        "official_evidence_status": _opt_str(payload.get("official_evidence_status")),
    }
    return Snapshot(
        dataset="theme-ranking",
        header_table="theme_ranking_snapshot",
        header=header,
        children=[themes, symbols],
        instruments=instruments,
    )


# ----------------------------------------------------------- theme momentum

MOMENTUM_METRIC_KEYS = (
    "event_count", "source_count", "tracking_candidate_count", "taiwan_mapping_count",
    "direct_mapping_event_count",
)


def map_theme_momentum(payload: Mapping[str, Any]) -> Snapshot:
    label = "theme-momentum"
    instruments: dict[str, dict[str, Any]] = {}
    themes = ChildTable(
        "theme_momentum_theme",
        ("theme_id", "rank", "name_zh", "qualification_status", "near_threshold_reason", "momentum_score",
         "lifecycle_stage", "heat_score", "heat_change_24h", "source_change_24h", *MOMENTUM_METRIC_KEYS,
         "single_source_concentration", "latest_qualifying_event_at", "news_id", "news_title_zh", "news_summary",
         "news_source_id", "news_source", "news_published_at", "news_url"),
    )
    symbols = ChildTable("theme_momentum_symbol", ("theme_id", "role", "position", "instrument_id", "evidence", "reason"))
    for tpos, theme in enumerate(_list(_require(payload, "themes", label), label)):
        tlabel = f"{label}.themes[{tpos}]"
        theme = _dict(theme, tlabel)
        theme_id = _str(_require(theme, "theme_id", tlabel), f"{tlabel}.theme_id")
        themes.rows.append((
            theme_id,
            _int(_require(theme, "rank", tlabel), f"{tlabel}.rank"),
            _str(_require(theme, "name_zh", tlabel), f"{tlabel}.name_zh"),
            _str(_require(theme, "qualification_status", tlabel), "qualification_status"),
            _opt_str(theme.get("near_threshold_reason")),
            _num(_require(theme, "momentum_score", tlabel), "momentum_score"),
            _str(_require(theme, "lifecycle_stage", tlabel), "lifecycle_stage"),
            _num(_require(theme, "heat_score", tlabel), "heat_score"),
            _opt_num(theme.get("heat_change_24h"), "heat_change_24h"),
            _opt_num(theme.get("source_change_24h"), "source_change_24h"),
            *(_opt_int(theme.get(k), f"{tlabel}.{k}") for k in MOMENTUM_METRIC_KEYS),
            _opt_num(theme.get("single_source_concentration"), "single_source_concentration"),
            _opt_str(theme.get("latest_qualifying_event_at")),
            *_news_columns(theme.get("representative_news"), f"{tlabel}.representative_news", with_cluster=False),
        ))
        for role, key in (("direct", "direct_symbols"), ("related", "related_symbols")):
            for spos, sym in enumerate(_list(theme.get(key) or [], f"{tlabel}.{key}")):
                slabel = f"{tlabel}.{key}[{spos}]"
                sym = _dict(sym, slabel)
                iid = add_instrument(instruments, _require(sym, "instrument_id", slabel), sym.get("name_zh"), label=slabel)
                symbols.rows.append((theme_id, role, spos, iid, _opt_str(sym.get("evidence")), _opt_str(sym.get("reason"))))
    header = {
        "generated_at": _str(_require(payload, "generated_at", label), f"{label}.generated_at"),
        "observed_hour": _str(_require(payload, "observed_hour", label), "observed_hour"),
        "schema_version": _str(_require(payload, "schema_version", label), "schema_version"),
        "ranking_rule_version": _str(_require(payload, "ranking_rule_version", label), "ranking_rule_version"),
        "inclusion_rule_version": _opt_str(payload.get("inclusion_rule_version")),
        "heat_rule_version": _opt_str(payload.get("heat_rule_version")),
        "market_id": _str(_require(payload, "market_id", label), "market_id"),
        "window_hours": _int(_require(payload, "window_hours", label), "window_hours"),
        "freshness_status": _opt_str(payload.get("freshness_status")),
        "theme_count": _int(payload.get("theme_count", len(themes.rows)), "theme_count"),
    }
    return Snapshot(
        dataset="theme-momentum",
        header_table="theme_momentum_snapshot",
        header=header,
        children=[themes, symbols],
        instruments=instruments,
    )


HOURLY_COLUMNS = (
    "observed_hour", "theme_id", "rank", "qualification_status", "near_threshold_reason", "momentum_score",
    "lifecycle_stage", "heat_score", *MOMENTUM_METRIC_KEYS, "single_source_concentration",
    "latest_qualifying_event_at",
)


def map_theme_momentum_history(payload: Mapping[str, Any]) -> Series:
    label = "theme-momentum-history"
    rows: dict[tuple[str, str], tuple[Any, ...]] = {}
    for opos, observation in enumerate(_list(_require(payload, "observations", label), label)):
        olabel = f"{label}.observations[{opos}]"
        observation = _dict(observation, olabel)
        hour = _str(_require(observation, "observed_hour", olabel), f"{olabel}.observed_hour")
        for tpos, theme in enumerate(_list(_require(observation, "themes", olabel), olabel)):
            tlabel = f"{olabel}.themes[{tpos}]"
            theme = _dict(theme, tlabel)
            theme_id = _str(_require(theme, "theme_id", tlabel), f"{tlabel}.theme_id")
            rows[(hour, theme_id)] = (
                hour, theme_id,
                _int(_require(theme, "rank", tlabel), "rank"),
                _str(_require(theme, "qualification_status", tlabel), "qualification_status"),
                _opt_str(theme.get("near_threshold_reason")),
                _num(_require(theme, "momentum_score", tlabel), "momentum_score"),
                _str(_require(theme, "lifecycle_stage", tlabel), "lifecycle_stage"),
                _num(_require(theme, "heat_score", tlabel), "heat_score"),
                *(_opt_int(theme.get(k), f"{tlabel}.{k}") for k in MOMENTUM_METRIC_KEYS),
                _opt_num(theme.get("single_source_concentration"), "single_source_concentration"),
                _opt_str(theme.get("latest_qualifying_event_at")),
            )
    return Series(
        dataset="theme-momentum-history",
        table="theme_momentum_hourly",
        key_columns=("observed_hour", "theme_id"),
        columns=HOURLY_COLUMNS,
        rows=list(rows.values()),
    )


# --------------------------------------------------------- stock watchlist

WATCHLIST_SHORT_COMPONENTS = ("theme_attention", "institutional_short_activity", "daytrade_activity", "fundamental_defense")
WATCHLIST_LONG_COMPONENTS = ("fundamental_quality", "institutional_support", "theme_persistence", "trading_stability")
WATCHLIST_FUNDAMENTAL_KEYS = (
    "score", "fiscal_quarter", "comparison_basis", "revenue_growth", "revenue_direction", "eps_growth",
    "eps_direction", "gross_margin", "operating_margin", "operating_cash_flow", "operating_cash_flow_margin",
    "debt_ratio",
)


def map_stock_watchlist(payload: Mapping[str, Any]) -> Snapshot:
    label = "stock-watchlist"
    instruments: dict[str, dict[str, Any]] = {}
    sources = _dict(_require(payload, "sources", label), f"{label}.sources")
    methodology = _dict(_require(payload, "methodology", label), f"{label}.methodology")
    coverage = _dict(_require(payload, "coverage", label), f"{label}.coverage")
    momentum = _dict(_require(sources, "momentum", label), "sources.momentum")

    values = ChildTable("watchlist_header_value", ("kind", "position", "value"))
    for kind, seq in (
        ("institutional_as_of", _dict(sources["institutional"], "sources.institutional").get("as_of") or []),
        ("fundamentals_fiscal_quarter", _dict(sources["fundamentals"], "sources.fundamentals").get("fiscal_quarters") or []),
        ("coverage_metric", coverage.get("metrics") or []),
        ("coverage_missing_reason", coverage.get("missing_reasons") or []),
    ):
        for position, value in enumerate(_list(seq, f"{label}.{kind}")):
            values.rows.append((kind, position, str(value)))

    day = ChildTable("watchlist_day_trading_source",
                     ("market", "as_of", "finality", "numerator_url", "denominator_url", "status", "error"))
    for market, src in _dict(_require(sources, "day_trading_activity", label), "day_trading_activity").items():
        src = _dict(src, f"day_trading_activity.{market}")
        day.rows.append((market, _opt_str(src.get("as_of")), _opt_str(src.get("finality")),
                         _opt_str(src.get("numerator_url")), _opt_str(src.get("denominator_url")),
                         _str(_require(src, "status", market), "status"), _opt_str(src.get("error"))))

    weights = ChildTable("watchlist_weight", ("weight_set", "component", "position", "weight"))
    for weight_set, key in (("short", "short_weights"), ("long", "long_weights"),
                            ("fundamental_quality", "fundamental_quality_weights")):
        for position, (component, weight) in enumerate(_dict(_require(methodology, key, label), key).items()):
            weights.rows.append((weight_set, component, position, _num(weight, f"{key}.{component}")))

    members = ChildTable("watchlist_member", ("instrument_id", "position", "selected_top50", "short_rank", "long_rank"))
    member_themes = ChildTable("watchlist_member_theme",
                               ("instrument_id", "position", "theme_id", "name_zh", "relation", "heat_score",
                                "heat_change_24h", "momentum_score"))
    member_flags = ChildTable("watchlist_member_flag", ("instrument_id", "position", "flag_key", "flag_type"))
    for position, entry in enumerate(_list(_require(payload, "searchable", label), f"{label}.searchable")):
        elabel = f"{label}.searchable[{position}]"
        entry = _dict(entry, elabel)
        inst = _dict(_require(entry, "instrument", elabel), f"{elabel}.instrument")
        iid = add_instrument(instruments, inst.get("instrument_id"), inst.get("name_zh"), label=elabel)
        members.rows.append((iid, position, _bool(_require(entry, "selected_top50", elabel), "selected_top50"),
                             _opt_int(entry.get("short_rank"), "short_rank"), _opt_int(entry.get("long_rank"), "long_rank")))
        for tpos, theme in enumerate(_list(entry.get("themes") or [], f"{elabel}.themes")):
            theme = _dict(theme, f"{elabel}.themes[{tpos}]")
            member_themes.rows.append((iid, tpos, _str(theme.get("theme_id"), "theme_id"), str(theme.get("name_zh") or ""),
                                       _str(theme.get("relation"), "relation"), _opt_num(theme.get("heat_score"), "heat_score"),
                                       _opt_num(theme.get("heat_change_24h"), "heat_change_24h"),
                                       _opt_num(theme.get("momentum_score"), "momentum_score")))
        for fpos, flag in enumerate(_list(entry.get("flags") or [], f"{elabel}.flags")):
            flag = _dict(flag, f"{elabel}.flags[{fpos}]")
            member_flags.rows.append((iid, fpos, _str(flag.get("key"), "flag.key"), _str(flag.get("type"), "flag.type")))
    member_ids = {row[0] for row in members.rows}

    items = ChildTable(
        "watchlist_item",
        ("instrument_id", "short_rank", "short_score", "long_rank", "long_score", "overnight_value",
         "overnight_applied", "overnight_missing_reason", "institutional_direction", "institutional_as_of",
         "institutional_observation_count", "institutional_five_day_net", "trading_as_of", "day_trading_volume",
         "total_volume", "day_trading_volume_ratio", "overnight_risk", "overnight_missing_reason_trading",
         "fundamental_score", *WATCHLIST_FUNDAMENTAL_KEYS[1:], "coverage_short_ratio", "coverage_long_ratio"),
    )
    components = ChildTable("watchlist_item_component",
                            ("instrument_id", "horizon", "component", "raw", "normalized", "base_weight",
                             "effective_weight", "available"))
    missing = ChildTable("watchlist_item_missing", ("instrument_id", "position", "metric"))
    short_items = _list(_dict(_require(payload, "short", label), "short").get("items"), "short.items")
    long_items = _list(_dict(_require(payload, "long", label), "long").get("items"), "long.items")
    long_by_id = {item["instrument"]["instrument_id"]: item for item in long_items}
    if not set(long_by_id).issubset({item["instrument"]["instrument_id"] for item in short_items}):
        raise ValueError(f"{label}: long list holds names outside the short list")
    for position, item in enumerate(short_items):
        ilabel = f"{label}.short.items[{position}]"
        item = _dict(item, ilabel)
        iid = item["instrument"]["instrument_id"]
        if iid not in member_ids:
            raise ValueError(f"{ilabel}: {iid} missing from searchable")
        if iid in long_by_id and long_by_id[iid] != item:
            raise ValueError(f"{ilabel}: short and long copies of {iid} differ")
        if iid not in long_by_id and _dict(item["long"], f"{ilabel}.long").get("rank") is not None:
            raise ValueError(f"{ilabel}: {iid} is outside the long list but carries a long rank")
        short = _dict(item["short"], f"{ilabel}.short")
        long = _dict(item["long"], f"{ilabel}.long")
        risk = _dict(_dict(short["risk_adjustment"], "risk_adjustment")["overnight_risk_adjustment"], "overnight")
        inst = _dict(item["institutional"], "institutional")
        trade = _dict(item["trading_activity"], "trading_activity")
        fund = _dict(item["fundamentals"], "fundamentals")
        cov = _dict(item["coverage"], "coverage")
        items.rows.append((
            iid, _int(short["rank"], "short.rank"), _num(short["score"], "short.score"),
            None if iid not in long_by_id else _int(long["rank"], "long.rank"),
            _num(long["score"], "long.score"),
            _opt_num(risk.get("value"), "overnight.value"), _num(risk["applied"], "overnight.applied"),
            _opt_str(risk.get("missing_reason")),
            _str(inst["direction"], "institutional.direction"), _opt_str(inst.get("as_of")),
            _opt_int(inst.get("observation_count"), "observation_count"), _opt_num(inst.get("five_day_net"), "five_day_net"),
            _opt_str(trade.get("as_of")), _opt_num(trade.get("day_trading_volume"), "day_trading_volume"),
            _opt_num(trade.get("total_volume"), "total_volume"),
            _opt_num(trade.get("day_trading_volume_ratio"), "day_trading_volume_ratio"),
            _opt_num(trade.get("overnight_risk"), "overnight_risk"), _opt_str(trade.get("overnight_missing_reason")),
            _opt_num(fund.get("score"), "fundamentals.score"),
            *(_opt_str(fund.get(k)) if k in ("fiscal_quarter", "comparison_basis", "revenue_direction", "eps_direction")
              else _opt_num(fund.get(k), f"fundamentals.{k}") for k in WATCHLIST_FUNDAMENTAL_KEYS[1:]),
            _num(cov["short_ratio"], "short_ratio"), _num(cov["long_ratio"], "long_ratio"),
        ))
        for horizon, summary, names in (("short", short, WATCHLIST_SHORT_COMPONENTS), ("long", long, WATCHLIST_LONG_COMPONENTS)):
            comps = _dict(summary["components"], f"{ilabel}.{horizon}.components")
            if set(comps) != set(names):
                raise ValueError(f"{ilabel}.{horizon}: unexpected components {sorted(comps)}")
            for name in names:
                comp = _dict(comps[name], f"{ilabel}.{horizon}.{name}")
                components.rows.append((iid, horizon, name, _opt_num(comp.get("raw"), "raw"),
                                        _opt_num(comp.get("normalized"), "normalized"), _num(comp["base_weight"], "base_weight"),
                                        _num(comp["effective_weight"], "effective_weight"), _bool(comp["available"], "available")))
        for mpos, metric in enumerate(_list(cov.get("missing") or [], f"{ilabel}.coverage.missing")):
            missing.rows.append((iid, mpos, str(metric)))

    header = {
        "generated_at": _str(_require(payload, "generated_at", label), "generated_at"),
        "schema_version": _str(_require(payload, "schema_version", label), "schema_version"),
        "methodology_version": _str(_require(payload, "methodology_version", label), "methodology_version"),
        "candidate_as_of": _opt_str(payload.get("candidate_as_of")),
        "momentum_generated_at": _opt_str(momentum.get("generated_at")),
        "momentum_observed_hour": _opt_str(momentum.get("observed_hour")),
        "methodology_missing_values": str(methodology.get("missing_values") or ""),
        "methodology_top50": str(methodology.get("top50") or ""),
        "eligible_count": _int(_require(coverage, "eligible_count", label), "eligible_count"),
        "selected_count": _int(_require(coverage, "selected_count", label), "selected_count"),
    }
    return Snapshot(
        dataset="stock-watchlist",
        header_table="watchlist_snapshot",
        header=header,
        children=[values, day, weights, members, member_themes, member_flags, items, components, missing],
        instruments=instruments,
    )


# ---------------------------------------------------------- fundamentals

INCOME_COLUMNS = ("revenue", "cost_of_sales", "gross_profit", "selling_expense", "admin_expense", "rd_expense",
                  "expected_credit_loss", "operating_expense", "operating_income", "pretax_income", "net_income", "eps")
BALANCE_COLUMNS = ("cash", "receivables", "inventory", "current_assets", "total_assets", "current_liabilities",
                   "total_liabilities", "total_equity")
CASH_FLOW_COLUMNS = ("operating", "investing", "financing", "depreciation", "capex", "dividends_paid", "ending_cash")
QUARTER_COLUMNS = ("revenue", "gross_margin", "operating_margin", "net_margin", "eps")
STATEMENTS = (("income", "fundamental_income", INCOME_COLUMNS), ("balance", "fundamental_balance", BALANCE_COLUMNS),
              ("cash_flow", "fundamental_cash_flow", CASH_FLOW_COLUMNS))
_HEALTH_PERIOD = re.compile(r"^(net_income|operating_cash_flow)_(\d{4}Q[1-4])$")
_HEALTH_FIXED = ("cash", "current_ratio", "debt_ratio")


def map_fundamentals(documents: Mapping[str, Mapping[str, Any]]) -> Versioned:
    """data/fundamentals/<EXCHANGE>-<code>.json keyed by instrument_id."""

    instruments: dict[str, dict[str, Any]] = {}
    headers: list[dict[str, Any]] = []
    quarters = ChildTable("fundamental_quarter", ("instrument_id", "fetched_at", "period", "position", *QUARTER_COLUMNS))
    health = ChildTable("fundamental_health_period", ("instrument_id", "fetched_at", "period", "net_income", "operating_cash_flow"))
    statements = {name: ChildTable(table, ("instrument_id", "fetched_at", "period", *cols)) for name, table, cols in STATEMENTS}
    missing = ChildTable("fundamental_missing", ("instrument_id", "fetched_at", "position", "note"))
    for instrument_id, doc in sorted(documents.items()):
        label = f"fundamentals.{instrument_id}"
        doc = _dict(doc, label)
        iid = add_instrument(instruments, instrument_id, label=label)
        fetched_at = _str(_require(doc, "fetched_at", label), f"{label}.fetched_at")
        health_doc = _dict(doc.get("health") or {}, f"{label}.health")
        valuation = _dict(doc.get("valuation") or {}, f"{label}.valuation")
        per_period: dict[str, dict[str, Any]] = {}
        for key, value in health_doc.items():
            if key in _HEALTH_FIXED:
                continue
            match = _HEALTH_PERIOD.match(key)
            if not match:
                raise ValueError(f"{label}.health: unexpected key {key!r}")
            per_period.setdefault(match.group(2), {})[match.group(1)] = _num(value, f"{label}.health.{key}")
        unknown = set(valuation) - {"ttm_eps"}
        if unknown:
            raise ValueError(f"{label}.valuation: unexpected keys {sorted(unknown)}")
        headers.append({
            "instrument_id": iid, "fetched_at": fetched_at,
            "basis": _str(_require(doc, "basis", label), "basis"),
            "currency": _str(_require(doc, "currency", label), "currency"),
            "source": _str(_require(doc, "source", label), "source"),
            "fiscal_quarter": _str(_require(doc, "fiscal_quarter", label), "fiscal_quarter"),
            **{k: _opt_num(health_doc.get(k), f"{label}.health.{k}") for k in _HEALTH_FIXED},
            "ttm_eps": _opt_num(valuation.get("ttm_eps"), f"{label}.ttm_eps"),
        })
        for period, metrics in sorted(per_period.items()):
            health.rows.append((iid, fetched_at, period, metrics.get("net_income"), metrics.get("operating_cash_flow")))
        for position, quarter in enumerate(_list(doc.get("quarters") or [], f"{label}.quarters")):
            quarter = _dict(quarter, f"{label}.quarters[{position}]")
            unknown = set(quarter) - {"period", *QUARTER_COLUMNS}
            if unknown:
                raise ValueError(f"{label}.quarters: unexpected keys {sorted(unknown)}")
            quarters.rows.append((iid, fetched_at, _str(quarter.get("period"), "period"), position,
                                  *(_opt_num(quarter.get(c), f"{label}.quarters.{c}") for c in QUARTER_COLUMNS)))
        statement_doc = _dict(doc.get("statements") or {}, f"{label}.statements")
        for name, _table, cols in STATEMENTS:
            for period, row in _dict(statement_doc.get(name) or {}, f"{label}.{name}").items():
                row = _dict(row, f"{label}.{name}.{period}")
                unknown = set(row) - set(cols)
                if unknown:
                    raise ValueError(f"{label}.{name}.{period}: unexpected keys {sorted(unknown)}")
                statements[name].rows.append((iid, fetched_at, period, *(_opt_num(row.get(c), f"{label}.{name}.{c}") for c in cols)))
        for position, note in enumerate(_list(doc.get("missing") or [], f"{label}.missing")):
            missing.rows.append((iid, fetched_at, position, str(note)))
    return Versioned(
        dataset="fundamentals",
        header_table="fundamental_set",
        key_column="instrument_id",
        version_column="fetched_at",
        headers=headers,
        children=[quarters, health, *statements.values(), missing],
        instruments=instruments,
    )


def read_fundamentals(data_dir: Path) -> dict[str, Any]:
    directory = data_dir / "fundamentals"
    out: dict[str, Any] = {}
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        exchange, sep, code = path.stem.partition("-")
        if sep:
            out[f"{exchange}:{code}"] = load_json(path)
    return out


def _load_fundamentals(data_dir: Path):
    docs = read_fundamentals(data_dir)
    return map_fundamentals(docs) if docs else None


# ------------------------------------------------------------ pre-market


def map_pre_market(payload: Mapping[str, Any]) -> Snapshot:
    label = "pre-market"
    sources = ChildTable("pm_source", ("position", "name"))
    for position, name in enumerate(_list(_require(payload, "sources", label), "sources")):
        sources.rows.append((position, _str(name, "sources[]")))
    events = ChildTable(
        "pm_event",
        ("position", "event_id", "tier", "score", "act_label", "speaker", "published_at", "title_zh", "title_en",
         "channel", "path_label", "path_id", "url", "direction", "direction_reason", "horizon", "has_backtest",
         "bt_target", "bt_hit_rate", "bt_n", "bt_avg_signed_excess_t1", "bt_foreign_hit_rate_t1",
         "bt_avg_foreign_t1", "bt_window_start", "bt_window_end", "has_flow_after", "fa_target", "fa_base_date",
         "fa_foreign_t1", "fa_excess_t1"),
    )
    sectors_of = ChildTable("pm_event_sector", ("event_position", "position", "sector"))
    related = ChildTable("pm_event_related", ("event_position", "position", "title", "url"))
    impacts = ChildTable("pm_event_impact", ("event_position", "position", "sector", "direction"))
    known = {"id", "tier", "score", "actLabel", "speaker", "publishedAt", "titleZh", "titleEn", "channel",
             "pathLabel", "sectors", "url", "related", "pathId", "direction", "directionReason", "horizon",
             "impacts", "pathBacktest", "flowAfter"}
    for position, event in enumerate(_list(_require(payload, "events", label), "events")):
        elabel = f"{label}.events[{position}]"
        event = _dict(event, elabel)
        unknown = set(event) - known
        if unknown:
            raise ValueError(f"{elabel}: unexpected keys {sorted(unknown)}")
        bt = event.get("pathBacktest")
        bt = _dict(bt, f"{elabel}.pathBacktest") if bt is not None else None
        window = _list(bt.get("window") or [None, None], "window") if bt else [None, None]
        if bt is not None and len(window) != 2:
            raise ValueError(f"{elabel}.pathBacktest.window: expected [start, end]")
        fa = event.get("flowAfter")
        fa = _dict(fa, f"{elabel}.flowAfter") if fa is not None else None
        events.rows.append((
            position,
            _str(_require(event, "id", elabel), f"{elabel}.id"),
            _str(_require(event, "tier", elabel), "tier"),
            _num(_require(event, "score", elabel), "score"),
            _opt_str(event.get("actLabel")),
            _opt_str(event.get("speaker")),
            _str(_require(event, "publishedAt", elabel), "publishedAt"),
            str(_require(event, "titleZh", elabel)),
            _opt_str(event.get("titleEn")),
            _opt_str(event.get("channel")),
            _opt_str(event.get("pathLabel")),
            _opt_str(event.get("pathId")),
            _opt_str(event.get("url")),
            _opt_int(event.get("direction"), "direction"),
            _opt_str(event.get("directionReason")),
            _opt_str(event.get("horizon")),
            bt is not None,
            None if bt is None else _opt_str(bt.get("target")),
            None if bt is None else _opt_num(bt.get("hitRate"), "hitRate"),
            None if bt is None else _opt_int(bt.get("n"), "n"),
            None if bt is None else _opt_num(bt.get("avgSignedExcessT1"), "avgSignedExcessT1"),
            None if bt is None else _opt_num(bt.get("foreignHitRateT1"), "foreignHitRateT1"),
            None if bt is None else _opt_num(bt.get("avgForeignT1"), "avgForeignT1"),
            _opt_str(window[0]), _opt_str(window[1]),
            fa is not None,
            None if fa is None else _opt_str(fa.get("target")),
            None if fa is None else _opt_str(fa.get("baseDate")),
            None if fa is None else _opt_num(fa.get("foreignT1"), "foreignT1"),
            None if fa is None else _opt_num(fa.get("excessT1"), "excessT1"),
        ))
        if bt is not None and set(bt) - {"target", "hitRate", "n", "avgSignedExcessT1", "foreignHitRateT1", "avgForeignT1", "window"}:
            raise ValueError(f"{elabel}.pathBacktest: unexpected keys")
        if fa is not None and set(fa) - {"target", "baseDate", "foreignT1", "excessT1"}:
            raise ValueError(f"{elabel}.flowAfter: unexpected keys")
        for spos, sector in enumerate(_list(event.get("sectors") or [], f"{elabel}.sectors")):
            sectors_of.rows.append((position, spos, _str(sector, "sector")))
        for rpos, rel in enumerate(_list(event.get("related") or [], f"{elabel}.related")):
            rel = _dict(rel, f"{elabel}.related[{rpos}]")
            if set(rel) - {"title", "url"}:
                raise ValueError(f"{elabel}.related: unexpected keys")
            related.rows.append((position, rpos, str(rel.get("title") or ""), _opt_str(rel.get("url"))))
        for ipos, imp in enumerate(_list(event.get("impacts") or [], f"{elabel}.impacts")):
            imp = _dict(imp, f"{elabel}.impacts[{ipos}]")
            impacts.rows.append((position, ipos, _str(imp.get("sector"), "impact.sector"), _int(imp.get("direction"), "impact.direction")))

    pulse = ChildTable("pm_pulse", ("position", "pulse_id", "label", "value_text", "delta_text", "up"))
    points = ChildTable("pm_pulse_point", ("pulse_position", "position", "value"))
    for position, row in enumerate(_list(_require(payload, "pulse", label), "pulse")):
        row = _dict(row, f"{label}.pulse[{position}]")
        pulse.rows.append((position, _str(row.get("id"), "pulse.id"), str(row.get("label") or ""),
                           str(row.get("value") or ""), str(row.get("delta") or ""), _bool(row.get("up"), "pulse.up")))
        for ppos, value in enumerate(_list(row.get("series") or [], "pulse.series")):
            points.rows.append((position, ppos, _num(value, "pulse.series[]")))

    sectors = ChildTable("pm_sector", ("position", "name", "chg"))
    for position, row in enumerate(_list(_require(payload, "sectors", label), "sectors")):
        row = _dict(row, f"{label}.sectors[{position}]")
        sectors.rows.append((position, _str(row.get("name"), "sector.name"), _num(row.get("chg"), "sector.chg")))

    flows = _dict(_require(payload, "flows", label), "flows")
    panels = ChildTable("pm_flow_panel", ("position", "panel_id", "title", "unit"))
    entries = ChildTable("pm_flow_entry", ("panel_position", "side", "position", "rank", "name", "value"))
    for position, panel in enumerate(_list(flows.get("panels") or [], "flows.panels")):
        panel = _dict(panel, f"flows.panels[{position}]")
        panels.rows.append((position, _str(panel.get("id"), "panel.id"), str(panel.get("title") or ""), _opt_str(panel.get("unit"))))
        for side in ("buy", "sell"):
            for epos, entry in enumerate(_list(panel.get(side) or [], f"panel.{side}")):
                entry = _dict(entry, f"panel.{side}[{epos}]")
                entries.rows.append((position, side, epos, _int(entry.get("rank"), "rank"), str(entry.get("name") or ""),
                                     _num(entry.get("value"), "value")))

    market = payload.get("market")
    market = _dict(market, "market") if market is not None else None
    indicators = ChildTable("pm_indicator", ("position", "indicator_id", "label", "missing", "reason", "value", "change",
                                             "change_pct", "unit", "as_of", "session", "source"))
    news = lean = div = None
    if market is not None:
        for position, ind in enumerate(_list(market.get("indicators") or [], "market.indicators")):
            ind = _dict(ind, f"market.indicators[{position}]")
            indicators.rows.append((position, _str(ind.get("id"), "indicator.id"), str(ind.get("label") or ""),
                                    _bool(ind.get("missing"), "indicator.missing"), _opt_str(ind.get("reason")),
                                    _opt_num(ind.get("value"), "value"), _opt_num(ind.get("change"), "change"),
                                    _opt_num(ind.get("change_pct"), "change_pct"), _opt_str(ind.get("unit")),
                                    _opt_str(ind.get("as_of")), _opt_str(ind.get("session")), _opt_str(ind.get("source"))))
        news = market.get("news")
        news = _dict(news, "market.news") if news is not None else None
        lean = _dict(market.get("market") or {}, "market.market")
        div = market.get("divergence")
        div = _dict(div, "market.divergence") if div is not None else None
    header = {
        "generated_at": _str(_require(payload, "generated_at", label), "generated_at"),
        "schema_version": _int(_require(payload, "schema_version", label), "schema_version"),
        "window_hours": _int(_require(payload, "window_hours", label), "window_hours"),
        "direction_rule_version": _opt_str(payload.get("direction_rule_version")),
        "flows_as_of": _opt_str(flows.get("as_of")),
        "has_market": market is not None,
        "market_generated_at": None if market is None else _opt_str(market.get("generated_at")),
        "has_news": news is not None,
        "news_net": None if news is None else _opt_num(news.get("net"), "news.net"),
        "news_bull": None if news is None else _opt_int(news.get("bull"), "news.bull"),
        "news_bear": None if news is None else _opt_int(news.get("bear"), "news.bear"),
        "news_lean": None if news is None else _opt_str(news.get("lean")),
        "news_window_hours": None if news is None else _opt_int(news.get("window_hours"), "news.window_hours"),
        "market_lean": None if lean is None else _opt_str(lean.get("lean")),
        "market_avg_pct": None if lean is None else _opt_num(lean.get("avg_pct"), "avg_pct"),
        "market_basis": None if lean is None else _opt_str(lean.get("basis")),
        "has_divergence": div is not None,
        "divergence_message": None if div is None else _opt_str(div.get("message")),
        "divergence_news_lean": None if div is None else _opt_str(div.get("news_lean")),
        "divergence_market_lean": None if div is None else _opt_str(div.get("market_lean")),
        "has_sectors_as_of": market is not None and "sectors_as_of" in market,
        "sectors_as_of": None if market is None else _opt_str(market.get("sectors_as_of")),
    }
    return Snapshot(
        dataset="pre-market",
        header_table="pm_snapshot",
        header=header,
        children=[sources, events, sectors_of, related, impacts, pulse, points, sectors, panels, entries, indicators],
    )


# ------------------------------------------------------------ stock audit


def map_stock_audit(payload: Mapping[str, Any]) -> Snapshot:
    label = "stock-audit"
    forecast = _dict(_require(payload, "forecast", label), "forecast")
    references = ChildTable("stock_audit_reference", ("position", "label", "value", "change_pct", "as_of", "source"))
    for position, ref in enumerate(_list(forecast.get("references") or [], "forecast.references")):
        ref = _dict(ref, f"references[{position}]")
        references.rows.append((position, _str(ref.get("label"), "label"), _num(ref.get("value"), "value"),
                                _num(ref.get("change_pct"), "change_pct"), _str(ref.get("as_of"), "as_of"),
                                _str(ref.get("source"), "source")))
    stocks = ChildTable(
        "stock_audit_stock",
        ("position", "symbol", "name", "price", "price_as_of", "source", "summary", "f_revenue", "f_revenue_unit",
         "f_period", "f_eps", "f_ttm_eps", "f_pe", "f_as_of", "f_source", "f_analysis", "v_source",
         "v_baseline_label", "v_baseline_pe", "v_premium_pct", "v_percentile", "v_sample_count", "v_analysis",
         "t_ma20", "t_ma60", "t_support", "t_resistance", "t_analysis", "q_sharpe", "q_sortino", "q_ttr_days",
         "q_index_shape", "q_period", "q_method", "q_source"),
    )
    candles = ChildTable("stock_audit_candle", ("stock_position", "trade_date", "open", "high", "low", "close", "volume"))
    operations = ChildTable("stock_audit_operation", ("stock_position", "position", "term", "horizon", "entry", "add_price",
                                                      "stop", "take_profit", "timing", "add_condition"))
    for position, stock in enumerate(_list(_require(payload, "stocks", label), "stocks")):
        sl = f"{label}.stocks[{position}]"
        stock = _dict(stock, sl)
        f = _dict(stock["fundamentals"], f"{sl}.fundamentals")
        v = _dict(stock["valuation"], f"{sl}.valuation")
        t = _dict(stock["technical"], f"{sl}.technical")
        q = _dict(stock["quality"], f"{sl}.quality")
        stocks.rows.append((
            position, _str(stock.get("symbol"), "symbol"), _str(stock.get("name"), "name"), _num(stock.get("price"), "price"),
            _str(stock.get("price_as_of"), "price_as_of"), _str(stock.get("source"), "source"), str(stock.get("summary") or ""),
            _num(f["revenue"], "f.revenue"), _str(f["revenue_unit"], "f.revenue_unit"), _str(f["period"], "f.period"),
            _num(f["eps"], "f.eps"), _num(f["ttm_eps"], "f.ttm_eps"), _num(f["pe"], "f.pe"), _str(f["as_of"], "f.as_of"),
            _str(f["source"], "f.source"), str(f.get("analysis") or ""),
            _str(v["source"], "v.source"), _str(v["baseline_label"], "v.baseline_label"), _num(v["baseline_pe"], "v.baseline_pe"),
            _num(v["premium_pct"], "v.premium_pct"), _num(v["percentile"], "v.percentile"), _int(v["sample_count"], "v.sample_count"),
            str(v.get("analysis") or ""),
            _num(t["ma20"], "t.ma20"), _num(t["ma60"], "t.ma60"), _num(t["support"], "t.support"),
            _num(t["resistance"], "t.resistance"), str(t.get("analysis") or ""),
            _num(q["sharpe"], "q.sharpe"), _num(q["sortino"], "q.sortino"), _int(q["ttr_days"], "q.ttr_days"),
            _str(q["index_shape"], "q.index_shape"), _str(q["period"], "q.period"), _str(q["method"], "q.method"),
            _str(q["source"], "q.source"),
        ))
        for candle in _list(t.get("candles") or [], f"{sl}.candles"):
            candle = _dict(candle, f"{sl}.candle")
            candles.rows.append((position, _str(candle.get("date"), "date"), _num(candle["open"], "open"),
                                 _num(candle["high"], "high"), _num(candle["low"], "low"), _num(candle["close"], "close"),
                                 _int(candle["volume"], "volume")))
        for opos, op in enumerate(_list(stock.get("operations") or [], f"{sl}.operations")):
            op = _dict(op, f"{sl}.operations[{opos}]")
            operations.rows.append((position, opos, _str(op["term"], "term"), _str(op["horizon"], "horizon"),
                                    _num(op["entry"], "entry"), _num(op["add"], "add"), _num(op["stop"], "stop"),
                                    _num(op["take_profit"], "take_profit"), str(op.get("timing") or ""),
                                    str(op.get("add_condition") or "")))
    receipts = ChildTable("stock_audit_receipt", ("position", "url", "fetched_at", "status"))
    for position, rec in enumerate(_list(payload.get("source_receipts") or [], "source_receipts")):
        rec = _dict(rec, f"source_receipts[{position}]")
        receipts.rows.append((position, _str(rec.get("url"), "url"), _str(rec.get("fetched_at"), "fetched_at"),
                              _int(rec.get("status"), "status")))
    generated = _str(_require(payload, "generated_at", label), "generated_at")
    header = {
        "generated_at": generated,
        "generated_at_text": generated,
        "schema_version": _int(_require(payload, "schema_version", label), "schema_version"),
        "report_date": _str(_require(payload, "report_date", label), "report_date"),
        "conclusion": str(payload.get("conclusion") or ""),
        "forecast_summary": str(forecast.get("summary") or ""),
        "forecast_as_of": _str(forecast.get("as_of"), "forecast.as_of"),
    }
    return Snapshot(
        dataset="stock-audit",
        header_table="stock_audit_report",
        header=header,
        children=[references, stocks, candles, operations, receipts],
    )


# ---------------------------------------------------------------- registry


def _json_file(name: str, mapper):
    def load(data_dir: Path):
        path = data_dir / name
        return mapper(load_json(path)) if path.is_file() else None
    return load


def _load_flows(data_dir: Path):
    files = read_flow_files(data_dir)
    return map_institutional_flows(files) if files else None


def _load_broker(data_dir: Path):
    inputs = read_broker_inputs(data_dir)
    return map_broker(*inputs) if inputs else None


# dataset name -> loader(data_dir) returning Snapshot | Series | None (input absent)
DATASETS = {
    "institutional-rankings": _json_file("institutional-rankings.json", map_institutional_rankings),
    "institutional-flows": _load_flows,
    "broker": _load_broker,
    "theme-focus": _json_file("theme-focus.json", map_theme_focus),
    "source-status": _json_file("source-status.json", map_source_status),
    "theme-events": _json_file("theme-events.json", map_theme_events),
    "theme-ranking": _json_file("public-theme-ranking-v0.8.json", map_theme_ranking),
    "theme-momentum": _json_file("public-theme-momentum-latest-v0.9.json", map_theme_momentum),
    "theme-momentum-history": _json_file("public-theme-momentum-history-v0.9.json", map_theme_momentum_history),
    "stock-watchlist": _json_file("public-stock-watchlist-v1.json", map_stock_watchlist),
    "fundamentals": _load_fundamentals,
    "pre-market": _json_file("pre-market-latest.json", map_pre_market),
    "stock-audit": _json_file("stock-audit-latest.json", map_stock_audit),
}
