#!/usr/bin/env python3
"""Publish pipeline outputs into the normalized `radar` tables.

    python scripts/radar_publish.py --data-dir data --dataset theme-focus --dataset source-status
    python scripts/radar_publish.py --data-dir data --all          # backfill everything present

Credential: THEME_RADAR_DATABASE_URL (a login granted radar_writer). Without it
the run logs ``radar_publish_skipped`` and exits 0, so forks and local runs need
no secrets.

Failure policy: by default a DB failure is logged (redacted) and the process
still exits 0, because during the cut-over the workflows must keep committing
their files. ``--require`` turns any failure, or a missing credential, into a
non-zero exit; the workflows switch to it once the site reads only the API.

Each snapshot is written in one transaction: header, then child tables via
COPY. A snapshot whose generated_at already exists is skipped (re-running a
backfill is a no-op). Series rows go through a temp table and are upserted.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

try:
    from scripts.radar_tables import DATASETS, Series, Snapshot
    from scripts.radar_store import redact_error
except ModuleNotFoundError:
    from radar_tables import DATASETS, Series, Snapshot
    from radar_store import redact_error

LOGGER = logging.getLogger("radar_publish")

INSTRUMENT_UPSERT_SQL = """
INSERT INTO radar.instrument (instrument_id, symbol, exchange, name_zh, is_etf)
VALUES (%(instrument_id)s, %(symbol)s, %(exchange)s, %(name_zh)s, %(is_etf)s)
ON CONFLICT (instrument_id) DO UPDATE SET
  name_zh = CASE WHEN EXCLUDED.name_zh <> '' THEN EXCLUDED.name_zh ELSE radar.instrument.name_zh END,
  is_etf = COALESCE(EXCLUDED.is_etf, radar.instrument.is_etf),
  updated_at = now()
WHERE (EXCLUDED.name_zh <> '' AND EXCLUDED.name_zh IS DISTINCT FROM radar.instrument.name_zh)
   OR (EXCLUDED.is_etf IS NOT NULL AND EXCLUDED.is_etf IS DISTINCT FROM radar.instrument.is_etf)
