// Contract tests for GET /api/calendar. Run: npm run test:api

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { CACHE_CONTROL_ERROR, CACHE_CONTROL_OK, handleCalendar, shapeCalendar } from '../../api/_lib/calendar.js';

const now = new Date('2026-11-20T05:00:00Z');
const rows = [
  { title: 'Prelim UoM Consumer Sentiment', country: 'USD', date: '2026-11-20T10:00:00-05:00', impact: 'Medium', forecast: '51.7', previous: '51.0' },
  { title: '1-y Loan Prime Rate', country: 'CNY', date: '2026-11-20T09:00:00+08:00', impact: 'Low', forecast: '3.00%', previous: '3.00%' },
  { title: 'Bad row', country: 'USD', date: 'not a date', impact: 'High' },
  { title: '', country: 'EUR', date: '2026-11-20T10:00:00+01:00', impact: 'High' },
];

test('rows are sorted, moved to the Taipei clock and labelled by region', () => {
  const out = shapeCalendar(rows, now);
  assert.equal(out.today, '2026-11-20');
  assert.equal(out.items.length, 2);
  assert.deepEqual(out.items.map((item) => [item.time, item.region]), [['09:00', '中國'], ['23:00', '美國']]);
  assert.equal(out.items[1].impact, 'medium');
});

test('missing actual stays null instead of being invented', () => {
  const out = shapeCalendar(rows, now);
  assert.equal(out.items[0].actual, null);
  assert.equal(out.items[0].forecast, '3.00%');
});

test('handler caches success at the edge and fails closed', async () => {
  const ok = await handleCalendar({ fetchExport: async () => rows, now });
  assert.equal(ok.status, 200);
  assert.equal(ok.headers['Cache-Control'], CACHE_CONTROL_OK);
  const bad = await handleCalendar({ fetchExport: async () => { throw new Error('boom'); }, now, log: () => {} });
  assert.equal(bad.status, 503);
  assert.equal(bad.headers['Cache-Control'], CACHE_CONTROL_ERROR);
  assert.doesNotMatch(bad.body, /boom/);
});
