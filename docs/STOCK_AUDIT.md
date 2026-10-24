# Stock Audit report

## Standalone mobile decision card

Target: `reports/stock-audit-2026-10-21.html`, with the original Nexus fonts,
palette and expandable research layout. This target does not redirect or modify
the watchlist route, its shared schema or hourly jobs.

```sh
.venv/bin/python scripts/render_stock_audit.py \
  --input reports/stock-audit-2026-10-21.json \
  --output reports/stock-audit-2026-10-21.html
.venv/bin/python -m pytest tests/test_stock_audit_report.py \
  tests/test_stock_audit_technical.py tests/test_stock_audit_pva_nexus_report.py -q
```

The JSON is completed research, not browser-computed analysis. Original five-stock
fundamentals, valuation, 235 daily bars and curve diagnostics remain unchanged.
Separate technical input contains 2023-01-03–2026-10-21 TWSE daily OHLCV: 917 bars
per stock, except 2317 with 916. The official 2025-07-30 2317 row had zero volume
and no OHLC price; it was explicitly excluded, never filled, and its reason was
not established. All original 235-bar overlaps were checked exactly.

### Actual PVA + Nexus analysis

- PVA is **Position / Velocity / Acceleration**, not price-volume analysis. The
  offline builder calls the existing pure-Python `compute_pva_series` with the
  native supported EMA200(HLC3) mode, ATR14, V=EMA3(ΔP), A=ΔV. P=(close-anchor)/ATR.
  Session VWAP is not substituted on daily bars. Pre-seed zeros are excluded and
  at least 400 post-seed updates are required. This D1 adaptation is not evidence
  that an intraday XAUUSD strategy's profitability transfers to Taiwan equities.
- Nexus runs the existing Dashboard `detectNexusStructure` on **D1 and completed
  W1** bars. As of 10/21, W1 ends 10/16; the current incomplete week is excluded.
  Its pinned mechanical fractal-5/body-close BOS/CHoCH detector supplies candidates
  and OB/FVG evidence, followed by salience, lifecycle and individual research
  review. It is not asserted to be canonical discretionary true-swing parity or
  Structure Pine v2.1 parity. In particular, this detector creates OB candidates
  after formal CHoCH rather than Pine's post-break FVG-confirmation rule.
- Prefix replay retains zone history. Active chart/defense zones pass independent
  body-close invalidation, FVG fill, age/current-engine and exhaustion checks.
  An untouched OB remains a candidate; a defended/reaction-reviewed zone is not
  called a universal or institutional guarantee. Expired, invalidated or exhausted
  zones are not silently recycled as new support/resistance.
- The exact foreign source SHA256/revision and parameters are recorded in each
  stock's technical receipts. The builder refuses source drift before/after
  execution, never launches a signal producer, broker or order tool, and returns
  nonzero for unavailable research. Foreign repositories are not modified.

Recompute machine research locally (the pinned external source checkouts are
required; no new packages are installed):

```sh
.venv/bin/python scripts/analyze_stock_audit_technical.py \
  --input reports/stock-audit-2026-10-21.json --output /tmp/stock-audit-computed.json \
  --pva-path "$HOME/Dev/algoTrade/nexus_bridge/pva_reclaim_runtime.py" \
  --detector-path "$HOME/Dev/iCloud-dev/NexusDashboard/src/lib/indicators/nexusStructureDetector.js"
```

Machine output is reviewed per stock and merged into the research snapshot before
rendering. The report has no frontend financial computations. CI can validate the
stored snapshot against its own candles and pinned receipts without importing
those external repos; cross-repo integration tests explicitly skip only when the
actual pinned source is unavailable, while local evidence records actual passes.

### Operation contract, not an automatic trade

A plan is either `conditional` or `no_trade`. Conditional entry originates from a
strictly older structural/liquidity candidate, followed by future body-close,
follow-through and PVA conditions. OB/FVG/PVA alone cannot trigger entry. Stops
are source defense plus an explicitly disclosed ATR buffer. Targets are existing
opposing supply/liquidity sources, never a new price made by entry+2R. W1 direction
has priority; a bearish W1 blocks automatic countertrend long plans. The report's
conservative first-barrier RR>=1 gate is disclosed as a policy, not a calibrated
profitability claim.

