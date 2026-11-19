-- Path backtest results (issue #12), written by scripts/backtest_path.py.
--
-- radar.path_backtest: one row per (path x sector x metric x horizon x rule
--   version): hit rate, average move and sample size. The page shows the
--   primary sector's T+1 excess-return row next to each path.
-- radar.event_outcome: what one (event x sector) call was followed by --
--   T+1/T+5 sector excess return over TAIEX (%) and T+1/T+3 foreign net (張).
--   No foreign key to radar.event: the backtest also scores events from the
--   git history of the JSON board that predate the DB.
--
-- Depends on 20261118080000_create_radar_schema.sql (schema + roles).
-- Re-runnable: guarded DDL and idempotent grants. Not exposed via PostgREST.
-- Rollback: drop table radar.event_outcome, radar.path_backtest;

create table if not exists radar.path_backtest (
  path_id text not null,
  target_id text not null,
  rule_version text not null,
  metric text not null,
  horizon_days smallint not null,
  sample_size integer not null,
  trading_days integer not null,
  hit_rate numeric not null,
  avg_value numeric not null,
  avg_signed_value numeric not null,
  window_start date not null,
  window_end date not null,
  computed_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (path_id, target_id, rule_version, metric, horizon_days),
  constraint path_backtest_metric_check check (metric in ('excess_return', 'foreign_net')),
  constraint path_backtest_horizon_check check (horizon_days between 1 and 20),
  constraint path_backtest_sample_check check (sample_size > 0 and trading_days > 0),
  constraint path_backtest_hit_rate_check check (hit_rate between 0 and 1),
  constraint path_backtest_window_check check (window_end >= window_start)
);

create table if not exists radar.event_outcome (
  event_id text not null,
  target_id text not null,
  rule_version text not null,
  path_id text not null,
  published_at timestamptz not null,
  base_date date not null,
  direction smallint not null,
  excess_t1 numeric,
  excess_t5 numeric,
  foreign_t1 numeric,
  foreign_t3 numeric,
  computed_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (event_id, target_id, rule_version),
  constraint event_outcome_direction_check check (direction in (-1, 1))
);

create index if not exists event_outcome_path_idx
  on radar.event_outcome (path_id, rule_version, base_date desc);

alter table radar.path_backtest owner to postgres;
alter table radar.event_outcome owner to postgres;

revoke all on radar.path_backtest from public;
revoke all on radar.event_outcome from public;
grant select, insert, update on radar.path_backtest, radar.event_outcome to radar_writer;
grant select on radar.path_backtest, radar.event_outcome to radar_reader;
grant select on radar.path_backtest, radar.event_outcome to radar_analyst;
