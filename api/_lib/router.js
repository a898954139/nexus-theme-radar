// Request handling for GET /api/v1/[dataset], independent of the DB driver so
// it can be contract-tested (tests/js/datasets-api.test.mjs).
import { BadRequest, NotFound } from './datasets/common.js';
import { DATASETS } from './datasets/index.js';

export const CACHE_CONTROL_OK = 'public, s-maxage=60, stale-while-revalidate=300';
export const CACHE_CONTROL_ERROR = 'no-store';
const DATASET_NAME = /^[a-z][a-z0-9-]{1,40}$/;

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

/** Strip anything that could identify the database before logging. */
export function redactError(error) {
  const name = error && typeof error === 'object' && 'name' in error ? String(error.name) : 'Error';
  const code = error && typeof error === 'object' && 'code' in error ? String(error.code) : '';
  return code ? `${name}(${code})` : name;
}

/**
 * @param {{ dataset: string, search: URLSearchParams,
 *           query: ((sql: string, values?: unknown[]) => Promise<{rows: any[]}>) | null,
 *           log?: (line: string) => void }} options
 */
export async function handleDataset({ dataset, search, query, log = (line) => console.warn(line) }) {
  const spec = DATASET_NAME.test(dataset || '') && Object.hasOwn(DATASETS, dataset) ? DATASETS[dataset] : null;
  if (!spec) return json(404, { error: 'unknown_dataset' }, CACHE_CONTROL_ERROR);
  let params = {};
  try {
    params = spec.params ? spec.params(search) : {};
  } catch (error) {
    if (error instanceof BadRequest) return json(400, { error: 'bad_request', reason: error.reason }, CACHE_CONTROL_ERROR);
    throw error;
  }
  if (!query) {
    log(`dataset_api_unavailable dataset=${dataset} reason=not_configured`);
    return json(503, { error: 'unavailable', reason: 'not_configured' }, CACHE_CONTROL_ERROR);
  }
  let body;
  try {
    body = await spec.load({ query, params });
  } catch (error) {
    if (error instanceof NotFound) return json(404, { error: 'not_found', reason: error.reason }, CACHE_CONTROL_OK);
    log(`dataset_api_unavailable dataset=${dataset} reason=db_error error=${redactError(error)}`);
    return json(503, { error: 'unavailable', reason: 'db_error' }, CACHE_CONTROL_ERROR);
  }
  if (body === null || body === undefined) {
    log(`dataset_api_unavailable dataset=${dataset} reason=no_snapshot`);
    return json(503, { error: 'unavailable', reason: 'no_snapshot' }, CACHE_CONTROL_ERROR);
  }
  return json(200, body, CACHE_CONTROL_OK, { 'X-Radar-Source': 'db' });
}
