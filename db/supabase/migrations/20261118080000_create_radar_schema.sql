-- Private `radar` schema: the Phase 1 store behind the pipeline's JSON output.
--
-- Like theme_radar and site_metrics, this schema is deliberately NOT added to
-- PostgREST's exposed schemas. Nothing here is reachable with the anon key;
-- only server-side direct-Postgres credentials granted one of the roles below
-- can read or write it.
--
-- Re-runnable: every statement is guarded (if not exists / idempotent grant),
-- so applying this file twice is a no-op. Constraints live inside the
-- `create table` so they are created exactly once with their table.
--
-- Roles (both NOLOGIN; grant them to a login role, never log in as them):
--   radar_writer  pipeline writer. SELECT/INSERT/UPDATE only, no DELETE and
--                 no DDL. ON CONFLICT DO UPDATE needs SELECT on the target.
--   radar_reader  read-only, for the server-side API (Vercel Functions).
--
-- Post-apply step (manual, per environment, not committed because the login
-- role name is environment-specific):
--   grant radar_writer to <login role behind THEME_RADAR_DATABASE_URL>;
--   grant radar_reader to <login role used by the API>;
-- Until the writer grant exists the pipeline logs radar_dual_write_failed and
-- keeps publishing JSON; nothing else changes.

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'radar_writer') then
    create role radar_writer nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'radar_reader') then
    create role radar_reader nologin;
  end if;
end
$$;

create schema if not exists radar;
alter schema radar owner to postgres;

-- Source registry mirror. Upserted from config/source_registry.tw.json each run.
create table if not exists radar.source (
  source_id text primary key,
  name text not null,
  source_class text,
  fetch_method text,
  feed_url text,
  homepage text,
  authority_rank integer,
  registry_status text not null,
  enabled boolean not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint source_id_check check (source_id <> ''),
  constraint source_authority_rank_check
    check (authority_rank is null or authority_rank >= 0)
);

-- One row per pipeline execution: the JSON-vs-DB reconciliation ledger used for
-- the 7-day dual-write comparison.
create table if not exists radar.pipeline_run (
  run_id text primary key,
  started_at timestamptz not null,
  window_hours integer not null,
  json_article_count integer not null,
  db_article_count integer not null,
  duplicate_url_count integer not null,
  json_event_count integer not null,
  db_event_count integer not null,
  duplicate_event_count integer not null,
  failed_source_count integer not null,
  created_at timestamptz not null default now(),
  constraint pipeline_run_id_check check (run_id <> ''),
  constraint pipeline_run_counts_check check (
    json_article_count >= 0 and db_article_count >= 0
    and duplicate_url_count >= 0 and json_event_count >= 0
    and db_event_count >= 0 and duplicate_event_count >= 0
    and failed_source_count >= 0
  ),
  -- Every JSON row is either written or explained as an in-run duplicate.
  constraint pipeline_run_article_reconcile_check
    check (db_article_count + duplicate_url_count = json_article_count),
  constraint pipeline_run_event_reconcile_check
    check (db_event_count + duplicate_event_count = json_event_count)
);

-- Per-source fetch outcome for one run (status, items, latency, error).
create table if not exists radar.source_run (
  run_id text not null references radar.pipeline_run (run_id),
  source_id text not null references radar.source (source_id),
  started_at timestamptz not null,
  status text not null,
  item_count integer not null,
  elapsed_ms integer,
  error text,
  detail jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  primary key (run_id, source_id),
  constraint source_run_item_count_check check (item_count >= 0),
  constraint source_run_elapsed_check check (elapsed_ms is null or elapsed_ms >= 0)
);

create index if not exists source_run_source_started_idx
  on radar.source_run (source_id, started_at desc);

-- Normalized news item. url_hash = sha256 of the normalized URL; a re-fetch of
-- the same URL updates the row instead of inserting a duplicate.
create table if not exists radar.article (
  url_hash text primary key,
  article_id text not null,
  source_id text not null references radar.source (source_id),
  source_class text,
  market_id text not null,
  url text not null,
  title text not null,
  summary text not null default '',
  extraction_method text,
  published_at timestamptz not null,
  first_fetched_at timestamptz not null,
  last_fetched_at timestamptz not null,
  first_run_id text not null,
  last_run_id text not null,
  seen_count integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint article_url_hash_check check (url_hash ~ '^[0-9a-f]{64}$'),
  constraint article_seen_count_check check (seen_count >= 1),
  constraint article_fetch_order_check check (last_fetched_at >= first_fetched_at)
);

