// Request handling for GET /api/v1/tracking-candidates (issue #6), independent
// of the DB driver so it can be contract-tested with a fake query
// (tests/js/tracking-candidates-api.test.mjs).
//
// Order matters: authentication runs before any DB access, so an
// unauthenticated caller can neither load the DB nor learn its state.

import { createHash, timingSafeEqual } from 'node:crypto';

import { isTrackingCandidatesPayload } from './trackingCandidatesContract.js';

// Authenticated, per-consumer data: never let a shared cache keep a copy.
export const CACHE_CONTROL = 'private, no-store';
// The hourly GitHub Actions run actually lands every 4-8 h (scheduled runs are
// dropped under load), so 12 h is the first point where "stale" means broken.
export const DEFAULT_MAX_AGE_MINUTES = 720;
export const MIN_KEY_LENGTH = 32;

export const LATEST_SNAPSHOT_SQL =
  'select payload from radar.tracking_candidates_snapshot order by generated_at desc limit 1';

function json(status, body, extra = {}) {
  return {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': CACHE_CONTROL,
      'X-Content-Type-Options': 'nosniff',
      Vary: 'Authorization',
      ...extra,
    },
    body: JSON.stringify(body),
  };
}

function unauthorized() {
  return json(401, { error: 'unauthorized' }, { 'WWW-Authenticate': 'Bearer realm="radar"' });
}

function unavailable(reason) {
  // Body carries a reason code only: never driver messages, hosts or DSNs.
  return json(503, { error: 'tracking_candidates_unavailable', reason });
}

/** Strip anything that could identify the database before logging. */
export function redactError(error) {
  const name = error && typeof error === 'object' && 'name' in error ? String(error.name) : 'Error';
  const code = error && typeof error === 'object' && 'code' in error ? String(error.code) : '';
  return code ? `${name}(${code})` : name;
}

/**
 * Parse RADAR_TRACKING_API_KEYS: comma-separated so a new key can be added
 * before the old one is removed (zero-downtime rotation). Keys shorter than
 * MIN_KEY_LENGTH are dropped so a placeholder can never authenticate.
 *
 * @param {string | undefined} raw
 * @returns {string[]}
 */
export function parseApiKeys(raw) {
  return String(raw || '')
    .split(',')
    .map((key) => key.trim())
    .filter((key) => key.length >= MIN_KEY_LENGTH);
}

function digest(value) {
  return createHash('sha256').update(value, 'utf8').digest();
}

/**
 * Constant-time check of an `Authorization: Bearer <key>` header against the
 * configured keys. Comparing SHA-256 digests keeps every comparison the same
 * length, so neither key content nor key length leaks through timing.
 *
 * @param {string | null | undefined} header
 * @param {string[]} keys
 */
export function isAuthorized(header, keys) {
  if (!keys.length || typeof header !== 'string') return false;
  const match = /^Bearer[ ]+([^\s]+)[ ]*$/i.exec(header);
  if (!match) return false;
  const presented = digest(match[1]);
  let ok = false;
  for (const key of keys) {
    // No early exit: every configured key is compared on every request.
    if (timingSafeEqual(presented, digest(key))) ok = true;
  }
  return ok;
}

/**
 * @param {{
 *   authorization: string | null | undefined,
 *   apiKeys: string[],
 *   queryLatest: (() => Promise<unknown>) | null,
 *   now?: Date,
 *   maxAgeMinutes?: number,
 *   log?: (line: string) => void,
 * }} options
 */
export async function handleTrackingCandidates({
  authorization,
  apiKeys,
  queryLatest,
  now = new Date(),
  maxAgeMinutes = DEFAULT_MAX_AGE_MINUTES,
  log = (line) => console.warn(line),
}) {
  if (!apiKeys.length) {
    // Fail closed and look identical to a wrong key from outside.
    log('tracking_candidates_api_unauthorized reason=keys_not_configured');
    return unauthorized();
  }
  if (!isAuthorized(authorization, apiKeys)) {
    log(`tracking_candidates_api_unauthorized reason=${authorization ? 'bad_key' : 'missing_key'}`);
    return unauthorized();
  }
  if (!queryLatest) {
    log('tracking_candidates_api_unavailable reason=not_configured');
    return unavailable('not_configured');
  }
  let payload;
  try {
    payload = await queryLatest();
  } catch (error) {
    log(`tracking_candidates_api_unavailable reason=db_error error=${redactError(error)}`);
    return unavailable('db_error');
  }
  if (payload === null || payload === undefined) {
    log('tracking_candidates_api_unavailable reason=no_snapshot');
    return unavailable('no_snapshot');
  }
  if (!isTrackingCandidatesPayload(payload)) {
    log('tracking_candidates_api_unavailable reason=contract_violation');
    return unavailable('contract_violation');
  }
  const ageMinutes = (now.getTime() - Date.parse(payload.generated_at)) / 60000;
  if (ageMinutes > maxAgeMinutes) {
    // Dual-write stopped (credential revoked, DB down): tell the consumer to
    // use its JSON fallback rather than hand it an old candidate list as fresh.
    log(`tracking_candidates_api_unavailable reason=stale age_minutes=${Math.round(ageMinutes)}`);
    return unavailable('stale');
  }
  return json(200, payload, {
    'X-Radar-Source': 'db',
    'X-Radar-Generated-At': payload.generated_at,
  });
}
