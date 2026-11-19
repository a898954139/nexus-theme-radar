-- Relational store, part 4: pre-market board and stock audit report.
-- See docs/RADAR_RELATIONAL.md. Additive and re-runnable; parts 1-3 first.
--
-- Supersedes radar.pre_market_snapshot (one jsonb payload per run) as the
-- read path. That table is left in place and still written by
-- update_pre_market.py's own mirror until the cut-over PR stops it.

-- ------------------------------------------------------------ pre-market

create table if not exists radar.pm_snapshot (
  snapshot_id bigint generated always as identity primary key,
  generated_at timestamptz not null unique,
  schema_version integer not null,
  window_hours integer not null,
  direction_rule_version text,
  flows_as_of date,
  has_market boolean not null,
  market_generated_at timestamptz,
  has_news boolean not null,
  news_net double precision,
  news_bull integer,
  news_bear integer,
  news_lean text,
  news_window_hours integer,
  market_lean text,
  market_avg_pct double precision,
  market_basis text,
  has_divergence boolean not null,
  divergence_message text,
  divergence_news_lean text,
  divergence_market_lean text,
  has_sectors_as_of boolean not null,
  sectors_as_of date,
  created_at timestamptz not null default now()
);

create table if not exists radar.pm_source (
  snapshot_id bigint not null references radar.pm_snapshot (snapshot_id) on delete cascade,
  position integer not null,
  name text not null,
  primary key (snapshot_id, position)
);

create table if not exists radar.pm_event (
  snapshot_id bigint not null references radar.pm_snapshot (snapshot_id) on delete cascade,
  position integer not null,
  event_id text not null,
  tier text not null,
  score double precision not null,
  act_label text,
  speaker text,
  published_at timestamptz not null,
  title_zh text not null,
  title_en text,
  channel text,
  path_label text,
  path_id text,
  url text,
  direction smallint,
  direction_reason text,
  horizon text,
  has_backtest boolean not null,
  bt_target text,
  bt_hit_rate double precision,
  bt_n integer,
  bt_avg_signed_excess_t1 double precision,
  bt_foreign_hit_rate_t1 double precision,
  bt_avg_foreign_t1 double precision,
  bt_window_start date,
  bt_window_end date,
  has_flow_after boolean not null,
  fa_target text,
  fa_base_date date,
  fa_foreign_t1 double precision,
  fa_excess_t1 double precision,
  primary key (snapshot_id, position),
  constraint pm_event_direction_check check (direction is null or direction in (-1, 0, 1))
);

create table if not exists radar.pm_event_sector (
  snapshot_id bigint not null,
  event_position integer not null,
  position integer not null,
  sector text not null,
  primary key (snapshot_id, event_position, position),
  foreign key (snapshot_id, event_position) references radar.pm_event (snapshot_id, position) on delete cascade
);

create table if not exists radar.pm_event_related (
  snapshot_id bigint not null,
  event_position integer not null,
  position integer not null,
  title text not null,
  url text,
  primary key (snapshot_id, event_position, position),
  foreign key (snapshot_id, event_position) references radar.pm_event (snapshot_id, position) on delete cascade
);

create table if not exists radar.pm_event_impact (
  snapshot_id bigint not null,
  event_position integer not null,
  position integer not null,
  sector text not null,
  direction smallint not null,
  primary key (snapshot_id, event_position, position),
  foreign key (snapshot_id, event_position) references radar.pm_event (snapshot_id, position) on delete cascade,
  constraint pm_event_impact_direction_check check (direction in (-1, 0, 1))
);

create table if not exists radar.pm_pulse (
  snapshot_id bigint not null references radar.pm_snapshot (snapshot_id) on delete cascade,
  position integer not null,
  pulse_id text not null,
  label text not null,
  value_text text not null,
  delta_text text not null,
  up boolean not null,
  primary key (snapshot_id, position)
);

