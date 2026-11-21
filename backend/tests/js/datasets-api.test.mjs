// Contract tests for GET /api/v1/[dataset] without a database. Run: npm run test:api
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { isoUtc } from '../../api/_lib/db.js';
import { CACHE_CONTROL_ERROR, CACHE_CONTROL_OK, handleDataset } from '../../api/_lib/router.js';
import { DATASETS } from '../../api/_lib/datasets/index.js';

const silent = () => {};
const run = (dataset, query, qs = '') =>
  handleDataset({ dataset, search: new URLSearchParams(qs), query, log: silent });

test('registry exposes the PR-A datasets', () => {
  assert.deepEqual(Object.keys(DATASETS).sort(), [
    'broker-coverage', 'broker-map', 'broker-stats', 'fundamentals', 'institutional-flows',
    'institutional-rankings', 'pre-market', 'source-status', 'stock-audit', 'stock-watchlist', 'theme-events', 'theme-focus',
    'theme-momentum', 'theme-momentum-history', 'theme-ranking',
  ]);
});

test('unknown or malformed dataset names are 404 and never reach the DB', async () => {
  let called = false;
  const query = async () => { called = true; return { rows: [] }; };
  for (const name of ['nope', '__proto__', 'constructor', '../pre-market', '']) {
    const res = await run(name, query);
    assert.equal(res.status, 404, name);
    assert.equal(res.headers['Cache-Control'], CACHE_CONTROL_ERROR);
  }
  assert.equal(called, false);
});

test('parameter validation happens before the DB', async () => {
  const query = async () => { throw new Error('must not query'); };
  assert.equal((await run('broker-map', query, 'symbol=../../etc')).status, 400);
  assert.equal((await run('broker-map', query, '')).status, 400);
  assert.equal((await run('institutional-flows', query, '')).status, 400);
  assert.equal((await run('institutional-flows', query, 'instrument_id=NYSE:IBM')).status, 400);
  assert.equal((await run('institutional-flows', query, 'symbol=2330&days=9999')).status, 400);
  assert.equal((await run('institutional-flows', query, 'symbol=2330&exchange=XX')).status, 400);
});

test('missing credential, DB error and empty store fail closed with 503 no-store', async () => {
  const notConfigured = await run('theme-focus', null);
  assert.equal(notConfigured.status, 503);
  assert.deepEqual(JSON.parse(notConfigured.body), { error: 'unavailable', reason: 'not_configured' });

  const lines = [];
  const failing = await handleDataset({
    dataset: 'theme-focus',
    search: new URLSearchParams(),
    query: async () => { const e = new Error('password=hunter2 host=db.internal'); e.code = '28P01'; throw e; },
    log: (l) => lines.push(l),
  });
  assert.equal(failing.status, 503);
  assert.equal(failing.headers['Cache-Control'], CACHE_CONTROL_ERROR);
  assert.doesNotMatch(failing.body + lines.join(''), /hunter2|db\.internal/);
  assert.match(lines[0], /reason=db_error error=Error\(28P01\)/);

  const empty = await run('institutional-rankings', async () => ({ rows: [] }));
  assert.equal(empty.status, 503);
  assert.equal(JSON.parse(empty.body).reason, 'no_snapshot');
});

test('success responses carry the CDN cache header', async () => {
  const query = async (sql) => {
    if (sql.includes('from radar.source_status_snapshot')) {
      return { rows: [{ snapshot_id: 1, generated_at: '2026-11-19T13:13:48.561225Z', fetched_raw_items: 1,
        items_before_topic_filter: 1, successful_sites: 1, failed_count: 0 }] };
    }
    return { rows: [{ source_id: 'cna', name: 'CNA', status: 'ok', error: null, items: 3, trial: null }] };
  };
  const res = await run('source-status', query);
  assert.equal(res.status, 200);
  assert.equal(res.headers['Cache-Control'], CACHE_CONTROL_OK);
  const body = JSON.parse(res.body);
  assert.deepEqual(body.sites, [{ source_id: 'cna', name: 'CNA', status: 'ok', error: null, items: 3 }]);
});

test('isoUtc keeps microseconds and converts any session offset to Z', () => {
  assert.equal(isoUtc('2026-11-19 13:13:48.561225+00'), '2026-11-19T13:13:48.561225Z');
  assert.equal(isoUtc('2026-11-19 21:13:48.5+08'), '2026-11-19T13:13:48.5Z');
  assert.equal(isoUtc('2026-11-19 09:30:00+00'), '2026-11-19T09:30:00Z');
  assert.equal(isoUtc('2026-11-19 15:00:00+05:30'), '2026-11-19T09:30:00Z');
  assert.equal(isoUtc(null), null);
});