create index if not exists article_published_idx
  on radar.article (published_at desc);
create index if not exists article_source_published_idx
  on radar.article (source_id, published_at desc);

-- Clustered event (one or more articles across sources). event_id is the
-- pipeline's cluster_id, which hashes the member set: when a cluster gains a
-- member it is a new event_id, matching what the JSON published at that time.
-- payload keeps the exact theme-events.json item so the API can serve the same
-- shape the front end validates today.
create table if not exists radar.event (
  event_id text primary key,
  representative_article_id text not null,
  representative_url_hash text not null,
  source_id text not null,
  title text not null,
  published_at timestamptz not null,
  primary_theme_id text,
  theme_score numeric,
  decision text,
  tw_relevance_status text,
  confirmation_status text,
  cluster_size integer not null,
  member_article_ids text[] not null,
  official_evidence_count integer not null default 0,
  payload jsonb not null,
  first_seen_at timestamptz not null,
  last_seen_at timestamptz not null,
  first_run_id text not null,
  last_run_id text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint event_id_check check (event_id <> ''),
  constraint event_cluster_size_check
    check (cluster_size >= 1 and cluster_size = cardinality(member_article_ids)),
  constraint event_seen_order_check check (last_seen_at >= first_seen_at)
);

create index if not exists event_published_idx
  on radar.event (published_at desc);
create index if not exists event_theme_published_idx
  on radar.event (primary_theme_id, published_at desc);

-- Event x target directional impact. Created now, written by WS2.
create table if not exists radar.event_impact (
  event_id text not null references radar.event (event_id) on delete cascade,
  target_type text not null,
  target_id text not null,
  rule_version text not null,
  path_id text,
  direction smallint not null,
  magnitude numeric not null,
  horizon text not null,
  reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (event_id, target_id, rule_version),
  constraint event_impact_target_type_check
    check (target_type in ('theme', 'sector', 'symbol', 'market')),
  constraint event_impact_direction_check check (direction in (-1, 0, 1)),
  constraint event_impact_magnitude_check check (magnitude between 0 and 1),
  constraint event_impact_horizon_check check (horizon in ('short', 'long'))
);

create index if not exists event_impact_target_idx
  on radar.event_impact (target_id, rule_version);

-- Market anchors (TAIEX, sector indices, TX futures, SOX, TSM ADR).
create table if not exists radar.market_snapshot (
  observed_at timestamptz not null,
  instrument_id text not null,
  session_date date,
  price numeric,
  change numeric,
  change_pct numeric,
  volume numeric,
  source text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (observed_at, instrument_id),
  constraint market_snapshot_instrument_check check (instrument_id <> '')
);

-- Per-symbol three-institution net buy/sell (shares). Names follow flows_store.
create table if not exists radar.institutional_flow_daily (
  trade_date date not null,
  symbol text not null,
  foreign_net bigint,
  trust_net bigint,
  dealer_net bigint,
  total_net bigint,
  source text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (trade_date, symbol),
  constraint institutional_flow_symbol_check check (symbol <> '')
);

alter table radar.source owner to postgres;
alter table radar.pipeline_run owner to postgres;
alter table radar.source_run owner to postgres;
alter table radar.article owner to postgres;
alter table radar.event owner to postgres;
alter table radar.event_impact owner to postgres;
alter table radar.market_snapshot owner to postgres;
alter table radar.institutional_flow_daily owner to postgres;

revoke all on schema radar from public;
revoke all on all tables in schema radar from public;

grant usage on schema radar to radar_writer;
grant select, insert, update on
  radar.source,
  radar.pipeline_run,
  radar.source_run,
  radar.article,
  radar.event,
  radar.event_impact,
  radar.market_snapshot,
  radar.institutional_flow_daily
  to radar_writer;

grant usage on schema radar to radar_reader;
grant select on all tables in schema radar to radar_reader;
