// GET /api/v1/institutional-flows?instrument_id=TWSE:2330[&days=60]
// GET /api/v1/institutional-flows?symbol=2330[&exchange=TWSE]
// Whole-market daily three-institution net (shares), newest first.
import { BadRequest, INSTRUMENT_ID, STOCK_CODE } from './common.js';

const MAX_DAYS = 250;

export function params(search) {
  const instrumentId = (search.get('instrument_id') || '').trim();
  const symbol = (search.get('symbol') || '').trim();
  const exchange = (search.get('exchange') || '').trim().toUpperCase();
  const daysRaw = search.get('days');
  const days = daysRaw === null ? 60 : Number(daysRaw);
  if (!Number.isInteger(days) || days < 1 || days > MAX_DAYS) throw new BadRequest('bad_days');
  let candidates;
  if (instrumentId) {
    if (!INSTRUMENT_ID.test(instrumentId)) throw new BadRequest('bad_instrument_id');
    candidates = [instrumentId];
  } else if (symbol) {
    if (!STOCK_CODE.test(symbol)) throw new BadRequest('bad_symbol');
    if (exchange && exchange !== 'TWSE' && exchange !== 'TPEX') throw new BadRequest('bad_exchange');
    candidates = exchange ? [`${exchange}:${symbol}`] : [`TWSE:${symbol}`, `TPEX:${symbol}`];
  } else {
    throw new BadRequest('instrument_id_or_symbol_required');
  }
  return { candidates, days };
}

export async function load({ query, params: { candidates, days } }) {
  const hit = await query(
    `select i.instrument_id, i.symbol, i.exchange, i.name_zh
       from radar.instrument i
      where i.instrument_id = any($1::text[])
        and exists (select 1 from radar.institutional_flow f where f.instrument_id = i.instrument_id)
      order by array_position($1::text[], i.instrument_id)
      limit 1`,
    [candidates],
  );
  const instrument = hit.rows[0];
  if (!instrument) {
    return { schema_version: 1, instrument_id: null, unit: 'shares', source: null, items: [] };
  }
  const { rows } = await query(
    `select trade_date, foreign_net, trust_net, dealer_net, total_net, source
       from radar.institutional_flow
      where instrument_id = $1
      order by trade_date desc
      limit $2`,
    [instrument.instrument_id, days],
  );
  return {
    schema_version: 1,
    instrument_id: instrument.instrument_id,
    symbol: instrument.symbol,
    exchange: instrument.exchange,
    name_zh: instrument.name_zh,
    unit: 'shares',
    source: rows[0]?.source ?? null,
    items: rows.map((r) => ({
      date: r.trade_date,
      foreign_net: r.foreign_net,
      trust_net: r.trust_net,
      dealer_net: r.dealer_net,
      total_net: r.total_net,
    })),
  };
}
