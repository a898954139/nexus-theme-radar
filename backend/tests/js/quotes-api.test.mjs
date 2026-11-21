// Contract tests for GET /api/quotes. Run: npm run test:api

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { CACHE_CONTROL_ERROR, CACHE_CONTROL_OK, handleQuotes, shapeQuote } from '../../api/_lib/quotes.js';

const spec = { id: 'sox', symbol: '^SOX', label: '費半', digits: 2 };
const chart = (closes, price) => ({
  chart: { result: [{ meta: { regularMarketPrice: price, regularMarketTime: 1763600000 }, indicators: { quote: [{ close: closes }] } }] },
});

test('change is measured against the prior close and nulls are skipped', () => {
  const row = shapeQuote(spec, chart([100, null, 110, 99], 99));
  assert.equal(row.value, 99);
  assert.equal(row.change_pct, -10);
  assert.deepEqual(row.series, [100, 110, 99]);
});

test('a symbol with fewer than two closes is dropped', () => {
  assert.equal(shapeQuote(spec, chart([100], 100)), null);
  assert.equal(shapeQuote(spec, {}), null);
});

test('partial upstream failure still answers with the symbols that worked', async () => {
  const symbols = [spec, { id: 'vix', symbol: '^VIX', label: 'VIX', digits: 2 }];
  const res = await handleQuotes({
    symbols,
    log: () => {},
    fetchChart: async (symbol) => { if (symbol === '^VIX') throw new Error('429'); return chart([1, 2], 2); },
  });
  assert.equal(res.status, 200);
  assert.equal(res.headers['Cache-Control'], CACHE_CONTROL_OK);
  assert.deepEqual(JSON.parse(res.body).items.map((item) => item.id), ['sox']);
});

test('total failure fails closed', async () => {
  const res = await handleQuotes({ symbols: [spec], log: () => {}, fetchChart: async () => { throw new Error('x'); } });
  assert.equal(res.status, 503);
  assert.equal(res.headers['Cache-Control'], CACHE_CONTROL_ERROR);
});
