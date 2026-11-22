-- Moat screen report (job/scripts/moat_screen.py, rule moat_v1), one snapshot
-- per hourly watchlist run (same generated_at as radar.watchlist_snapshot).
-- Shown on the stock radar page: the rules and thresholds, each candidate's
-- four metrics against them, and why a name was dropped.
-- Additive and re-runnable. Until this runs, the hourly job's moat-screen
-- publish fails without --require (log: radar_publish_failed dataset=moat-screen)
-- and the page hides the report; nothing else is affected.

create table if not exists radar.moat_screen_snapshot (
  snapshot_id bigint generated always as identity primary key,
  generated_at timestamptz not null unique,
  rule_version text not null,
  roe_ttm_min double precision not null,
  gross_margin_4q_min double precision not null,
  debt_ratio_max double precision not null,
  operating_cash_flow_ttm_min_exclusive double precision not null,
  universe_evaluated integer not null,
  universe_short_pass integer not null,
  universe_long_pass integer not null,
  candidate_count integer not null,
  candidate_evaluated integer not null,
  candidate_short_pass integer not null,
  candidate_long_pass integer not null,
  candidate_no_fundamentals integer not null,
  created_at timestamptz not null default now()
);

-- One row per rule: whether it gates each horizon, and the distribution of the
-- metric over the whole fundamentals universe (the basis for the threshold).
create table if not exists radar.moat_screen_rule (
  snapshot_id bigint not null
    references radar.moat_screen_snapshot (snapshot_id) on delete cascade,
  rule text not null,
  position integer not null,
  in_short boolean not null,
  in_long boolean not null,
  universe_p25 double precision,
  universe_p50 double precision,
  universe_p75 double precision,
  universe_failed integer not null,
  universe_missing integer not null,
  primary key (snapshot_id, rule),
  constraint moat_screen_rule_check check (rule in (
    'roe_ttm', 'gross_margin_4q', 'debt_ratio', 'operating_cash_flow_ttm'))
);

-- Every theme candidate of the hour, passed or not.
create table if not exists radar.moat_screen_candidate (
  snapshot_id bigint not null
    references radar.moat_screen_snapshot (snapshot_id) on delete cascade,
  instrument_id text not null references radar.instrument (instrument_id),
  position integer not null,
  has_fundamentals boolean not null,
  roe_ttm double precision,
  gross_margin_4q double precision,
  debt_ratio double precision,
  operating_cash_flow_ttm double precision,
  short_pass boolean not null,
  long_pass boolean not null,
  selected_top50 boolean not null,
  short_rank integer,
  long_rank integer,
  primary key (snapshot_id, instrument_id),
  constraint moat_screen_candidate_pass_check check (short_pass or not long_pass),
  constraint moat_screen_candidate_selected_check check (short_pass or not selected_top50)
);

create table if not exists radar.moat_screen_candidate_failure (
  snapshot_id bigint not null,
  instrument_id text not null,
  position integer not null,
  rule text not null,
  primary key (snapshot_id, instrument_id, position),
  foreign key (snapshot_id, instrument_id)
    references radar.moat_screen_candidate (snapshot_id, instrument_id) on delete cascade,
  constraint moat_screen_candidate_failure_rule_check check (rule in (
    'roe_ttm', 'gross_margin_4q', 'debt_ratio', 'operating_cash_flow_ttm',
    'roe_ttm_missing', 'gross_margin_4q_missing', 'debt_ratio_missing', 'operating_cash_flow_ttm_missing',
    'no_fundamentals'))
);

create table if not exists radar.moat_screen_candidate_theme (
  snapshot_id bigint not null,
  instrument_id text not null,
  position integer not null,
  theme_id text not null,
  name_zh text not null,
  relation text not null,
  primary key (snapshot_id, instrument_id, position),
  foreign key (snapshot_id, instrument_id)
    references radar.moat_screen_candidate (snapshot_id, instrument_id) on delete cascade,
  constraint moat_screen_candidate_theme_relation_check check (relation in ('direct', 'related'))
);

insert into radar.snapshot_retention (header_table, keep_count) values
  ('moat_screen_snapshot', 72)
on conflict (header_table) do nothing;

alter table radar.moat_screen_snapshot owner to postgres;
alter table radar.moat_screen_rule owner to postgres;
alter table radar.moat_screen_candidate owner to postgres;
alter table radar.moat_screen_candidate_failure owner to postgres;
alter table radar.moat_screen_candidate_theme owner to postgres;

revoke all on
  radar.moat_screen_snapshot, radar.moat_screen_rule, radar.moat_screen_candidate,
  radar.moat_screen_candidate_failure, radar.moat_screen_candidate_theme
  from public;

grant select, insert, update on
  radar.moat_screen_snapshot, radar.moat_screen_rule, radar.moat_screen_candidate,
  radar.moat_screen_candidate_failure, radar.moat_screen_candidate_theme
  to radar_writer;

grant select on
  radar.moat_screen_snapshot, radar.moat_screen_rule, radar.moat_screen_candidate,
  radar.moat_screen_candidate_failure, radar.moat_screen_candidate_theme
  to radar_reader;