create table if not exists radar.pm_pulse_point (
  snapshot_id bigint not null,
  pulse_position integer not null,
  position integer not null,
  value double precision not null,
  primary key (snapshot_id, pulse_position, position),
  foreign key (snapshot_id, pulse_position) references radar.pm_pulse (snapshot_id, position) on delete cascade
);

create table if not exists radar.pm_sector (
  snapshot_id bigint not null references radar.pm_snapshot (snapshot_id) on delete cascade,
  position integer not null,
  name text not null,
  chg double precision not null,
  primary key (snapshot_id, position)
);

create table if not exists radar.pm_flow_panel (
  snapshot_id bigint not null references radar.pm_snapshot (snapshot_id) on delete cascade,
  position integer not null,
  panel_id text not null,
  title text not null,
  unit text,
  primary key (snapshot_id, position)
);

create table if not exists radar.pm_flow_entry (
  snapshot_id bigint not null,
  panel_position integer not null,
  side text not null,
  position integer not null,
  rank integer not null,
  name text not null,
  value double precision not null,
  primary key (snapshot_id, panel_position, side, position),
  foreign key (snapshot_id, panel_position) references radar.pm_flow_panel (snapshot_id, position) on delete cascade,
  constraint pm_flow_entry_side_check check (side in ('buy', 'sell'))
);

create table if not exists radar.pm_indicator (
  snapshot_id bigint not null references radar.pm_snapshot (snapshot_id) on delete cascade,
  position integer not null,
  indicator_id text not null,
  label text not null,
  missing boolean not null,
  reason text,
  value double precision,
  change double precision,
  change_pct double precision,
  unit text,
  as_of text,
  session text,
  source text,
  primary key (snapshot_id, position)
);

-- ------------------------------------------------------------ stock audit
-- The report's timestamps are kept as the ISO text the report states
-- (offsets such as +08:00 carry the local trading date the page shows);
-- the checks only accept ISO-8601 forms.

