// GET /api/quotes — US pre-market leads for the feed page (費半, Nasdaq, S&P 500,
// TSM ADR, NVDA, 美元/台幣, VIX), 20 daily closes each.
//
// The hourly pipeline's quote feed does not carry US indices, so this reads
// Yahoo Finance's public chart endpoint (no key). One upstream call per symbol,
// cached at the edge for 5 minutes; a symbol that fails is left out and the
// page shows the rest.

export const CACHE_CONTROL_OK = 'public, s-maxage=300, stale-while-revalidate=900';
export const CACHE_CONTROL_ERROR = 'no-store';

export const QUOTE_SYMBOLS = [
  { id: 'sox', symbol: '^SOX', label: '費半', digits: 2 },
  { id: 'nasdaq', symbol: '^IXIC', label: 'Nasdaq', digits: 2 },
  { id: 'spx', symbol: '^GSPC', label: 'S&P 500', digits: 2 },
  { id: 'tsm_adr', symbol: 'TSM', label: 'TSM ADR', digits: 2 },
  { id: 'nvda', symbol: 'NVDA', label: 'NVDA', digits: 2 },
  { id: 'usdtwd', symbol: 'TWD=X', label: '美元/台幣', digits: 3 },
  { id: 'vix', symbol: '^VIX', label: 'VIX', digits: 2 },
  { id: 'gold', symbol: 'GC=F', label: '黃金期貨', digits: 1 },
];

export function chartUrl(symbol) {
  return `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=1mo&interval=1d`;
}

/** One Yahoo chart response -> quote row, or null when it has fewer than two closes. */
export function shapeQuote(spec, payload) {
  const result = payload?.chart?.result?.[0];
  const closes = (result?.indicators?.quote?.[0]?.close ?? []).filter((value) => typeof value === 'number' && Number.isFinite(value));
  if (closes.length < 2) return null;
  const meta = result.meta ?? {};
  const last = typeof meta.regularMarketPrice === 'number' ? meta.regularMarketPrice : closes[closes.length - 1];
  // Yahoo's last bar is the live session; when it equals regularMarketPrice the
  // previous bar is the prior close.
  const previous = closes[closes.length - 1] === last ? closes[closes.length - 2] : closes[closes.length - 1];
  const factor = 10 ** spec.digits;
  const round = (value) => Math.round(value * factor) / factor;
  const series = closes.slice(-20).map(round);
  if (series[series.length - 1] !== round(last)) series.push(round(last));
  return {
    id: spec.id,
    label: spec.label,
    symbol: spec.symbol,
    value: round(last),
    change_pct: previous ? Math.round(((last - previous) / previous) * 10000) / 100 : null,
    as_of: typeof meta.regularMarketTime === 'number' ? new Date(meta.regularMarketTime * 1000).toISOString() : null,
    series: series.slice(-20),
  };
}

export async function handleQuotes({ fetchChart, now = new Date(), log = console.error, symbols = QUOTE_SYMBOLS }) {
  const settled = await Promise.allSettled(symbols.map(async (spec) => shapeQuote(spec, await fetchChart(spec.symbol))));
  const items = [];
  settled.forEach((outcome, index) => {
    if (outcome.status === 'fulfilled' && outcome.value) items.push(outcome.value);
    else log(`quotes: ${symbols[index].symbol} unavailable`);
  });
  if (items.length === 0) {
    return {
      status: 503,
      headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': CACHE_CONTROL_ERROR },
      body: JSON.stringify({ error: 'quotes unavailable' }),
    };
  }
  return {
    status: 200,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': CACHE_CONTROL_OK },
    body: JSON.stringify({ generated_at: now.toISOString(), source: 'Yahoo Finance', items }),
  };
}
