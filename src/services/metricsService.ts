// HTTP boundary for the visitor counter. Knows nothing about React.
//
// Every function here resolves rather than throws: the counter is decoration on
// a stock radar, and an analytics outage must never surface as a broken page.

const ENDPOINT = 'https://abtdxucfppnjdqkwqiqh.supabase.co/functions/v1/pageview';
const VISITOR_ID_KEY = 'nexus-visitor-id';
// The database sits in ap-southeast-2, so a POST costs ~2.5-3s of round trips
// before any client latency. 5s left almost no margin: a slow mobile leg pushed
// past it, and the aborted poll used to blank the counter.
const REQUEST_TIMEOUT_MS = 12000;

export interface SiteCounts {
  total: number;
  online: number;
}

/** Stable per-browser id. Clearable by the visitor, which the design accepts. */
export function visitorId(): string {
  try {
    const existing = window.localStorage.getItem(VISITOR_ID_KEY);
    if (existing) return existing;
    const created = crypto.randomUUID();
    window.localStorage.setItem(VISITOR_ID_KEY, created);
    return created;
  } catch {
    // Private mode or blocked storage: still report, just without continuity.
    return crypto.randomUUID();
  }
}

function isCounts(value: unknown): value is SiteCounts {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    Number.isFinite(candidate.total) &&
    Number.isFinite(candidate.online) &&
    (candidate.total as number) >= 0 &&
    (candidate.online as number) >= 0
  );
}

async function request(init: RequestInit): Promise<SiteCounts | null> {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(ENDPOINT, { ...init, signal: abort.signal });
    if (!response.ok) return null;
    const body: unknown = await response.json();
    return isCounts(body) ? { total: body.total, online: body.online } : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function post(kind: 'view' | 'heartbeat'): Promise<SiteCounts | null> {
  return request({
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ visitorId: visitorId(), kind })
  });
}

export function recordPageView(): Promise<SiteCounts | null> {
  return post('view');
}

export function sendHeartbeat(): Promise<SiteCounts | null> {
  return post('heartbeat');
}

export function fetchCounts(): Promise<SiteCounts | null> {
  return request({ method: 'GET' });
}
