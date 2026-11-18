-- High-frequency ingest (issue #7): bookkeeping columns + the pg_cron entry point.
--
-- Re-runnable. Creates no schedule and stores no secret: the cron jobs and the
-- Vault secrets are an operational switch applied by hand per environment from
-- supabase/manual/radar_ingest_schedule.sql (see docs/INGEST_SCHEDULER.md), so
-- applying this migration changes nothing at runtime on its own.
--
-- The hourly writer never references the new columns (its INSERT is unchanged
-- and the defaults below fill them), so this migration can land before or
-- after the code without breaking the hourly dual-write.

alter table radar.pipeline_run
  add column if not exists run_kind text not null default 'hourly',
  add column if not exists ingest_group text,
  add column if not exists elapsed_ms integer;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'pipeline_run_kind_check'
      and conrelid = 'radar.pipeline_run'::regclass
  ) then
    alter table radar.pipeline_run
      add constraint pipeline_run_kind_check check (
        run_kind in ('hourly', 'ingest')
        and (run_kind = 'ingest') = (ingest_group is not null)
        and (elapsed_ms is null or elapsed_ms >= 0)
      );
  end if;
end
$$;

create index if not exists pipeline_run_kind_started_idx
  on radar.pipeline_run (run_kind, ingest_group, started_at desc);

-- Latency KPI (article published -> first in DB) is computed from
-- article.first_run_id; index it so the 7-day p95 query stays cheap.
create index if not exists article_first_run_idx
  on radar.article (first_run_id);

-- pg_cron entry point. Reads the endpoint and shared secret from Supabase
-- Vault at call time, so neither ever appears in this file, in cron.job, or in
-- cron.job_run_details (which only records the statement `select
-- radar.invoke_ingest('tw-news-a')`).
--
-- pg_net is asynchronous: this returns the request id immediately and the
-- response lands in net._http_response (kept ~6h). The function's own
-- outcome is recorded in radar.pipeline_run / radar.source_run.
--
-- SECURITY DEFINER so the cron job can read Vault without granting the
-- scheduling role vault access in general; search_path is pinned and EXECUTE
-- is revoked from everyone except the owner.
create or replace function radar.invoke_ingest(p_group text)
returns bigint
language plpgsql
security definer
set search_path = pg_catalog, pg_temp
as $$
declare
  v_base_url text;
  v_secret text;
  v_bypass text;
  v_headers jsonb;
  v_request_id bigint;
begin
  if p_group is null or p_group !~ '^[a-z0-9][a-z0-9-]{0,39}$' then
    raise exception 'invalid ingest group';
  end if;

  select decrypted_secret into v_base_url
    from vault.decrypted_secrets where name = 'radar_ingest_base_url';
  select decrypted_secret into v_secret
    from vault.decrypted_secrets where name = 'radar_ingest_cron_secret';
  select decrypted_secret into v_bypass
    from vault.decrypted_secrets where name = 'radar_ingest_vercel_bypass';

  if v_base_url is null or v_secret is null then
    raise exception 'radar ingest vault secrets are not configured';
  end if;

  v_headers := jsonb_build_object('Authorization', 'Bearer ' || v_secret);
  -- Only needed if Vercel Deployment Protection covers the production URL.
  if v_bypass is not null and v_bypass <> '' then
    v_headers := v_headers || jsonb_build_object('x-vercel-protection-bypass', v_bypass);
  end if;

  select net.http_get(
    url := rtrim(v_base_url, '/') || '/api/cron/ingest',
    params := jsonb_build_object('group', p_group),
    headers := v_headers,
    timeout_milliseconds := 60000
  ) into v_request_id;

  return v_request_id;
end
$$;

alter function radar.invoke_ingest(text) owner to postgres;
revoke all on function radar.invoke_ingest(text) from public;

-- Supabase's API roles get EXECUTE through default privileges in some
-- schemas; strip it explicitly where those roles exist.
do $$
declare
  r text;
begin
  foreach r in array array['anon', 'authenticated', 'service_role', 'radar_writer', 'radar_reader'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('revoke all on function radar.invoke_ingest(text) from %I', r);
    end if;
  end loop;
end
$$;
