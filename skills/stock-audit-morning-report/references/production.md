# Production reference

## Repository commands

Use the project virtual environment; install only existing requirements when necessary. Paths below are relative to the selected repository, not the skill directory.

```sh
.venv/bin/python scripts/prepare_stock_audit_day.py --date YYYY-MM-DD \
  --baseline reports/stock-audit-BASELINE.json --cache-dir WORK/raw --output WORK/input.json
.venv/bin/python scripts/analyze_stock_audit_technical.py \
  --input WORK/input.json --output WORK/computed.json
# Perform fresh source-bound research -> WORK/review.json; market/calendar -> WORK/market.json.
.venv/bin/python scripts/assemble_stock_audit_day.py --computed WORK/computed.json \
  --review WORK/review.json --market WORK/market.json --baseline WORK/input.json \
  --financial-review WORK/financial-review.json \
  --output WORK/reviewed.json
.venv/bin/python scripts/produce_stock_audit_report.py --input WORK/reviewed.json \
  --baseline reports/stock-audit-BASELINE.html --output-dir WORK/reports
```

The assembler joins only same-date reviewed inputs; its `--baseline` means the prepared financial/OHLC input, not an old dated report. All review fields must be newly adjudicated, with matching computed/input digests. Financial review is required per symbol: report `as_of`, `reviewed:true`, exact filing URLs in `sources`, a company-specific `insight`, and `financial_sha256` over the prepared financial object encoded as UTF-8 JSON (`ensure_ascii=False, sort_keys=True, separators=(",",":")`). Missing/revised facts require new adjudication, never generic fallback prose.

The collector is an input-preparation step, not an autonomous research engine. It preserves financial fields for review but removes research/technical decisions and market data. Do not render `inputs_only` or silently copy the previous `research` block. The analyzer requires its pinned local PVA runtime and Dashboard detector; a missing/version-mismatched engine is a blocker, not permission to rewrite methods.

## Sources and clocks

- TWSE `exchangeReport/STOCK_DAY?response=json&date=YYYYMM01&stockNo=SYMBOL`: ROC date, volume, O/H/L/C. `BWIBBU` supplies official PE. Preserve URL, raw digest, retrieval timestamp and observed date; cache files are not proof of historical capture.
- MOPS/TWSE financial filings: revenue period, EPS period and matching gross-margin period, publication available by cutoff, units verified. A later retrieval may include revisions; mark historical reconstruction unless independently archived.
- US regular-session close is **16:00 America/New_York**, convert with DST; Yahoo daily candle timestamp may be session OPEN, not close. Use the requested day and previous US session for changes, not an older cached change.
- TX night actual session: requested day 15:00 → next calendar day 05:00 Taipei. Its TAIFEX trading attribution can be later across holidays. Use official session interval and contract; calculate change against that contract's regular settlement, not Taiwan spot. Spot/night basis is non-synchronous.
- Forecast cutoff normally next calendar day 06:00 Taipei. Separately derive next **scheduled exchange session** from official closures/holidays; do not promise it will open. Review holidays before treating an absent quote as missing data.
- W1 contains completed weeks only. For a shortened week, retain announced closure evidence and cutoff; validate calendar metadata before including the current week. No future knowledge or partial-week confirmation.

## Research contract

Use the current schemas enforced by `render_stock_audit.complete_stock`, `valid_morning_brief` and `stock_audit_technical_contract.valid_technical`; inspect them rather than cloning an obsolete schema into a second validator.

For each stock:
- `technical_candles` are the full warmed history; `candles` and `pe_history` share the requested last observed date. Technical `as_of`, candle digest and all citations must match.
- `technical_analysis.canonical_review` binds D1/W1 direction and trigger/defense/W1-source reviews to actual candles and source IDs. Mechanical pivots alone do not prove true-swing context.
- `research.morning_brief` binds PVA numbers, OB/FVG state and short insight, and conditional table rows to concrete candle/zone sources. Inactive zones are not active demand; a candidate is not a confirmed entry.
- Conditional plans must stop at the **nearest** unbroken opposing swing/supply; no skipping a poor near-term RR for a far attractive target. No qualified trade still has price-based reassessment rows, not a fabricated executable order.
- `research.metrics` must be recalculated with `render_stock_audit.metrics(stock)`. All price/PE/premium/curve prose must agree with those numbers. Same fiscal facts may remain only after explicit review.
- Root `research_status` must be `reviewed`; include `retrieved_at`, `forecast_cutoff`, `market` and an explicit `market.economic_events` list (empty is valid only after checking), so a new date does not inherit an old event fallback.

## Format and release

Keep `reports/stock-audit.css` and the shared renderer as the sole visual system. Cards expose chart → PVA/OB/FVG numeric interpretation → conditional price table, with detailed analysis collapsed. The producer compares headings, stock component layout, table headers, disclosures, fonts and stylesheet identity; it cannot prove equal pixel geometry or economic validity.

Run focused report/technical/date/production tests, then inspect desktop and mobile. For source changes follow applicable repo review policy. Do not edit an approved older report just to make comparison pass. Scope release commits to requested files; preserve unrelated dirty work. After authorized Pages publishing, verify both HTTP success and content digest for the new dated artifacts.
