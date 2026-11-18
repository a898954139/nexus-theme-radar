# Private `radar` schema (Phase 1 dual-write)

The hourly pipeline (`scripts/update_theme_radar.py`) still writes and commits
JSON under `data/` exactly as before. After the JSON is on disk it mirrors the
same run into the private Supabase schema `radar` via `scripts/radar_store.py`.
JSON stays the source of truth until the API cut-over (WS1 step 2).

## What is written each run

| Table | Rows per run | Key | Source in the run |
|---|---|---|---|
| `radar.source` | upsert all registry entries | `source_id` | `config/source_registry.tw.json` |
| `radar.pipeline_run` | 1 | `run_id` (= `producer_run_id`) | reconciliation counts |
| `radar.source_run` | 1 per fetched source | `(run_id, source_id)` | `source-status.json` `sites[]` |
| `radar.article` | upsert per raw discovery record | `url_hash` | raw RSS records (`fetched_raw_items`) |
| `radar.event` | upsert per published event | `event_id` (= `cluster_id`) | `theme-events.json` `items[]` |
| `radar.tracking_candidates_snapshot` | 1 (upsert) | `generated_at`, FK `run_id` | `tracking-candidates.json` verbatim; served by `/api/v1/tracking-candidates` (see `docs/TRACKING_CANDIDATES_API.md`) |

Created but not yet written: `event_impact` (WS2), `market_snapshot`,
`institutional_flow_daily`. Momentum history stays in
`theme_radar.hourly_theme_heat`.

`url_hash` is sha256 of the normalized URL (lower-case scheme/host, no
fragment, `utm_*`/`fbclid`/`gclid` removed). A re-fetch updates `title`,
`summary`, `last_fetched_at`, `last_run_id` and increments `seen_count`;
`first_*` columns never change.

`event_id` is the pipeline's `cluster_id`, a hash of the member set. When a
cluster gains a member it gets a new `event_id`, matching what the JSON
published at that moment. `event.payload` holds the exact JSON item.

## Fail-closed behaviour

- Uses the same `THEME_RADAR_DATABASE_URL` secret and workflow gate as the
  momentum history path. No credential → logs
  `radar_dual_write_skipped reason=credential_unavailable`, writes nothing.
- One transaction per run. Any error → `radar_dual_write_failed` with the
  DSN and `password=` redacted; JSON output and the run's exit code are
  unaffected.
- Run summary (stdout JSON) carries `radar_dual_write`
  (`written` / `skipped` / `failed`), `radar_articles_upserted`,
  `radar_events_upserted`.

## Deploying (per environment)

1. Apply `supabase/migrations/20261118080000_create_radar_schema.sql`
   (re-runnable). Do **not** add `radar` to PostgREST exposed schemas.
2. Grant the writer role to the login role behind `THEME_RADAR_DATABASE_URL`:

   ```sql
   grant radar_writer to <pipeline_login_role>;
   -- later, for the API:
   grant radar_reader to <api_login_role>;
   ```

3. Next scheduled run on `master` should log `radar_dual_write_reconcile`.

Rollback: `revoke radar_writer from <pipeline_login_role>;` stops all writes
immediately with no code change; JSON is unaffected. The schema can stay.

## 7-day reconciliation

`pipeline_run` has check constraints forcing
`db_article_count + duplicate_url_count = json_article_count` (and the same for
events), so a run that cannot be explained is rejected, not silently stored.

```sql
-- Daily JSON vs DB counts, last 7 days (Asia/Taipei days)
select (started_at at time zone 'Asia/Taipei')::date as day,
       count(*)                         as runs,
       sum(json_article_count)          as json_articles,
       sum(db_article_count)            as db_articles,
       sum(duplicate_url_count)         as in_run_duplicate_urls,
       sum(json_event_count)            as json_events,
       sum(db_event_count)              as db_events
from radar.pipeline_run
where started_at >= now() - interval '7 days'
group by 1 order by 1;

-- Runs whose commit landed in git but have no DB row (compare to Actions run times)
select started_at from radar.pipeline_run order by started_at desc limit 50;

-- Source health
select source_id, count(*) filter (where status = 'ok')::float / count(*) as ok_rate,
       percentile_cont(0.95) within group (order by elapsed_ms) as p95_ms
from radar.source_run
where started_at >= now() - interval '7 days'
group by 1 order by 2;
```

## Local verification

```bash
# throwaway Postgres with the migration applied, then:
RADAR_TEST_WRITER_URL="host=... dbname=... user=<granted radar_writer>" \
RADAR_TEST_READER_URL="host=... dbname=... user=<granted radar_reader>" \
.venv/bin/python -m pytest tests/test_radar_store.py -q
```

The live tests are skipped when those variables are unset (CI).
