# Stock Audit report

Canonical route: `index.html#page=watchlist`. The old dated report URL redirects to
this report rather than serving its unsourced financial / execution figures.

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
