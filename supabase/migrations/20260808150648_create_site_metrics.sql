-- Visitor counter storage for the public site's StatusBar.
--
-- Like theme_radar, this schema is deliberately kept out of PostgREST's exposed
-- schemas. The site is fully static, so a browser holding an anon key could
-- loop inserts forever; instead the pageview Edge Function is the only reader
-- and writer, which is what makes per-IP rate limiting expressible at all --
-- an RLS policy cannot see the caller's IP.

create schema if not exists site_metrics;
alter schema site_metrics owner to postgres;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'site_metrics_writer') then
    create role site_metrics_writer nologin;
  end if;
end
$$;

-- One row per counted visit. Deduplication happens in the Edge Function, which
-- refuses a second insert for the same visitor inside the dedup window.
create table if not exists site_metrics.page_view (
  id bigint generated always as identity primary key,
  visitor_id uuid not null,
  -- Assigned server-side. Clients never send a time, so they cannot backdate
  -- rows or push them into the future.
  viewed_at timestamptz not null default now()
);

alter table site_metrics.page_view owner to postgres;

create index if not exists page_view_visitor_recent_idx
  on site_metrics.page_view (visitor_id, viewed_at desc);

-- One row per visitor, upserted on each heartbeat. Keeping it keyed by visitor
-- rather than appending means the table cannot grow without bound and "online"
-- stays a cheap indexed count instead of a widening count(distinct).
create table if not exists site_metrics.heartbeat (
  visitor_id uuid primary key,
  last_seen_at timestamptz not null default now()
);

alter table site_metrics.heartbeat owner to postgres;

create index if not exists heartbeat_last_seen_idx
  on site_metrics.heartbeat (last_seen_at desc);

-- Per-IP request log backing the rate limit. Rows outside the window are
-- deleted by the Edge Function on write, so this also stays bounded.
create table if not exists site_metrics.rate_limit (
  id bigint generated always as identity primary key,
  client_ip inet not null,
  requested_at timestamptz not null default now()
);

alter table site_metrics.rate_limit owner to postgres;

create index if not exists rate_limit_ip_requested_idx
  on site_metrics.rate_limit (client_ip, requested_at desc);

revoke all on schema site_metrics from public;
revoke all on site_metrics.page_view from public;
revoke all on site_metrics.heartbeat from public;
revoke all on site_metrics.rate_limit from public;

grant usage on schema site_metrics to site_metrics_writer;
grant select, insert, delete on site_metrics.page_view to site_metrics_writer;
grant select, insert, update, delete on site_metrics.heartbeat to site_metrics_writer;
grant select, insert, delete on site_metrics.rate_limit to site_metrics_writer;
grant usage on all sequences in schema site_metrics to site_metrics_writer;
