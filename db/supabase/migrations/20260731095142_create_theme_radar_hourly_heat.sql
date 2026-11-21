-- Private history source for the server-side Theme Momentum projection.
-- This schema is intentionally not added to PostgREST's exposed schemas.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'theme_radar_writer') then
    create role theme_radar_writer nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'theme_radar_materializer') then
    create role theme_radar_materializer nologin;
  end if;
end
$$;

create schema if not exists theme_radar;
alter schema theme_radar owner to postgres;

create table theme_radar.hourly_theme_heat (
  observed_at timestamptz not null,
  theme_id text not null,
  heat_score smallint not null,
  rank smallint,
  qualification_status text not null,
  near_threshold_reason text,
  momentum_score smallint not null,
  lifecycle_stage text not null,
  event_count integer not null,
  source_count integer not null,
  tracking_candidate_count integer not null,
  taiwan_mapping_count integer not null,
  direct_mapping_event_count integer not null,
  single_source_concentration numeric not null,
  latest_qualifying_event_at timestamptz,
  heat_rule_version text not null,
  momentum_rule_version text not null,
  inclusion_rule_version text not null,
  schema_version text not null,
  producer_run_id text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (observed_at, theme_id),
  constraint hourly_theme_heat_exact_hour_check
    check (observed_at = date_trunc('hour', observed_at)),
  constraint hourly_theme_heat_heat_score_check
    check (heat_score between 0 and 100),
  constraint hourly_theme_heat_momentum_score_check
    check (momentum_score between 0 and 100),
  constraint hourly_theme_heat_rank_check
    check (rank is null or rank > 0),
  constraint hourly_theme_heat_event_count_check
    check (event_count >= 0),
  constraint hourly_theme_heat_source_count_check
    check (source_count >= 0),
  constraint hourly_theme_heat_candidate_count_check
    check (tracking_candidate_count >= 0),
  constraint hourly_theme_heat_mapping_count_check
    check (taiwan_mapping_count >= 0),
  constraint hourly_theme_heat_direct_count_check
    check (direct_mapping_event_count between 0 and event_count),
  constraint hourly_theme_heat_concentration_check
    check (single_source_concentration between 0 and 1),
  constraint hourly_theme_heat_qualification_check
    check (qualification_status in ('qualified', 'near_threshold')),
  constraint hourly_theme_heat_reason_check
    check (
      (qualification_status = 'qualified' and near_threshold_reason is null)
      or (
        qualification_status = 'near_threshold'
        and near_threshold_reason in ('events_1_of_2', 'sources_1_of_2')
      )
    ),
  constraint hourly_theme_heat_lifecycle_check
    check (lifecycle_stage in ('new', 'accelerating', 'cooling', 'rising', 'steady')),
  constraint hourly_theme_heat_run_id_check
    check (producer_run_id <> ''),
  constraint hourly_theme_heat_version_check
    check (
      heat_rule_version = 'public_theme_heat_v0.8'
      and momentum_rule_version = 'public_theme_momentum_v0.9'
      and inclusion_rule_version = 'public_theme_momentum_inclusion_v0.9'
      and schema_version = 'theme_radar_hourly_theme_heat.v0.9'
    )
);

alter table theme_radar.hourly_theme_heat owner to postgres;

create index hourly_theme_heat_theme_observed_idx
  on theme_radar.hourly_theme_heat (theme_id, observed_at desc);

create index hourly_theme_heat_observed_rank_idx
  on theme_radar.hourly_theme_heat (observed_at desc, rank)
  where rank is not null;

revoke all on schema theme_radar from public;
revoke all on theme_radar.hourly_theme_heat from public;

grant usage on schema theme_radar to theme_radar_writer;
grant select, insert, update, delete
  on theme_radar.hourly_theme_heat to theme_radar_writer;

grant usage on schema theme_radar to theme_radar_materializer;
grant select on theme_radar.hourly_theme_heat to theme_radar_materializer;
