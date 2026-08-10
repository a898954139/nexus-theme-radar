import {
  InstitutionalFlowItem,
  BrokerCoverageData,
  BrokerMapData,
  BrokerStatsData,
  FlowMetric,
  InstitutionalRankingsData,
  MomentumHistoryData,
  MomentumLatestData,
  RadarData,
  SourceStatusData,
  StockWatchlistData,
  StockFundamentals,
  ThemeEvent,
  ThemeRankingData,
  WaytoAgiData
} from '../types';

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
    && typeof value.rank === 'number'
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
  const sameSet = shortIds.length === longIds.length && shortIds.every((id) => longIds.includes(id));
  const ranksContinuous = value.short.items.every((item, index) => (item.short as Record<string, unknown>).rank === index + 1)
    && value.long.items.every((item, index) => (item.long as Record<string, unknown>).rank === index + 1);
  return sameSet
    && ranksContinuous
    && typeof value.short.count === 'number'
    && typeof value.long.count === 'number'
    && value.short.count === value.short.items.length
    && value.long.count === value.long.items.length;
}

async function readJson<T>(path: string, cacheBust = false): Promise<T> {
  const requestPath = cacheBust ? `${path}${path.includes('?') ? '&' : '?'}refresh=${Date.now()}` : path;
  const response = await fetch(requestPath, { cache: cacheBust ? 'no-store' : 'default' });
  if (!response.ok) {
    throw new Error(`Unable to load ${path}: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function loadRadarData(cacheBust = false): Promise<RadarData> {
  const [themeRanking, momentumLatest, momentumHistory, events, sourceStatus, waytoagi] = await Promise.all([
    readJson<ThemeRankingData>('./data/public-theme-ranking-v0.8.json', cacheBust),
    readJson<MomentumLatestData>('./data/public-theme-momentum-latest-v0.9.json', cacheBust),
    readJson<MomentumHistoryData>('./data/public-theme-momentum-history-v0.9.json', cacheBust),
    readJson<{ items: ThemeEvent[] }>('./data/theme-events.json', cacheBust),
    readJson<SourceStatusData>('./data/source-status.json', cacheBust),
    readJson<WaytoAgiData>('./data/waytoagi-7d.json', cacheBust)
  ]);

  return {
    themeRanking,
    momentumLatest,
    momentumHistory,
    events: events.items,
    sourceStatus,
    waytoagi
  };
}

export async function fetchStockWatchlist(cacheBust = false): Promise<StockWatchlistData> {
  const payload = await readJson<unknown>('./data/public-stock-watchlist-v1.json', cacheBust);
  if (!isStockWatchlistData(payload)) {
    throw new Error('Invalid public stock watchlist v1 payload');
  }
  return payload;
}

async function readInstitutionalData(cacheBust = false): Promise<InstitutionalRankingsData> {
  return readJson<InstitutionalRankingsData>('./data/institutional-rankings.json', cacheBust);
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

function resolveInstrumentKey(symbol: string, exchange?: string): string[] {
  if (symbol.includes(':')) return [symbol];
  if (exchange) return [`${exchange}:${symbol}`];
  return [`TWSE:${symbol}`, `TPEX:${symbol}`];
}

export async function fetchInstitutionalFlows(symbol: string, exchange?: string, cacheBust = false): Promise<InstitutionalFlowItem[]> {
  const data = await readJson<{ symbols: Record<string, InstitutionalFlowItem[]> }>('./data/institutional-flows.json', cacheBust);
  for (const key of resolveInstrumentKey(symbol, exchange)) {
    if (data.symbols[key]) return data.symbols[key];
  }
  return [];
}

export async function fetchBrokerStats(cacheBust = false): Promise<BrokerStatsData> {
  return readJson<BrokerStatsData>('./data/broker-stats.json', cacheBust);
}

export async function fetchBrokerCoverage(cacheBust = false): Promise<BrokerCoverageData> {
  return readJson<BrokerCoverageData>('./data/broker-coverage.json', cacheBust);
}

export async function fetchBrokerMap(symbol: string, cacheBust = false): Promise<BrokerMapData | null> {
  const index = await readJson<{
    symbols: Record<string, {
      file: string;
      name?: string;
      broker_count?: number;
      summary?: { buy: number; sell: number; net: number };
    }>;
  }>('./data/broker-map/index.json', cacheBust);
  const metadata = index.symbols?.[symbol];
  if (!metadata?.file) return null;
  const brokers = await readJson<BrokerMapData['brokers']>(`./data/broker-map/${metadata.file}`, cacheBust);
  const summary = metadata.summary ?? {
    buy: brokers.reduce((total, branch) => total + Math.max(branch.net, 0), 0),
    sell: brokers.reduce((total, branch) => total + Math.max(-branch.net, 0), 0),
    net: brokers.reduce((total, branch) => total + branch.net, 0),
  };
  return {
    schema_version: 1,
    generated_at: '',
    source: '',
    unit: 'lots',
    stock_code: symbol,
    stock_name: metadata.name ?? '',
    summary: { ...summary, broker_count: metadata.broker_count ?? brokers.length },
    brokers,
  };
}

export async function fetchStockFundamentals(symbol: string, exchange?: string, cacheBust = false): Promise<StockFundamentals | null> {
  const index = await readJson<{ symbols: Record<string, { file: string }> }>('./data/fundamentals-index.json', cacheBust);
  for (const key of resolveInstrumentKey(symbol, exchange)) {
    const filename = index.symbols[key]?.file;
    if (filename) {
      return readJson<StockFundamentals>(`./data/fundamentals/${encodeURIComponent(filename)}`, cacheBust);
    }
  }
  return null;
}
