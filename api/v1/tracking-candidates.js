// GET /api/v1/tracking-candidates — newest radar.tracking_candidates_snapshot
// row, same shape as data/tracking-candidates.json (issue #6). Upstream
// endpoint for NexusDashboard; requires `Authorization: Bearer <key>`.
//
// Server-side only. Vercel environment variables (never VITE_-prefixed, so
// Vite cannot inline them into the client bundle):
//   RADAR_TRACKING_API_KEYS  required. Comma-separated bearer keys, each
//                            >= 32 chars; two entries during rotation.
//   RADAR_API_DATABASE_URL   required. Login role granted radar_reader ONLY
//                            (same variable as /api/pre-market, #5).
//                            Supabase transaction pooler (port 6543).
// Optional:
//   RADAR_API_DATABASE_CA    PEM of the Supabase root CA; enables certificate
//                            verification (set it in Production).
//   RADAR_TRACKING_API_MAX_AGE_MINUTES  staleness cut-off, default 720.

import pg from 'pg';

import {
  DEFAULT_MAX_AGE_MINUTES,
  LATEST_SNAPSHOT_SQL,
  handleTrackingCandidates,
  parseApiKeys,
} from '../_lib/trackingCandidates.js';

let pool = null;

function parseUrl(raw) {
  // pg lets sslmode in the URL override the ssl object below; drop it so the
  // CA setting decides verification. sslmode=disable is honoured for local
  // verification against a non-TLS Postgres only.
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
      application_name: 'radar-api-tracking-candidates',
    });
    // An idle client error must not crash the function instance.
    pool.on('error', () => {});
  }
  return pool;
}

export async function GET(request) {
  const maxAge = Number(process.env.RADAR_TRACKING_API_MAX_AGE_MINUTES);
  const result = await handleTrackingCandidates({
    authorization: request.headers.get('authorization'),
    apiKeys: parseApiKeys(process.env.RADAR_TRACKING_API_KEYS),
    // Resolved lazily: no pool is created for a request that fails auth.
    queryLatest: (process.env.RADAR_API_DATABASE_URL || '').trim()
      ? async () => {
          const { rows } = await getPool().query(LATEST_SNAPSHOT_SQL);
          return rows.length ? rows[0].payload : null;
        }
      : null,
    maxAgeMinutes: Number.isFinite(maxAge) && maxAge > 0 ? maxAge : DEFAULT_MAX_AGE_MINUTES,
  });
  return new Response(result.body, { status: result.status, headers: result.headers });
}
