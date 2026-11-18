-- radar.pre_market_snapshot: one row per pre-market board build, holding the
-- exact payload that scripts/update_pre_market.py writes to
-- data/pre-market-latest.json. `/api/pre-market` serves the newest row, so the
-- API contract is the JSON contract by construction (issue #5).
--
-- Depends on 20261118080000_create_radar_schema.sql (schema + roles).
-- Re-runnable: guarded DDL and idempotent grants. Not exposed via PostgREST.

create table if not exists radar.pre_market_snapshot (
  generated_at timestamptz primary key,
  schema_version integer not null,
  window_hours integer not null,
  event_count integer not null,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint pre_market_snapshot_event_count_check check (event_count >= 0),
  constraint pre_market_snapshot_payload_check
    check (jsonb_typeof(payload) = 'object' and payload ? 'events')
);

alter table radar.pre_market_snapshot owner to postgres;

revoke all on radar.pre_market_snapshot from public;
grant select, insert, update on radar.pre_market_snapshot to radar_writer;
grant select on radar.pre_market_snapshot to radar_reader;
