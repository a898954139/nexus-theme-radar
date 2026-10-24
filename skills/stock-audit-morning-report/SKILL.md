---
name: stock-audit-morning-report
description: Produce a dated Nexus Stock Audit Taiwan-equity morning report with fresh source-backed research, PVA/Nexus conditional price levels, and the established mobile/desktop format. Use for generating another trading day's report or checking report-format consistency.
---

# Stock Audit morning report

Use the existing Nexus Theme Radar pipeline, not a new page/template. Work from the repository root (`scripts/render_stock_audit.py` must exist). Read [production.md](references/production.md) for source clocks, analysis contracts, and commands.

## Workflow

1. Confirm the requested **Taiwan stock-session date** and candidate symbols. Find the latest approved dated JSON/HTML as a baseline. Preserve its files; it is a format reference, not new-day research.
2. Collect observed OHLCV and official PE through the requested date with `prepare_stock_audit_day.py`. This deliberately removes old decisions and market observations. Refresh financial facts when their latest published period changes; independently verify unchanged facts. Missing quote/financial/technical evidence excludes the stock, never creates placeholders.
3. Gather same-session US closes, the actual overnight TX session and exchange calendar. Keep actual session timestamps distinct from TAIFEX attribution dates. Label retrospective retrieval honestly, not point-in-time evidence. Add calendar-backed completed-week metadata only when the closure was known by the stated cutoff.
4. Run the pinned PVA/Nexus analyzer. Review true-swing context, OB/FVG lifecycle and nearest opposing barriers from actual candles. Complete each stock's source-bound canonical review and compact morning brief. Give **conditional entry prices even when no trade is qualified**; never turn them into immediate orders. See the production reference for schema and method limitations.
5. Recompute quote/valuation/curve metrics; write concise company, valuation, technical and action insights. No model thinking, detector debug logs, or long implementation paragraphs in the reader UI. Keep period/source/method/timeframe disclosure available.
6. Run `produce_stock_audit_report.py` on the fully reviewed JSON. It refuses incomplete/relabelled inputs, renders through the shared renderer, and compares structural format against the approved baseline. Fix source errors upstream, not in generated HTML.
7. Inspect real 390px and 1440px renders: no horizontal overflow, red-positive/green-negative Taiwan signs, chart/price/table readable, analysis collapsible, desktop space used. Report **same structural format**, not pixel identity (data-dependent chart/text naturally differ).
8. Publish only with explicit user authorization. Use the repository's existing GitHub Pages workflow; verify the exact run and public HTML/JSON read-back. Local generation is not deployment. Do not create schedules or claim native Pine parity without proof.

## Method boundary

Current approved preview uses SVG charts and the pinned Dashboard structure detector plus PVA runtime. It is **not verified identical to Pine v2.1**. If native TradingView/Pine results are requested, use authenticated official tools and the compiled script on the exact symbol/timeframe/date; retain screenshot/result provenance. If unavailable, report that gap—do not substitute a third-party bridge or label detector output as native.

## Completion evidence

Return the skill location, dated report link/path, actual data date, stock count, format comparison, tests/browser checks, and any unresolved method/source limitations. A format PASS does not validate a trading strategy or authenticate source truth.
