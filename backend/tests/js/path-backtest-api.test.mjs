// GET /api/v1/path-backtest: radar.path_backtest rows -> per-path, per-sector badges.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { handleDataset } from '../../api/_lib/router.js';
import { buildPathBacktest, MIN_SAMPLE } from '../../api/_lib/datasets/backtest.js';

const row = (path, target, metric, horizon, n, hit, avg, signed) => ({
  path_id: path, target_id: target, metric, horizon_days: horizon, sample_size: n,
  hit_rate: String(hit), avg_value: String(avg), avg_signed_value: String(signed),
  window_start: '2026-08-04', window_end: '2026-11-20',
});

const ROWS = [
  row('fed_rates', '大盤全體', 'excess_return', 1, 100, 0.68, 0.21, 0.35),
  row('fed_rates', '大盤全體', 'excess_return', 5, 98, 0.6, 0.5, 0.7),
  row('fed_rates', '大盤全體', 'foreign_net', 1, 90, 0.55, -1200.5, 300),
  row('fed_rates', '金融', 'excess_return', 1, 3, 1, 0.4, 0.4),
  row('fed_rates', '金融', 'foreign_net', 1, 3, 1, 50, 50),
  row('chip_export', '半導體', 'foreign_net', 1, 20, 0.5, 10, 5), // no T+1 excess row
];

test('rows map to the PathBacktestBadge shape, hit rates null below the minimum sample', () => {
  const body = buildPathBacktest({ rule_version: 'direction-v2', computed_at: '2026-11-21T09:50:00Z' }, ROWS);
  assert.equal(body.min_sample, MIN_SAMPLE);
  assert.equal(body.rule_version, 'direction-v2');
  assert.deepEqual(body.paths.fed_rates['大盤全體'], {
    target: '大盤全體', hitRate: 0.68, n: 100, avgSignedExcessT1: 0.35,
    foreignHitRateT1: 0.55, avgForeignT1: -1200.5, window: ['2026-08-04', '2026-11-20'],
  });
  assert.deepEqual(body.paths.fed_rates['金融'], {
    target: '金融', hitRate: null, n: 3, avgSignedExcessT1: 0.4,
    foreignHitRateT1: null, avgForeignT1: 50, window: ['2026-08-04', '2026-11-20'],
  });
  assert.equal(body.paths.chip_export, undefined);
});

test('serves the newest rule version and 503s when the table is empty', async () => {
  const calls = [];
  const query = async (sql, values) => {
    calls.push({ sql, values });
    if (/group by rule_version/.test(sql)) return { rows: [{ rule_version: 'direction-v2', computed_at: '2026-11-21T09:50:00Z' }] };
    return { rows: ROWS };
  };
  const res = await handleDataset({ dataset: 'path-backtest', search: new URLSearchParams(), query, log: () => {} });
  assert.equal(res.status, 200);
  assert.deepEqual(calls[1].values, ['direction-v2']);
  assert.equal(JSON.parse(res.body).paths.fed_rates['大盤全體'].hitRate, 0.68);

  const empty = await handleDataset({ dataset: 'path-backtest', search: new URLSearchParams(), query: async () => ({ rows: [] }), log: () => {} });
  assert.equal(empty.status, 503);
});
