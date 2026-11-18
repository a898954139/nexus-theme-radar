// Pre-market payload contract, shared by the browser (src/services/dataService.ts)
// and the server (api/pre-market.js). Plain ESM JavaScript with no imports so
// Vite, the Vercel Node runtime and `node --test` all load the same file.
//
// Mirrors what scripts/update_pre_market.py writes. The DB stores that payload
// verbatim (radar.pre_market_snapshot.payload), so this check is the API's
// response contract and the front end's acceptance test for either source.

export const PRE_MARKET_TOP_LEVEL_KEYS = Object.freeze([
  'schema_version',
  'generated_at',
  'window_hours',
  'sources',
  'events',
  'pulse',
  'sectors',
  'flows',
]);

export const PRE_MARKET_SCHEMA_VERSION = 1;

function isRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * @param {unknown} value
 * @returns {boolean}
 */
export function isPreMarketPayload(value) {
  if (!isRecord(value)) return false;
  const keys = Object.keys(value).sort();
  const expected = [...PRE_MARKET_TOP_LEVEL_KEYS].sort();
  if (keys.length !== expected.length || !keys.every((key, i) => key === expected[i])) return false;
  if (value.schema_version !== PRE_MARKET_SCHEMA_VERSION) return false;
  if (typeof value.generated_at !== 'string' || Number.isNaN(Date.parse(value.generated_at))) return false;
  if (typeof value.window_hours !== 'number') return false;
  if (!Array.isArray(value.sources) || !value.sources.every((s) => typeof s === 'string')) return false;
  if (!Array.isArray(value.events) || !value.events.every(isRecord)) return false;
  if (!Array.isArray(value.pulse) || !Array.isArray(value.sectors)) return false;
  const flows = value.flows;
  return isRecord(flows)
    && (flows.as_of === null || typeof flows.as_of === 'string')
    && Array.isArray(flows.panels);
}
