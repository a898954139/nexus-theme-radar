# Vercel deployment and `/api/pre-market` (issue #5)

First end-to-end Vercel path: the pre-market board reads
`radar.pre_market_snapshot` through a server-side function, behind a build
flag, and falls back to the static JSON on any failure. GitHub Pages keeps
working unchanged (flag off, no `/api`).

## Request path

```
browser ──GET /api/pre-market──▶ Vercel Function (api/pre-market.js)
                                   │ RADAR_API_DATABASE_URL (radar_reader only)
                                   ▼
                     select payload from radar.pre_market_snapshot
                     order by generated_at desc limit 1
   ▲                               │
   │ 200 + s-maxage=60, swr=300    │ contract check + staleness check
   │ 503 + no-store ───────────────┘
   └─ on non-2xx / timeout (5 s) / contract mismatch ─▶ ./data/pre-market-latest.json
```

| Response | When | Cache-Control |
|---|---|---|
| 200, body = stored payload, `X-Radar-Source: db` | newest snapshot passes the contract and is ≤ `RADAR_API_MAX_AGE_MINUTES` old (default 360) | `public, s-maxage=60, stale-while-revalidate=300` |
| 503 `{"error":"pre_market_unavailable","reason":…}` | `not_configured`, `db_error`, `no_snapshot`, `contract_violation`, `stale` | `no-store` |

The body never contains driver messages; logs carry only the error class and
code (e.g. `Error(ECONNREFUSED)`).

## One-time setup (manual, per environment)

1. **DB** — apply `supabase/migrations/20261118090000_create_radar_pre_market_snapshot.sql`
   after the base `radar` migration. Create a dedicated API login role:

   ```sql
   create role radar_api login password '<generated>';   -- store only in Vercel
   grant radar_reader to radar_api;                       -- SELECT only
   ```

   The pipeline's existing login (behind `THEME_RADAR_DATABASE_URL`) already
   has `radar_writer`; no new GitHub secret is needed.
2. **Vercel project** — import the repo; `vercel.json` sets install/build/output.
   Plan: Hobby. Commits to `master` (~10/day today) each trigger a deploy,
   well under the Hobby daily deployment limit.
3. **Environment variables** (Production, and Preview if wanted):

   | Name | Value | Exposed to client? |
   |---|---|---|
   | `RADAR_API_DATABASE_URL` | `postgresql://radar_api.<project-ref>:<pw>@<region>.pooler.supabase.com:6543/postgres` | No (not `VITE_`) |
   | `RADAR_API_DATABASE_CA` | Supabase root CA PEM (Project Settings → Database → SSL) | No |
   | `VITE_PRE_MARKET_SOURCE` | `api` to enable; unset = JSON | Yes, public flag |
   | `RADAR_API_MAX_AGE_MINUTES` | optional, default `360` | No |

   Without `RADAR_API_DATABASE_CA` the function still uses TLS but does not
   verify the server certificate. Set it in Production.
4. **Deployment Protection** — Project Settings → Deployment Protection →
   Vercel Authentication on for **All Deployments** (Production included;
   personal use).

## Turning it on / rolling back

- On: set `VITE_PRE_MARKET_SOURCE=api` and redeploy (Vite inlines the flag at
  build time).
- Instant rollback without redeploy: `revoke radar_reader from radar_api;`
  → API returns 503 `db_error` → page reads JSON.
- Code-level rollback: unset `VITE_PRE_MARKET_SOURCE` and redeploy.

## Verification

```bash
npm run test:api                                   # API contract (node:test)
npm run build && .venv/bin/python -m pytest tests/test_pre_market_db_api.py -q
curl -sI https://<deployment>/api/pre-market       # expect 200 + s-maxage=60 (with protection bypass/cookie)
```
