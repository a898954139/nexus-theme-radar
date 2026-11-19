// GET /api/v1/theme-focus -> ThemeFocusData (src/types.ts)
import { compact, latestSnapshot } from './common.js';

export async function load({ query }) {
  const h = await latestSnapshot(query, 'theme_focus_snapshot');
  if (!h) return null;
  const [themes, stocks] = await Promise.all([
    query(`select * from radar.theme_focus_theme where snapshot_id = $1 order by position`, [h.snapshot_id]),
    query(
      `select s.*, i.symbol, i.exchange, i.name_zh
         from radar.theme_focus_stock s join radar.instrument i using (instrument_id)
        where s.snapshot_id = $1
        order by s.theme_id, s.role, s.position`,
      [h.snapshot_id],
    ),
  ]);
  const members = new Map();
  for (const s of stocks.rows) {
    const key = `${s.theme_id}\u0000${s.role}`;
    if (!members.has(key)) members.set(key, []);
    members.get(key).push({
      instrument_id: s.instrument_id,
      symbol: s.symbol,
      exchange: s.exchange,
      name_zh: s.name_zh,
      relation: s.relation,
      flow: s.flow_as_of === null ? null : {
        as_of: s.flow_as_of,
        days: s.flow_days,
        total_5d: s.total_5d,
        foreign_5d: s.foreign_5d,
        trust_5d: s.trust_5d,
        total_1d: s.total_1d,
        streak: s.streak,
      },
      ...compact({
        short_rank: s.short_rank,
        short_score: s.short_score,
        long_rank: s.long_rank,
        long_score: s.long_score,
      }),
    });
  }
  return {
    schema_version: h.schema_version,
    generated_at: h.generated_at,
    theme_generated_at: h.theme_generated_at,
    flow_as_of: h.flow_as_of,
    flow_window_days: h.flow_window_days,
    unit: h.unit,
    flow_source: h.flow_source,
    method: {
      focus_score: h.method_focus_score,
      hot_heat: h.method_hot_heat,
      broad_breadth: h.method_broad_breadth,
      weak_breadth: h.method_weak_breadth,
    },
    themes: themes.rows.map((t) => ({
      theme_id: t.theme_id,
      name_zh: t.name_zh,
      rank: t.rank,
      heat_score: t.heat_score,
      momentum_score: t.momentum_score,
      lifecycle_stage: t.lifecycle_stage,
      event_count: t.event_count,
      stance: t.stance,
      stance_label: t.stance_label,
      focus_score: t.focus_score,
      flow: {
        member_count: t.member_count,
        covered_count: t.covered_count,
        positive_count: t.positive_count,
        breadth: t.breadth,
        total_5d: t.total_5d,
        foreign_5d: t.foreign_5d,
        trust_5d: t.trust_5d,
        total_1d: t.total_1d,
      },
      leaders: members.get(`${t.theme_id}\u0000leader`) ?? [],
      outflows: members.get(`${t.theme_id}\u0000outflow`) ?? [],
      headline: t.has_headline
        ? { title: t.headline_title, source: t.headline_source, published_at: t.headline_published_at, url: t.headline_url }
        : null,
      focus_rank: t.focus_rank,
    })),
  };
}