`no_trade` is a valid completed finding, not missing data: retain the stock,
explain why and show source-linked repair/defense/pressure observations, but do not
invent entry/add/stop/profit orders. This snapshot has no eligible new long plan
for all five stocks. Old generic 20/60/120-extrema + fixed-2R targets are retired
from this dated target; the separate legacy generator below is unchanged.

Quick summaries keep dated current price and decision/observation levels visible.
Opening a stock shows D1 chart, W1/D1/PVA context and concise conclusion; full
fundamental → technical → operations → summary analysis remains initially folded.
OB/FVG annotations include timeframe and source IDs. Fonts/palette stay canonical.
The CSS link is content-versioned so returning readers receive updated styles.

### Data and inference limits

This is a **2026-10-23 historical reconstruction**, not unchanged point-in-time
archival evidence. Prices are 10/21 close, unadjusted for corporate actions; source
revisions and corporate actions can affect long-window interpretation. The US
10/21 close / TX night ending 10/22 05:00 forecast retains its separate clocks and
06:00 cutoff. It is not a fitted prediction-probability model. Existing fundamental
and one-year return-quality limitations remain; PVA price momentum never qualifies
fundamentals, moat or valuation. No personal allocation percentages are invented.

The Pages workflow copies all of `reports/`, including CSS and the larger optional
research JSON (not downloaded by the report page). Local green is not evidence of
deployment; production HTML/CSS and browser behavior require read-back.

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

### Dated canonical structure adjudication

The stored `canonical_review` separately evaluates market-respected swings using
bar-cited rejection, displacement and later reactions. It retains the original
`detector_structure`/`detector_plan` as machine evidence, not the current final bias.
A detector recognition date can lag the first actual close through a level because
of its age gate. `BOS`/`CHoCH` are events, never market phases. The final W1/D1
bias and phase are separately recorded with qualification (`qualified`, `uncertain`,
`rejected`) and dated OHLC citations. Qualified context alone is not an executable
trade; uncertain/rejected candidates cannot be promoted into a conditional plan.

The review withdrew 2317's swept 238 floor from active observations, recognized
2454's already-completed 10/16 close below 4400, and recognized 2368's two completed
weekly closes back above 1215. Five no-trade decisions are therefore based on the
current structure/reaction review, not stale last-event bias gates. Every cited
bar/price and the complete PVA recurrence from independent EMA/ATR seeds are
validated offline. These checks establish evidence integrity, not future returns.

## Reusable dated-report skill

`skills/stock-audit-morning-report/SKILL.md` is the maintained workflow; the local
Codex skill directory links to it. It separates fresh official input preparation,
source-bound research, shared rendering, structural-format checks and authorized
publication. Invoke `$stock-audit-morning-report` with a Taiwan session date.

The dated producer (`scripts/produce_stock_audit_report.py`) requires reviewed
research and an approved HTML baseline, refuses existing dated output, and uses
`render_stock_audit.py` plus the unchanged `reports/stock-audit.css`. A structural
format PASS means equal component contracts, not identical chart pixels or a
validated trading strategy. Native TradingView/Pine v2.1 parity remains unverified.

### 2026-10-22 format reproduction

- Fresh TWSE closes/PE, 10/22 US close and actual 10/22→23 TX night session.
  Oct23 closure was announced Oct22 20:10 before the forecast cutoff; W1 ends
  Oct22. Next scheduled Taiwan session is Oct27, separate from actual night time.
- Five source-bound financial/technical reviews; new dated output uses the shared
  renderer/CSS. 10/21 HTML/JSON and stylesheet remain unchanged.
- Independent Codex code-reviewer: APPROVE; architect: CLEAR. Financial-placeholder,
  nearest-barrier, missing-source and calendar-boundary findings were repaired and
  rechecked. Claude cross-model verification: SKIPPED (user-approved; subscription expired).
- Native Pine v2.1 parity and historical point-in-time source immutability remain
  unverified. This is a historical SVG detector preview, not validated execution.
