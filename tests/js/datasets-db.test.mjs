// Round-trip tests for GET /api/v1/[dataset] against a real Postgres.
//
//   data/*.json --scripts/radar_publish.py--> radar tables --api/_lib/datasets--> body
//
// The body must equal what the page used to read from the committed JSON
// (modulo nulls vs absent keys and trailing zeros in fractional seconds).
// Skipped unless RADAR_TEST_DATABASE_URL points at a database that has every
// migration applied and `radar_publish.py --all` run against the current data/.
// See docs/RADAR_RELATIONAL.md ("Local verification").

import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { test } from 'node:test';

import pg from 'pg';

import { parseDatabaseUrl, radarTypes } from '../../api/_lib/db.js';
import { handleDataset } from '../../api/_lib/router.js';

const DSN = (process.env.RADAR_TEST_DATABASE_URL || '').trim();
const skip = DSN ? false : 'RADAR_TEST_DATABASE_URL not set';
const data = (name) => JSON.parse(readFileSync(new URL(`../../data/${name}`, import.meta.url), 'utf8'));

const ISO_FRACTION = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.(\d*?)0*Z$/;

/** Drop null/undefined keys, normalize ISO fractions, recurse. */
export function normalize(value) {
  if (Array.isArray(value)) return value.map(normalize);
  if (value && typeof value === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(value)) {
      if (v !== null && v !== undefined) out[k] = normalize(v);
    }
    return out;
  }
  if (typeof value === 'string') {
    const m = ISO_FRACTION.exec(value);
    if (m) return m[2] ? `${m[1]}.${m[2]}Z` : `${m[1]}Z`;
  }
  return value;
}

let pool;
async function call(dataset, query = '') {
  if (!pool) {
    const { connectionString, disableTls } = parseDatabaseUrl(DSN);
    pool = new pg.Pool({ connectionString, ssl: disableTls ? false : { rejectUnauthorized: false }, max: 2, types: radarTypes });
  }
  const res = await handleDataset({
    dataset,
    search: new URLSearchParams(query),
    query: (sql, values) => pool.query(sql, values),
    log: () => {},
  });
  return { status: res.status, body: JSON.parse(res.body) };
}

/** Names are normalized through radar.instrument; align the few aliases. */
async function instrumentNames() {
  const { rows } = await pool.query('select instrument_id, name_zh from radar.instrument');
  return new Map(rows.map((r) => [r.instrument_id, r.name_zh]));
}

test('institutional-rankings round-trips', { skip }, async () => {
  const { status, body } = await call('institutional-rankings');
  assert.equal(status, 200);
  const expected = data('institutional-rankings.json');
  const names = await instrumentNames();
  for (const board of Object.values(expected.rankings)) {
    for (const e of board.entries) e.name = names.get(e.instrument_id) ?? e.name;
  }
  assert.deepEqual(normalize(body), normalize(expected));
});

test('institutional-flows serves the whole-market series per symbol', { skip }, async () => {
  const files = readdirSync(new URL('../../data/flows/', import.meta.url)).filter((f) => f !== 'index.json');
  const sample = files.filter((_, i) => i % 97 === 0).concat(['TWSE-2330.json']);
  // radar.purge_snapshots() keeps 120 days; older rows (delisted or
  // suspended symbols) are intentionally gone.
  const cutoff = new Date(Date.now() - 120 * 86400000).toISOString().slice(0, 10);
  for (const file of sample) {
    const doc = data(`flows/${file}`);
    const { status, body } = await call('institutional-flows', `instrument_id=${doc.instrument_id}&days=250`);
    assert.equal(status, 200);
    const recent = doc.series.filter(([date]) => date >= cutoff);
    if (!recent.length) {
      assert.deepEqual(body.items, [], file);
      continue;
    }
    assert.equal(body.instrument_id, doc.instrument_id);
    const expected = recent
      .map(([date, foreign_net, trust_net, dealer_net, total_net]) => ({ date, foreign_net, trust_net, dealer_net, total_net }))
      .sort((a, b) => (a.date < b.date ? 1 : -1));
    assert.deepEqual(body.items, expected, file);
  }
  const bySymbol = await call('institutional-flows', 'symbol=2330');
  assert.equal(bySymbol.body.instrument_id, 'TWSE:2330');
  assert.equal(bySymbol.body.items.length, 60);
  const missing = await call('institutional-flows', 'symbol=ZZZZ');
  assert.deepEqual(missing.body.items, []);
});

test('the legacy 45-symbol institutional-flows.json is a subset of the API', { skip }, async () => {
  const legacy = data('institutional-flows.json');
  for (const [key, items] of Object.entries(legacy.symbols).slice(0, 10)) {
    const { body } = await call('institutional-flows', `instrument_id=${key}&days=250`);
    const byDate = new Map(body.items.map((i) => [i.date, i]));
    for (const item of items) {
      if (byDate.has(item.date)) assert.deepEqual(byDate.get(item.date), item, `${key} ${item.date}`);
    }
  }
});

test('broker-stats and broker-coverage round-trip', { skip }, async () => {
  const stats = await call('broker-stats');
  assert.equal(stats.status, 200);
  assert.deepEqual(normalize(stats.body), normalize(data('broker-stats.json')));
  const coverage = await call('broker-coverage');
  assert.equal(coverage.status, 200);
  assert.deepEqual(normalize(coverage.body), normalize(data('broker-coverage.json')));
});

