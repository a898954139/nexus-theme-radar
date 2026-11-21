-- Relational store, part 2: theme events, theme ranking, theme momentum.
-- See docs/RADAR_RELATIONAL.md. Additive and re-runnable, like part 1
-- (20261119150000_create_radar_relational_core.sql, which must run first).
--
-- Fields the pipeline emits only as run diagnostics (match / relevance
-- distributions, per-signal lists, heat_reason breakdowns, per-symbol
-- fundamentals copies) are not stored: no page reads them and the inputs they
-- summarize are stored here.

-- ------------------------------------------------------------ theme events

create table if not exists radar.theme_event_snapshot (
  snapshot_id bigint generated always as identity primary key,
  generated_at timestamptz not null unique,
  market_id text not null,
  window_hours integer not null,
  max_items integer,
  total_items integer not null,
  total_items_available integer,
  taxonomy_version text,
  created_at timestamptz not null default now()
);

create table if not exists radar.theme_event_item (
  snapshot_id bigint not null
    references radar.theme_event_snapshot (snapshot_id) on delete cascade,
  position integer not null,
  article_id text not null,
  cluster_id text,
  title_zh text not null,
  summary text not null,
  source text not null,
  source_id text not null,
  source_class text,
  published_at timestamptz not null,
  url text,
  extraction_method text,
  fetched_at timestamptz,
  primary_theme_id text,
  theme_score double precision,
  decision text,
  tw_relevance_status text,
  tw_relevance_reason text,
  confirmation_status text,
  cluster_size integer,
  official_evidence_count integer,
  primary key (snapshot_id, position)
);

create index if not exists theme_event_item_theme_idx
  on radar.theme_event_item (snapshot_id, primary_theme_id);

create table if not exists radar.theme_event_theme (
  snapshot_id bigint not null,
  event_position integer not null,
  position integer not null,
  theme_id text not null,
  name_zh text not null,
  score double precision,
  reason text,
  primary key (snapshot_id, event_position, position),
  foreign key (snapshot_id, event_position)
    references radar.theme_event_item (snapshot_id, position) on delete cascade
);

create table if not exists radar.theme_event_symbol (
  snapshot_id bigint not null,
  event_position integer not null,
  role text not null,
  position integer not null,
  instrument_id text not null references radar.instrument (instrument_id),
  evidence text,
  reason text,
  primary key (snapshot_id, event_position, role, position),
  foreign key (snapshot_id, event_position)
    references radar.theme_event_item (snapshot_id, position) on delete cascade,
  constraint theme_event_symbol_role_check check (role in ('direct', 'related'))
);

create table if not exists radar.theme_event_source (
  snapshot_id bigint not null,
  event_position integer not null,
  position integer not null,
  source_id text not null,
  source text not null,
  title text not null,
  url text,
  published_at timestamptz,
  primary key (snapshot_id, event_position, position),
  foreign key (snapshot_id, event_position)
    references radar.theme_event_item (snapshot_id, position) on delete cascade
);

-- ----------------------------------------------------------- theme ranking

create table if not exists radar.theme_ranking_snapshot (
  snapshot_id bigint generated always as identity primary key,
  generated_at timestamptz not null unique,
  schema_version text not null,
  ranking_rule_version text not null,
  company_rule_version text,
  market_id text not null,
  window_hours integer not null,
  max_themes integer,
  qualified_theme_count integer,
  displayed_theme_count integer,
  threshold_note text,
  generation_status text,
  failed_source_count integer,
  official_evidence_status text,
  created_at timestamptz not null default now()
);

create table if not exists radar.theme_ranking_theme (
  snapshot_id bigint not null
    references radar.theme_ranking_snapshot (snapshot_id) on delete cascade,
  theme_id text not null,
  rank integer not null,
  name_zh text not null,
  heat_score double precision not null,
  event_count integer,
  source_count integer,
  tracking_candidate_count integer,
  taiwan_mapping_count integer,
  news_id text,
  news_cluster_id text,
  news_title_zh text,
  news_summary text,
  news_source_id text,
  news_source text,
  news_published_at timestamptz,
  news_url text,
  primary key (snapshot_id, theme_id)
);

create table if not exists radar.theme_ranking_symbol (
  snapshot_id bigint not null,
  theme_id text not null,
  role text not null,
  position integer not null,
  instrument_id text not null references radar.instrument (instrument_id),
  direct_event_count integer,
  official_evidence_count integer,
  company_rank_score double precision,
  latest_mentioned_at timestamptz,
  latest_official_at timestamptz,
  primary key (snapshot_id, theme_id, role, position),
  foreign key (snapshot_id, theme_id)
    references radar.theme_ranking_theme (snapshot_id, theme_id) on delete cascade,
  constraint theme_ranking_symbol_role_check check (role in ('direct', 'supply_chain'))
);

-- ------------------------------------------------- theme momentum (latest)

create table if not exists radar.theme_momentum_snapshot (
  snapshot_id bigint generated always as identity primary key,
  generated_at timestamptz not null unique,
  observed_hour timestamptz not null,
  schema_version text not null,
  ranking_rule_version text not null,
  inclusion_rule_version text,
  heat_rule_version text,
  market_id text not null,
  window_hours integer not null,
  freshness_status text,
  theme_count integer not null,
  created_at timestamptz not null default now()
);

