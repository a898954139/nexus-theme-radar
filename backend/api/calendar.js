// GET /api/calendar — see api/_lib/calendar.js. No secrets or env vars needed.

import { CALENDAR_SOURCE_URL, handleCalendar } from './_lib/calendar.js';

async function fetchExport() {
  const response = await fetch(CALENDAR_SOURCE_URL, {
    headers: { Accept: 'application/json', 'User-Agent': 'nexus-theme-radar-calendar' },
    signal: AbortSignal.timeout(6000),
  });
  if (!response.ok) throw new Error(`source answered ${response.status}`);
  return response.json();
}

export async function GET() {
  const result = await handleCalendar({ fetchExport });
  return new Response(result.body, { status: result.status, headers: result.headers });
}
