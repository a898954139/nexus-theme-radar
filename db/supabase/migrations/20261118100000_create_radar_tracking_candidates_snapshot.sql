-- radar.tracking_candidates_snapshot: one row per hourly pipeline run, holding
-- the exact payload scripts/update_theme_radar.py writes to
-- data/tracking-candidates.json. GET /api/v1/tracking-candidates serves the
-- newest row, so the API contract is the JSON contract by construction
-- (issue #6, upstream of NexusDashboard).
--
-- Written in the same transaction as the run's radar.pipeline_run row, so a
-- snapshot always has its reconciliation ledger entry.
--
-- Depends on 20261118080000_create_radar_schema.sql (schema + roles).
-- Re-runnable: guarded DDL and idempotent grants. Not exposed via PostgREST.

create table if not exists radar.tracking_candidates_snapshot (
  generated_at timestamptz primary key,
  run_id text not null references radar.pipeline_run (run_id),
  item_count integer not null,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint tracking_candidates_snapshot_item_count_check check (item_count >= 0),
  constraint tracking_candidates_snapshot_payload_check
    check (jsonb_typeof(payload) = 'object' and jsonb_typeof(payload -> 'items') = 'array')
);

alter table radar.tracking_candidates_snapshot owner to postgres;

revoke all on radar.tracking_candidates_snapshot from public;
grant select, insert, update on radar.tracking_candidates_snapshot to radar_writer;
grant select on radar.tracking_candidates_snapshot to radar_reader;
