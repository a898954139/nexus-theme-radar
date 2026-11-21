// tracking-candidates.json contract: what NexusDashboard reads (issue #6).
// Plain ESM with no imports so the Vercel Node runtime and `node --test` load
// the same file. Files under api/_lib are not deployed as functions.
//
// Mirrors TRACKING_CANDIDATES_REQUIRED_KEYS in scripts/radar_store.py, which
// refuses to store a payload that fails this check. Extra top-level keys are
// accepted: additive fields do not break the consumer, removals do.

export const TRACKING_CANDIDATES_REQUIRED_KEYS = Object.freeze([
  'generated_at',
  'market_id',
  'market_scope',
  'window_hours',
  'max_items',
  'total_items',
  'total_items_available',
  'items',
  'pre_cluster_items',
  'excluded_items',
  'tw_relevance_distribution',
  'tw_relevance_reason_distribution',
  'selected_theme_score_min',
  'candidate_theme_score_min',
  'matcher_contract',
  'taxonomy_version',
  'legacy_theme_count',
  'structured_theme_count',
  'theme_match_distribution',
  'theme_veto_distribution',
]);

// Per-item fields a downstream consumer keys on. Every published item carries
// them (see build of tracking candidates in scripts/update_theme_radar.py).
export const TRACKING_CANDIDATE_ITEM_KEYS = Object.freeze([
  'id',
  'title_zh',
  'url',
  'source_id',
  'published_at',
  'market_id',
  'matched_themes',
  'primary_theme_id',
  'related_symbols',
  'decision',
  'cluster_id',
]);

function isRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isInt(value) {
  return Number.isInteger(value) && value >= 0;
}

/** @param {unknown} value */
export function isTrackingCandidatesPayload(value) {
  if (!isRecord(value)) return false;
  for (const key of TRACKING_CANDIDATES_REQUIRED_KEYS) {
    if (!(key in value)) return false;
  }
  if (typeof value.generated_at !== 'string' || Number.isNaN(Date.parse(value.generated_at))) {
    return false;
  }
  if (typeof value.market_id !== 'string' || !Array.isArray(value.market_scope)) return false;
  for (const key of ['window_hours', 'max_items', 'total_items', 'total_items_available']) {
    if (!isInt(value[key])) return false;
  }
  if (!Array.isArray(value.items) || value.items.length !== value.total_items) return false;
  for (const item of value.items) {
    if (!isRecord(item)) return false;
    for (const key of TRACKING_CANDIDATE_ITEM_KEYS) {
      if (!(key in item)) return false;
    }
    if (!Array.isArray(item.matched_themes) || !Array.isArray(item.related_symbols)) return false;
  }
  return true;
}
