// Moat screen report (rule moat_v1, job/scripts/moat_screen.py):
//   GET /api/v1/moat-screen -> MoatScreenData (exact keys, front/src/services/dataService.ts)
// One snapshot per hourly watchlist run; generated_at equals the watchlist's.
import { latestSnapshot } from './common.js';

const RULES = ['roe_ttm', 'gross_margin_4q', 'debt_ratio', 'operating_cash_flow_ttm'];

function group(rows) {
  const out = new Map();
  for (const r of rows) {
    if (!out.has(r.instrument_id)) out.set(r.instrument_id, []);
    out.get(r.instrument_id).push(r);
  }
  return out;
}

export async function load({ query }) {
  const h = await latestSnapshot(query, 'moat_screen_snapshot');
  if (!h) return null;
  const id = [h.snapshot_id];
  const [rules, candidates, failures, themes] = await Promise.all([
    query('select * from radar.moat_screen_rule where snapshot_id = $1 order by position', id),
    query(
      `select c.*, i.symbol, i.exchange, i.name_zh
         from radar.moat_screen_candidate c join radar.instrument i using (instrument_id)
        where c.snapshot_id = $1 order by c.position`, id),
    query('select instrument_id, rule from radar.moat_screen_candidate_failure where snapshot_id = $1 order by instrument_id, position', id),
    query('select instrument_id, theme_id, name_zh, relation from radar.moat_screen_candidate_theme where snapshot_id = $1 order by instrument_id, position', id),
  ]);
  const failedBy = group(failures.rows);
  const themesBy = group(themes.rows);
  return {
    rule_version: h.rule_version,
    generated_at: h.generated_at,
    thresholds: {
      roe_ttm_min: h.roe_ttm_min,
      gross_margin_4q_min: h.gross_margin_4q_min,
      debt_ratio_max: h.debt_ratio_max,
      operating_cash_flow_ttm_min_exclusive: h.operating_cash_flow_ttm_min_exclusive,
    },
    universe: { evaluated: h.universe_evaluated, short_pass: h.universe_short_pass, long_pass: h.universe_long_pass },
    candidates: {
      count: h.candidate_count,
      evaluated: h.candidate_evaluated,
      short_pass: h.candidate_short_pass,
      long_pass: h.candidate_long_pass,
      no_fundamentals: h.candidate_no_fundamentals,
    },
    rules: rules.rows.map((r) => ({
      rule: r.rule,
      in_short: r.in_short,
      in_long: r.in_long,
      universe_p25: r.universe_p25,
      universe_p50: r.universe_p50,
      universe_p75: r.universe_p75,
      universe_failed: r.universe_failed,
      universe_missing: r.universe_missing,
    })),
    items: candidates.rows.map((c) => ({
      instrument: { instrument_id: c.instrument_id, symbol: c.symbol, exchange: c.exchange, name_zh: c.name_zh },
      themes: (themesBy.get(c.instrument_id) ?? []).map((t) => ({ theme_id: t.theme_id, name_zh: t.name_zh, relation: t.relation })),
      has_fundamentals: c.has_fundamentals,
      metrics: Object.fromEntries(RULES.map((rule) => [rule, c[rule]])),
      failed: (failedBy.get(c.instrument_id) ?? []).map((f) => f.rule),
      short_pass: c.short_pass,
      long_pass: c.long_pass,
      selected_top50: c.selected_top50,
      short_rank: c.short_rank,
      long_rank: c.long_rank,
    })),
  };
}
