// GET /api/v1/institutional-rankings -> InstitutionalRankingsData (src/types.ts)
import { compact, latestSnapshot } from './common.js';

export async function load({ query }) {
  const header = await latestSnapshot(query, 'institutional_ranking_snapshot', 'snapshot_id, generated_at, source');
  if (!header) return null;
  const [boards, entries] = await Promise.all([
    query(
      `select board_key, metric, window_days, side, unit, updated_at, date_start, date_end, source, source_rows
         from radar.institutional_ranking_board where snapshot_id = $1 order by board_key`,
      [header.snapshot_id],
    ),
    query(
      `select e.board_key, e.instrument_id, i.symbol, i.exchange, i.name_zh, i.is_etf, e.in_universe,
              e.ratio_out_of_range, e.three_inst_ratio, e.change, e.rank, e.foreign_net, e.trust_net,
              e.dealer_net, e.total_net, e.days
         from radar.institutional_ranking_entry e
         join radar.instrument i using (instrument_id)
        where e.snapshot_id = $1
        order by e.board_key, e.position`,
      [header.snapshot_id],
    ),
  ]);
  const rankings = {};
  for (const b of boards.rows) {
    rankings[b.board_key] = {
      metric: b.metric,
      window: b.window_days,
      side: b.side,
      unit: b.unit,
      updated: b.updated_at,
      date_range: b.date_start ? { start: b.date_start, end: b.date_end } : null,
      ...(b.source !== null ? { source: b.source } : {}),
      entries: [],
      source_rows: b.source_rows,
    };
  }
  for (const e of entries.rows) {
    rankings[e.board_key]?.entries.push({
      code: e.symbol,
      name: e.name_zh,
      exchange: e.exchange,
      instrument_id: e.instrument_id,
      in_universe: e.in_universe,
      is_etf: e.is_etf ?? false,
      ...compact({
        ratio_out_of_range: e.ratio_out_of_range,
        three_inst_ratio: e.three_inst_ratio,
        change: e.change,
        foreign: e.foreign_net,
        trust: e.trust_net,
        dealer: e.dealer_net,
        total: e.total_net,
        days: e.days,
        rank: e.rank,
      }),
    });
  }
  return { schema_version: 1, generated_at: header.generated_at, source: header.source, rankings };
}
