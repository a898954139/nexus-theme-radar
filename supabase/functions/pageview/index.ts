// The only reader and writer of site_metrics.
//
// POST { visitorId, kind: 'view' | 'heartbeat' }  -> records, returns counts
// GET                                             -> returns counts only
//
// Responses are aggregate-only ({ total, online }); raw rows never leave this
// function, so the public endpoint leaks nothing about individual visitors.
//
// Connects over plain Postgres rather than supabase-js on purpose: site_metrics
// is kept out of PostgREST's exposed schemas, so the REST client cannot see it.
// Keeping it that way means the tables have no HTTP surface of their own.

import postgres from 'https://deno.land/x/postgresjs@v3.4.4/mod.js';
import {
  DEDUP_WINDOW_MS,
  ONLINE_WINDOW_MS,
  RATE_LIMIT_MAX_REQUESTS,
  RATE_LIMIT_WINDOW_MS,
  isAllowedOrigin,
  isValidVisitorId
} from './limits.ts';

const sql = postgres(Deno.env.get('SUPABASE_DB_URL')!, {
  prepare: false,
  max: 3,
  idle_timeout: 20
});

function corsHeaders(origin: string | null): Record<string, string> {
  return {
    'Access-Control-Allow-Origin': isAllowedOrigin(origin) ? origin! : 'null',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'content-type, authorization, apikey',
    'Content-Type': 'application/json'
  };
}

function json(body: unknown, status: number, origin: string | null): Response {
  return new Response(JSON.stringify(body), { status, headers: corsHeaders(origin) });
}

function clientIp(req: Request): string {
  // Supabase sits behind a proxy, so the socket address is the proxy's. The
  // leftmost x-forwarded-for entry is the caller as the edge saw it; a client
  // can prepend junk, but cannot remove the entry the edge appends.
  const forwarded = req.headers.get('x-forwarded-for') ?? '';
  const first = forwarded.split(',')[0]?.trim();
  return first || '0.0.0.0';
}

const intervalMs = (ms: number) => `${ms} milliseconds`;

async function overRateLimit(ip: string): Promise<boolean> {
  try {
    const [{ count }] = await sql<{ count: number }[]>`
      select count(*)::int as count
      from site_metrics.rate_limit
      where client_ip = ${ip}::inet
        and requested_at > now() - ${intervalMs(RATE_LIMIT_WINDOW_MS)}::interval
    `;

    if (count >= RATE_LIMIT_MAX_REQUESTS) return true;

    await sql`insert into site_metrics.rate_limit (client_ip) values (${ip}::inet)`;
    await sql`
      delete from site_metrics.rate_limit
      where requested_at < now() - ${intervalMs(RATE_LIMIT_WINDOW_MS)}::interval
    `;
    return false;
  } catch {
    // Fail closed: if the limiter itself is broken, refuse the write rather
    // than leave the endpoint unmetered.
    return true;
  }
}

async function readCounts(): Promise<{ total: number; online: number }> {
  const [row] = await sql<{ total: number; online: number }[]>`
    select
      (select count(*)::int from site_metrics.page_view) as total,
      (select count(*)::int from site_metrics.heartbeat
        where last_seen_at > now() - ${intervalMs(ONLINE_WINDOW_MS)}::interval) as online
  `;
  return { total: row?.total ?? 0, online: row?.online ?? 0 };
}

async function record(visitorId: string, kind: 'view' | 'heartbeat'): Promise<void> {
  // Heartbeats keep "online" fresh; they must never touch page_view or every
  // 45-second ping would inflate the total.
  await sql`
    insert into site_metrics.heartbeat (visitor_id, last_seen_at)
    values (${visitorId}::uuid, now())
    on conflict (visitor_id) do update set last_seen_at = now()
  `;

  if (kind !== 'view') return;

  // The dedup window is enforced by the insert itself, so two simultaneous
  // requests from one visitor cannot both pass a separate check and double-count.
  await sql`
    insert into site_metrics.page_view (visitor_id)
    select ${visitorId}::uuid
    where not exists (
      select 1 from site_metrics.page_view
      where visitor_id = ${visitorId}::uuid
        and viewed_at > now() - ${intervalMs(DEDUP_WINDOW_MS)}::interval
    )
  `;
}

Deno.serve(async (req: Request) => {
  const origin = req.headers.get('origin');

  if (req.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders(origin) });
  }

  try {
    if (req.method === 'GET') {
      return json(await readCounts(), 200, origin);
    }

    if (req.method !== 'POST') {
      return json({ error: 'method not allowed' }, 405, origin);
    }

    if (!isAllowedOrigin(origin)) {
      return json({ error: 'origin not allowed' }, 403, origin);
    }

    let payload: { visitorId?: unknown; kind?: unknown };
    try {
      payload = await req.json();
    } catch {
      return json({ error: 'invalid json' }, 400, origin);
    }

    if (!isValidVisitorId(payload.visitorId)) {
      return json({ error: 'invalid visitorId' }, 400, origin);
    }

    if (await overRateLimit(clientIp(req))) {
      return json({ error: 'rate limited' }, 429, origin);
    }

    await record(payload.visitorId, payload.kind === 'heartbeat' ? 'heartbeat' : 'view');
    return json(await readCounts(), 200, origin);
  } catch {
    return json({ error: 'unavailable' }, 503, origin);
  }
});
