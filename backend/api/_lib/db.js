// Shared read-only Postgres pool for Vercel Functions (radar_api login, a member of radar_reader; see db/roles.json).
//
// Server-side only. Environment (never VITE_-prefixed):
//   RADAR_API_DATABASE_URL   login role granted radar_reader ONLY.
//                            Supabase transaction pooler (port 6543).
//   RADAR_API_DATABASE_CA    PEM of the Supabase root CA; enables certificate
//                            verification (required for PRD).
//
// Type parsing is pinned per pool so rows serialize the same way the pipeline
// JSON did: timestamptz -> ISO-8601 UTC with the stored microseconds,
// date -> 'YYYY-MM-DD' (never a local-time Date), int8 -> Number.

import pg from 'pg';

const OID_INT8 = 20;
const OID_DATE = 1082;
const OID_TIMESTAMP = 1114;
const OID_TIMESTAMPTZ = 1184;

const TS = /^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(\.\d+)?(?:([+-]\d{2})(?::?(\d{2}))?(?::?(\d{2}))?)?$/;

/** Postgres timestamptz text (any session TimeZone) -> 'YYYY-MM-DDTHH:MM:SS[.ffffff]Z'. */
export function isoUtc(text) {
  if (text === null || text === undefined) return null;
  const match = TS.exec(String(text));
  if (!match) return String(text);
  const [, day, time, fraction = '', offsetHours = '+00', offsetMinutes = '00'] = match;
  const ms = Date.parse(`${day}T${time}${offsetHours}:${offsetMinutes}`);
  if (!Number.isFinite(ms)) return String(text);
  return `${new Date(ms).toISOString().slice(0, 19)}${fraction}Z`;
}

function toNumber(text) {
  return text === null ? null : Number(text);
}

export const radarTypes = {
  getTypeParser(oid, format) {
    if (format === 'text' || format === undefined) {
      if (oid === OID_INT8) return toNumber;
      if (oid === OID_DATE) return (text) => text;
      if (oid === OID_TIMESTAMPTZ || oid === OID_TIMESTAMP) return isoUtc;
    }
    return pg.types.getTypeParser(oid, format);
  },
};

export function parseDatabaseUrl(raw) {
  // pg lets sslmode in the URL override the ssl object; drop it so the CA
  // setting decides verification. sslmode=disable is honoured for local tests.
  const url = new URL(raw);
  const disableTls = url.searchParams.get('sslmode') === 'disable';
  url.searchParams.delete('sslmode');
  return { connectionString: url.toString(), disableTls };
}

const pools = new Map();

/** Lazily created pool, or null when RADAR_API_DATABASE_URL is unset. */
export function getReaderPool(applicationName = 'radar-api') {
  const raw = (process.env.RADAR_API_DATABASE_URL || '').trim();
  if (!raw) return null;
  if (!pools.has(applicationName)) {
    const ca = (process.env.RADAR_API_DATABASE_CA || '').trim();
    const { connectionString, disableTls } = parseDatabaseUrl(raw);
    const pool = new pg.Pool({
      connectionString,
      ssl: disableTls ? false : ca ? { ca, rejectUnauthorized: true } : { rejectUnauthorized: false },
      max: 1,
      connectionTimeoutMillis: 5000,
      idleTimeoutMillis: 10000,
      statement_timeout: 8000,
      query_timeout: 9000,
      application_name: applicationName,
      types: radarTypes,
    });
    // An idle client error must not crash the function instance.
    pool.on('error', () => {});
    pools.set(applicationName, pool);
  }
  return pools.get(applicationName);
}
