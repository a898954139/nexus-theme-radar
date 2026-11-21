// GET /api/calendar — this week's economic calendar, reshaped for the feed page.
//
// Source: the public Forex Factory weekly export (no key, no cookie). The
// export carries forecast and previous only; `actual` is passed through when a
// row has one and is otherwise null, so the page shows "—" instead of guessing.
// Forex Factory asks clients not to poll the export, so the response is cached
// at the edge for 30 minutes and every visitor shares that copy.

export const CALENDAR_SOURCE_URL = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json';
export const CACHE_CONTROL_OK = 'public, s-maxage=1800, stale-while-revalidate=3600';
export const CACHE_CONTROL_ERROR = 'no-store';
export const TAIPEI_TZ = 'Asia/Taipei';

const REGION = {
  USD: '美國', EUR: '歐元區', GBP: '英國', JPY: '日本', CNY: '中國', AUD: '澳洲',
  CAD: '加拿大', NZD: '紐西蘭', CHF: '瑞士', ALL: '全球',
};
const IMPACT = { High: 'high', Medium: 'medium', Low: 'low', Holiday: 'holiday' };

function taipeiParts(date) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: TAIPEI_TZ, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(date).map((part) => [part.type, part.value]));
  return { day: `${parts.year}-${parts.month}-${parts.day}`, time: `${parts.hour}:${parts.minute}` };
}

function text(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

/** Forex Factory rows -> sorted calendar items, Taipei clock. Rows without a
 *  parseable date are dropped rather than placed at an invented time. */
export function shapeCalendar(rows, now = new Date()) {
  if (!Array.isArray(rows)) throw new Error('calendar export is not a list');
  const items = [];
  for (const row of rows) {
    if (!row || typeof row !== 'object') continue;
    const at = new Date(row.date);
    const title = text(row.title);
    if (Number.isNaN(at.getTime()) || !title) continue;
    const local = taipeiParts(at);
    const country = text(row.country) ?? '';
    items.push({
      at: at.toISOString(),
      day: local.day,
      time: local.time,
      country,
      region: REGION[country] ?? country,
      title,
      impact: IMPACT[row.impact] ?? 'low',
      actual: text(row.actual),
      forecast: text(row.forecast),
      previous: text(row.previous),
    });
  }
  items.sort((a, b) => a.at.localeCompare(b.at));
  return {
    generated_at: now.toISOString(),
    today: taipeiParts(now).day,
    timezone: TAIPEI_TZ,
    source: 'Forex Factory',
    items,
  };
}

export async function handleCalendar({ fetchExport, now = new Date(), log = console.error }) {
  try {
    const rows = await fetchExport();
    const body = JSON.stringify(shapeCalendar(rows, now));
    return {
      status: 200,
      headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': CACHE_CONTROL_OK },
      body,
    };
  } catch (error) {
    log(`calendar: ${error instanceof Error ? error.message : 'unknown error'}`);
    return {
      status: 503,
      headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': CACHE_CONTROL_ERROR },
      body: JSON.stringify({ error: 'calendar unavailable' }),
    };
  }
}
