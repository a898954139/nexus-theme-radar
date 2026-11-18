// GET /api/pre-market — newest radar.pre_market_snapshot row, same shape as
// data/pre-market-latest.json (issue #5).
//
// Server-side only. Required Vercel environment variable (never VITE_-prefixed,
// so Vite cannot inline it into the client bundle):
//   RADAR_API_DATABASE_URL   login role granted radar_reader ONLY.
//                            Supabase transaction pooler (port 6543) recommended.
// Optional:
//   RADAR_API_DATABASE_CA    PEM of the Supabase root CA; enables certificate
//                            verification (recommended for PRD).
//   RADAR_API_MAX_AGE_MINUTES  staleness cut-off, default 360.

import pg from 'pg';
import { DEFAULT_MAX_AGE_MINUTES, LATEST_SNAPSHOT_SQL, handlePreMarket } from './_lib/preMarket.js';

let pool = null;

function parseUrl(raw) {
  // pg lets sslmode in the URL override the ssl object below; drop it so the
  // CA setting is what decides verification. sslmode=disable is honoured for
  // local verification against a non-TLS Postgres only.
  const url = new URL(raw);
  const disableTls = url.searchParams.get('sslmode') === 'disable';
  url.searchParams.delete('sslmode');
  return { connectionString: url.toString(), disableTls };
}

function getPool() {
  const raw = (process.env.RADAR_API_DATABASE_URL || '').trim();
  if (!raw) return null;
  if (!pool) {
    const ca = (process.env.RADAR_API_DATABASE_CA || '').trim();
    const { connectionString, disableTls } = parseUrl(raw);
    pool = new pg.Pool({
      connectionString,
      ssl: disableTls ? false : ca ? { ca, rejectUnauthorized: true } : { rejectUnauthorized: false },
      max: 1,
      connectionTimeoutMillis: 5000,
      idleTimeoutMillis: 10000,
      statement_timeout: 5000,
      query_timeout: 6000,
      application_name: 'radar-api-pre-market',
    });
    // An idle client error must not crash the function instance.
    pool.on('error', () => {});
  }
  return pool;
}

export async function GET() {
  const db = getPool();
  const maxAge = Number(process.env.RADAR_API_MAX_AGE_MINUTES);
  const result = await handlePreMarket({
    queryLatest: db
      ? async () => {
          const { rows } = await db.query(LATEST_SNAPSHOT_SQL);
          return rows.length ? rows[0].payload : null;
        }
      : null,
    maxAgeMinutes: Number.isFinite(maxAge) && maxAge > 0 ? maxAge : DEFAULT_MAX_AGE_MINUTES,
  });
  return new Response(result.body, { status: result.status, headers: result.headers });
}
