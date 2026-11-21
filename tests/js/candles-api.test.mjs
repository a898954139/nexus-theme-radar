// Contract tests for GET /api/candles. Run: npm run test:api

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { CACHE_CONTROL_ERROR, CACHE_CONTROL_OK, handleCandles, shapeCandles, yahooSymbol } from '../../api/_lib/candles.js';

const day = (iso) => Date.parse(`${iso}T01:00:00Z`) / 1000;
const payload = {
  chart: { result: [{
    meta: { gmtoffset: 28800 },
    timestamp: [day('2026-11-18'), day('2026-11-19'), day('2026-11-20')],
    indicators: { quote: [{ open: [1000, null, 1010], high: [1020, 1, 1030], low: [990, 1, 1005], close: [1010, 1, 1025.555], volume: [30123456, 1, 25000000] }] },
  }] },
};

test('exchange maps to the Yahoo suffix and bad input is refused', () => {
  assert.equal(yahooSymbol('2330', 'TWSE'), '2330.TW');
  assert.equal(yahooSymbol('6488', 'TPEX'), '6488.TWO');
  assert.equal(yahooSymbol('2330', 'NYSE'), null);
  assert.equal(yahooSymbol('../x', 'TWSE'), null);
});

test('rows with a missing price are skipped, volume is in lots, dates are Taipei', () => {
  const rows = shapeCandles(payload);
  assert.deepEqual(rows.map((row) => row.date), ['2026-11-18', '2026-11-20']);
  assert.equal(rows[0].volume, 30123);
  assert.equal(rows[1].close, 1025.56);
});

test('success is cached, upstream failure fails closed', async () => {
  const ok = await handleCandles({ symbol: '2330', exchange: 'TWSE', fetchChart: async () => payload });
  assert.equal(ok.status, 200);
  assert.equal(ok.headers['Cache-Control'], CACHE_CONTROL_OK);
  assert.equal(JSON.parse(ok.body).items.length, 2);
  const bad = await handleCandles({ symbol: '2330', exchange: 'TWSE', log: () => {}, fetchChart: async () => { throw new Error('429'); } });
  assert.equal(bad.status, 502);
  assert.equal(bad.headers['Cache-Control'], CACHE_CONTROL_ERROR);
  const invalid = await handleCandles({ symbol: '2330', exchange: 'X', fetchChart: async () => payload });
  assert.equal(invalid.status, 400);
});
