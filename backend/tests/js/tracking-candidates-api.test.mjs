// Contract + auth tests for GET /api/v1/tracking-candidates (issue #6).
// Run: npm run test:api
// The handler must reject missing/wrong keys with 401 before touching the DB,
// return exactly the committed JSON payload on success, and fail closed
// (503, no-store, no driver detail) otherwise.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import {
  CACHE_CONTROL,
  LATEST_SNAPSHOT_SQL,
  MIN_KEY_LENGTH,
  handleTrackingCandidates,
  isAuthorized,
  parseApiKeys,
} from '../../api/_lib/trackingCandidates.js';
import { isTrackingCandidatesPayload } from '../../api/_lib/trackingCandidatesContract.js';

const fixture = JSON.parse(
  readFileSync(new URL('../../../job/data/tracking-candidates.json', import.meta.url), 'utf8'),
);
const KEY = 'k'.repeat(MIN_KEY_LENGTH) + '-current';
const NEXT_KEY = 'n'.repeat(MIN_KEY_LENGTH) + '-next';
const fresh = new Date(Date.parse(fixture.generated_at) + 5 * 60000);
const silent = () => {};

function call(options) {
  return handleTrackingCandidates({
    authorization: `Bearer ${KEY}`,
    apiKeys: [KEY],
    queryLatest: async () => fixture,
    now: fresh,
    log: silent,
    ...options,
  });
}

// --- contract ---------------------------------------------------------------

test('committed JSON satisfies the contract', () => {
  assert.equal(isTrackingCandidatesPayload(fixture), true);
});

test('200 body equals the committed JSON, private no-store', async () => {
  const res = await call({});
  assert.equal(res.status, 200);
  assert.deepEqual(JSON.parse(res.body), fixture);
  assert.equal(res.headers['Content-Type'], 'application/json; charset=utf-8');
  assert.equal(res.headers['Cache-Control'], CACHE_CONTROL);
  assert.equal(CACHE_CONTROL, 'private, no-store');
  assert.equal(res.headers.Vary, 'Authorization');
  assert.equal(res.headers['X-Radar-Source'], 'db');
  assert.equal(res.headers['X-Radar-Generated-At'], fixture.generated_at);
});

test('additive top-level keys pass, removed keys do not', () => {
  assert.equal(isTrackingCandidatesPayload({ ...fixture, new_field: 1 }), true);
  const { matcher_contract: _drop, ...missing } = fixture;
  assert.equal(isTrackingCandidatesPayload(missing), false);
  assert.equal(isTrackingCandidatesPayload({ ...fixture, items: 'x' }), false);
  assert.equal(isTrackingCandidatesPayload({ ...fixture, total_items: fixture.total_items + 1 }), false);
  if (fixture.items.length) {
    const { cluster_id: _c, ...item } = fixture.items[0];
    assert.equal(isTrackingCandidatesPayload({ ...fixture, items: [item, ...fixture.items.slice(1)] }), false);
  }
});

test('reads only the newest snapshot, read-only SQL', () => {
  assert.match(LATEST_SNAPSHOT_SQL, /^select payload from radar\.tracking_candidates_snapshot /);
  assert.match(LATEST_SNAPSHOT_SQL, /order by generated_at desc limit 1$/);
  assert.doesNotMatch(LATEST_SNAPSHOT_SQL, /insert|update|delete|;/i);
});

// --- auth ---------------------------------------------------------------------

for (const [name, authorization] of [
  ['no header', null],
  ['empty header', ''],
  ['wrong key', `Bearer ${'x'.repeat(MIN_KEY_LENGTH)}`],
  ['key prefix only', `Bearer ${KEY.slice(0, -1)}`],
  ['key with suffix', `Bearer ${KEY}x`],
  ['basic scheme', `Basic ${KEY}`],
  ['bare key', KEY],
  ['bearer without key', 'Bearer '],
]) {
  test(`401 and no DB call: ${name}`, async () => {
    let queried = false;
    const res = await call({
      authorization,
      queryLatest: async () => {
        queried = true;
        return fixture;
      },
    });
    assert.equal(res.status, 401);
    assert.equal(queried, false);
    assert.deepEqual(JSON.parse(res.body), { error: 'unauthorized' });
    assert.equal(res.headers['WWW-Authenticate'], 'Bearer realm="radar"');
    assert.equal(res.headers['Cache-Control'], CACHE_CONTROL);
  });
}

test('401 when no key is configured, even for a would-be valid key', async () => {
  const res = await call({ apiKeys: [] });
  assert.equal(res.status, 401);
});

test('scheme is case-insensitive', async () => {
  assert.equal((await call({ authorization: `bearer ${KEY}` })).status, 200);
});

test('rotation: both configured keys work, short placeholders are dropped', async () => {
  const keys = parseApiKeys(` ${KEY} , ${NEXT_KEY},changeme,`);
  assert.deepEqual(keys, [KEY, NEXT_KEY]);
  assert.equal(isAuthorized(`Bearer ${KEY}`, keys), true);
  assert.equal(isAuthorized(`Bearer ${NEXT_KEY}`, keys), true);
  assert.equal(isAuthorized('Bearer changeme', keys), false);
  assert.deepEqual(parseApiKeys(undefined), []);
});

// --- fail closed ----------------------------------------------------------------

for (const [name, options, reason] of [
  ['DB not configured', { queryLatest: null }, 'not_configured'],
  ['empty table', { queryLatest: async () => null }, 'no_snapshot'],
  ['contract violation', { queryLatest: async () => ({ ...fixture, items: null }) }, 'contract_violation'],
  ['stale snapshot', { now: new Date(Date.parse(fixture.generated_at) + 721 * 60000) }, 'stale'],
]) {
  test(`503 no-store when ${name}`, async () => {
    const res = await call(options);
    assert.equal(res.status, 503);
    assert.equal(res.headers['Cache-Control'], CACHE_CONTROL);
    assert.deepEqual(JSON.parse(res.body), { error: 'tracking_candidates_unavailable', reason });
  });
}

test('DB error body and log carry no driver detail', async () => {
  const lines = [];
  const error = Object.assign(new Error('connect to db.secret-host.supabase.co password=hunter2'), {
    code: 'ECONNREFUSED',
  });
  const res = await call({
    queryLatest: async () => {
      throw error;
    },
    log: (line) => lines.push(line),
  });
  assert.equal(res.status, 503);
  assert.deepEqual(JSON.parse(res.body), { error: 'tracking_candidates_unavailable', reason: 'db_error' });
  assert.deepEqual(lines, ['tracking_candidates_api_unavailable reason=db_error error=Error(ECONNREFUSED)']);
  assert.doesNotMatch(res.body + lines.join(''), /secret-host|hunter2/);
});

test('auth log never contains the presented key', async () => {
  const lines = [];
  await call({ authorization: 'Bearer leaked-candidate-key-0123456789abcdef', log: (l) => lines.push(l) });
  assert.deepEqual(lines, ['tracking_candidates_api_unauthorized reason=bad_key']);
});
