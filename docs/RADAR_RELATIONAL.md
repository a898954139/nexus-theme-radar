# Relational radar store and `/api/v1`

Decision (2026-11-19): the static-JSON site with a partial DB dual-write was
transitional. The target is:

- every pipeline writes **normalized, typed tables** in the private `radar`
  schema (no table stores a whole JSON payload);
- every page reads **only** through the Vercel API (`/api/v1/<dataset>`);
- GitHub Pages and the published `data/*.json` copies are retired at cut-over.

```
pipeline (GitHub Actions) ── writes data/*.json (build artefact)
        └─ scripts/radar_publish.py ── maps (scripts/radar_tables.py) ──► radar.* tables
                                                                         │ radar_reader
browser ── /api/v1/<dataset> (api/v1/[dataset].js → api/_lib/datasets) ◄─┘
```

## Table patterns

| Pattern | Used for | Key | Lifecycle |
|---|---|---|---|
| Snapshot header + children | rankings, broker, theme focus, source status, … | header `snapshot_id`, unique `generated_at` | one transaction per snapshot; API serves the newest header; `radar.purge_snapshots()` keeps `snapshot_retention.keep_count` |
| Time series | `institutional_flow`, `theme_momentum_hourly` | natural key | upsert (only changed rows are rewritten); purge keeps `series_retention.keep_days` |
| Dimension | `instrument`, `broker` | natural id | upsert; children reference it by FK |

Rules that keep this safe on the shared Supabase project (`nexus-dashboard-preview`):

- Migrations are additive and re-runnable (`if not exists`, `create or replace`,
  `on conflict do nothing`). Nothing drops or rewrites an existing table.
- `radar_writer` still has **no DELETE**. Retention runs in
  `radar.purge_snapshots()` (SECURITY DEFINER, `search_path` pinned, table list
  only from `radar.snapshot_retention`, EXECUTE granted to `radar_writer` only).
- `radar_reader` gets SELECT only; the API login (`radar_api`) holds only that.
- Re-publishing the same file is a no-op (`ON CONFLICT (generated_at) DO NOTHING`).

## Datasets

| `/api/v1/…` | Tables | Writer (workflow) | Replaces |
|---|---|---|---|
| `institutional-rankings` | `institutional_ranking_snapshot/_board/_entry` | update-institutional-flows | `institutional-rankings.json` |
| `institutional-flows?instrument_id=TWSE:2330` or `?symbol=2330[&exchange=]` `[&days=60]` | `institutional_flow` | update-institutional-flows | `institutional-flows.json` (45 symbols) → whole market, ~2,400 symbols |
| `broker-stats` | `broker_snapshot`, `broker_stat`, `broker_stat_top` | update-broker-data | `broker-stats.json` |
| `broker-coverage` | `broker_snapshot`, `broker_coverage_code` | update-broker-data | `broker-coverage.json` |
| `broker-map?symbol=2330` | `broker_symbol`, `broker_symbol_branch`, `broker_branch_stock`, `broker` | update-broker-data | `broker-map/` (~600MB, each branch's book repeated per symbol) → ~135k rows per snapshot |
| `theme-focus` | `theme_focus_snapshot/_theme/_stock` | update-theme-radar, update-institutional-flows | `theme-focus.json` |
| `source-status` | `source_status_snapshot/_site` | update-theme-radar | `source-status.json` |
| `theme-events` | `theme_event_snapshot/_item/_theme/_symbol/_source` | update-theme-radar | `theme-events.json` (match/relevance distributions, signals and duplicate code lists not stored: no page reads them) |
| `theme-ranking` | `theme_ranking_snapshot/_theme/_symbol` | update-theme-radar | `public-theme-ranking-v0.8.json` (`heat_reason` breakdown not stored) |
| `theme-momentum` | `theme_momentum_snapshot/_theme/_symbol` | update-theme-radar | `public-theme-momentum-latest-v0.9.json` (per-symbol fundamentals copy not stored; the stock page reads fundamentals from its own dataset) |
| `theme-momentum-history[?hours=720]` | `theme_momentum_hourly` (series, 60-day retention) | update-theme-radar | `public-theme-momentum-history-v0.9.json` |

Later parts (separate PRs): stock watchlist, fundamentals, stock audit, and normalizing the two existing jsonb
snapshot tables (`pre_market_snapshot`, `tracking_candidates_snapshot`).
`waytoagi-7d.json` (stale since 2026-07-26, inherited from the AI-news fork) is
removed rather than migrated.

Response shapes are the TypeScript contracts in `src/types.ts`, so the page
switch is a URL change. Differences from the files, all deliberate:

- instrument names come from `radar.instrument` (one name per instrument; the
  files disagreed for three symbols, e.g. 廣穎 / 廣穎電通);
- `broker-map` now carries the real `generated_at`/`source`;
- `institutional-flows` covers the whole market, not the 45 watchlist symbols.

Errors: `404 unknown_dataset`, `400 bad_request` (params validated before any
query), `404 not_found` (e.g. unknown broker-map symbol), `503 unavailable`
with `reason` `not_configured | db_error | no_snapshot` and `no-store`. Bodies
never contain driver messages, hosts or DSNs.

## Cut-over sequence

1. Merge the writer + API PRs. Nothing user-visible changes; the workflow
   publish steps are `continue-on-error` and skip without the credential.
2. PRD (manual, once): apply the relational migrations on
   `nexus-dashboard-preview` and run **Backfill radar tables**
   (`backfill-radar-tables.yml`, `datasets=all`) to load today's committed files.
   Verify `GET /api/v1/<dataset>` returns 200 on the Vercel production URL.
3. Merge the front-end PR: every page fetches `/api/v1/*` only, publish steps
   become `--require`, GitHub Pages deploy and `copy_runtime_data.sh` data copy
   are removed.

Rollback before step 3: nothing to do (site still reads files). After step 3:
revert the front-end PR. Tables can stay; they are not read by anything else.

## Local verification

```bash
# Postgres 16 in a scratch dir
PGBIN=/usr/lib/postgresql/16/bin
$PGBIN/initdb -D /var/tmp/ntrpg/data -A trust -U postgres
$PGBIN/pg_ctl -D /var/tmp/ntrpg/data -o '-p 54329 -k /var/tmp/ntrpg' start
psql -h /var/tmp/ntrpg -p 54329 -U postgres -c 'create database radar_test'
for f in supabase/migrations/*.sql; do psql -h /var/tmp/ntrpg -p 54329 -U postgres -d radar_test -v ON_ERROR_STOP=1 -qf "$f"; done
psql -h /var/tmp/ntrpg -p 54329 -U postgres -d radar_test \
  -c 'create role w_login login; create role r_login login; grant radar_writer to w_login; grant radar_reader to r_login;'

THEME_RADAR_DATABASE_URL="host=/var/tmp/ntrpg port=54329 dbname=radar_test user=w_login" \
  .venv/bin/python scripts/radar_publish.py --all --require
RADAR_TEST_DATABASE_URL="postgresql://r_login@localhost:54329/radar_test?host=/var/tmp/ntrpg&sslmode=disable" \
  npm run test:api
```

`tests/js/datasets-db.test.mjs` asserts every API body equals the committed file
it replaces (as the writer's role writes it and the reader's role reads it).
