-- Relational store, part 3: stock watchlist and per-stock fundamentals.
-- See docs/RADAR_RELATIONAL.md. Additive and re-runnable; parts 1-2
-- (20261119150000, 20261119160000) must run first.

-- -------------------------------------------------------- stock watchlist
-- nexus_stock_watchlist.v1 has an exact-key validator in the page
-- (src/services/dataService.ts isStockWatchlistData); the API rebuilds it
-- key-for-key from these tables.

create table if not exists radar.watchlist_snapshot (
  snapshot_id bigint generated always as identity primary key,
  generated_at timestamptz not null unique,
  schema_version text not null,
  methodology_version text not null,
  candidate_as_of timestamptz,
  momentum_generated_at timestamptz,
  momentum_observed_hour timestamptz,
  methodology_missing_values text not null,
  methodology_top50 text not null,
  eligible_count integer not null,
  selected_count integer not null,
  created_at timestamptz not null default now()
);

-- Ordered string lists of the header (sources / coverage), one row per value.
create table if not exists radar.watchlist_header_value (
  snapshot_id bigint not null
    references radar.watchlist_snapshot (snapshot_id) on delete cascade,
  kind text not null,
  position integer not null,
  value text not null,
  primary key (snapshot_id, kind, position),
  constraint watchlist_header_value_kind_check check (kind in (
    'institutional_as_of', 'fundamentals_fiscal_quarter', 'coverage_metric', 'coverage_missing_reason'))
);

create table if not exists radar.watchlist_day_trading_source (
  snapshot_id bigint not null
    references radar.watchlist_snapshot (snapshot_id) on delete cascade,
  market text not null,
  as_of date,
  finality text,
  numerator_url text,
  denominator_url text,
  status text not null,
  error text,
  primary key (snapshot_id, market),
  constraint watchlist_day_trading_market_check check (market in ('TWSE', 'TPEX')),
  constraint watchlist_day_trading_status_check check (status in ('fresh', 'stale', 'missing'))
);

create table if not exists radar.watchlist_weight (
  snapshot_id bigint not null
    references radar.watchlist_snapshot (snapshot_id) on delete cascade,
  weight_set text not null,
  component text not null,
  position integer not null,
  weight double precision not null,
  primary key (snapshot_id, weight_set, component),
  constraint watchlist_weight_set_check check (weight_set in ('short', 'long', 'fundamental_quality'))
);

-- Every searchable instrument (the selected top 50 and the rest).
create table if not exists radar.watchlist_member (
  snapshot_id bigint not null
    references radar.watchlist_snapshot (snapshot_id) on delete cascade,
  instrument_id text not null references radar.instrument (instrument_id),
  position integer not null,
  selected_top50 boolean not null,
  short_rank integer,
  long_rank integer,
  primary key (snapshot_id, instrument_id)
);

create table if not exists radar.watchlist_member_theme (
  snapshot_id bigint not null,
  instrument_id text not null,
  position integer not null,
  theme_id text not null,
  name_zh text not null,
  relation text not null,
  heat_score double precision,
  heat_change_24h double precision,
  momentum_score double precision,
  primary key (snapshot_id, instrument_id, position),
  foreign key (snapshot_id, instrument_id)
    references radar.watchlist_member (snapshot_id, instrument_id) on delete cascade,
  constraint watchlist_member_theme_relation_check check (relation in ('direct', 'related'))
);

create table if not exists radar.watchlist_member_flag (
  snapshot_id bigint not null,
  instrument_id text not null,
  position integer not null,
  flag_key text not null,
  flag_type text not null,
  primary key (snapshot_id, instrument_id, position),
  foreign key (snapshot_id, instrument_id)
    references radar.watchlist_member (snapshot_id, instrument_id) on delete cascade,
  constraint watchlist_member_flag_type_check check (flag_type in ('risk', 'positive', 'info'))
);