test('broker-map rebuilds each symbol file', { skip }, async () => {
  const index = data('broker-map/index.json');
  const codes = Object.keys(index.symbols);
  const sample = codes.filter((_, i) => i % 61 === 0).concat(['2330']);
  for (const code of sample) {
    const meta = index.symbols[code];
    const { status, body } = await call('broker-map', `symbol=${code}`);
    assert.equal(status, 200, code);
    assert.equal(body.stock_name, meta.name);
    assert.deepEqual(body.summary, { ...meta.summary, broker_count: meta.broker_count });
    assert.deepEqual(body.brokers, data(`broker-map/${meta.file}`), code);
  }
  assert.equal((await call('broker-map', 'symbol=ZZZZ')).status, 404);
  assert.equal((await call('broker-map', 'symbol=../x')).status, 400);
});

test('theme-focus round-trips', { skip }, async () => {
  const { status, body } = await call('theme-focus');
  assert.equal(status, 200);
  const expected = data('theme-focus.json');
  const names = await instrumentNames();
  for (const t of expected.themes) for (const s of [...t.leaders, ...t.outflows]) s.name_zh = names.get(s.instrument_id) ?? s.name_zh;
  assert.deepEqual(normalize(body), normalize(expected));
});

test('source-status serves the fields the sources page reads', { skip }, async () => {
  const { status, body } = await call('source-status');
  assert.equal(status, 200);
  const expected = data('source-status.json');
  const keep = ['source_id', 'name', 'source_class', 'adapter', 'fetch_method', 'status', 'items', 'error',
    'trial', 'not_modified', 'runs_7d', 'success_rate_7d', 'elapsed_ms'];
  const sites = expected.sites.map((s) => Object.fromEntries(keep.filter((k) => k in s).map((k) => [k, s[k]])));
  assert.deepEqual(normalize(body), normalize({
    generated_at: expected.generated_at,
    fetched_raw_items: expected.fetched_raw_items,
    items_before_topic_filter: expected.items_before_topic_filter,
    successful_sites: expected.successful_sites,
    failed_count: expected.failed_count,
    failed_sites: expected.sites.filter((s) => s.status === 'failed').map((s) => s.source_id),
    sites,
  }));
});

const omit = (object, keys) => Object.fromEntries(Object.entries(object).filter(([k]) => !keys.includes(k)));

test('theme-events round-trips the fields the pages read', { skip }, async () => {
  const { status, body } = await call('theme-events');
  assert.equal(status, 200);
  const file = data('theme-events.json');
  const names = await instrumentNames();
  const fixName = (s) => ({ ...s, name_zh: names.get(s.instrument_id) ?? s.name_zh });
  const expected = {
    ...Object.fromEntries(['generated_at', 'market_id', 'market_scope', 'window_hours', 'max_items', 'total_items',
      'total_items_available', 'taxonomy_version'].map((k) => [k, file[k]])),
    items: file.items.map((item) => ({
      ...omit(item, ['symbol_evidence', 'tw_related_symbols', 'official_evidence_ids', 'cluster_event_ids']),
      matched_themes: item.matched_themes.map((t) => omit(t, ['signals'])),
      direct_symbols: item.direct_symbols.map(fixName),
      related_symbols: item.related_symbols.map(fixName),
    })),
  };
  assert.deepEqual(normalize(body), normalize(expected));
});

test('theme-ranking round-trips (heat_reason diagnostics dropped)', { skip }, async () => {
  const { status, body } = await call('theme-ranking');
  assert.equal(status, 200);
  const file = data('public-theme-ranking-v0.8.json');
  const names = await instrumentNames();
  const fix = (s) => ({ ...s, name_zh: names.get(s.instrument_id) ?? s.name_zh });
  const expected = {
    ...file,
    themes: file.themes.map((t) => ({
      ...omit(t, ['heat_reason']),
      direct_mentions: t.direct_mentions.map(fix),
      supply_chain_candidates: t.supply_chain_candidates.map(fix),
    })),
  };
  assert.deepEqual(normalize(body), normalize(expected));
});

test('theme-momentum round-trips (per-symbol fundamentals copy dropped)', { skip }, async () => {
  const { status, body } = await call('theme-momentum');
  assert.equal(status, 200);
  const file = data('public-theme-momentum-latest-v0.9.json');
  const names = await instrumentNames();
  const fix = (s) => ({ ...omit(s, ['fundamentals']), name_zh: names.get(s.instrument_id) ?? s.name_zh });
  const expected = {
    ...file,
    themes: file.themes.map((t) => ({
      ...t, direct_symbols: t.direct_symbols.map(fix), related_symbols: t.related_symbols.map(fix),
    })),
  };
  assert.deepEqual(normalize(body), normalize(expected));
});

test('theme-momentum-history serves the hourly series', { skip }, async () => {
  const { status, body } = await call('theme-momentum-history');
  assert.equal(status, 200);
  const file = data('public-theme-momentum-history-v0.9.json');
  const newest = Date.parse(file.newest_observed_hour);
  const expected = file.observations
    .filter((o) => Date.parse(o.observed_hour) > newest - 720 * 3600000)
    .sort((a, b) => Date.parse(a.observed_hour) - Date.parse(b.observed_hour))
    .map((o) => ({ ...o, themes: o.themes.slice().sort((a, b) => a.rank - b.rank || (a.theme_id < b.theme_id ? -1 : 1)) }));
  assert.deepEqual(normalize(body.observations), normalize(expected));
  assert.equal(body.newest_observed_hour, file.newest_observed_hour);
  assert.equal(body.observation_count, expected.length);
  assert.equal((await call('theme-momentum-history', 'hours=0')).status, 400);
});

test('close pool', { skip }, async () => {
  await pool?.end();
});
