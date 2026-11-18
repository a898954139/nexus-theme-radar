-- Daily pre-market analysis reports (issue #8).
--
-- Two halves, two credentials:
--   cloud (radar_writer)   prepares the day's to-analyze list and the
--                          deterministic snapshots before 07:00 Taipei:
--                          daily_bar, technical_snapshot, fundamental_snapshot,
--                          analysis_batch, analysis_queue.
--   local (radar_analyst)  the user's own Claude scheduled task (~07:30). It
--                          may READ the list and snapshots and WRITE only
--                          analysis_report. Nothing else in `radar` is
--                          visible to it.
--
-- Same rules as 20261118080000_create_radar_schema.sql: not exposed through
-- PostgREST, every statement re-runnable, roles are NOLOGIN.
--
-- Post-apply step (manual, per environment):
--   create role <analyst_login> login password '...';   -- value stays local
--   grant radar_analyst to <analyst_login>;
-- Rollback for the local half: revoke radar_analyst from <analyst_login>;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'radar_analyst') then
    create role radar_analyst nologin;
  end if;
end
$$;

-- Observed daily OHLCV per symbol, a cache so the morning job only fetches the
-- current month. Volume is shares (TPEX lots are converted x1000).
create table if not exists radar.daily_bar (
  symbol text not null,
  trade_date date not null,
  exchange text not null,
  open numeric not null,
  high numeric not null,
  low numeric not null,
  close numeric not null,
  volume numeric not null,
  source_url text not null,
  fetched_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (symbol, trade_date),
  constraint daily_bar_exchange_check check (exchange in ('TWSE', 'TPEX')),
  constraint daily_bar_ohlc_check
    check (0 < low and low <= least(open, close) and greatest(open, close) <= high),
  constraint daily_bar_volume_check check (volume >= 0)
);

-- One prepared batch per morning edition. Frozen once written: a later cron
-- slot for the same report_date is a no-op, so the local task always analyses
-- the list it was shown.
create table if not exists radar.analysis_batch (
  report_date date primary key,
  data_as_of date not null,
  candidate_as_of timestamptz,
  selection_rule text not null,
  selected_count integer not null,
  excluded jsonb not null default '[]'::jsonb,
  prepared_at timestamptz not null,
  prepared_run_id text not null,
  created_at timestamptz not null default now(),
  constraint analysis_batch_dates_check check (data_as_of < report_date),
  constraint analysis_batch_selected_check check (selected_count between 0 and 10)
);

-- The to-analyze list: up to 10 symbols for one edition.
create table if not exists radar.analysis_queue (
  report_date date not null references radar.analysis_batch (report_date),
  symbol text not null,
  rank smallint not null,
  instrument_id text not null,
  exchange text not null,
  name_zh text not null,
  selected_by text not null,
  short_rank integer,
  short_score numeric,
  long_rank integer,
  long_score numeric,
  themes jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  primary key (report_date, symbol),
  unique (report_date, rank),
  constraint analysis_queue_rank_check check (rank between 1 and 10),
  constraint analysis_queue_selected_by_check check (selected_by in ('short', 'long')),
  constraint analysis_queue_exchange_check check (exchange in ('TWSE', 'TPEX'))
);

-- Deterministic price inputs as of the last completed session. `candles` is
-- the full warmed history the local PVA/Nexus analyzer needs; `metrics` are
-- plain arithmetic (MA, ATR, recent range). sha256 covers `candles`.
create table if not exists radar.technical_snapshot (
  symbol text not null,
  data_as_of date not null,
  exchange text not null,
  bar_count integer not null,
  last_close numeric not null,
  candles jsonb not null,
  metrics jsonb not null,
  candles_sha256 text not null,
  prepared_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (symbol, data_as_of),
  constraint technical_snapshot_bar_count_check check (bar_count > 0),
  constraint technical_snapshot_sha_check check (candles_sha256 ~ '^[0-9a-f]{64}$')
);

-- Financial facts as published in the repo's quarterly cache, plus valuation
-- recomputed from the snapshot close. Missing metrics stay missing.
create table if not exists radar.fundamental_snapshot (
  symbol text not null,
  data_as_of date not null,
  fiscal_quarter text not null,
  payload jsonb not null,
  missing text[] not null default '{}',
  source_fetched_at timestamptz,
  payload_sha256 text not null,
  prepared_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (symbol, data_as_of),
  constraint fundamental_snapshot_sha_check check (payload_sha256 ~ '^[0-9a-f]{64}$')
);

-- The LLM report. Written by the local task only. One row per
-- (symbol, report_date, framework_version); a new framework version is a new
-- row, so older versions stay for backtesting.
create table if not exists radar.analysis_report (
  symbol text not null,
  report_date date not null,
  framework_version text not null,
  data_as_of date not null,
  bias text not null,
  actionability text not null,
  invalidation_price numeric not null,
  last_close numeric not null,
  conclusion text not null,
  report jsonb not null,
  technical_sha256 text not null,
  fundamental_sha256 text not null,
  generated_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (symbol, report_date, framework_version),
  foreign key (report_date, symbol) references radar.analysis_queue (report_date, symbol),
  foreign key (symbol, data_as_of) references radar.technical_snapshot (symbol, data_as_of),
  constraint analysis_report_dates_check check (data_as_of < report_date),
  constraint analysis_report_bias_check check (bias in ('bullish', 'bearish', 'neutral')),
  constraint analysis_report_actionability_check
    check (actionability in ('actionable', 'wait_for_confirmation', 'no_trade')),
  constraint analysis_report_invalidation_check check (invalidation_price > 0),
  constraint analysis_report_framework_check check (framework_version <> '')
);

create index if not exists analysis_report_date_idx
  on radar.analysis_report (report_date, symbol);

alter table radar.daily_bar owner to postgres;
alter table radar.analysis_batch owner to postgres;
alter table radar.analysis_queue owner to postgres;
alter table radar.technical_snapshot owner to postgres;
alter table radar.fundamental_snapshot owner to postgres;
alter table radar.analysis_report owner to postgres;

revoke all on
  radar.daily_bar,
  radar.analysis_batch,
  radar.analysis_queue,
  radar.technical_snapshot,
  radar.fundamental_snapshot,
  radar.analysis_report
  from public;

-- Cloud writer: prepares inputs. It cannot write reports.
grant select, insert, update on
  radar.daily_bar,
  radar.analysis_batch,
  radar.analysis_queue,
  radar.technical_snapshot,
  radar.fundamental_snapshot
  to radar_writer;
grant select on radar.analysis_report to radar_writer;

-- Server-side API: read only.
grant select on
  radar.daily_bar,
  radar.analysis_batch,
  radar.analysis_queue,
  radar.technical_snapshot,
  radar.fundamental_snapshot,
  radar.analysis_report
  to radar_reader;

-- Local analyst: read the list and snapshots, write reports. SELECT on
-- analysis_report is required by INSERT ... ON CONFLICT DO UPDATE.
grant usage on schema radar to radar_analyst;
grant select on
  radar.analysis_batch,
  radar.analysis_queue,
  radar.technical_snapshot,
  radar.fundamental_snapshot
  to radar_analyst;
grant select, insert, update on radar.analysis_report to radar_analyst;
