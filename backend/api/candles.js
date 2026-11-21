// GET /api/candles — see api/_lib/candles.js. No secrets or env vars needed.

import { handleCandles } from './_lib/candles.js';

async function fetchChart(url) {
  const response = await fetch(url, {
    headers: { Accept: 'application/json', 'User-Agent': 'Mozilla/5.0 (compatible; nexus-theme-radar)' },
    signal: AbortSignal.timeout(6000),
  });
  if (!response.ok) throw new Error(`source answered ${response.status}`);
  return response.json();
}

export async function GET(request) {
  const params = new URL(request.url).searchParams;
  const result = await handleCandles({ symbol: params.get('symbol'), exchange: params.get('exchange'), range: params.get('range') ?? '1y', fetchChart });
  return new Response(result.body, { status: result.status, headers: result.headers });
}
