-- Relational store, part 1 (core + flows/broker/theme focus/source status).
--
-- Target architecture (2026-11-19): every pipeline writes normalized, typed
-- rows here and the site reads only through the Vercel API (api/v1/[dataset]).
-- No table in this file stores a whole JSON payload.
--
-- Additive only: this runs against a shared Supabase project that also holds
-- live theme_radar writes. Every statement is guarded (if not exists / create
-- or replace / idempotent grant / on conflict), so applying it twice is a no-op.
--
-- Patterns
--   * Snapshot datasets: one header row per published snapshot (unique
--     generated_at, so re-publishing the same file is a no-op) plus child rows
--     that cascade from it. A snapshot is written in one transaction, so a
--     reader sees all of it or none of it. The API serves the newest header.
--   * Time-series datasets (institutional_flow): upserted by natural key.
--   * Dimensions (instrument, broker): upserted, referenced by FK.
--   * radar_writer still has no DELETE. Old snapshots are removed by
--     radar.purge_snapshots(), a SECURITY DEFINER function that only deletes
--     from tables registered in radar.snapshot_retention.
--
-- Post-apply: nothing environment-specific. Existing grants of radar_writer /
-- radar_reader to login roles pick up the new tables through the grants below.

create schema if not exists radar;

-- ---------------------------------------------------------------- dimensions

create table if not exists radar.instrument (
  instrument_id text primary key,
  symbol text not null,
  exchange text not null,
  name_zh text not null default '',
  is_etf boolean,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint instrument_id_check check (instrument_id = exchange || ':' || symbol),
  constraint instrument_exchange_check check (exchange ~ '^[A-Z]{2,8}$'),
  constraint instrument_symbol_check check (symbol ~ '^[A-Za-z0-9]{1,10}$')
);

create table if not exists radar.broker (
  broker_id text primary key,
  name text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint broker_id_check check (broker_id <> '')
);

-- ---------------------------------------------------------------- retention

create table if not exists radar.snapshot_retention (
  header_table text primary key,
  keep_count integer not null,
  constraint snapshot_retention_table_check check (header_table ~ '^[a-z_]+$'),
  constraint snapshot_retention_keep_check check (keep_count >= 1)
);

-- ------------------------------------------- institutional flow (time series)

-- Replaces radar.institutional_flow_daily, whose key (trade_date, symbol)
-- collides across exchanges. That table is left in place, unused.
create table if not exists radar.institutional_flow (
  instrument_id text not null references radar.instrument (instrument_id),
  trade_date date not null,
  foreign_net bigint not null,
  trust_net bigint not null,
  dealer_net bigint not null,
  total_net bigint not null,
  source text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (instrument_id, trade_date)
);

create index if not exists institutional_flow_date_idx
  on radar.institutional_flow (trade_date desc);

-- ------------------------------------------------ institutional rankings

create table if not exists radar.institutional_ranking_snapshot (
  snapshot_id bigint generated always as identity primary key,
  generated_at timestamptz not null unique,
  source text,
  created_at timestamptz not null default now()
);

create table if not exists radar.institutional_ranking_board (
  snapshot_id bigint not null
    references radar.institutional_ranking_snapshot (snapshot_id) on delete cascade,
  board_key text not null,
  metric text not null,
  window_days integer not null,
  side text not null,
  unit text,
  updated_at timestamptz,
  date_start date,
  date_end date,
  source text,
  source_rows integer,
  primary key (snapshot_id, board_key),
  constraint institutional_ranking_board_side_check check (side in ('up', 'down')),
  constraint institutional_ranking_board_window_check check (window_days > 0),
  constraint institutional_ranking_board_range_check
    check ((date_start is null) = (date_end is null))
);

create table if not exists radar.institutional_ranking_entry (
  snapshot_id bigint not null,
  board_key text not null,
  position integer not null,
  instrument_id text not null references radar.instrument (instrument_id),
  in_universe boolean not null,
  ratio_out_of_range boolean,
  three_inst_ratio double precision,
  change double precision,
  rank integer,
  foreign_net bigint,
  trust_net bigint,
  dealer_net bigint,
  total_net bigint,
  days integer,
  primary key (snapshot_id, board_key, position),
  foreign key (snapshot_id, board_key)
    references radar.institutional_ranking_board (snapshot_id, board_key) on delete cascade,
  constraint institutional_ranking_entry_position_check check (position >= 0)
);

-- ------------------------------------------------------------ broker data

