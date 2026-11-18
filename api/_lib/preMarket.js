// Request handling for GET /api/pre-market, independent of the DB driver so it
// can be contract-tested with a fake query (tests/js/pre-market-api.test.mjs).
// Files under api/_lib are not deployed as functions (leading underscore).

import { isPreMarketPayload } from '../../src/lib/preMarketContract.js';

export const CACHE_CONTROL_OK = 'public, s-maxage=60, stale-while-revalidate=300';
export const CACHE_CONTROL_ERROR = 'no-store';
export const DEFAULT_MAX_AGE_MINUTES = 360;

export const LATEST_SNAPSHOT_SQL =
  'select payload from radar.pre_market_snapshot order by generated_at desc limit 1';

function json(status, body, cacheControl, extra = {}) {
  return {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': cacheControl,
      'X-Content-Type-Options': 'nosniff',
      ...extra,
    },
    body: JSON.stringify(body),
  };
}

function unavailable(reason) {
  // Body carries a reason code only: never driver messages, hosts or DSNs.
  return json(503, { error: 'pre_market_unavailable', reason }, CACHE_CONTROL_ERROR);
}

/** Strip anything that could identify the database before logging. */
export function redactError(error) {
  const name = error && typeof error === 'object' && 'name' in error ? String(error.name) : 'Error';
  const code = error && typeof error === 'object' && 'code' in error ? String(error.code) : '';
  return code ? `${name}(${code})` : name;
}

/**
 * @param {{
 *   queryLatest: (() => Promise<unknown>) | null,
 *   now?: Date,
 *   maxAgeMinutes?: number,
 *   log?: (line: string) => void,
 * }} options
 */
export async function handlePreMarket({
  queryLatest,
  now = new Date(),
  maxAgeMinutes = DEFAULT_MAX_AGE_MINUTES,
  log = (line) => console.warn(line),
}) {
  if (!queryLatest) {
    log('pre_market_api_unavailable reason=not_configured');
    return unavailable('not_configured');
  }
  let payload;
  try {
    payload = await queryLatest();
  } catch (error) {
    log(`pre_market_api_unavailable reason=db_error error=${redactError(error)}`);
    return unavailable('db_error');
  }
  if (payload === null || payload === undefined) {
    log('pre_market_api_unavailable reason=no_snapshot');
    return unavailable('no_snapshot');
  }
  if (!isPreMarketPayload(payload)) {
    log('pre_market_api_unavailable reason=contract_violation');
    return unavailable('contract_violation');
  }
  const ageMinutes = (now.getTime() - Date.parse(payload.generated_at)) / 60000;
  if (ageMinutes > maxAgeMinutes) {
    // Dual-write stopped (credential revoked, DB down): let the page fall back
    // to the JSON shipped with the deploy instead of serving an old board.
    log(`pre_market_api_unavailable reason=stale age_minutes=${Math.round(ageMinutes)}`);
    return unavailable('stale');
  }
  return json(200, payload, CACHE_CONTROL_OK, { 'X-Radar-Source': 'db' });
}