create table if not exists radar.theme_momentum_theme (
  snapshot_id bigint not null
    references radar.theme_momentum_snapshot (snapshot_id) on delete cascade,
  theme_id text not null,
  rank integer not null,
  name_zh text not null,
  qualification_status text not null,
  near_threshold_reason text,
  momentum_score double precision not null,
  lifecycle_stage text not null,
  heat_score double precision not null,
  heat_change_24h double precision,
  source_change_24h double precision,
  event_count integer,
  source_count integer,
  tracking_candidate_count integer,
  taiwan_mapping_count integer,
  direct_mapping_event_count integer,
  single_source_concentration double precision,
  latest_qualifying_event_at timestamptz,
  news_id text,
  news_title_zh text,
  news_summary text,
  news_source_id text,
  news_source text,
  news_published_at timestamptz,
  news_url text,
  primary key (snapshot_id, theme_id)
);

create table if not exists radar.theme_momentum_symbol (
  snapshot_id bigint not null,
  theme_id text not null,
  role text not null,
  position integer not null,
  instrument_id text not null references radar.instrument (instrument_id),
  evidence text,
  reason text,
  primary key (snapshot_id, theme_id, role, position),
  foreign key (snapshot_id, theme_id)
    references radar.theme_momentum_theme (snapshot_id, theme_id) on delete cascade,
  constraint theme_momentum_symbol_role_check check (role in ('direct', 'related'))
);

-- ------------------------------------------- theme momentum (hourly series)

create table if not exists radar.theme_momentum_hourly (
  observed_hour timestamptz not null,
  theme_id text not null,
  rank integer not null,
  qualification_status text not null,
  near_threshold_reason text,
  momentum_score double precision not null,
  lifecycle_stage text not null,
  heat_score double precision not null,
  event_count integer,
  source_count integer,
  tracking_candidate_count integer,
  taiwan_mapping_count integer,
  direct_mapping_event_count integer,
  single_source_concentration double precision,
  latest_qualifying_event_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (observed_hour, theme_id)
);

-- ------------------------------------------------------------ retention

insert into radar.snapshot_retention (header_table, keep_count) values
  ('theme_event_snapshot', 48),
  ('theme_ranking_snapshot', 72),
  ('theme_momentum_snapshot', 72)
on conflict (header_table) do nothing;

-- Time-series retention registry (time column must be a date or timestamptz).
create table if not exists radar.series_retention (
  series_table text primary key,
  time_column text not null,
  keep_days integer not null,
  constraint series_retention_table_check check (series_table ~ '^[a-z_]+$'),
  constraint series_retention_column_check check (time_column ~ '^[a-z_]+$'),
  constraint series_retention_keep_check check (keep_days >= 30)
);

insert into radar.series_retention (series_table, time_column, keep_days) values
  ('institutional_flow', 'trade_date', 120),
  ('theme_momentum_hourly', 'observed_hour', 60)
on conflict (series_table) do nothing;

-- Same signature as part 1 (grants are kept by create or replace). The
-- argument is retained for compatibility and no longer used: series
-- retention now comes from radar.series_retention.
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
  for spec in select series_table, time_column, keep_days from radar.series_retention loop
    if to_regclass(format('radar.%I', spec.series_table)) is null then
      continue;
    end if;
    execute format('delete from radar.%I where %I < date_trunc(''day'', now()) - make_interval(days => %s)',
      spec.series_table, spec.time_column, spec.keep_days);
    get diagnostics n = row_count;
    removed := removed + n;
  end loop;
  return removed;
end
$$;

-- ------------------------------------------------------------- ownership/grants

alter table radar.theme_event_snapshot owner to postgres;
alter table radar.theme_event_item owner to postgres;
alter table radar.theme_event_theme owner to postgres;
alter table radar.theme_event_symbol owner to postgres;
alter table radar.theme_event_source owner to postgres;
alter table radar.theme_ranking_snapshot owner to postgres;
alter table radar.theme_ranking_theme owner to postgres;
alter table radar.theme_ranking_symbol owner to postgres;
alter table radar.theme_momentum_snapshot owner to postgres;
alter table radar.theme_momentum_theme owner to postgres;
alter table radar.theme_momentum_symbol owner to postgres;
alter table radar.theme_momentum_hourly owner to postgres;
alter table radar.series_retention owner to postgres;
alter function radar.purge_snapshots(integer) owner to postgres;

revoke all on
  radar.theme_event_snapshot, radar.theme_event_item, radar.theme_event_theme,
  radar.theme_event_symbol, radar.theme_event_source,
  radar.theme_ranking_snapshot, radar.theme_ranking_theme, radar.theme_ranking_symbol,
  radar.theme_momentum_snapshot, radar.theme_momentum_theme, radar.theme_momentum_symbol,
  radar.theme_momentum_hourly, radar.series_retention
  from public;
revoke all on function radar.purge_snapshots(integer) from public;

grant select, insert, update on
  radar.theme_event_snapshot, radar.theme_event_item, radar.theme_event_theme,
  radar.theme_event_symbol, radar.theme_event_source,
  radar.theme_ranking_snapshot, radar.theme_ranking_theme, radar.theme_ranking_symbol,
  radar.theme_momentum_snapshot, radar.theme_momentum_theme, radar.theme_momentum_symbol,
  radar.theme_momentum_hourly
  to radar_writer;
grant select on radar.series_retention to radar_writer;
grant execute on function radar.purge_snapshots(integer) to radar_writer;

grant select on
  radar.theme_event_snapshot, radar.theme_event_item, radar.theme_event_theme,
  radar.theme_event_symbol, radar.theme_event_source,
  radar.theme_ranking_snapshot, radar.theme_ranking_theme, radar.theme_ranking_symbol,
  radar.theme_momentum_snapshot, radar.theme_momentum_theme, radar.theme_momentum_symbol,
  radar.theme_momentum_hourly
  to radar_reader;
