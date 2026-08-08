// The only reader and writer of site_metrics.
//
// POST { visitorId, kind: 'view' | 'heartbeat' }  -> records, returns counts
// GET                                             -> returns counts only
//
// Responses are aggregate-only ({ total, online }); raw rows never leave this
// function, so the public endpoint leaks nothing about individual visitors.

import { createClient } from 'jsr:@supabase/supabase-js@2';
import {
  DEDUP_WINDOW_MS,
  ONLINE_WINDOW_MS,
  RATE_LIMIT_WINDOW_MS,
  isAllowedOrigin,
  isRateLimited,
  isValidVisitorId,
  windowStart
} from './limits.ts';

const db = createClient(
  Deno.env.get('SUPABASE_URL')!,
  Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
  { db: { schema: 'site_metrics' }, auth: { persistSession: false } }
);

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

async function overRateLimit(ip: string, now: Date): Promise<boolean> {
  const since = windowStart(now, RATE_LIMIT_WINDOW_MS);

  const { count, error } = await db
    .from('rate_limit')
    .select('id', { count: 'exact', head: true })
    .eq('client_ip', ip)
    .gte('requested_at', since);

  // Fail closed: if the limiter itself is broken, refuse the write rather than
  // leave the endpoint unmetered.
  if (error) return true;
  if (isRateLimited(count ?? 0)) return true;

  await db.from('rate_limit').insert({ client_ip: ip });
  await db.from('rate_limit').delete().lt('requested_at', since);
  return false;
}

async function alreadyCountedRecently(visitorId: string, now: Date): Promise<boolean> {
  const { data, error } = await db
    .from('page_view')
    .select('id')
    .eq('visitor_id', visitorId)
    .gte('viewed_at', windowStart(now, DEDUP_WINDOW_MS))
    .limit(1);

  if (error) return true;
  return (data?.length ?? 0) > 0;
}

async function readCounts(now: Date): Promise<{ total: number; online: number }> {
  const [totalResult, onlineResult] = await Promise.all([
    db.from('page_view').select('id', { count: 'exact', head: true }),
    db
      .from('heartbeat')
      .select('visitor_id', { count: 'exact', head: true })
      .gte('last_seen_at', windowStart(now, ONLINE_WINDOW_MS))
  ]);

  return {
    total: totalResult.count ?? 0,
    online: onlineResult.count ?? 0
  };
}

Deno.serve(async (req: Request) => {
  const origin = req.headers.get('origin');

  if (req.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders(origin) });
  }

  const now = new Date();

  if (req.method === 'GET') {
    return json(await readCounts(now), 200, origin);
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

  const kind = payload.kind === 'heartbeat' ? 'heartbeat' : 'view';
  const visitorId = payload.visitorId;

  if (await overRateLimit(clientIp(req), now)) {
    return json({ error: 'rate limited' }, 429, origin);
  }

  // Heartbeats keep "online" fresh; they must never touch page_view or every
  // 45-second ping would inflate the total.
  await db
    .from('heartbeat')
    .upsert({ visitor_id: visitorId, last_seen_at: now.toISOString() });

  if (kind === 'view' && !(await alreadyCountedRecently(visitorId, now))) {
    await db.from('page_view').insert({ visitor_id: visitorId });
  }

  return json(await readCounts(now), 200, origin);
});
