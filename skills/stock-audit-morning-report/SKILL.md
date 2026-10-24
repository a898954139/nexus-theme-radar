---
name: stock-audit-morning-report
description: Produce a dated Nexus Stock Audit Taiwan-equity morning report with short/medium/long judgement, existing PVA/Nexus entry/add/invalidation levels, and DCA plus monthly floating-profit context in the established format. Use for daily opening analysis and report-format checks; not automated trading or position sizing.
---

# Stock Audit morning report

Use the existing Nexus Theme Radar pipeline, not a new page/template. Work from the repository root (`scripts/render_stock_audit.py` must exist). Read [production.md](references/production.md) for source clocks, analysis contracts, and commands.

## Maintenance

This is the single maintained Stock Audit skill. Codex and Domina discovery links resolve to this repository folder. Revise this canonical skill and its existing pipeline; do not recreate the retired `stock-audit` skill or keep a second competing workflow.

## Decision scope

Before researching a report, read [DCA and monthly floating-profit policy](references/dca-moon-decision.md). Use fundamentals for core eligibility, existing PVA for momentum, Nexus for price structure/confirmation, and the monthly cohort rule for the relevant capital pool. This is judgement and conditional entry guidance, not an order or a sizing engine. Do not make report production depend on new Sigmoid thresholds, position caps or allocation calculations.

## Opening-analysis identity

For this example, all observations from the10/21 market cycle serve the10/22 Taiwan opening analysis: Taiwan10/21 close, US10/21 close and TX10/21→22 night. Label the report by the intended Taiwan opening morning, never by the input stock date. Display “{data_as_of} 資料 → {report_date} 台股開盤分析” using month/day labels (this example: “10/21 資料 → 10/22 台股開盤分析”); do not imply this is a10/21 opening analysis.

## Workflow

1. Confirm the requested **morning publication date** and candidate symbols. A 10/22 edition uses the preceding completed Taiwan stock session (10/21) plus its 10/21→10/22 overnight observations available by 10/22 06:00 Taipei. Store `report_date` (edition) separately from `data_as_of` (stock-session date); do not collect the publication day’s future close. Find the latest approved dated JSON/HTML as a baseline. Preserve its files; it is a format reference, not new-day research.
2. Collect observed OHLCV and official PE through `data_as_of`, never the publication day’s close, with `prepare_stock_audit_day.py`. This deliberately removes old decisions and market observations. Refresh financial facts when their latest published period changes; independently verify unchanged facts. Missing quote/financial/technical evidence excludes the stock, never creates placeholders.
3. Independently select each market’s latest completed session available by the publication cutoff; do not assume US and Taiwan holidays match. Declare `market.us_session_date` and `market.night_session_date` after source review. The current renderer only supports sessions matching `data_as_of`; if the latest US/TX session differs, stop as unsupported rather than relabel or use stale quotes. For 10/22 these are US10/21 and TX10/21→22. Gather exchange notices available by the cutoff. Never use the publication evening’s announcements to revise that morning’s forecast. Keep actual session timestamps distinct from TAIFEX attribution dates. Label retrospective retrieval honestly, not point-in-time evidence. Add calendar-backed completed-week metadata only when the closure was known by the stated cutoff.
4. Run the pinned PVA/Nexus analyzer. Review true-swing context, OB/FVG lifecycle and nearest opposing barriers from actual candles. Complete each stock's source-bound canonical review and compact morning brief. Give **conditional entry prices even when no trade is qualified**; never turn them into immediate orders. See the production reference for schema and method limitations.
5. Recompute quote/valuation/curve metrics; apply the decision policy to short/medium/long positioning. Within the existing fields, give numeric entry zones, confirmation, add conditions and invalidation, plus source-backed exit/target scenarios where available. Keep momentum separate from trade permission: slowing decline is not a confirmed reversal. If portfolio records are absent, still produce complete price research; do not invent floating profit, available cash, share counts or allocation percentages. No model thinking or detector debug logs in the reader UI.
6. Run `produce_stock_audit_report.py` on the fully reviewed JSON. It refuses incomplete/relabelled inputs, renders through the shared renderer, and compares structural format against the approved baseline. Fix source errors upstream, not in generated HTML.
7. Inspect real 390px and 1440px renders: no horizontal overflow, red-positive/green-negative Taiwan signs, chart/price/table readable, analysis collapsible, desktop space used. Report **same structural format**, not pixel identity (data-dependent chart/text naturally differ).
8. Publish only with explicit user authorization. Use the repository's existing GitHub Pages workflow; verify the exact run and public HTML/JSON read-back. Local generation is not deployment. Do not create schedules or claim native Pine parity without proof.

## Method boundary

Current approved preview uses SVG charts and the pinned Dashboard structure detector plus PVA runtime. It is **not verified identical to Pine v2.1**. If native TradingView/Pine results are requested, use authenticated official tools and the compiled script on the exact symbol/timeframe/date; retain screenshot/result provenance. If unavailable, report that gap—do not substitute a third-party bridge or label detector output as native.

## Execution boundary

Keep the shared renderer, CSS, schemas and report section order unchanged. Express DCA/monthly-pool context in existing investment-type, operation-rationale and conclusion fields; do not add a ledger, new panel or unsupported payload fields. The current scripts do not implement monthly cohort accounting, automated DCA or account execution. A skill-policy update must not be reported as those runtime features being implemented. Creating orders, alerts, schedules, sales or transfers is outside this skill's authority.

## Completion evidence

Return the skill location, dated report link/path, actual data date, stock count, format comparison, tests/browser checks, and any unresolved method/source limitations. A format PASS does not validate a trading strategy or authenticate source truth.