-- One snapshot per broker-data run: coverage, branch statistics and the
-- per-symbol branch map (formerly broker-stats.json, broker-coverage.json and
-- ~2,400 broker-map/*.json files that repeated each branch's book per symbol).
create table if not exists radar.broker_snapshot (
  snapshot_id bigint generated always as identity primary key,
  generated_at timestamptz not null unique,
  source text not null,
  source_scope text,
  source_updated date,
  map_source text,
  unit text not null,
  requested_symbols integer not null,
  attempted_symbols integer not null,
  failed_symbols integer not null,
  successful_symbols integer not null,
  symbols_with_data integer not null,
  attempt_coverage double precision not null,
  data_coverage double precision not null,
  data_coverage_denominator text not null,
  status text not null,
  created_at timestamptz not null default now()
);

create table if not exists radar.broker_coverage_code (
  snapshot_id bigint not null
    references radar.broker_snapshot (snapshot_id) on delete cascade,
  kind text not null,
  stock_code text not null,
  primary key (snapshot_id, kind, stock_code),
  constraint broker_coverage_code_kind_check
    check (kind in ('failed', 'no_data', 'not_attempted'))
);

create table if not exists radar.broker_stat (
  snapshot_id bigint not null
    references radar.broker_snapshot (snapshot_id) on delete cascade,
  position integer not null,
  broker_name text not null,
  buy bigint not null,
  sell bigint not null,
  day_trade bigint,
  overnight bigint,
  primary key (snapshot_id, position)
);

create table if not exists radar.broker_stat_top (
  snapshot_id bigint not null,
  stat_position integer not null,
  position integer not null,
  stock_code text not null,
  stock_name text not null,
  primary key (snapshot_id, stat_position, position),
  foreign key (snapshot_id, stat_position)
    references radar.broker_stat (snapshot_id, position) on delete cascade
);

create table if not exists radar.broker_symbol (
  snapshot_id bigint not null
    references radar.broker_snapshot (snapshot_id) on delete cascade,
  stock_code text not null,
  stock_name text not null,
  broker_count integer not null,
  buy bigint not null,
  sell bigint not null,
  net bigint not null,
  primary key (snapshot_id, stock_code)
);

create table if not exists radar.broker_symbol_branch (
  snapshot_id bigint not null,
  stock_code text not null,
  position integer not null,
  broker_id text not null references radar.broker (broker_id),
  net bigint not null,
  ratio double precision not null,
  primary key (snapshot_id, stock_code, position),
  foreign key (snapshot_id, stock_code)
    references radar.broker_symbol (snapshot_id, stock_code) on delete cascade
);

create index if not exists broker_symbol_branch_broker_idx
  on radar.broker_symbol_branch (snapshot_id, broker_id);

-- A branch's whole book for the day, stored once per branch.
create table if not exists radar.broker_branch_stock (
  snapshot_id bigint not null
    references radar.broker_snapshot (snapshot_id) on delete cascade,
  broker_id text not null references radar.broker (broker_id),
  position integer not null,
  stock_code text not null,
  stock_name text not null,
  net bigint not null,
  primary key (snapshot_id, broker_id, position)
);

-- ------------------------------------------------------------- theme focus

create table if not exists radar.theme_focus_snapshot (
  snapshot_id bigint generated always as identity primary key,
  generated_at timestamptz not null unique,
  schema_version text not null,
  theme_generated_at timestamptz,
  flow_as_of date,
  flow_window_days integer not null,
  unit text not null,
  flow_source text not null,
  method_focus_score text not null,
  method_hot_heat double precision not null,
  method_broad_breadth double precision not null,
  method_weak_breadth double precision not null,
  created_at timestamptz not null default now()
);

create table if not exists radar.theme_focus_theme (
  snapshot_id bigint not null
    references radar.theme_focus_snapshot (snapshot_id) on delete cascade,
  theme_id text not null,
  position integer not null,
  name_zh text not null,
  rank integer,
  focus_rank integer not null,
  heat_score double precision not null,
  momentum_score double precision,
  lifecycle_stage text,
  event_count integer,
  stance text not null,
  stance_label text not null,
  focus_score double precision not null,
  member_count integer not null,
  covered_count integer not null,
  positive_count integer not null,
  breadth double precision,
  total_5d bigint not null,
  foreign_5d bigint not null,
  trust_5d bigint not null,
  total_1d bigint not null,
  headline_title text,
  headline_source text,
  headline_published_at timestamptz,
  headline_url text,
  has_headline boolean not null,
  primary key (snapshot_id, theme_id),
  constraint theme_focus_theme_stance_check
    check (stance in ('focus', 'money_first', 'news_only', 'outflow', 'watch'))
);

create table if not exists radar.theme_focus_stock (
  snapshot_id bigint not null,
  theme_id text not null,
  role text not null,
  position integer not null,
  instrument_id text not null references radar.instrument (instrument_id),
  relation text not null,
  flow_as_of date,
  flow_days integer,
  total_5d bigint,
  foreign_5d bigint,
  trust_5d bigint,
  total_1d bigint,
  streak integer,
  short_rank integer,
  short_score double precision,
  long_rank integer,
  long_score double precision,
  primary key (snapshot_id, theme_id, role, position),
  foreign key (snapshot_id, theme_id)
    references radar.theme_focus_theme (snapshot_id, theme_id) on delete cascade,
  constraint theme_focus_stock_role_check check (role in ('leader', 'outflow')),
  constraint theme_focus_stock_relation_check check (relation in ('direct', 'related'))
);

-- ----------------------------------------------------------- source status

create table if not exists radar.source_status_snapshot (
  snapshot_id bigint generated always as identity primary key,
  generated_at timestamptz not null unique,
  fetched_raw_items integer,
  items_before_topic_filter integer,
  successful_sites integer not null,
  failed_count integer not null,
  created_at timestamptz not null default now()
);

create table if not exists radar.source_status_site (
  snapshot_id bigint not null
    references radar.source_status_snapshot (snapshot_id) on delete cascade,
  position integer not null,
  source_id text not null,
  name text not null,
  source_class text,
  adapter text,
  fetch_method text,
  status text not null,
  items integer,
  error text,
  trial boolean,
  not_modified boolean,
  runs_7d integer,
  success_rate_7d double precision,
  elapsed_ms integer,
  primary key (snapshot_id, position)
);

-- ------------------------------------------------------------- purge

insert into radar.snapshot_retention (header_table, keep_count) values
  ('institutional_ranking_snapshot', 14),
  ('broker_snapshot', 3),
  ('theme_focus_snapshot', 72),
  ('source_status_snapshot', 72)
on conflict (header_table) do nothing;

-- Deletes all but the newest keep_count snapshots of every registered header
-- table (children cascade) and institutional_flow rows older than
-- flow_keep_days. Runs as the owner so radar_writer needs no DELETE grant;
-- the table list comes from radar.snapshot_retention, never from the caller.
create or replace function radar.purge_snapshots(flow_keep_days integer default 120)
returns integer
language plpgsql
security definer
set search_path = pg_catalog, radar
as $$
declare
  spec record;
  removed integer := 0;
  n integer;
begin
  for spec in select header_table, keep_count from radar.snapshot_retention loop
    if to_regclass(format('radar.%I', spec.header_table)) is null then
      continue;
    end if;
    execute format(
      'delete from radar.%I where snapshot_id in (
         select snapshot_id from radar.%I
         order by generated_at desc, snapshot_id desc offset %s)',
      spec.header_table, spec.header_table, spec.keep_count);
    get diagnostics n = row_count;
    removed := removed + n;
  end loop;
  delete from radar.institutional_flow
   where trade_date < current_date - greatest(flow_keep_days, 30);
  get diagnostics n = row_count;
  return removed + n;
end
$$;

-- ------------------------------------------------------------- ownership/grants

alter table radar.instrument owner to postgres;
alter table radar.broker owner to postgres;
alter table radar.snapshot_retention owner to postgres;
alter table radar.institutional_flow owner to postgres;
alter table radar.institutional_ranking_snapshot owner to postgres;
alter table radar.institutional_ranking_board owner to postgres;
alter table radar.institutional_ranking_entry owner to postgres;
alter table radar.broker_snapshot owner to postgres;
alter table radar.broker_coverage_code owner to postgres;
alter table radar.broker_stat owner to postgres;
alter table radar.broker_stat_top owner to postgres;
alter table radar.broker_symbol owner to postgres;
alter table radar.broker_symbol_branch owner to postgres;
alter table radar.broker_branch_stock owner to postgres;
alter table radar.theme_focus_snapshot owner to postgres;
alter table radar.theme_focus_theme owner to postgres;
alter table radar.theme_focus_stock owner to postgres;
alter table radar.source_status_snapshot owner to postgres;
alter table radar.source_status_site owner to postgres;
alter function radar.purge_snapshots(integer) owner to postgres;

revoke all on
  radar.instrument, radar.broker, radar.snapshot_retention,
  radar.institutional_flow,
  radar.institutional_ranking_snapshot, radar.institutional_ranking_board,
  radar.institutional_ranking_entry,
  radar.broker_snapshot, radar.broker_coverage_code, radar.broker_stat,
  radar.broker_stat_top, radar.broker_symbol, radar.broker_symbol_branch,
  radar.broker_branch_stock,
  radar.theme_focus_snapshot, radar.theme_focus_theme, radar.theme_focus_stock,
  radar.source_status_snapshot, radar.source_status_site
  from public;
revoke all on function radar.purge_snapshots(integer) from public;

grant usage on schema radar to radar_writer, radar_reader;

grant select, insert, update on
  radar.instrument, radar.broker, radar.institutional_flow,
  radar.institutional_ranking_snapshot, radar.institutional_ranking_board,
  radar.institutional_ranking_entry,
  radar.broker_snapshot, radar.broker_coverage_code, radar.broker_stat,
  radar.broker_stat_top, radar.broker_symbol, radar.broker_symbol_branch,
  radar.broker_branch_stock,
  radar.theme_focus_snapshot, radar.theme_focus_theme, radar.theme_focus_stock,
  radar.source_status_snapshot, radar.source_status_site
  to radar_writer;
grant select on radar.snapshot_retention to radar_writer;
grant execute on function radar.purge_snapshots(integer) to radar_writer;

grant select on
  radar.instrument, radar.broker, radar.institutional_flow,
  radar.institutional_ranking_snapshot, radar.institutional_ranking_board,
  radar.institutional_ranking_entry,
  radar.broker_snapshot, radar.broker_coverage_code, radar.broker_stat,
  radar.broker_stat_top, radar.broker_symbol, radar.broker_symbol_branch,
  radar.broker_branch_stock,
  radar.theme_focus_snapshot, radar.theme_focus_theme, radar.theme_focus_stock,
  radar.source_status_snapshot, radar.source_status_site
  to radar_reader;