-- Detail for the selected top 50 (the short and long lists hold the same set).
create table if not exists radar.watchlist_item (
  snapshot_id bigint not null,
  instrument_id text not null,
  short_rank integer not null,
  short_score double precision not null,
  long_rank integer not null,
  long_score double precision not null,
  overnight_value double precision,
  overnight_applied double precision not null,
  overnight_missing_reason text,
  institutional_direction text not null,
  institutional_as_of date,
  institutional_observation_count integer,
  institutional_five_day_net double precision,
  trading_as_of date,
  day_trading_volume double precision,
  total_volume double precision,
  day_trading_volume_ratio double precision,
  overnight_risk double precision,
  overnight_missing_reason_trading text,
  fundamental_score double precision,
  fiscal_quarter text,
  comparison_basis text,
  revenue_growth double precision,
  revenue_direction text,
  eps_growth double precision,
  eps_direction text,
  gross_margin double precision,
  operating_margin double precision,
  operating_cash_flow double precision,
  operating_cash_flow_margin double precision,
  debt_ratio double precision,
  coverage_short_ratio double precision not null,
  coverage_long_ratio double precision not null,
  primary key (snapshot_id, instrument_id),
  foreign key (snapshot_id, instrument_id)
    references radar.watchlist_member (snapshot_id, instrument_id) on delete cascade
);

create table if not exists radar.watchlist_item_component (
  snapshot_id bigint not null,
  instrument_id text not null,
  horizon text not null,
  component text not null,
  raw double precision,
  normalized double precision,
  base_weight double precision not null,
  effective_weight double precision not null,
  available boolean not null,
  primary key (snapshot_id, instrument_id, horizon, component),
  foreign key (snapshot_id, instrument_id)
    references radar.watchlist_item (snapshot_id, instrument_id) on delete cascade,
  constraint watchlist_item_component_horizon_check check (horizon in ('short', 'long'))
);

create table if not exists radar.watchlist_item_missing (
  snapshot_id bigint not null,
  instrument_id text not null,
  position integer not null,
  metric text not null,
  primary key (snapshot_id, instrument_id, position),
  foreign key (snapshot_id, instrument_id)
    references radar.watchlist_item (snapshot_id, instrument_id) on delete cascade
);

-- ------------------------------------------------------ stock fundamentals
-- One current statement set per instrument (Goodinfo quarterly, throttled).
-- Children carry the set's fetched_at; rows of an older fetch are removed by
-- radar.purge_snapshots() once a newer set replaces the header.

