// Broker (securities branch) datasets, all from the newest radar.broker_snapshot.
//   GET /api/v1/broker-stats            -> BrokerStatsData
//   GET /api/v1/broker-coverage         -> BrokerCoverageData
//   GET /api/v1/broker-map?symbol=2330  -> BrokerMapData
import { BadRequest, NotFound, STOCK_CODE, latestSnapshot } from './common.js';

async function header(query) {
  return latestSnapshot(query, 'broker_snapshot');
}

export const stats = {
  async load({ query }) {
    const h = await header(query);
    if (!h) return null;
    const [statRows, topRows] = await Promise.all([
      query(
        `select position, broker_name, buy, sell, day_trade, overnight
           from radar.broker_stat where snapshot_id = $1 order by position`,
        [h.snapshot_id],
      ),
      query(
        `select stat_position, stock_code, stock_name
           from radar.broker_stat_top where snapshot_id = $1 order by stat_position, position`,
        [h.snapshot_id],
      ),
    ]);
    const tops = new Map();
    for (const t of topRows.rows) {
      if (!tops.has(t.stat_position)) tops.set(t.stat_position, []);
      tops.get(t.stat_position).push([t.stock_code, t.stock_name]);
    }
    return statRows.rows.map((s) => ({
      name: s.broker_name,
      buy: s.buy,
      sell: s.sell,
      dt: s.day_trade,
      ov: s.overnight,
      top: tops.get(s.position) ?? [],
    }));
  },
};

export const coverage = {
  async load({ query }) {
    const h = await header(query);
    if (!h) return null;
    const { rows } = await query(
      `select kind, stock_code from radar.broker_coverage_code where snapshot_id = $1 order by kind, stock_code`,
      [h.snapshot_id],
    );
    const codes = { failed: [], no_data: [], not_attempted: [] };
    for (const r of rows) codes[r.kind]?.push(r.stock_code);
    return {
      schema_version: 1,
      generated_at: h.generated_at,
      source_updated: h.source_updated,
      source: h.source,
      source_scope: h.source_scope,
      requested_symbols: h.requested_symbols,
      attempted_symbols: h.attempted_symbols,
      failed_symbols: h.failed_symbols,
      successful_symbols: h.successful_symbols,
      symbols_with_data: h.symbols_with_data,
      attempt_coverage: h.attempt_coverage,
      data_coverage: h.data_coverage,
      data_coverage_denominator: h.data_coverage_denominator,
      failed_symbol_codes: codes.failed,
      no_data_symbol_codes: codes.no_data,
      not_attempted_symbol_codes: codes.not_attempted,
      status: h.status,
    };
  },
};

export const map = {
  params(search) {
    const symbol = (search.get('symbol') || '').trim();
    if (!STOCK_CODE.test(symbol)) throw new BadRequest('bad_symbol');
    return { symbol };
  },
  async load({ query, params: { symbol } }) {
    const h = await header(query);
    if (!h) return null;
    const sym = await query(
      `select stock_code, stock_name, broker_count, buy, sell, net
         from radar.broker_symbol where snapshot_id = $1 and stock_code = $2`,
      [h.snapshot_id, symbol],
    );
    if (!sym.rows[0]) throw new NotFound('symbol_not_found');
    const branches = await query(
      `select b.broker_id, k.name, b.net, b.ratio
         from radar.broker_symbol_branch b join radar.broker k using (broker_id)
        where b.snapshot_id = $1 and b.stock_code = $2
        order by b.position`,
      [h.snapshot_id, symbol],
    );
    const ids = branches.rows.map((b) => b.broker_id);
    const books = await query(
      `select broker_id, stock_code, stock_name, net
         from radar.broker_branch_stock
        where snapshot_id = $1 and broker_id = any($2::text[]) and stock_code <> $3
        order by broker_id, position`,
      [h.snapshot_id, ids, symbol],
    );
    const byBroker = new Map(ids.map((id) => [id, []]));
    for (const s of books.rows) byBroker.get(s.broker_id)?.push([s.stock_code, s.stock_name, s.net]);
    const s = sym.rows[0];
    return {
      schema_version: 1,
      generated_at: h.generated_at,
      source: h.map_source ?? h.source,
      unit: h.unit,
      stock_code: s.stock_code,
      stock_name: s.stock_name,
      summary: { buy: s.buy, sell: s.sell, net: s.net, broker_count: s.broker_count },
      brokers: branches.rows.map((b) => ({
        id: b.broker_id,
        name: b.name,
        net: b.net,
        ratio: b.ratio,
        stocks: byBroker.get(b.broker_id) ?? [],
      })),
    };
  },
};
