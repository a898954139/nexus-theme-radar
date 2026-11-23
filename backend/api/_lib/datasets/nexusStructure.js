// Nexus core technical read for one stock (job/scripts/nexus_structure.py, Mac job nexus-structure):
//   GET /api/v1/nexus-structure?instrument_id=TWSE:2330 | ?symbol=2330[&exchange=]
//     -> NexusStructure (exact keys, front/src/services/nexusStructure.ts)
// One current row per instrument (radar.nexus_structure); 404 when the stock was never analyzed.
// Dates come back as YYYY-MM-DD text and timestamps as ISO UTC (db.js radarTypes).
import { NotFound } from './common.js';
import { instrumentParams } from './stock.js';

function timeframe(h, prefix) {
  if (h[`${prefix}_bias`] == null) return null;
  return {
    bias: h[`${prefix}_bias`],
    last_event: h[`${prefix}_last_event`],
    last_event_dir: h[`${prefix}_event_dir`],
    last_event_price: h[`${prefix}_event_price`],
    last_event_date: h[`${prefix}_event_date`],
    inside_zone: h[`${prefix}_inside_zone`],
    bar_count: h[`${prefix}_bar_count`],
  };
}

export const params = instrumentParams;

export async function load({ query, params: { candidates } }) {
  const head = await query(
    `select n.*, i.symbol, i.exchange, i.name_zh
       from radar.nexus_structure n join radar.instrument i using (instrument_id)
      where n.instrument_id = any($1::text[])
      order by array_position($1::text[], n.instrument_id) limit 1`,
    [candidates],
  );
  const h = head.rows[0];
  if (!h) throw new NotFound('instrument_not_found');
  const key = [h.instrument_id, h.fetched_at];
  const where = 'where instrument_id = $1 and fetched_at = $2 order by position';
  const [levels, breaks] = await Promise.all([
    query(`select timeframe, kind, side, dir, low, high, formed_on, state
             from radar.nexus_structure_level ${where}`, key),
    query(`select timeframe, label, dir, price, strong, confirmed_on
             from radar.nexus_structure_break ${where}`, key),
  ]);
  return {
    instrument: { instrument_id: h.instrument_id, symbol: h.symbol, exchange: h.exchange, name_zh: h.name_zh },
    analyzed_at: h.fetched_at,
    method_version: h.method_version,
    detector_revision: h.detector_revision,
    as_of: h.as_of,
    close: h.close,
    bias: h.bias,
    timeframes: {
      D1: timeframe(h, 'd1'),
      W1: timeframe(h, 'w1'),
    },
    pva: {
      status: h.pva_status,
      reason: h.pva_reason,
      P: h.pva_p,
      V: h.pva_v,
      A: h.pva_a,
      anchor: h.pva_anchor,
      ATR: h.pva_atr,
    },
    levels: levels.rows,
    breaks: breaks.rows,
    summary: h.summary,
  };
}