""".strip()

BROKER_UPSERT_SQL = """
INSERT INTO radar.broker (broker_id, name) VALUES (%s, %s)
ON CONFLICT (broker_id) DO UPDATE SET name = EXCLUDED.name, updated_at = now()
WHERE EXCLUDED.name IS DISTINCT FROM radar.broker.name
""".strip()


def _ident(name: str) -> str:
    if not name.replace("_", "").isalnum() or not name.islower():
        raise ValueError(f"unsafe identifier {name!r}")
    return name


def _upsert_dimensions(cursor: Any, instruments: dict[str, dict[str, Any]], brokers: dict[str, str] | None = None) -> None:
    if instruments:
        cursor.executemany(INSTRUMENT_UPSERT_SQL, sorted(instruments.values(), key=lambda r: r["instrument_id"]))
    if brokers:
        cursor.executemany(BROKER_UPSERT_SQL, sorted(brokers.items()))


def write_snapshot(connection: Any, snapshot: Snapshot) -> dict[str, Any]:
    """Write one snapshot in a single transaction; skip if already present."""

    header_table = _ident(snapshot.header_table)
    columns = list(snapshot.header)
    insert_sql = (
        f"INSERT INTO radar.{header_table} ({', '.join(_ident(c) for c in columns)}) "
        f"VALUES ({', '.join('%(' + c + ')s' for c in columns)}) "
        "ON CONFLICT (generated_at) DO NOTHING RETURNING snapshot_id"
    )
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(insert_sql, snapshot.header)
            created = cursor.fetchone()
            if created is None:
                return {"status": "exists", "rows": 0}
            snapshot_id = created[0]
            _upsert_dimensions(cursor, snapshot.instruments, snapshot.brokers)
            for child in snapshot.children:
                if not child.rows:
                    continue
                cols = ", ".join(_ident(c) for c in ("snapshot_id", *child.columns))
                with cursor.copy(f"COPY radar.{_ident(child.table)} ({cols}) FROM STDIN") as copy:
                    for row in child.rows:
                        copy.write_row((snapshot_id, *row))
            cursor.execute("SELECT radar.purge_snapshots()")
    return {"status": "written", "rows": snapshot.row_count(), "snapshot_id": snapshot_id}


def write_series(connection: Any, series: Series) -> dict[str, Any]:
    """Upsert time-series rows by natural key in one transaction."""

    table = _ident(series.table)
    cols = [_ident(c) for c in series.columns]
    keys = [_ident(c) for c in series.key_columns]
    updates = [c for c in cols if c not in keys]
    staging = f"_stage_{table}"
    with connection.transaction():
        with connection.cursor() as cursor:
            _upsert_dimensions(cursor, series.instruments)
            cursor.execute(
                f"CREATE TEMP TABLE {staging} (LIKE radar.{table} INCLUDING DEFAULTS) ON COMMIT DROP"
            )
            with cursor.copy(f"COPY {staging} ({', '.join(cols)}) FROM STDIN") as copy:
                for row in series.rows:
                    copy.write_row(row)
            cursor.execute(
                f"INSERT INTO radar.{table} ({', '.join(cols)}) "
                f"SELECT {', '.join(cols)} FROM {staging} "
                f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET "
                + ", ".join(f"{c} = EXCLUDED.{c}" for c in updates)
                + ", updated_at = now() WHERE ("
                + ", ".join(f"radar.{table}.{c}" for c in updates)
                + ") IS DISTINCT FROM ("
                + ", ".join(f"EXCLUDED.{c}" for c in updates)
                + ")"
            )
            changed = cursor.rowcount
            cursor.execute("SELECT radar.purge_snapshots()")
    return {"status": "written", "rows": series.row_count(), "changed": changed}


def publish(connection: Any, item: Snapshot | Series) -> dict[str, Any]:
    if isinstance(item, Snapshot):
        return write_snapshot(connection, item)
    return write_series(connection, item)


def connect_from_environment() -> Any | None:
    database_url = os.environ.get("THEME_RADAR_DATABASE_URL", "").strip()
    if not database_url:
        return None
    import psycopg

    return psycopg.connect(database_url, connect_timeout=15)


def run(data_dir: Path, datasets: list[str], *, require: bool, connect=connect_from_environment) -> int:
    unknown = [name for name in datasets if name not in DATASETS]
    if unknown:
        LOGGER.error("radar_publish_unknown_dataset names=%s", ",".join(unknown))
        return 2

    # Map every dataset before touching the DB: a malformed payload must not
    # leave some datasets written and others not because of ordering.
    items: list[Snapshot | Series] = []
    failures = 0
    for name in datasets:
        try:
            item = DATASETS[name](data_dir)
        except (ValueError, KeyError, TypeError) as error:
            LOGGER.error("radar_publish_invalid dataset=%s error=%s", name, error)
            failures += 1
            continue
        if item is None:
            LOGGER.warning("radar_publish_input_missing dataset=%s", name)
            continue
        items.append(item)

    try:
        connection = connect()
    except Exception as error:  # noqa: BLE001 - redacted and contained
        LOGGER.error("radar_publish_failed stage=connect error=%s", redact_error(error))
        return 1 if require else 0
    if connection is None:
        LOGGER.warning("radar_publish_skipped reason=credential_unavailable")
        return 1 if require else 0

    with connection:
        for item in items:
            started = time.monotonic()
            try:
                result = publish(connection, item)
            except Exception as error:  # noqa: BLE001 - redacted and contained
                failures += 1
                LOGGER.error("radar_publish_failed dataset=%s error=%s", item.dataset, redact_error(error))
                continue
            LOGGER.info(
                "radar_publish_%s dataset=%s rows=%d elapsed_ms=%d",
                result["status"], item.dataset, result["rows"], int((time.monotonic() - started) * 1000),
            )
    return 1 if failures and require else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--dataset", action="append", default=[], choices=sorted(DATASETS))
    parser.add_argument("--all", action="store_true", help="publish every registered dataset whose input exists")
    parser.add_argument("--require", action="store_true", help="exit non-zero on any failure or missing credential")
    args = parser.parse_args(argv)
    if not args.dataset and not args.all:
        parser.error("pass --dataset (repeatable) or --all")
    return args


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)
    datasets = sorted(DATASETS) if args.all else list(dict.fromkeys(args.dataset))
    return run(args.data_dir, datasets, require=args.require)


if __name__ == "__main__":
    sys.exit(main())
