# Daily pre-market analysis report (issue #8)

Each Taiwan trading morning: cloud prepares the top-10 list and deterministic
snapshots before 07:00 Taipei; the user's local Claude scheduled task (~07:30)
writes the LLM reports; the stock page reads today's report or says
**今日報告未產出**.

```
06:05/06:35/06:50  GitHub Actions  prepare-analysis-queue.yml (radar_writer)
                   watchlist → top 10 → daily_bar cache → technical/fundamental
                   snapshot → analysis_batch + analysis_queue (frozen)
07:30              local Claude task  skills/daily-analysis-report (radar_analyst)
                   pull → local PVA/Nexus analyzer → nexus-market-analysis
                   → push analysis_report
any time           /api/analysis-report?symbol= (radar_reader) → stock page card
20:10              GitHub Actions  same workflow, --mode warm (bar cache only)
```

## Tables (`supabase/migrations/20261118090000_create_analysis_report.sql`)

| Table | Writer | Key | Notes |
|---|---|---|---|
| `daily_bar` | cloud | `(symbol, trade_date)` | TWSE `STOCK_DAY` / TPEX `tradingStock`; volume in shares |
| `analysis_batch` | cloud | `report_date` | one per edition, frozen; `excluded` lists skipped symbols + reason |
| `analysis_queue` | cloud | `(report_date, symbol)` | rank 1-10, `selected_by` short/long |
| `technical_snapshot` | cloud | `(symbol, data_as_of)` | ≥600 bars (analyzer minimum), arithmetic metrics, `candles_sha256` |
| `fundamental_snapshot` | cloud | `(symbol, data_as_of)` | repo quarterly cache + PE from snapshot close; `missing` never zero-filled |
| `analysis_report` | local | `(symbol, report_date, framework_version)` | `data_as_of < report_date` enforced |

Selection rule (`analysis_batch.selection_rule`): short-rank top 7 + long-rank
top 3 from `public-stock-watchlist-v1.json`, deduplicated. A candidate with no
quotes, <600 bars, a last bar older than the reference session (2330), or no
fundamentals is excluded and the next one by rank takes its slot. Change with
`--short-slots/--long-slots` (sum must be 10).

## Roles

| Role | Can | Cannot |
|---|---|---|
| `radar_writer` (cloud) | read/insert/update bars, batch, queue, snapshots; read reports | write reports, delete |
| `radar_analyst` (local) | read batch, queue, snapshots; read/insert/update `analysis_report` | read `daily_bar`, news, events, pipeline tables; delete; DDL |
| `radar_reader` (API) | read everything in `radar` | write |

Pinned by `tests/test_daily_analysis_report.py` (static grants + live
`test_live_cloud_prepares_and_local_writes_report`, which asserts the analyst
login is refused on every other table).

## Deploy (per environment, manual)

1. Apply the migration (re-runnable).
2. Create the local login and grant only the analyst role:
   ```sql
   create role radar_analyst_login login password '<generate locally>';
   grant radar_analyst to radar_analyst_login;
   ```
   Use the Supabase session pooler or direct host; keep `sslmode=require`.
3. API login for Vercel: `grant radar_reader to radar_api;` (same login as #5 /api/pre-market) and set
   `RADAR_API_DATABASE_URL` in Vercel project env (server only).
4. GitHub: the workflow reuses secret `THEME_RADAR_DATABASE_URL` (already
   granted `radar_writer` by #1). It only receives it on `master`.
5. First run: dispatch the workflow with `mode=warm` 2-3 times (each run
   fetches ≤550 months, ~31 months per cold symbol). After that the evening
   warm keeps the cache current and the morning run fetches ~1 request per
   symbol.

Rollback: disable the workflow; `revoke radar_analyst from radar_analyst_login;`
stops local writes immediately. The page then shows 今日報告未產出.

## Local scheduled task (user's Mac)

Environment variable names (values only in your shell profile / keychain):

- `RADAR_ANALYST_DATABASE_URL`: `postgresql://radar_analyst_login:<pw>@<host>:5432/postgres?sslmode=require`
- `NEXUS_PVA_PATH`, `NEXUS_DETECTOR_PATH`: optional overrides for the local analyzer

Claude scheduled task: weekdays 07:30 Asia/Taipei, working directory = local
clone of this repo (pull `master` first), prompt:

> 用 skills/daily-analysis-report 產出今天的盤前報告，完成後回報寫入幾檔、缺哪幾檔與原因。

The Mac must be awake at 07:30 (Energy settings → schedule wake 07:25). If it
is asleep, nothing is written and the page says 今日報告未產出; it never shows
yesterday's report as today's.

## Acceptance check (10 trading days)

```sql
-- Per edition: list size, reports written, last report time (Taipei)
select b.report_date, b.data_as_of, b.selected_count,
       count(r.symbol) as reports,
       max(r.created_at at time zone 'Asia/Taipei') as last_written_tpe,
       (b.prepared_at at time zone 'Asia/Taipei')   as list_ready_tpe
from radar.analysis_batch b
left join radar.analysis_report r on r.report_date = b.report_date
where b.report_date >= current_date - 21
group by b.report_date, b.data_as_of, b.selected_count, b.prepared_at
order by b.report_date desc;
```

Pass = `list_ready_tpe < 07:00`, `reports = selected_count`,
`last_written_tpe < 08:30` on 10 consecutive editions.

## Known limits

- Weekday exchange holidays are not detected by the cloud job; the list is
  still built from the last session. The local task can skip (no report is
  better than a holiday report); a holiday calendar can be added later.
- TPEX `tradingStock` parsing locates columns by header; it is covered by a
  fixture, not yet by a live run from CI. A parse failure excludes the symbol.
- The API needs the Vercel deployment from #5. On GitHub Pages the card says
  盤前報告服務尚未啟用.
