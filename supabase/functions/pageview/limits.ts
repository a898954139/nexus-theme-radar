// Pure validation and windowing rules for the pageview function.
//
// These are split out from index.ts so they can be tested without a database
// or an HTTP server. This is the code that decides whether a write is allowed,
// so it is the part worth testing directly.

export const DEDUP_WINDOW_MS = 30 * 60 * 1000;
export const ONLINE_WINDOW_MS = 2 * 60 * 1000;
export const RATE_LIMIT_WINDOW_MS = 60 * 1000;
export const RATE_LIMIT_MAX_REQUESTS = 20;

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

// The Pages URL and the CNAME both redirect to radar.mynexustrading.com, so
// that is the origin browsers actually send. The other two stay listed because
// a direct hit on either resolves before the redirect.
export const ALLOWED_ORIGINS = [
  'https://radar.mynexustrading.com',
  'https://a898954139.github.io',
  'https://news.learnprompt.pro'
];

export function isValidVisitorId(value: unknown): value is string {
  return typeof value === 'string' && UUID_PATTERN.test(value);
}

export function isAllowedOrigin(origin: string | null): boolean {
  // A same-origin or non-browser caller may omit Origin entirely. Rejecting
  // those breaks nothing an attacker relies on -- a script can set any Origin
  // it likes -- so this only stops other sites embedding the endpoint.
  if (!origin) return false;
  return ALLOWED_ORIGINS.includes(origin);
}

export function isRateLimited(recentRequestCount: number): boolean {
  return recentRequestCount >= RATE_LIMIT_MAX_REQUESTS;
}
