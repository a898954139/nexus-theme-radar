// Optional data for the feed page's right rail. Both loaders resolve to null on
// any failure: the rail hides a block rather than blocking the page.

export interface CalendarItem {
  at: string;
  day: string;
  time: string;
  country: string;
  region: string;
  title: string;
  impact: 'high' | 'medium' | 'low' | 'holiday';
  actual: string | null;
  forecast: string | null;
  previous: string | null;
}

export interface CalendarData {
  generated_at: string;
  today: string;
  timezone: string;
  source: string;
  items: CalendarItem[];
}

export async function fetchCalendar(): Promise<CalendarData | null> {
  try {
    const response = await fetch('/api/calendar', { headers: { Accept: 'application/json' } });
    if (!response.ok) return null;
    const data = (await response.json()) as CalendarData;
    return Array.isArray(data?.items) ? data : null;
  } catch {
    return null;
  }
}

export interface CryptoQuote {
  id: 'btc' | 'eth' | 'xau';
  label: string;
  symbol: string;
  value: number;
  changePct: number;
  series: number[];
}

// Public market-data hosts; no key. data-api.binance.vision serves spot data
// without the regional block that api.binance.com applies. Gold uses the
// XAUUSDT perpetual and falls back to PAXG (one token per troy ounce) when the
// futures host is unreachable from the viewer's region.
const SPOT = 'https://data-api.binance.vision/api/v3/klines';
const FUTURES = 'https://fapi.binance.com/fapi/v1/klines';

async function klines(base: string, symbol: string): Promise<number[] | null> {
  try {
    const response = await fetch(`${base}?symbol=${symbol}&interval=1d&limit=21`);
    if (!response.ok) return null;
    const rows = (await response.json()) as unknown[];
    const closes = rows.map((row) => Number((row as unknown[])[4])).filter((value) => Number.isFinite(value));
    return closes.length >= 2 ? closes : null;
  } catch {
    return null;
  }
}

function quote(id: CryptoQuote['id'], label: string, symbol: string, closes: number[] | null): CryptoQuote | null {
  if (!closes) return null;
  const value = closes[closes.length - 1];
  const previous = closes[closes.length - 2];
  return { id, label, symbol, value, changePct: previous ? ((value - previous) / previous) * 100 : 0, series: closes };
}

export async function fetchCryptoQuotes(): Promise<CryptoQuote[]> {
  const [btc, eth, xau] = await Promise.all([
    klines(SPOT, 'BTCUSDT'),
    klines(SPOT, 'ETHUSDT'),
    klines(FUTURES, 'XAUUSDT').then((rows) => rows ? { rows, symbol: 'XAUUSDT' } : klines(SPOT, 'PAXGUSDT').then((paxg) => paxg ? { rows: paxg, symbol: 'PAXGUSDT' } : null)),
  ]);
  return [
    quote('btc', 'BTC', 'BTCUSDT', btc),
    quote('eth', 'ETH', 'ETHUSDT', eth),
    xau ? quote('xau', 'XAU', xau.symbol, xau.rows) : null,
  ].filter((item): item is CryptoQuote => item !== null);
}

export interface UsQuote {
  id: string;
  label: string;
  symbol: string;
  value: number;
  change_pct: number | null;
  as_of: string | null;
  series: number[];
}

export async function fetchUsQuotes(): Promise<UsQuote[]> {
  try {
    const response = await fetch('/api/quotes', { headers: { Accept: 'application/json' } });
    if (!response.ok) return [];
    const data = (await response.json()) as { items?: UsQuote[] };
    return Array.isArray(data?.items) ? data.items : [];
  } catch {
    return [];
  }
}
