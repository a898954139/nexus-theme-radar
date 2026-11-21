#!/usr/bin/env python3
"""Emit the commentary prompts, or fold generated answers back into the cache.

Executing the prompts needs a model, which this project does not call from the
pipeline. So the work is split in two, and the model call happens in between:

    1. ``--emit-prompts <dir>``  writes one prompt file per symbol that is due
    2. (a model answers each prompt, writing <symbol>.json beside it)
    3. ``--collect <dir>``       validates the answers and writes the cache

Step 2 is Claude Code today. An API-backed runner can replace it without
touching either end, because the contract between them is a directory of JSON
files rather than a function call.

Everything is quarterly-throttled: a symbol whose commentary already describes
the current quarter is skipped, so re-running costs nothing.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

try:  # pragma: no cover - exercised by the real CI entrypoint
    from scripts.fundamental_commentary import (
        COMMENTARY_FILE,
        build_commentary_prompt,
        generate_commentary,
        load_commentary,
        symbols_needing_commentary,
        write_commentary,
    )
    from scripts.fundamentals_pipeline import FUNDAMENTALS_CACHE_FILE
except ModuleNotFoundError:  # pragma: no cover - running as scripts/<file>.py
    from fundamental_commentary import (
        COMMENTARY_FILE,
        build_commentary_prompt,
        generate_commentary,
        load_commentary,
        symbols_needing_commentary,
        write_commentary,
    )
    from fundamentals_pipeline import FUNDAMENTALS_CACHE_FILE

LOGGER = logging.getLogger("generate_fundamental_commentary")

ROOT = Path(__file__).resolve().parents[1]


def _bare_ticker(instrument_id: str) -> str:
    return instrument_id.split(":", 1)[1] if ":" in instrument_id else instrument_id


def _load_contexts(data_dir: Path) -> dict:
    path = data_dir / FUNDAMENTALS_CACHE_FILE
    if not path.exists():
        raise SystemExit(f"fundamentals cache not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    symbols = payload.get("symbols")
    if not isinstance(symbols, dict):
        raise SystemExit(f"fundamentals cache has no symbols: {path}")
    return symbols


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--emit-prompts", type=Path, metavar="DIR",
        help="Write one prompt per due symbol into DIR and exit.",
    )
    parser.add_argument(
        "--collect", type=Path, metavar="DIR",
        help="Read <symbol>.json answers from DIR and write the commentary cache.",
    )
    parser.add_argument(
        "--only", help="Comma-separated tickers to restrict the run to (e.g. 2330,8299).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report the work, change nothing.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    contexts = _load_contexts(args.data_dir)
    if args.only:
        wanted = {t.strip() for t in args.only.split(",") if t.strip()}
        contexts = {k: v for k, v in contexts.items() if _bare_ticker(k) in wanted}
        missing = wanted - {_bare_ticker(k) for k in contexts}
        if missing:
            LOGGER.warning("not in the fundamentals cache: %s", ", ".join(sorted(missing)))

    commentary_path = args.data_dir / COMMENTARY_FILE
    existing = load_commentary(commentary_path)
    due = symbols_needing_commentary(contexts, commentary=existing)

    LOGGER.info(
        "commentary universe=%d due=%d skipped=%d",
        len(contexts), len(due), len(contexts) - len(due),
    )

    if args.dry_run:
        for instrument_id in due:
            LOGGER.info("would generate %s (%s)", instrument_id, contexts[instrument_id].get("fiscal_quarter"))
        return 0

    if args.emit_prompts:
        args.emit_prompts.mkdir(parents=True, exist_ok=True)
        for instrument_id in due:
            ticker = _bare_ticker(instrument_id)
            target = args.emit_prompts / f"{ticker}.prompt.txt"
            target.write_text(
                build_commentary_prompt(ticker, contexts[instrument_id]), encoding="utf-8",
            )
        LOGGER.info("wrote %d prompt(s) to %s", len(due), args.emit_prompts)
        if due:
            LOGGER.info("answer each as %s/<ticker>.json, then re-run with --collect", args.emit_prompts)
        return 0

    if args.collect:
        # generate_commentary walks `due` in sorted order and calls run() once
        # per symbol, so the answers are consumed in that same order rather than
        # being recovered by parsing the prompt text back apart.
        pending = iter(due)

        def run(_prompt: str) -> dict:
            instrument_id = next(pending)
            answer = args.collect / f"{_bare_ticker(instrument_id)}.json"
            if not answer.exists():
                raise FileNotFoundError(f"no answer file: {answer}")
            return json.loads(answer.read_text(encoding="utf-8"))

        merged, report = generate_commentary(contexts, commentary=existing, run=run)
        LOGGER.info(
            "collect ok=%d failed=%d", report.succeeded, report.failed,
        )
        for symbol, error in sorted(report.failures.items()):
            LOGGER.warning("  %s: %s", symbol, error)
        write_commentary(commentary_path, merged)
        LOGGER.info("wrote %s (%d symbols)", commentary_path, len(merged))
        return 0 if report.failed == 0 else 1

    parser.error("choose one of --emit-prompts, --collect, or --dry-run")
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
