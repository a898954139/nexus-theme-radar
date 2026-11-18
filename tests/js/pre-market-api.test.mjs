// Contract tests for GET /api/pre-market (issue #5). Run: npm run test:api
// The handler must return exactly the committed JSON payload, with the agreed
// cache header, and fail closed (503, no-store, no driver detail) otherwise.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import {
  CACHE_CONTROL_ERROR,
  CACHE_CONTROL_OK,
  LATEST_SNAPSHOT_SQL,
  handlePreMarket,
} from '../../api/_lib/preMarket.js';
import { isPreMarketPayload } from '../../src/lib/preMarketContract.js';

const fixture = JSON.parse(
  readFileSync(new URL('../../data/pre-market-latest.json', import.meta.url), 'utf8'),
);
const fresh = new Date(Date.parse(fixture.generated_at) + 5 * 60000);
const silent = () => {};

test('committed JSON satisfies the shared contract', () => {
  assert.equal(isPreMarketPayload(fixture), true);
});

test('API body is byte-for-byte the stored payload and carries the cache header', async () => {
  const res = await handlePreMarket({ queryLatest: async () => fixture, now: fresh, log: silent });
  assert.equal(res.status, 200);
  assert.equal(res.headers['Cache-Control'], CACHE_CONTROL_OK);
  assert.equal(CACHE_CONTROL_OK, 'public, s-maxage=60, stale-while-revalidate=300');
  assert.equal(res.headers['Content-Type'], 'application/json; charset=utf-8');
  assert.deepEqual(JSON.parse(res.body), fixture);
  assert.deepEqual(Object.keys(JSON.parse(res.body)), Object.keys(fixture));
});

test('reads only the newest snapshot, read-only SQL', () => {
  assert.match(LATEST_SNAPSHOT_SQL, /^select payload from radar\.pre_market_snapshot /);
  assert.match(LATEST_SNAPSHOT_SQL, /order by generated_at desc limit 1$/);
  assert.doesNotMatch(LATEST_SNAPSHOT_SQL, /insert|update|delete|;/i);
});

for (const [name, options, reason] of [
  ['not configured', { queryLatest: null }, 'not_configured'],
  ['empty table', { queryLatest: async () => null }, 'no_snapshot'],
  ['extra key', { queryLatest: async () => ({ ...fixture, extra: 1 }) }, 'contract_violation'],
  ['missing key', { queryLatest: async () => { const { flows, ...rest } = fixture; return rest; } }, 'contract_violation'],
  ['stale snapshot', { queryLatest: async () => fixture, now: new Date(Date.parse(fixture.generated_at) + 361 * 60000) }, 'stale'],
]) {
  test(`503 no-store when ${name}`, async () => {
    const res = await handlePreMarket({ now: fresh, log: silent, ...options });
    assert.equal(res.status, 503);
    assert.equal(res.headers['Cache-Control'], CACHE_CONTROL_ERROR);
    assert.deepEqual(JSON.parse(res.body), { error: 'pre_market_unavailable', reason });
  });
}

test('DB errors never leak connection details to the body or logs', async () => {
  const lines = [];
  const secret = 'postgresql://radar_api:hunter2@db.example.supabase.co:6543/postgres';
  const error = Object.assign(new Error(`connect failed ${secret}`), { code: 'ECONNREFUSED' });
  const res = await handlePreMarket({
    queryLatest: async () => { throw error; },
    now: fresh,
    log: (line) => lines.push(line),
  });
  assert.equal(res.status, 503);
  for (const text of [res.body, ...lines]) {
    assert.doesNotMatch(text, /hunter2|supabase\.co|postgres(ql)?:\/\//);
  }
  assert.match(lines.join('\n'), /reason=db_error error=Error\(ECONNREFUSED\)/);
});

test('deployed GET returns 503 no-store when the server env var is absent', async () => {
  const saved = process.env.RADAR_API_DATABASE_URL;
  delete process.env.RADAR_API_DATABASE_URL;
  const originalWarn = console.warn;
  console.warn = silent;
  try {
    const { GET } = await import('../../api/pre-market.js');
    const res = await GET();
    assert.equal(res.status, 503);
    assert.equal(res.headers.get('cache-control'), CACHE_CONTROL_ERROR);
  } finally {
    console.warn = originalWarn;
    if (saved !== undefined) process.env.RADAR_API_DATABASE_URL = saved;
  }
});
