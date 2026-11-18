---
name: daily-analysis-report
description: "Local half of the daily pre-market report (issue #8). Use from the user's Claude scheduled task around 07:30 Taipei, or when asked to produce/redo today's top-10 analysis reports. Reads the cloud-prepared list and snapshots, runs the local PVA/Nexus analyzer, applies nexus-market-analysis, and writes radar.analysis_report. Not for trading, orders or sizing."
---

# Daily pre-market analysis report (local)

Run from the repository root on the user's machine. The cloud job has already
frozen today's list (`radar.analysis_batch` / `analysis_queue`) and the
deterministic snapshots by 07:00 Taipei. Your job is judgement only: read the
numbers, write one report per stock, push. Never fetch prices yourself and
never fill a missing number.

Environment (values live only in the local shell profile, never in the repo):

| Variable | Meaning |
|---|---|
| `RADAR_ANALYST_DATABASE_URL` | login granted `radar_analyst` only |
| `NEXUS_PVA_PATH` | optional, local PVA runtime (default `~/Dev/algoTrade/nexus_bridge/pva_reclaim_runtime.py`) |
| `NEXUS_DETECTOR_PATH` | optional, pinned structure detector (see #4) |

## Steps

1. `D=$(TZ=Asia/Taipei date +%F); W=~/.nexus-radar/daily-report/$D`
2. `.venv/bin/python scripts/local_analysis_report.py pull --report-date $D --work-dir $W`
   - exit 3 = no list for today (holiday, or cloud not ready). Stop. Do not
     reuse yesterday's list; the site will show 今日報告未產出.
3. Technical structure, locally (PVA runtime is local only):
   ```
   .venv/bin/python scripts/analyze_stock_audit_technical.py \
     --input $W/analyzer-input.json --output $W/computed.json \
     ${NEXUS_PVA_PATH:+--pva-path "$NEXUS_PVA_PATH"} ${NEXUS_DETECTOR_PATH:+--detector-path "$NEXUS_DETECTOR_PATH"}
   ```
   A stock whose `technical_analysis.analysis_status` is not `complete` gets
   **no report** (exclude, do not guess).
4. For each remaining stock in `$W/queue.json`, apply the local
   `nexus-market-analysis` skill (HTF → LTF, phase, Bias vs Actionability,
   primary + alternative scenario, confirmation, invalidation, no-trade call)
   using only `queue.json` (metrics, fundamentals, themes) and `computed.json`.
   Write `$W/reports/<symbol>.json` with exactly these keys:

   ```json
   {
     "symbol": "2330",
     "report_date": "<D>",
     "data_as_of": "<queue.json data_as_of>",
     "framework_version": "nexus-market-analysis/v1",
     "generated_at": "<ISO timestamp with +08:00>",
     "bias": "bullish | bearish | neutral",
     "actionability": "actionable | wait_for_confirmation | no_trade",
     "conclusion": "≤400 字，一段結論",
     "market_structure": "≤600 字，W1/D1 結構與階段",
     "key_levels": [{"label": "前高轉支撐", "price": 1020, "kind": "support | resistance | trigger | invalidation | target"}],
     "primary_scenario": {"summary": "…", "trigger": "…", "entry_zone": [1015, 1025] , "targets": [1080]},
     "alternative_scenario": {"summary": "…", "trigger": "…"},
     "confirmation": "…",
     "invalidation": {"price": 995, "condition": "日收盤跌破 995"},
     "no_trade_warning": null,
     "news_context": "新聞只是輸入之一；可為 null"
   }
   ```

   Rules the push step enforces: every price within ±50% of the snapshot
   close; `actionable` needs `entry_zone`; `no_trade` needs
   `no_trade_warning`; no extra keys; no key containing thinking / reasoning /
   debug / log / raw / detector. Text in zh-TW. News direction never replaces
   price-structure confirmation. Conditional prices are not orders.
5. `.venv/bin/python scripts/local_analysis_report.py push --report-date $D --work-dir $W`
   - exit 2 lists invalid files and writes nothing; fix the report, push again.
6. `… status --report-date $D` and reply with: pushed count, stocks without a
   report and why (analyzer incomplete, excluded by cloud), finish time.

Re-running is safe: the same `(symbol, report_date, framework_version)` is
replaced; a new `framework_version` adds a row and keeps the old one.
