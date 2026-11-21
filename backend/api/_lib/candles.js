// GET /api/candles?symbol=2330&exchange=TWSE — daily OHLCV for the stock
// page's K-line chart (replaces the TradingView embed, which cannot draw
// Taiwan colours: red = up, green = down).
//
// Reads Yahoo Finance's public chart endpoint (no key). TWSE -> 2330.TW,
// TPEX -> 6488.TWO. One upstream call per request, cached at the edge.

export const CACHE_CONTROL_OK = 'public, s-maxage=600, stale-while-revalidate=3600';
export const CACHE_CONTROL_ERROR = 'no-store';
const SYMBOL_PATTERN = /^[0-9A-Z]{4,6}$/;
const RANGES = new Set(['6mo', '1y', '2y']);

export function yahooSymbol(symbol, exchange) {
  const code = String(symbol ?? '').trim().toUpperCase();
  if (!SYMBOL_PATTERN.test(code)) return null;
  if (exchange === 'TWSE') return `${code}.TW`;
  if (exchange === 'TPEX') return `${code}.TWO`;
  return null;
}

export function candlesUrl(yahoo, range = '1y') {
  return `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(yahoo)}?range=${range}&interval=1d`;
}

const round2 = (value) => Math.round(value * 100) / 100;

/** Yahoo chart payload -> [{date, open, high, low, close, volume}] oldest first, Taipei dates. */
export function shapeCandles(payload) {
  const result = payload?.chart?.result?.[0];
  const times = result?.timestamp ?? [];
  const quote = result?.indicators?.quote?.[0] ?? {};
  const offset = Number.isFinite(result?.meta?.gmtoffset) ? result.meta.gmtoffset : 8 * 3600;
  const rows = [];
  const seen = new Set();
  times.forEach((time, index) => {
    const open = quote.open?.[index];
    const high = quote.high?.[index];
    const low = quote.low?.[index];
    const close = quote.close?.[index];
    if (![open, high, low, close].every((value) => typeof value === 'number' && Number.isFinite(value) && value > 0)) return;
    const date = new Date((time + offset) * 1000).toISOString().slice(0, 10);
    if (seen.has(date)) rows.pop();
    seen.add(date);
    const volume = quote.volume?.[index];
    rows.push({ date, open: round2(open), high: round2(high), low: round2(low), close: round2(close), volume: Number.isFinite(volume) ? Math.round(volume / 1000) : 0 });
  });
  return rows;
}

function json(status, body, cache) {
  return { status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': cache }, body: JSON.stringify(body) };
}

export async function handleCandles({ symbol, exchange, range = '1y', fetchChart, now = new Date(), log = console.error }) {
  const yahoo = yahooSymbol(symbol, exchange);
  if (!yahoo) return json(400, { error: 'symbol must be 4-6 alphanumerics and exchange TWSE or TPEX' }, CACHE_CONTROL_ERROR);
  const span = RANGES.has(range) ? range : '1y';
  try {
    const items = shapeCandles(await fetchChart(candlesUrl(yahoo, span)));
    if (items.length < 2) return json(404, { error: 'no candles' }, CACHE_CONTROL_ERROR);
    return json(200, { generated_at: now.toISOString(), source: 'Yahoo Finance', symbol: String(symbol).toUpperCase(), exchange, unit: { price: 'TWD', volume: 'lots' }, items }, CACHE_CONTROL_OK);
  } catch (error) {
    log(`candles: ${yahoo} unavailable: ${error?.message ?? error}`);
    return json(502, { error: 'candles unavailable' }, CACHE_CONTROL_ERROR);
  }
}
