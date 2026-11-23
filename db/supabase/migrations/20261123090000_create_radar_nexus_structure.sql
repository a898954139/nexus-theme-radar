-- Nexus core technical read per radar stock (job/scripts/nexus_structure.py,
-- Mac job nexus-structure). One current row per instrument, replaced when a
-- newer analysis lands (Versioned dataset: header upsert by instrument_id,
-- children stamped with fetched_at (the column name radar.purge_snapshots()
-- expects of every versioned child), superseded children purged by
-- radar.purge_snapshots() via radar.versioned_child).
-- Shown on the stock page (GET /api/v1/nexus-structure?symbol=...).
-- Additive and re-runnable. Until this runs, the job's publish step fails
-- without --require (log: radar_publish_failed dataset=nexus-structure) and the
-- stock page hides the card; nothing else is affected.

create table if not exists radar.nexus_structure (
  instrument_id text primary key references radar.instrument (instrument_id),
  fetched_at timestamptz not null,
  method_version text not null,
  detector_revision text,
  as_of date not null,
  close double precision not null,
  bias text not null,
  d1_bias text not null,
  d1_last_event text,
  d1_event_dir smallint,
  d1_event_price double precision,
  d1_event_date date,
  d1_inside_zone boolean not null,
  d1_bar_count integer not null,
  w1_bias text,
  w1_last_event text,
  w1_event_dir smallint,
  w1_event_price double precision,
  w1_event_date date,
  w1_inside_zone boolean,
  w1_bar_count integer,
  pva_status text not null,
  pva_reason text,
  pva_p double precision,
  pva_v double precision,
  pva_a double precision,
  pva_anchor double precision,
  pva_atr double precision,
  summary text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint nexus_structure_bias_check check (bias in ('偏多', '偏空', '中性', '分歧')),
  constraint nexus_structure_d1_bias_check check (d1_bias in ('偏多', '偏空', '中性')),
  constraint nexus_structure_w1_bias_check check (w1_bias is null or w1_bias in ('偏多', '偏空', '中性'))
);

-- Nearest resistance above / support below the close (live FVG / OB zones and
-- unbroken swing pivots), plus any zone the close sits inside.
create table if not exists radar.nexus_structure_level (
  instrument_id text not null references radar.nexus_structure (instrument_id),
  fetched_at timestamptz not null,
  position integer not null,
  timeframe text not null,
  kind text not null,
  side text not null,
  dir smallint not null,
  low double precision not null,
  high double precision not null,
  formed_on date,
  state text not null,
  primary key (instrument_id, fetched_at, position),
  constraint nexus_structure_level_tf_check check (timeframe in ('D1', 'W1')),
  constraint nexus_structure_level_kind_check check (kind in ('fvg', 'ob', 'swing_high', 'swing_low')),
  constraint nexus_structure_level_side_check check (side in ('support', 'resistance', 'inside'))
);

-- Latest external structure breaks (BOS / CHoCH), newest first per timeframe.
create table if not exists radar.nexus_structure_break (
  instrument_id text not null references radar.nexus_structure (instrument_id),
  fetched_at timestamptz not null,
  position integer not null,
  timeframe text not null,
  label text not null,
  dir smallint not null,
  price double precision not null,
  strong boolean not null,
  confirmed_on date not null,
  primary key (instrument_id, fetched_at, position),
  constraint nexus_structure_break_tf_check check (timeframe in ('D1', 'W1'))
);

insert into radar.versioned_child (child_table, header_table) values
  ('nexus_structure_level', 'nexus_structure'),
  ('nexus_structure_break', 'nexus_structure')
on conflict (child_table) do nothing;

alter table radar.nexus_structure owner to postgres;
alter table radar.nexus_structure_level owner to postgres;
alter table radar.nexus_structure_break owner to postgres;

revoke all on radar.nexus_structure, radar.nexus_structure_level, radar.nexus_structure_break from public;

grant select, insert, update on
  radar.nexus_structure, radar.nexus_structure_level, radar.nexus_structure_break
  to radar_writer;

grant select on
  radar.nexus_structure, radar.nexus_structure_level, radar.nexus_structure_break
  to radar_reader;
