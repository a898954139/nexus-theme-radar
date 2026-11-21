"""Narrative commentary over the cached quarterly statements.

The detail page renders the numbers; this produces the sentences that say what
they mean. Writing those takes a model, which makes this different from every
other step in the pipeline: it costs real money per symbol per quarter and it
can invent things.

Both problems shape the design. The quarterly throttle means a re-run costs
nothing. And *executing* the prompt is injected rather than imported, so the
model call lives outside this module: today Claude Code runs it by hand once a
quarter, and an API-backed runner can take over later without changing the
stored format or these tests.

Everything a generation returns is validated before it is kept. A model that
answers about the wrong quarter is a failure, not a success -- recording it as
done would mean the next run skips it and the stale prose stays forever.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

LOGGER = logging.getLogger(__name__)

COMMENTARY_FILE = "fundamental-commentary.json"
SCHEMA_VERSION = 1

# Enough to ground the prose without pasting the whole statement set into the
# prompt; the page shows the full tables anyway.
MAX_QUARTERS_IN_PROMPT = 6


@dataclass
class CommentaryReport:
    universe: int = 0
    selected: list[str] = field(default_factory=list)
    succeeded: int = 0
    failed: int = 0
    failures: dict[str, str] = field(default_factory=dict)

    @property
    def skipped(self) -> int:
        return self.universe - len(self.selected)


def symbols_needing_commentary(
    contexts: Mapping[str, Mapping[str, Any]],
    *,
    commentary: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Return the symbols whose commentary is missing or describes a stale
    quarter.

    A symbol with no quarters is skipped rather than attempted: there is
    nothing to summarise, so a generation could only invent one.
    """
    due: list[str] = []
    for instrument_id in sorted(contexts):
        context = contexts[instrument_id]
        quarter = context.get("fiscal_quarter")
        if not isinstance(quarter, str) or not context.get("quarters"):
            continue
        existing = commentary.get(instrument_id)
        if isinstance(existing, Mapping) and existing.get("fiscal_quarter") == quarter:
            continue
        due.append(instrument_id)
    return due


def build_commentary_prompt(ticker: str, context: Mapping[str, Any]) -> str:
    """Build the prompt for one symbol.

    Every figure the commentary may cite is pasted in. Asking a model to recall
    a company's revenue is asking it to make one up, and a fabricated figure on
    a page of real ones is the failure mode worth the most effort to avoid.
    """
    quarter = context.get("fiscal_quarter", "")
    basis = context.get("basis", "parent_only")
    currency = context.get("currency", "TWD 億元")

    payload = {
        "quarters": list(context.get("quarters", []))[:MAX_QUARTERS_IN_PROMPT],
        "health": context.get("health", {}),
        "valuation": context.get("valuation", {}),
        "statements": context.get("statements", {}),
    }

    return f"""你是財務分析助理。根據以下 {ticker} 的季度財報數字，寫出 4-5 條重點觀察。

資料期別：{quarter}
編製基礎：{basis}（母公司個體財報）
金額單位：{currency}，EPS 為元，比率為小數（0.6624 = 66.24%）

```json
{json.dumps(payload, ensure_ascii=False, indent=2)}
```

規則：
- 只能使用上面出現過的數字。**不得引用任何未提供的數據**，包含股價、市值、
  同業比較、產業份額、未來預估。
- 每條觀察必須包含：起點→終點的具體數字、變化幅度、以及一句話說明意義。
- 缺少的欄位就是沒有揭露，不要推測，也不要當作零。
- 現金流量表為合併基礎、資產負債表為母公司基礎，兩者現金不一定相等，不要當成錯誤。
- 資本支出為負數代表投入；自由現金流 = 營業現金流 + 資本支出。
- **不得給出投資建議**、買賣評等或目標價。只描述已發生的財務事實。

輸出格式：僅回傳 JSON，不要有其他文字。
{{"fiscal_quarter": "{quarter}", "highlights": ["觀察一", "觀察二", "..."]}}
"""


def validate_commentary(
    payload: Any, *, expected_quarter: str,
) -> dict[str, Any] | None:
    """Return the commentary if it is usable, else None.

    Rejecting is always safe here: the caller keeps whatever was there before,
    and the symbol stays due so the next run retries it.
    """
    if not isinstance(payload, Mapping):
        return None
    if payload.get("fiscal_quarter") != expected_quarter:
        return None
    highlights = payload.get("highlights")
    if not isinstance(highlights, list) or not highlights:
        return None
    if not all(isinstance(item, str) and item.strip() for item in highlights):
        return None
    return dict(payload)


def generate_commentary(
    contexts: Mapping[str, Mapping[str, Any]],
    *,
    commentary: Mapping[str, Mapping[str, Any]],
    run: Callable[[str], Any],
    dry_run: bool = False,
) -> tuple[dict[str, Any], CommentaryReport]:
    """Generate commentary for every symbol that needs it.

    ``run`` takes a prompt and returns the parsed response. It may raise; a
    raising symbol keeps the commentary it already had rather than losing it.
    """
    due = symbols_needing_commentary(contexts, commentary=commentary)
    report = CommentaryReport(universe=len(contexts), selected=due)

    if dry_run:
        return {}, report

    merged: dict[str, Any] = dict(commentary)
    for instrument_id in due:
        context = contexts[instrument_id]
        quarter = str(context.get("fiscal_quarter", ""))
        ticker = _bare_ticker(instrument_id)
        try:
            response = run(build_commentary_prompt(ticker, context))
        except Exception as error:  # noqa: BLE001 - one symbol must not end the run
            LOGGER.warning("commentary_failed symbol=%s error=%s", instrument_id, error)
            report.failed += 1
            report.failures[instrument_id] = str(error)
            continue

        validated = validate_commentary(response, expected_quarter=quarter)
        if validated is None:
            # Not recorded as done: a success here would make the next run skip
            # this symbol and leave the bad answer in place.
            LOGGER.warning(
                "commentary_rejected symbol=%s expected=%s", instrument_id, quarter,
            )
            report.failed += 1
            report.failures[instrument_id] = f"rejected: not valid for {quarter}"
            continue

        merged[instrument_id] = validated
        report.succeeded += 1

    return merged, report


def _bare_ticker(instrument_id: str) -> str:
    return instrument_id.split(":", 1)[1] if ":" in instrument_id else instrument_id


def load_commentary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        LOGGER.warning("commentary_cache_unreadable path=%s error=%s", path, error)
        return {}
    symbols = payload.get("symbols")
    return dict(symbols) if isinstance(symbols, dict) else {}


def write_commentary(path: Path, commentary: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": SCHEMA_VERSION,
        "symbols": {key: commentary[key] for key in sorted(commentary)},
    }
    path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