create table if not exists radar.stock_audit_report (
  snapshot_id bigint generated always as identity primary key,
  generated_at timestamptz not null unique,
  generated_at_text text not null,
  schema_version integer not null,
  report_date date not null,
  conclusion text not null,
  forecast_summary text not null,
  forecast_as_of text not null,
  created_at timestamptz not null default now(),
  constraint stock_audit_report_ts_check check (
    generated_at_text ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$'
    and forecast_as_of ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$')
);

create table if not exists radar.stock_audit_reference (
  snapshot_id bigint not null references radar.stock_audit_report (snapshot_id) on delete cascade,
  position integer not null,
  label text not null,
  value double precision not null,
  change_pct double precision not null,
  as_of text not null,
  source text not null,
  primary key (snapshot_id, position)
);

create table if not exists radar.stock_audit_stock (
  snapshot_id bigint not null references radar.stock_audit_report (snapshot_id) on delete cascade,
  position integer not null,
  symbol text not null,
  name text not null,
  price double precision not null,
  price_as_of text not null,
  source text not null,
  summary text not null,
  f_revenue double precision not null,
  f_revenue_unit text not null,
  f_period text not null,
  f_eps double precision not null,
  f_ttm_eps double precision not null,
  f_pe double precision not null,
  f_as_of text not null,
  f_source text not null,
  f_analysis text not null,
  v_source text not null,
  v_baseline_label text not null,
  v_baseline_pe double precision not null,
  v_premium_pct double precision not null,
  v_percentile double precision not null,
  v_sample_count integer not null,
  v_analysis text not null,
  t_ma20 double precision not null,
  t_ma60 double precision not null,
  t_support double precision not null,
  t_resistance double precision not null,
  t_analysis text not null,
  q_sharpe double precision not null,
  q_sortino double precision not null,
  q_ttr_days integer not null,
  q_index_shape text not null,
  q_period text not null,
  q_method text not null,
  q_source text not null,
  primary key (snapshot_id, position)
);

create table if not exists radar.stock_audit_candle (
  snapshot_id bigint not null,
  stock_position integer not null,
  trade_date date not null,
  open double precision not null,
  high double precision not null,
  low double precision not null,
  close double precision not null,
  volume bigint not null,
  primary key (snapshot_id, stock_position, trade_date),
  foreign key (snapshot_id, stock_position) references radar.stock_audit_stock (snapshot_id, position) on delete cascade
);

create table if not exists radar.stock_audit_operation (
  snapshot_id bigint not null,
  stock_position integer not null,
  position integer not null,
  term text not null,
  horizon text not null,
  entry double precision not null,
  add_price double precision not null,
  stop double precision not null,
  take_profit double precision not null,
  timing text not null,
  add_condition text not null,
  primary key (snapshot_id, stock_position, position),
  foreign key (snapshot_id, stock_position) references radar.stock_audit_stock (snapshot_id, position) on delete cascade
);

create table if not exists radar.stock_audit_receipt (
  snapshot_id bigint not null references radar.stock_audit_report (snapshot_id) on delete cascade,
  position integer not null,
  url text not null,
  fetched_at text not null,
  status integer not null,
  primary key (snapshot_id, position)
);

-- ------------------------------------------------------------ retention

insert into radar.snapshot_retention (header_table, keep_count) values
  ('pm_snapshot', 96),
  ('stock_audit_report', 30)
on conflict (header_table) do nothing;

-- ------------------------------------------------------------- ownership/grants

alter table radar.pm_snapshot owner to postgres;
alter table radar.pm_source owner to postgres;
alter table radar.pm_event owner to postgres;
alter table radar.pm_event_sector owner to postgres;
alter table radar.pm_event_related owner to postgres;
alter table radar.pm_event_impact owner to postgres;
alter table radar.pm_pulse owner to postgres;
alter table radar.pm_pulse_point owner to postgres;
alter table radar.pm_sector owner to postgres;
alter table radar.pm_flow_panel owner to postgres;
alter table radar.pm_flow_entry owner to postgres;
alter table radar.pm_indicator owner to postgres;
alter table radar.stock_audit_report owner to postgres;
alter table radar.stock_audit_reference owner to postgres;
alter table radar.stock_audit_stock owner to postgres;
alter table radar.stock_audit_candle owner to postgres;
alter table radar.stock_audit_operation owner to postgres;
alter table radar.stock_audit_receipt owner to postgres;

revoke all on
  radar.pm_snapshot, radar.pm_source, radar.pm_event, radar.pm_event_sector, radar.pm_event_related,
  radar.pm_event_impact, radar.pm_pulse, radar.pm_pulse_point, radar.pm_sector, radar.pm_flow_panel,
  radar.pm_flow_entry, radar.pm_indicator,
  radar.stock_audit_report, radar.stock_audit_reference, radar.stock_audit_stock, radar.stock_audit_candle,
  radar.stock_audit_operation, radar.stock_audit_receipt
  from public;

grant select, insert, update on
  radar.pm_snapshot, radar.pm_source, radar.pm_event, radar.pm_event_sector, radar.pm_event_related,
  radar.pm_event_impact, radar.pm_pulse, radar.pm_pulse_point, radar.pm_sector, radar.pm_flow_panel,
  radar.pm_flow_entry, radar.pm_indicator,
  radar.stock_audit_report, radar.stock_audit_reference, radar.stock_audit_stock, radar.stock_audit_candle,
  radar.stock_audit_operation, radar.stock_audit_receipt
  to radar_writer;

grant select on
  radar.pm_snapshot, radar.pm_source, radar.pm_event, radar.pm_event_sector, radar.pm_event_related,
  radar.pm_event_impact, radar.pm_pulse, radar.pm_pulse_point, radar.pm_sector, radar.pm_flow_panel,
  radar.pm_flow_entry, radar.pm_indicator,
  radar.stock_audit_report, radar.stock_audit_reference, radar.stock_audit_stock, radar.stock_audit_candle,
  radar.stock_audit_operation, radar.stock_audit_receipt
  to radar_reader;
