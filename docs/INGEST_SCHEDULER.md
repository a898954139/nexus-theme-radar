# High-frequency ingest scheduler (issue #7)

GitHub Actions `schedule` fires every 4–8 hours in practice, not hourly. News
ingestion therefore moves to a scheduler that reliably runs every 5 minutes and
writes straight to the private `radar` schema.

```
Supabase pg_cron ──(every 5 min, staggered)──► radar.invoke_ingest('<group>')
        │  reads base URL + secret from Supabase Vault
        ▼
pg_net HTTP GET  /api/cron/ingest?group=<group>   Authorization: Bearer <secret>
        ▼
Vercel Python Function (Hobby, maxDuration 60s)
  1. 401 unless the bearer secret matches RADAR_INGEST_CRON_SECRET
  2. read last fetch per source from radar.source_run → skip sources still
     inside their min interval (counts the hourly GitHub run's fetches too)
  3. fetch due sources concurrently, 40s budget for the whole group
  4. one transaction: radar.source, radar.pipeline_run (run_kind='ingest'),
     radar.source_run (status, items, elapsed_ms, error), radar.article (upsert)
```

Vercel Hobby cron only runs once a day, which is why the trigger lives in
Supabase. Fly.io/Railway remain the fallback only if pg_cron proves unworkable.

## What moved and what did not

| Work | Where it runs now |
|---|---|
| RSS news fetch (`tw-news-a`, `tw-news-b`) → `radar.article` | Vercel, every 5 min |
| FinancialJuice wire (`global-wire`) → `radar.article` | Vercel, every 5 min (the feed only retains ~10h) |
| Event clustering, theme scoring, MOPS, JSON publish | Hourly GitHub Actions, unchanged |
| Pre-market board build (translation, quotes, focus events) | GitHub Actions, unchanged |
| Broker / institutional flows (daily, long-running) | GitHub Actions, unchanged |

Groups and per-source minimum intervals live in
[`config/ingest_groups.tw.json`](../config/ingest_groups.tw.json). A source may
belong to only one group (enforced by `load_ingest_config`). New RSS sources
(e.g. issue #3) are added to the registry first, then to a group.

## Manual setup (owner, per environment)

Nothing below is automated; no secret is in the repo.

### 1. Database roles

```sql
-- Supabase SQL editor. Generate passwords locally, store them only in Vercel.
create role radar_ingest_login login password '<generate>';
grant radar_writer to radar_ingest_login;

create role radar_api login password '<generate>';
grant radar_reader to radar_api;
```

### 2. Migration

Apply `supabase/migrations/20261118090100_radar_ingest_scheduler.sql`
(re-runnable). It only adds `pipeline_run.run_kind / ingest_group / elapsed_ms`,
two indexes and the `radar.invoke_ingest(text)` function. It schedules nothing.

### 3. Vercel project (Settings → Environment Variables, Production only)

| Name | Value |
|---|---|
| `RADAR_INGEST_CRON_SECRET` | `openssl rand -hex 32` (≥ 32 chars, else the endpoint answers 503) |
| `RADAR_INGEST_DATABASE_URL` | Supavisor **transaction** pooler URL (port 6543) for `radar_ingest_login.<project-ref>` |
| `RADAR_API_DATABASE_URL` | same, for `radar_api.<project-ref>` |

The pooler URL is needed because Vercel Functions are IPv4-only and the direct
DB host is IPv6. Prepared statements are disabled in code, so transaction mode
is safe. Redeploy after setting the variables.

Check: `curl -i https://<domain>/api/cron/ingest?group=tw-news-a` → **401**.

If Deployment Protection covers production (issue #5), create a *Protection
Bypass for Automation* secret and store it in Vault as
`radar_ingest_vercel_bypass` (step 4); `invoke_ingest` adds the header.

### 4. Supabase schedule

Run [`supabase/manual/radar_ingest_schedule.sql`](../supabase/manual/radar_ingest_schedule.sql)
section by section: enable `pg_cron` + `pg_net`, create the Vault secrets, smoke
test one call, then create the three staggered schedules.

## Verifying (7-day acceptance)

```sql
-- p95 latency, source publish -> first in DB, for articles first seen by ingest.
-- Starts at the first ingest run so each feed's initial backlog is excluded.
with start as (
  select min(started_at) as t from radar.pipeline_run where run_kind = 'ingest'
)
select a.source_id,
       count(*) as articles,
       round(percentile_cont(0.95) within group (
         order by extract(epoch from a.first_fetched_at - a.published_at) / 60
       )::numeric, 1) as p95_minutes
from radar.article a
join radar.pipeline_run p on p.run_id = a.first_run_id and p.run_kind = 'ingest'
cross join start
where a.published_at >= start.t
  and a.first_fetched_at >= now() - interval '7 days'
  and a.first_fetched_at >= a.published_at
group by rollup (a.source_id)
order by a.source_id nulls last;

-- Group duration vs the 60s Hobby limit
select ingest_group, count(*) as runs,
       percentile_cont(0.95) within group (order by elapsed_ms) as p95_ms,
       max(elapsed_ms) as max_ms
from radar.pipeline_run
where run_kind = 'ingest' and started_at >= now() - interval '7 days'
group by 1 order by 1;

-- Failures per source (also on the 源狀態 page via /api/source-health)
select source_id, count(*) filter (where status <> 'ok') as failures,
       count(*) as runs, max(started_at) filter (where status = 'ok') as last_ok
from radar.source_run
where started_at >= now() - interval '7 days'
group by 1 order by failures desc;

-- Calls that never reached the function (DNS, 401, 5xx, timeouts). ~6h retention.
select id, status_code, error_msg, left(content, 200), created
from net._http_response where status_code is distinct from 200
order by id desc limit 20;
```

Caveats: an RSS entry with no date is stamped with its fetch time, so it counts
as zero latency; a feed that itself publishes late is outside our control and
shows up per source in the first query.

## Cut-over (separate PR, after 7 stable days)

Remove the RSS sources from the hourly run's fetch (or keep it reading the DB)
and drop the `schedule:` block from `.github/workflows/update-theme-radar.yml`,
keeping `workflow_dispatch`. Until then both paths run; the min-interval check
counts the hourly run's fetches, so the feeds see no extra burst.

## Rollback

```sql
select cron.unschedule('radar-ingest-tw-news-a');
select cron.unschedule('radar-ingest-tw-news-b');
select cron.unschedule('radar-ingest-global-wire');
```

Calls stop immediately. The hourly GitHub Actions run never depended on this
path and keeps publishing JSON and mirroring to the DB. For a harder stop,
`revoke radar_writer from radar_ingest_login;` or delete
`RADAR_INGEST_CRON_SECRET` in Vercel (endpoint then answers 503).
