// GET /api/quotes — see api/_lib/quotes.js. No secrets or env vars needed.

import { chartUrl, handleQuotes } from './_lib/quotes.js';

async function fetchChart(symbol) {
  const response = await fetch(chartUrl(symbol), {
    headers: { Accept: 'application/json', 'User-Agent': 'Mozilla/5.0 (compatible; nexus-theme-radar)' },
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error(`source answered ${response.status}`);
  return response.json();
}

export async function GET() {
  const result = await handleQuotes({ fetchChart });
  return new Response(result.body, { status: result.status, headers: result.headers });
}
