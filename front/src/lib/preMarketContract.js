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

// Optional top-level keys added by later tickets. #9 (PR #20) adds
// direction_rule_version; #10 adds market (market temperature). Listed here so
// either merge order keeps the board up.
export const PRE_MARKET_OPTIONAL_KEYS = Object.freeze(['direction_rule_version', 'market']);

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
  const keys = Object.keys(value);
  if (!PRE_MARKET_TOP_LEVEL_KEYS.every((key) => keys.includes(key))) return false;
  if (!keys.every((key) => PRE_MARKET_TOP_LEVEL_KEYS.includes(key) || PRE_MARKET_OPTIONAL_KEYS.includes(key))) return false;
  if ('direction_rule_version' in value && typeof value.direction_rule_version !== 'string') return false;
  if ('market' in value && !(isRecord(value.market) && Array.isArray(value.market.indicators))) return false;
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
