import {
  InstitutionalFlowItem,
  BrokerCoverageData,
  BrokerMapData,
  BrokerStatsData,
  FlowMetric,
  InstitutionalRankingBoard,
  InstitutionalRankingsData,
  MoatScreenData,
  MomentumHistoryData,
  MomentumLatestData,
  PathBacktestTable,
  PreMarketData,
  RadarData,
  SourceHealthData,
  SourceStatusData,
  StockWatchlistData,
  StockFundamentals,
  ThemeFocusData,
  ThemeEvent,
  ThemeRankingData
} from '../types';
import { isPreMarketPayload } from '../lib/preMarketContract.js';

const WATCHLIST_TOP_LEVEL_KEYS = [
  'schema_version',
  'methodology_version',
  'generated_at',
  'candidate_as_of',
  'sources',
  'methodology',
  'coverage',
  'short',
  'long',
  'searchable'
] as const;

const WATCHLIST_ITEM_KEYS = [
  'instrument',
  'themes',
  'short',
  'long',
  'institutional',
  'trading_activity',
  'fundamentals',
  'flags',
  'coverage'
] as const;

const WATCHLIST_SEARCHABLE_KEYS = ['instrument', 'themes', 'selected_top50', 'short_rank', 'long_rank', 'flags'] as const;
const WATCHLIST_INSTRUMENT_KEYS = ['instrument_id', 'symbol', 'exchange', 'name_zh'] as const;
const WATCHLIST_THEME_KEYS = ['theme_id', 'name_zh', 'relation', 'heat_score', 'heat_change_24h', 'momentum_score'] as const;
const WATCHLIST_SCORE_KEYS = ['rank', 'score', 'components'] as const;
const WATCHLIST_SCORE_WITH_RISK_KEYS = [...WATCHLIST_SCORE_KEYS, 'risk_adjustment'] as const;
const WATCHLIST_SCORE_COMPONENT_KEYS = ['raw', 'normalized', 'base_weight', 'effective_weight', 'available'] as const;
const WATCHLIST_FLAG_KEYS = ['key', 'type'] as const;
const WATCHLIST_INSTITUTIONAL_KEYS = ['direction', 'as_of', 'observation_count', 'five_day_net'] as const;
const WATCHLIST_TRADING_KEYS = ['as_of', 'day_trading_volume', 'total_volume', 'day_trading_volume_ratio', 'overnight_risk', 'overnight_missing_reason'] as const;
const WATCHLIST_FUNDAMENTAL_KEYS = ['score', 'fiscal_quarter', 'comparison_basis', 'revenue_growth', 'revenue_direction', 'eps_growth', 'eps_direction', 'gross_margin', 'operating_margin', 'operating_cash_flow', 'operating_cash_flow_margin', 'debt_ratio'] as const;
const WATCHLIST_COVERAGE_KEYS = ['short_ratio', 'long_ratio', 'missing'] as const;
const WATCHLIST_LIST_KEYS = ['count', 'items'] as const;
const WATCHLIST_TOP_COVERAGE_KEYS = ['eligible_count', 'selected_count', 'metrics', 'missing_reasons'] as const;
const WATCHLIST_RISK_ADJUSTMENT_KEYS = ['overnight_risk_adjustment'] as const;
const WATCHLIST_RISK_ENTRY_KEYS = ['value', 'applied', 'missing_reason'] as const;
const WATCHLIST_SOURCES_KEYS = ['momentum', 'institutional', 'fundamentals', 'day_trading_activity'] as const;
const WATCHLIST_MOMENTUM_SOURCE_KEYS = ['generated_at', 'observed_hour'] as const;
const WATCHLIST_INSTITUTIONAL_SOURCE_KEYS = ['as_of'] as const;
const WATCHLIST_FUNDAMENTALS_SOURCE_KEYS = ['fiscal_quarters'] as const;
const WATCHLIST_DAY_TRADING_MARKETS = ['TWSE', 'TPEX'] as const;
const WATCHLIST_DAY_TRADING_SOURCE_KEYS = ['as_of', 'finality', 'numerator_url', 'denominator_url', 'status', 'error'] as const;
const WATCHLIST_METHODOLOGY_KEYS = ['missing_values', 'top50', 'short_weights', 'long_weights', 'fundamental_quality_weights'] as const;
const WATCHLIST_SHORT_COMPONENT_KEYS = ['theme_attention', 'institutional_short_activity', 'daytrade_activity', 'fundamental_defense'] as const;
const WATCHLIST_LONG_COMPONENT_KEYS = ['fundamental_quality', 'institutional_support', 'theme_persistence', 'trading_stability'] as const;
const WATCHLIST_FUNDAMENTAL_QUALITY_KEYS = ['growth', 'profitability', 'structure'] as const;
const WATCHLIST_FLAG_NAMES = new Set([
  'heat_rising', 'multi_theme', 'institutional_positive', 'fundamentals_improving',
  'high_daytrade', 'overnight_risk', 'cashflow_weak', 'high_leverage', 'data_sparse'
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const required = [...expected].sort();
  return actual.length === required.length && actual.every((key, index) => key === required[index]);
}

function isNumberOrNull(value: unknown): boolean {
  return value === null || typeof value === 'number';
}

function isWatchlistInstrument(value: unknown): boolean {
  return isRecord(value)
    && hasExactKeys(value, WATCHLIST_INSTRUMENT_KEYS)
    && typeof value.instrument_id === 'string'
    && typeof value.symbol === 'string'
    && (value.exchange === 'TWSE' || value.exchange === 'TPEX')
    && typeof value.name_zh === 'string';
}

function isWatchlistTheme(value: unknown): boolean {
  return isRecord(value)
    && hasExactKeys(value, WATCHLIST_THEME_KEYS)
    && typeof value.theme_id === 'string'
    && typeof value.name_zh === 'string'
    && (value.relation === 'direct' || value.relation === 'related')
    && isNumberOrNull(value.heat_score)
    && isNumberOrNull(value.heat_change_24h)
    && isNumberOrNull(value.momentum_score);
}

function isWatchlistFlag(value: unknown): boolean {
  return isRecord(value)
    && hasExactKeys(value, WATCHLIST_FLAG_KEYS)
    && typeof value.key === 'string' && WATCHLIST_FLAG_NAMES.has(value.key)
    && (value.type === 'risk' || value.type === 'positive' || value.type === 'info');
}

function isScoreComponent(value: unknown): boolean {
  return isRecord(value)
    && hasExactKeys(value, WATCHLIST_SCORE_COMPONENT_KEYS)
    && isNumberOrNull(value.raw)
    && isNumberOrNull(value.normalized)
    && typeof value.base_weight === 'number'
    && typeof value.effective_weight === 'number'
    && typeof value.available === 'boolean';
}

function isRiskAdjustment(value: unknown): boolean {
  if (!isRecord(value) || !hasExactKeys(value, WATCHLIST_RISK_ADJUSTMENT_KEYS)) return false;
  const entry = value.overnight_risk_adjustment;
  return isRecord(entry)
    && hasExactKeys(entry, WATCHLIST_RISK_ENTRY_KEYS)
    && isNumberOrNull(entry.value)
    && typeof entry.applied === 'number'
    && (entry.missing_reason === null || typeof entry.missing_reason === 'string');
}

function isScoreSummary(value: unknown, withRiskAdjustment: boolean): boolean {
  if (!isRecord(value)) return false;
  const exact = hasExactKeys(value, withRiskAdjustment ? WATCHLIST_SCORE_WITH_RISK_KEYS : WATCHLIST_SCORE_KEYS);
  const expectedComponents = withRiskAdjustment ? WATCHLIST_SHORT_COMPONENT_KEYS : WATCHLIST_LONG_COMPONENT_KEYS;
  return exact
    // moat_v1: a short-only name (outside the long list) carries long.rank = null.
    && (typeof value.rank === 'number' || (!withRiskAdjustment && value.rank === null))
    && typeof value.score === 'number'
    && isRecord(value.components) && hasExactKeys(value.components, expectedComponents)
    && Object.values(value.components).every(isScoreComponent)
    && (!withRiskAdjustment || isRiskAdjustment(value.risk_adjustment));
}

function isWatchlistSources(value: Record<string, unknown>): boolean {
  const momentum = value.momentum;
  const institutional = value.institutional;
  const fundamentals = value.fundamentals;
  const dayTrading = value.day_trading_activity;
  if (!isRecord(momentum) || !hasExactKeys(momentum, WATCHLIST_MOMENTUM_SOURCE_KEYS)) return false;
  if (!isRecord(institutional) || !hasExactKeys(institutional, WATCHLIST_INSTITUTIONAL_SOURCE_KEYS)) return false;
  if (!isRecord(fundamentals) || !hasExactKeys(fundamentals, WATCHLIST_FUNDAMENTALS_SOURCE_KEYS)) return false;
  if (!isRecord(dayTrading) || !hasExactKeys(dayTrading, WATCHLIST_DAY_TRADING_MARKETS)) return false;
  return WATCHLIST_DAY_TRADING_MARKETS.every((market) => {
    const source = dayTrading[market];
    return isRecord(source)
      && hasExactKeys(source, WATCHLIST_DAY_TRADING_SOURCE_KEYS)
      && (source.status === 'fresh' || source.status === 'stale' || source.status === 'missing');
  });
}

function isWatchlistMethodology(value: Record<string, unknown>): boolean {
  const shortWeights = value.short_weights;
  const longWeights = value.long_weights;
  const qualityWeights = value.fundamental_quality_weights;
  return isRecord(shortWeights) && hasExactKeys(shortWeights, WATCHLIST_SHORT_COMPONENT_KEYS)
    && Object.values(shortWeights).every((weight) => typeof weight === 'number')
    && isRecord(longWeights) && hasExactKeys(longWeights, WATCHLIST_LONG_COMPONENT_KEYS)
    && Object.values(longWeights).every((weight) => typeof weight === 'number')
    && isRecord(qualityWeights) && hasExactKeys(qualityWeights, WATCHLIST_FUNDAMENTAL_QUALITY_KEYS)
    && Object.values(qualityWeights).every((weight) => typeof weight === 'number');
}

function isWatchlistItem(item: unknown): item is Record<string, unknown> {
  if (!isRecord(item) || !hasExactKeys(item, WATCHLIST_ITEM_KEYS)) return false;
  return isWatchlistInstrument(item.instrument)
    && Array.isArray(item.themes) && item.themes.every(isWatchlistTheme)
    && isScoreSummary(item.short, true)
    && isScoreSummary(item.long, false)
    && isRecord(item.institutional) && hasExactKeys(item.institutional, WATCHLIST_INSTITUTIONAL_KEYS)
    && isRecord(item.trading_activity) && hasExactKeys(item.trading_activity, WATCHLIST_TRADING_KEYS)
    && isRecord(item.fundamentals) && hasExactKeys(item.fundamentals, WATCHLIST_FUNDAMENTAL_KEYS)
    && Array.isArray(item.flags) && item.flags.every(isWatchlistFlag)
    && isRecord(item.coverage) && hasExactKeys(item.coverage, WATCHLIST_COVERAGE_KEYS);
}

function isSearchableItem(item: unknown): boolean {
  return isRecord(item)
    && hasExactKeys(item, WATCHLIST_SEARCHABLE_KEYS)
    && isWatchlistInstrument(item.instrument)
    && Array.isArray(item.themes) && item.themes.every(isWatchlistTheme)
    && typeof item.selected_top50 === 'boolean'
    && isNumberOrNull(item.short_rank)
    && isNumberOrNull(item.long_rank)
    && Array.isArray(item.flags) && item.flags.every(isWatchlistFlag);
}

export function isStockWatchlistData(value: unknown): value is StockWatchlistData {
  if (!isRecord(value) || !hasExactKeys(value, WATCHLIST_TOP_LEVEL_KEYS)) return false;
  if (value.schema_version !== 'nexus_stock_watchlist.v1') return false;
  if (!isRecord(value.short) || !isRecord(value.long)) return false;
  if (!isRecord(value.sources) || !hasExactKeys(value.sources, WATCHLIST_SOURCES_KEYS) || !isWatchlistSources(value.sources)) return false;
  if (!isRecord(value.methodology) || !hasExactKeys(value.methodology, WATCHLIST_METHODOLOGY_KEYS) || !isWatchlistMethodology(value.methodology)) return false;
  if (!hasExactKeys(value.short, WATCHLIST_LIST_KEYS) || !hasExactKeys(value.long, WATCHLIST_LIST_KEYS)) return false;
  if (!isRecord(value.coverage) || !hasExactKeys(value.coverage, WATCHLIST_TOP_COVERAGE_KEYS)) return false;
  if (!Array.isArray(value.short.items) || !Array.isArray(value.long.items) || !Array.isArray(value.searchable)) return false;

  if (![...value.short.items, ...value.long.items].every(isWatchlistItem)) return false;
  if (!value.searchable.every(isSearchableItem)) return false;
  const shortIds = value.short.items.map((item) => (item.instrument as Record<string, unknown>).instrument_id);
  const longIds = value.long.items.map((item) => (item.instrument as Record<string, unknown>).instrument_id);
  // moat_v1: the long list is a subset of the short list.
  const longWithinShort = longIds.every((id) => shortIds.includes(id));
  const ranksContinuous = value.short.items.every((item, index) => (item.short as Record<string, unknown>).rank === index + 1)
    && value.long.items.every((item, index) => (item.long as Record<string, unknown>).rank === index + 1);
  return longWithinShort
    && ranksContinuous
    && typeof value.short.count === 'number'
    && typeof value.long.count === 'number'
    && value.short.count === value.short.items.length
    && value.long.count === value.long.items.length;
}

/**
 * Every dataset comes from the Vercel API backed by the normalized radar
 * tables (docs/RADAR_RELATIONAL.md); the site serves no data files.
 */
export const API_BASE = '/api/v1';
const API_TIMEOUT_MS = 10000;

export class ApiNotFound extends Error {}

async function readApi<T>(dataset: string, params: Record<string, string | undefined> = {}, cacheBust = false): Promise<T> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value) search.set(key, value);
  if (cacheBust) search.set('refresh', String(Date.now()));
  const query = search.toString();
  const path = `${API_BASE}/${dataset}${query ? `?${query}` : ''}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  try {
    const response = await fetch(path, { cache: cacheBust ? 'no-store' : 'default', signal: controller.signal });
    if (response.status === 404) throw new ApiNotFound(`${dataset}: not found`);
    if (!response.ok) throw new Error(`Unable to load ${dataset}: ${response.status}`);
    return (await response.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export async function loadRadarData(cacheBust = false): Promise<RadarData> {
  const [themeRanking, momentumLatest, momentumHistory, events, sourceStatus] = await Promise.all([
    readApi<ThemeRankingData>('theme-ranking', {}, cacheBust),
    readApi<MomentumLatestData>('theme-momentum', {}, cacheBust),
    readApi<MomentumHistoryData>('theme-momentum-history', {}, cacheBust),
    readApi<{ items: ThemeEvent[] }>('theme-events', {}, cacheBust),
    readApi<SourceStatusData>('source-status', {}, cacheBust),
  ]);

  return {
    themeRanking,
    momentumLatest,
    momentumHistory,
    events: events.items,
    sourceStatus,
  };
}

/**
 * Live per-source fetch health from the DB (Vercel /api/source-health).
 * Resolves to null on any failure so the snapshot-based source table keeps
 * rendering on its own.
 */
export async function fetchSourceHealth(): Promise<SourceHealthData | null> {
  try {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 8000);
    const response = await fetch('/api/source-health', { signal: controller.signal });
    window.clearTimeout(timer);
    if (!response.ok || !(response.headers.get('content-type') || '').includes('application/json')) {
      return null;
    }
    const body = (await response.json()) as SourceHealthData;
    return Array.isArray(body?.sources) ? body : null;
  } catch {
    return null;
  }
}

/**
 * Pre-market board. Resolves to null instead of throwing: the wire feed and the
 * quote source are both third-party, and the homepage must still render its
 * theme and news sections when the board is unavailable.
 */
/**
 * Path backtest hit rates straight from radar.path_backtest. Null on any
 * failure: the page then falls back to the copy each pre-market event carries.
 */
export async function fetchPathBacktest(cacheBust = false): Promise<PathBacktestTable | null> {
  try {
    const payload = await readApi<PathBacktestTable>('path-backtest', {}, cacheBust);
    return payload && typeof payload === 'object' && payload.paths && typeof payload.paths === 'object' ? payload : null;
  } catch {
    return null;
  }
}

export async function fetchPreMarket(cacheBust = false): Promise<PreMarketData | null> {
  try {
    const payload = await readApi<unknown>('pre-market', {}, cacheBust);
    return isPreMarketPayload(payload) ? (payload as PreMarketData) : null;
  } catch {
    return null;
  }
}

export async function fetchStockWatchlist(cacheBust = false): Promise<StockWatchlistData> {
  const payload = await readApi<unknown>('stock-watchlist', {}, cacheBust);
  if (!isStockWatchlistData(payload)) {
    throw new Error('Invalid public stock watchlist v1 payload');
  }
  return payload;
}

async function readInstitutionalData(cacheBust = false): Promise<InstitutionalRankingsData> {
  return readApi<InstitutionalRankingsData>('institutional-rankings', {}, cacheBust);
}

export async function fetchInstitutionalRankings(
  days: number,
  direction: 'up' | 'down',
  metric: FlowMetric = 'net',
  cacheBust = false
) {
  const data = await readInstitutionalData(cacheBust);
  const prefix = metric === 'net' ? 'top_three_inst_netbuy' : 'top_three_inst_change';
  const key = `${prefix}_${days}_${direction}`;
  return data.rankings[key]?.entries ?? [];
}

/** Same board as fetchInstitutionalRankings, with its date range and source. */
export async function fetchInstitutionalBoard(
  days: number,
  direction: 'up' | 'down',
  metric: FlowMetric = 'net',
  cacheBust = false
): Promise<InstitutionalRankingBoard | null> {
  const data = await readInstitutionalData(cacheBust);
  const prefix = metric === 'net' ? 'top_three_inst_netbuy' : 'top_three_inst_change';
  const board = data.rankings[`${prefix}_${days}_${direction}`];
  if (!board) return null;
  return { ...board, source: board.source ?? data.source };
}

function instrumentQuery(symbol: string, exchange?: string): Record<string, string | undefined> {
  if (symbol.includes(':')) return { instrument_id: symbol };
  return { symbol, exchange };
}

/** Daily three-institution net (shares), newest first; whole market. */
export async function fetchInstitutionalFlows(symbol: string, exchange?: string, cacheBust = false): Promise<InstitutionalFlowItem[]> {
  const body = await readApi<{ items: InstitutionalFlowItem[] }>(
    'institutional-flows', instrumentQuery(symbol, exchange), cacheBust,
  );
  return body.items ?? [];
}

export async function fetchBrokerStats(cacheBust = false): Promise<BrokerStatsData> {
  return readApi<BrokerStatsData>('broker-stats', {}, cacheBust);
}

export async function fetchBrokerCoverage(cacheBust = false): Promise<BrokerCoverageData> {
  return readApi<BrokerCoverageData>('broker-coverage', {}, cacheBust);
}

export async function fetchBrokerMap(symbol: string, cacheBust = false): Promise<BrokerMapData | null> {
  try {
    return await readApi<BrokerMapData>('broker-map', { symbol }, cacheBust);
  } catch (error) {
    if (error instanceof ApiNotFound) return null;
    throw error;
  }
}

export async function fetchStockFundamentals(symbol: string, exchange?: string, cacheBust = false): Promise<StockFundamentals | null> {
  try {
    return await readApi<StockFundamentals>('fundamentals', instrumentQuery(symbol, exchange), cacheBust);
  } catch (error) {
    if (error instanceof ApiNotFound) return null;
    throw error;
  }
}

/**
 * Theme x institutional-flow focus board. Resolves to null instead of throwing:
 * every page that shows the board must still render without it.
 */
export async function fetchThemeFocus(cacheBust = false): Promise<ThemeFocusData | null> {
  try {
    const payload = await readApi<ThemeFocusData>('theme-focus', {}, cacheBust);
    if (payload?.schema_version !== 'nexus_theme_focus.v1' || !Array.isArray(payload.themes)) return null;
    return payload;
  } catch {
    return null;
  }
}

const MOAT_RULES = ['roe_ttm', 'gross_margin_4q', 'debt_ratio', 'operating_cash_flow_ttm'] as const;
const MOAT_FAILURES = new Set<string>([...MOAT_RULES, ...MOAT_RULES.map((rule) => `${rule}_missing`), 'no_fundamentals']);

function isMoatScreenItem(value: unknown): boolean {
  if (!isRecord(value)) return false;
  if (!hasExactKeys(value, ['instrument', 'themes', 'has_fundamentals', 'metrics', 'failed', 'short_pass', 'long_pass',
    'selected_top50', 'short_rank', 'long_rank'])) return false;
  const metrics = value.metrics;
  return isWatchlistInstrument(value.instrument)
    && Array.isArray(value.themes)
    && value.themes.every((theme) => isRecord(theme) && hasExactKeys(theme, ['theme_id', 'name_zh', 'relation'])
      && typeof theme.theme_id === 'string' && typeof theme.name_zh === 'string'
      && (theme.relation === 'direct' || theme.relation === 'related'))
    && typeof value.has_fundamentals === 'boolean'
    && isRecord(metrics) && hasExactKeys(metrics, MOAT_RULES) && MOAT_RULES.every((rule) => isNumberOrNull(metrics[rule]))
    && Array.isArray(value.failed) && value.failed.every((rule) => typeof rule === 'string' && MOAT_FAILURES.has(rule))
    && typeof value.short_pass === 'boolean' && typeof value.long_pass === 'boolean'
    && typeof value.selected_top50 === 'boolean'
    && isNumberOrNull(value.short_rank) && isNumberOrNull(value.long_rank)
    && (value.short_pass || (!value.long_pass && !value.selected_top50));
}

export function isMoatScreenData(value: unknown): value is MoatScreenData {
  if (!isRecord(value) || !hasExactKeys(value, ['rule_version', 'generated_at', 'thresholds', 'universe', 'candidates', 'rules', 'items'])) return false;
  const { thresholds, universe, candidates, rules, items } = value;
  const allNumbers = (record: unknown, keys: readonly string[]) =>
    isRecord(record) && hasExactKeys(record, keys) && keys.every((key) => typeof record[key] === 'number');
  return typeof value.rule_version === 'string'
    && typeof value.generated_at === 'string'
    && allNumbers(thresholds, ['roe_ttm_min', 'gross_margin_4q_min', 'debt_ratio_max', 'operating_cash_flow_ttm_min_exclusive'])
    && allNumbers(universe, ['evaluated', 'short_pass', 'long_pass'])
    && allNumbers(candidates, ['count', 'evaluated', 'short_pass', 'long_pass', 'no_fundamentals'])
    && Array.isArray(rules) && rules.length === MOAT_RULES.length
    && rules.every((rule, index) => isRecord(rule)
      && hasExactKeys(rule, ['rule', 'in_short', 'in_long', 'universe_p25', 'universe_p50', 'universe_p75', 'universe_failed', 'universe_missing'])
      && rule.rule === MOAT_RULES[index]
      && typeof rule.in_short === 'boolean' && typeof rule.in_long === 'boolean'
      && isNumberOrNull(rule.universe_p25) && isNumberOrNull(rule.universe_p50) && isNumberOrNull(rule.universe_p75)
      && typeof rule.universe_failed === 'number' && typeof rule.universe_missing === 'number')
    && Array.isArray(items) && items.every(isMoatScreenItem);
}

/**
 * Moat screen report for the stock radar page. Null on any failure (including
 * before its migration runs): the page then hides the report and still renders.
 */
export async function fetchMoatScreen(cacheBust = false): Promise<MoatScreenData | null> {
  try {
    const payload = await readApi<unknown>('moat-screen', {}, cacheBust);
    return isMoatScreenData(payload) ? payload : null;
  } catch {
    return null;
  }
}