create table if not exists radar.fundamental_set (
  instrument_id text primary key references radar.instrument (instrument_id),
  fetched_at timestamptz not null,
  basis text not null,
  currency text not null,
  source text not null,
  fiscal_quarter text not null,
  cash double precision,
  current_ratio double precision,
  debt_ratio double precision,
  ttm_eps double precision,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists radar.fundamental_quarter (
  instrument_id text not null references radar.fundamental_set (instrument_id),
  fetched_at timestamptz not null,
  period text not null,
  position integer not null,
  revenue double precision,
  gross_margin double precision,
  operating_margin double precision,
  net_margin double precision,
  eps double precision,
  primary key (instrument_id, fetched_at, period)
);

create table if not exists radar.fundamental_health_period (
  instrument_id text not null references radar.fundamental_set (instrument_id),
  fetched_at timestamptz not null,
  period text not null,
  net_income double precision,
  operating_cash_flow double precision,
  primary key (instrument_id, fetched_at, period)
);

create table if not exists radar.fundamental_income (
  instrument_id text not null references radar.fundamental_set (instrument_id),
  fetched_at timestamptz not null,
  period text not null,
  revenue double precision,
  cost_of_sales double precision,
  gross_profit double precision,
  selling_expense double precision,
  admin_expense double precision,
  rd_expense double precision,
  expected_credit_loss double precision,
  operating_expense double precision,
  operating_income double precision,
  pretax_income double precision,
  net_income double precision,
  eps double precision,
  primary key (instrument_id, fetched_at, period)
);

create table if not exists radar.fundamental_balance (
  instrument_id text not null references radar.fundamental_set (instrument_id),
  fetched_at timestamptz not null,
  period text not null,
  cash double precision,
  receivables double precision,
  inventory double precision,
  current_assets double precision,
  total_assets double precision,
  current_liabilities double precision,
  total_liabilities double precision,
  total_equity double precision,
  primary key (instrument_id, fetched_at, period)
);

create table if not exists radar.fundamental_cash_flow (
  instrument_id text not null references radar.fundamental_set (instrument_id),
  fetched_at timestamptz not null,
  period text not null,
  operating double precision,
  investing double precision,
  financing double precision,
  depreciation double precision,
  capex double precision,
  dividends_paid double precision,
  ending_cash double precision,
  primary key (instrument_id, fetched_at, period)
);

create table if not exists radar.fundamental_missing (
  instrument_id text not null references radar.fundamental_set (instrument_id),
  fetched_at timestamptz not null,
  position integer not null,
  note text not null,
  primary key (instrument_id, fetched_at, position)
);

-- ------------------------------------------------------------ retention

insert into radar.snapshot_retention (header_table, keep_count) values
  ('watchlist_snapshot', 72)
on conflict (header_table) do nothing;

-- Versioned children: rows whose fetched_at no longer matches their header.
create table if not exists radar.versioned_child (
  child_table text primary key,
  header_table text not null,
  constraint versioned_child_table_check check (child_table ~ '^[a-z_]+$' and header_table ~ '^[a-z_]+$')
);

insert into radar.versioned_child (child_table, header_table) values
  ('fundamental_quarter', 'fundamental_set'),
  ('fundamental_health_period', 'fundamental_set'),
  ('fundamental_income', 'fundamental_set'),
  ('fundamental_balance', 'fundamental_set'),
  ('fundamental_cash_flow', 'fundamental_set'),
  ('fundamental_missing', 'fundamental_set')
on conflict (child_table) do nothing;

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
  for spec in select child_table, header_table from radar.versioned_child loop
    if to_regclass(format('radar.%I', spec.child_table)) is null then
      continue;
    end if;
    execute format(
      'delete from radar.%I c using radar.%I h
        where c.instrument_id = h.instrument_id and c.fetched_at <> h.fetched_at',
      spec.child_table, spec.header_table);
    get diagnostics n = row_count;
    removed := removed + n;
  end loop;
  return removed;
end
$$;

-- ------------------------------------------------------------- ownership/grants

alter table radar.watchlist_snapshot owner to postgres;
alter table radar.watchlist_header_value owner to postgres;
alter table radar.watchlist_day_trading_source owner to postgres;
alter table radar.watchlist_weight owner to postgres;
alter table radar.watchlist_member owner to postgres;
alter table radar.watchlist_member_theme owner to postgres;
alter table radar.watchlist_member_flag owner to postgres;
alter table radar.watchlist_item owner to postgres;
alter table radar.watchlist_item_component owner to postgres;
alter table radar.watchlist_item_missing owner to postgres;
alter table radar.fundamental_set owner to postgres;
alter table radar.fundamental_quarter owner to postgres;
alter table radar.fundamental_health_period owner to postgres;
alter table radar.fundamental_income owner to postgres;
alter table radar.fundamental_balance owner to postgres;
alter table radar.fundamental_cash_flow owner to postgres;
alter table radar.fundamental_missing owner to postgres;
alter table radar.versioned_child owner to postgres;
alter function radar.purge_snapshots(integer) owner to postgres;

revoke all on
  radar.watchlist_snapshot, radar.watchlist_header_value, radar.watchlist_day_trading_source,
  radar.watchlist_weight, radar.watchlist_member, radar.watchlist_member_theme,
  radar.watchlist_member_flag, radar.watchlist_item, radar.watchlist_item_component,
  radar.watchlist_item_missing,
  radar.fundamental_set, radar.fundamental_quarter, radar.fundamental_health_period,
  radar.fundamental_income, radar.fundamental_balance, radar.fundamental_cash_flow,
  radar.fundamental_missing, radar.versioned_child
  from public;
revoke all on function radar.purge_snapshots(integer) from public;

grant select, insert, update on
  radar.watchlist_snapshot, radar.watchlist_header_value, radar.watchlist_day_trading_source,
  radar.watchlist_weight, radar.watchlist_member, radar.watchlist_member_theme,
  radar.watchlist_member_flag, radar.watchlist_item, radar.watchlist_item_component,
  radar.watchlist_item_missing,
  radar.fundamental_set, radar.fundamental_quarter, radar.fundamental_health_period,
  radar.fundamental_income, radar.fundamental_balance, radar.fundamental_cash_flow,
  radar.fundamental_missing
  to radar_writer;
grant select on radar.versioned_child to radar_writer;
grant execute on function radar.purge_snapshots(integer) to radar_writer;

grant select on
  radar.watchlist_snapshot, radar.watchlist_header_value, radar.watchlist_day_trading_source,
  radar.watchlist_weight, radar.watchlist_member, radar.watchlist_member_theme,
  radar.watchlist_member_flag, radar.watchlist_item, radar.watchlist_item_component,
  radar.watchlist_item_missing,
  radar.fundamental_set, radar.fundamental_quarter, radar.fundamental_health_period,
  radar.fundamental_income, radar.fundamental_balance, radar.fundamental_cash_flow,
  radar.fundamental_missing
  to radar_reader;
