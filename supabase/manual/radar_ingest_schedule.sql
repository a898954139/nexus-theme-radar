-- Operational switch for high-frequency ingest (issue #7). NOT a migration.
--
-- Run by hand in the Supabase SQL editor, one section at a time, after:
--   1. supabase/migrations/20261118090100_radar_ingest_scheduler.sql is applied
--   2. the Vercel deployment serving /api/cron/ingest is live with
--      RADAR_INGEST_CRON_SECRET and RADAR_INGEST_DATABASE_URL set
-- Full runbook: docs/INGEST_SCHEDULER.md
--
-- Never commit this file with real values filled in. Placeholders are <...>.

-- ---------------------------------------------------------------------------
-- 1. Extensions (or enable pg_cron + pg_net under Database > Extensions)
-- ---------------------------------------------------------------------------
create extension if not exists pg_cron;
create extension if not exists pg_net;

-- ---------------------------------------------------------------------------
-- 2. Vault secrets. The cron secret must equal Vercel's RADAR_INGEST_CRON_SECRET
--    (>= 32 chars; e.g. `openssl rand -hex 32`). The base URL is the production
--    domain without a trailing path, e.g. https://<your-project>.vercel.app
-- ---------------------------------------------------------------------------
select vault.create_secret('<https://your-production-domain>', 'radar_ingest_base_url', 'Vercel base URL for radar ingest');
select vault.create_secret('<same value as RADAR_INGEST_CRON_SECRET>', 'radar_ingest_cron_secret', 'Shared secret for /api/cron/ingest');
-- Only if Vercel Deployment Protection covers the production URL:
-- select vault.create_secret('<Protection Bypass for Automation secret>', 'radar_ingest_vercel_bypass', 'Vercel protection bypass');

-- Rotate later with:
-- select vault.update_secret(
--   (select id from vault.secrets where name = 'radar_ingest_cron_secret'),
--   '<new value>');

-- ---------------------------------------------------------------------------
-- 3. Smoke test one call, then read the response (pg_net is async; wait ~30s)
-- ---------------------------------------------------------------------------
select radar.invoke_ingest('tw-news-a');

select id, status_code, left(content, 400) as body, error_msg, created
from net._http_response
order by id desc
limit 5;
-- Expect status_code 200 and "result": "written" (or "nothing_due").

-- ---------------------------------------------------------------------------
-- 4. Schedules: every 5 minutes, staggered by one minute so the three
--    functions never cold-start in the same second. cron.schedule with an
--    existing job name updates it, so re-running this section is safe.
-- ---------------------------------------------------------------------------
select cron.schedule('radar-ingest-tw-news-a',   '*/5 * * * *',    $$select radar.invoke_ingest('tw-news-a')$$);
select cron.schedule('radar-ingest-tw-news-b',   '1-59/5 * * * *', $$select radar.invoke_ingest('tw-news-b')$$);
select cron.schedule('radar-ingest-global-wire', '2-59/5 * * * *', $$select radar.invoke_ingest('global-wire')$$);

-- Purge pg_cron's own run log daily so it cannot grow without bound
-- (3 jobs x 288 runs/day).
select cron.schedule('radar-ingest-purge-cron-log', '17 3 * * *',
  $$delete from cron.job_run_details where end_time < now() - interval '7 days'$$);

-- ---------------------------------------------------------------------------
-- ROLLBACK: stop all scheduled calls immediately. The hourly GitHub Actions
-- run is unaffected and keeps publishing JSON and mirroring to the DB.
-- ---------------------------------------------------------------------------
-- select cron.unschedule('radar-ingest-tw-news-a');
-- select cron.unschedule('radar-ingest-tw-news-b');
-- select cron.unschedule('radar-ingest-global-wire');
-- select cron.unschedule('radar-ingest-purge-cron-log');
