// GET /api/v1/path-backtest -> path backtest results (issue #12), read from
// radar.path_backtest (written by job/scripts/backtest_path.py, weekdays 17:50).
//
// Before this reader the page only saw a path's hit rate through the copy the
// next pre-market run carried on each event (pathBacktest). Serving the table
// directly makes the numbers current as soon as the backtest finishes and
// exposes every sector of a path, not only its primary one.
//
// Body:
//   { rule_version, computed_at, min_sample,
//     paths: { [path_id]: { [sector]: PathBacktestBadge } } }
// PathBacktestBadge matches the pre-market event field (front/src/types.ts):
//   { target, hitRate|null, n, avgSignedExcessT1, foreignHitRateT1|null,
//     avgForeignT1|null, window: [start, end] }
// hitRate is null below MIN_SAMPLE, as backtest_path.MIN_SAMPLE does.

export const MIN_SAMPLE = 5;

function num(value) {
  if (value === null || value === undefined) return null;
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

function day(value) {
  if (value instanceof Date) return value.toISOString().slice(0, 10);
  return String(value).slice(0, 10);
}

function iso(value) {
  return value instanceof Date ? value.toISOString() : String(value);
}

/** Pure mapping from table rows to the response body (unit-tested). */
export function buildPathBacktest(header, rows) {
  const byKey = new Map();
  for (const row of rows) {
    const key = `${row.path_id}\u0000${row.target_id}`;
    if (!byKey.has(key)) byKey.set(key, { path: row.path_id, target: row.target_id, metrics: {} });
    byKey.get(key).metrics[`${row.metric}:${row.horizon_days}`] = row;
  }
  const paths = {};
  for (const { path, target, metrics } of byKey.values()) {
    const ret = metrics['excess_return:1'];
    if (!ret) continue; // the page's badge is the T+1 excess-return row
    const flow = metrics['foreign_net:1'];
    const n = Number(ret.sample_size);
    const flowN = flow ? Number(flow.sample_size) : 0;
    (paths[path] ??= {})[target] = {
      target,
      hitRate: n >= MIN_SAMPLE ? num(ret.hit_rate) : null,
      n,
      avgSignedExcessT1: num(ret.avg_signed_value),
      foreignHitRateT1: flow && flowN >= MIN_SAMPLE ? num(flow.hit_rate) : null,
      avgForeignT1: flow ? num(flow.avg_value) : null,
      window: [day(ret.window_start), day(ret.window_end)],
    };
  }
  return {
    rule_version: header.rule_version,
    computed_at: iso(header.computed_at),
    min_sample: MIN_SAMPLE,
    paths,
  };
}

export const pathBacktest = {
  async load({ query }) {
    // Latest backtest run = the rule version with the newest computed_at;
    // rows of older rule versions stay in the table but are not served.
    const head = await query(
      'select rule_version, max(computed_at) as computed_at from radar.path_backtest '
      + 'group by rule_version order by max(computed_at) desc limit 1',
    );
    const header = head.rows[0];
    if (!header) return null;
    const { rows } = await query(
      'select path_id, target_id, metric, horizon_days, sample_size, hit_rate, avg_value, '
      + 'avg_signed_value, window_start, window_end from radar.path_backtest '
      + 'where rule_version = $1 order by path_id, target_id, metric, horizon_days',
      [header.rule_version],
    );
    return buildPathBacktest(header, rows);
  },
};
