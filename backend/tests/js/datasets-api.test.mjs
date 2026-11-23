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
    'institutional-rankings', 'moat-screen', 'nexus-structure', 'path-backtest', 'pre-market', 'source-status', 'stock-audit', 'stock-watchlist', 'theme-events', 'theme-focus',
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

test('moat-screen rebuilds the report with reasons per candidate', async () => {
  const query = async (sql) => {
    if (sql.includes('from radar.moat_screen_snapshot')) {
      return { rows: [{ snapshot_id: 7, generated_at: '2026-11-22T09:17:00Z', rule_version: 'moat_v1',
        roe_ttm_min: 0.08, gross_margin_4q_min: 0.15, debt_ratio_max: 0.6, operating_cash_flow_ttm_min_exclusive: 0,
        universe_evaluated: 1974, universe_short_pass: 620, universe_long_pass: 545, candidate_count: 2,
        candidate_evaluated: 2, candidate_short_pass: 1, candidate_long_pass: 1, candidate_no_fundamentals: 0 }] };
    }
    if (sql.includes('from radar.moat_screen_rule')) {
      return { rows: [{ rule: 'roe_ttm', position: 0, in_short: true, in_long: true, universe_p25: 0.01,
        universe_p50: 0.066, universe_p75: 0.132, universe_failed: 900, universe_missing: 12 }] };
    }
    if (sql.includes('from radar.moat_screen_candidate c')) {
      return { rows: [
        { instrument_id: 'TWSE:2408', symbol: '2408', exchange: 'TWSE', name_zh: '南亞科', has_fundamentals: true,
          roe_ttm: 0.12, gross_margin_4q: 0.3, debt_ratio: 0.2, operating_cash_flow_ttm: 100,
          short_pass: true, long_pass: true, selected_top50: true, short_rank: 4, long_rank: 1 },
        { instrument_id: 'TWSE:6770', symbol: '6770', exchange: 'TWSE', name_zh: '力積電', has_fundamentals: true,
          roe_ttm: -0.05, gross_margin_4q: 0.096, debt_ratio: 0.4, operating_cash_flow_ttm: 10,
          short_pass: false, long_pass: false, selected_top50: false, short_rank: null, long_rank: null },
      ] };
    }
    if (sql.includes('from radar.moat_screen_candidate_failure')) {
      return { rows: [{ instrument_id: 'TWSE:6770', rule: 'roe_ttm' }, { instrument_id: 'TWSE:6770', rule: 'gross_margin_4q' }] };
    }
    return { rows: [{ instrument_id: 'TWSE:6770', theme_id: 'memory_hbm', name_zh: '記憶體', relation: 'related' }] };
  };
  const res = await run('moat-screen', query);
  assert.equal(res.status, 200);
  const body = JSON.parse(res.body);
  assert.deepEqual(Object.keys(body), ['rule_version', 'generated_at', 'thresholds', 'universe', 'candidates', 'rules', 'items']);
  assert.equal(body.items.length, 2);
  const rejected = body.items[1];
  assert.deepEqual(rejected.failed, ['roe_ttm', 'gross_margin_4q']);
  assert.deepEqual(rejected.themes, [{ theme_id: 'memory_hbm', name_zh: '記憶體', relation: 'related' }]);
  assert.equal(rejected.metrics.gross_margin_4q, 0.096);
  assert.deepEqual(body.items[0].failed, []);
});

test('nexus-structure returns one stock read with levels and breaks', async () => {
  const seen = [];
  const query = async (sql, values) => {
    seen.push(values);
    if (sql.includes('from radar.nexus_structure n')) {
      return { rows: [{ instrument_id: 'TWSE:2317', symbol: '2317', exchange: 'TWSE', name_zh: '鴻海',
        fetched_at: '2026-11-23T07:10:00Z', method_version: 'nexus_structure_v1', detector_revision: 'b1534508',
        as_of: '2026-11-21', close: 250, bias: '分歧',
        d1_bias: '偏空', d1_last_event: 'BOS', d1_event_dir: -1, d1_event_price: 237, d1_event_date: '2026-11-20',
        d1_inside_zone: false, d1_bar_count: 1200,
        w1_bias: '偏多', w1_last_event: 'CHoCH', w1_event_dir: 1, w1_event_price: 247, w1_event_date: '2026-10-16',
        w1_inside_zone: false, w1_bar_count: 250,
        pva_status: 'unavailable', pva_reason: 'PVA runtime not installed on this host',
        pva_p: null, pva_v: null, pva_a: null, pva_anchor: null, pva_atr: null, summary: '週線偏多，日線偏空。' }] };
    }
    if (sql.includes('from radar.nexus_structure_level')) {
      return { rows: [{ timeframe: 'D1', kind: 'swing_high', side: 'resistance', dir: -1, low: 257, high: 257,
        formed_on: '2026-09-23', state: 'active' }] };
    }
    return { rows: [{ timeframe: 'D1', label: 'BOS', dir: -1, price: 237, strong: false, confirmed_on: '2026-11-20' }] };
  };
  const res = await run('nexus-structure', query, 'symbol=2317');
  assert.equal(res.status, 200);
  const body = JSON.parse(res.body);
  assert.deepEqual(Object.keys(body), ['instrument', 'analyzed_at', 'method_version', 'detector_revision', 'as_of',
    'close', 'bias', 'timeframes', 'pva', 'levels', 'breaks', 'summary']);
  assert.equal(body.timeframes.W1.bias, '偏多');
  assert.equal(body.timeframes.D1.last_event_price, 237);
  assert.equal(body.levels[0].side, 'resistance');
  assert.deepEqual(seen[0], [['TWSE:2317', 'TPEX:2317']]);
  assert.deepEqual(seen[1], ['TWSE:2317', '2026-11-23T07:10:00Z']);

  const missing = await run('nexus-structure', async () => ({ rows: [] }), 'symbol=9999');
  assert.equal(missing.status, 404);
  assert.equal((await run('nexus-structure', async () => { throw new Error('no'); }, 'symbol=../x')).status, 400);
});
