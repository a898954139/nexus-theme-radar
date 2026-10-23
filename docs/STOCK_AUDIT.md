# Stock Audit report

## Standalone mobile decision card

Target: `reports/stock-audit-2026-10-21.html` (no redirect and no watchlist route change).
The dated research input is `reports/stock-audit-2026-10-21.json`; its CSS is
`reports/stock-audit.css`. Render after completing research, not in the browser:

```sh
.venv/bin/python scripts/render_stock_audit.py \
  --input reports/stock-audit-2026-10-21.json \
  --output reports/stock-audit-2026-10-21.html
.venv/bin/python -m pytest tests/test_stock_audit_report.py -q
```

This snapshot contains five independently collected TWSE daily price/PE histories
(235 sessions, 2025-11-03 through 2026-10-21), September monthly revenue and YoY,
and consolidated H1 cumulative EPS/margins from TWSE/MOPS (API, CSV and original
HTML cross-checked). It does not copy the unrelated six-stock latest JSON. Missing
research excludes a candidate; fewer than three complete candidates blocks output
before any target file is replaced. All calculations and SVGs are pre-rendered;
native `details` work without JavaScript and only the first stock starts open.
The scan layer keeps dated price and four **short-scenario** levels visible even
when a stock is closed. Opening it shows the existing conclusion's first sentence
and the daily chart before a separate, initially closed full-analysis disclosure.
The original fundamental → technical → operations → summary research remains in
that disclosure unchanged. A price alone is not an entry: the visible context
requires a close above the trigger and a subsequent-session retest.

The chart marks the actual current-price line, the last-20-session low/high range
and the existing resistance-to-entry retest band at their true price coordinates.
These are **not OBs**. This snapshot has no confirmed Order Block evidence, and
this UI-only iteration does not invent a detector or relabel support as an OB.
Each stock carries source-backed written fundamental, valuation, curve, daily Nexus
scenario and action/conclusion research; the renderer does not assign every stock
the same classification. Stored numeric research is recomputed only for integrity
validation, with a tight roundoff tolerance across Python runtimes. A 90-session
chart with MA60 needs at least 149 source candles; financial periods and both
OHLCV/PE source URLs are required before a candidate may render.

**Historical reconstruction, not point-in-time evidence:** all sources were fetched
on 2026-10-23 and may reflect revisions. Stock prices are 10/21 close. Forecast
uses the completed US 10/21 session (10/22 04:00 Taipei) and TX November night
session ending 10/22 05:00, with a 06:00 cutoff. The phase and levels are a daily-only
Nexus-style simplification, not intraday structure verification. Market breadth is
a conditional heuristic, not calibrated prediction odds. The future/spot difference
uses different clocks and includes carry/contract effects. Next FOMC is linked to
the official calendar; DXY/yields are omitted because they do not drive this bounded
scenario. No complete peer valuation set was collected, so no industry-average PE
is invented. A single year cannot establish long-term compound quality.

Growth metrics use unadjusted closes, zero risk-free rate, 252-session annualization,
completed peak-to-recovery sessions plus the current unrecovered duration, maximum
drawdown and log-price regression R². They never gate fundamental eligibility.
Entry/add/stop use valid TWSE ticks; the 20/60/120-session high/low generates three
separate 2R scenarios. The short plan's stop must not be reused for the longer
plans. No allocation percentages or analyst price targets are invented.

The existing Pages workflow already copies all of `reports/`, including CSS and
research JSON. Local verification is not evidence of deployment.

## Existing separate latest-snapshot workflow

The original `data/stock-audit-latest.json` and generator below remain unchanged by
the dated target redesign; their existing regression failures are reported separately.

## Refresh (manual, not the hourly news job)

```sh
.venv/bin/python scripts/build_stock_audit.py --date 2026-10-22
npm run build
.venv/bin/python -m pytest tests/test_stock_audit_analysis.py tests/test_stock_audit_ui.py tests/test_stock_watchlist_ui.py -q
```

The generator writes `data/stock-audit-latest.json` atomically only after analysis
and collection succeed. It is a dated research snapshot, **not a live quote feed**.
The current bounded universe is 2317; do not expand it by copying old report values.
Published source receipts record fetched times separately from market timestamps.

- Daily unadjusted OHLCV and published historical PE: TWSE monthly STOCK_DAY / BWIBBU.
  The observed window and sample size are displayed; it is not assumed to be 252 days.
- Revenue / quarterly EPS: existing Goodinfo individual-company quarterly cache,
  fiscal quarter and fetched time shown. TWSE PE uses its own earnings convention;
  it is not recomputed from parent-only EPS. These bases must not be conflated.
- US indices and large tech: Yahoo quote metadata timestamps and previous completed
  daily close from the **same response**. Intraday snapshots are explicitly labelled.
- Taiwan futures: TAIFEX nearest monthly TX night session. Timestamp is the official
  session end, not the last trade time. This is a different clock from US quotes.

## Calculations and safeguards

PE premium = `(current published PE / observed historical median PE - 1) * 100`;
negative means discount, not an invented premium. Percentile is the fraction of
observed PE values less than or equal to current PE. MA20/60 are simple daily close
averages. Support/resistance are the prior 20-session low/high including the report
day. The chart is unadjusted, so corporate actions can affect comparisons.

Three alternative long-only scenarios use the 20/60/120-session high plus one whole
TWD for entry, the window low minus one TWD for stop, entry plus one TWD for add,
and entry + 2*(entry-stop) for the gross 2R take-profit. These valid whole-TWD levels
are scoped to 2317's observed price band. They are **not analyst price targets**,
return forecasts, executable orders, or a mandate to trade. Fees/slippage are not
included. Gaps may exceed planned risk; never imply a guaranteed stop fill.

Sharpe/Sortino, completed time-to-recovery and the price index are **post-selection
curve diagnostics**, not a fundamental gate. They use unadjusted closes (no dividend
reinvestment), zero risk-free rate and 252-day annualization. TTR is the longest
completed recovery within the observed window in trading sessions; an ongoing
underwater spell is not falsely called recovered. No quality threshold chooses a
candidate. The forecast is a disclosed conditional breadth heuristic, not a fitted
or backtested prediction model.

Malformed / incomplete candidates are removed before rendering; missing values do
not become zero. No public fixtures or synthetic finance values are used. Static
snapshots do not silently refresh with the hourly theme run; run the manual command
and review again when updating this report.

## Target release review (2026-10-23)

The dated target has code-reviewer `APPROVE` and architect `CLEAR` (cycle 2).
Anthony explicitly authorized skipping the unavailable Claude AC gate: **skipped,
not PASS**. No hook or test policy was changed. This is acceptance with a
user-authorized skipped gate, not full three-lane acceptance. The independent
latest-snapshot/watchlist baseline regressions are outside this target release;
no existing assertions were relaxed. Target and bounded source/pipeline checks
passed (44 tests), alongside the frontend build and responsive browser checks.
