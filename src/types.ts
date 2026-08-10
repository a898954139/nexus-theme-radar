export type PageType = 'index' | 'momentum' | 'flows' | 'watchlist' | 'stock' | 'sources';
export type DeviceType = 'desktop' | 'mobile';
export type LoadState = 'normal' | 'loading' | 'empty';
export type StockTab = 'fundamentals' | 'technical' | 'flows' | 'broker';
export type StockGroup = 'all' | 'direct' | 'supply';
export type FlowMetric = 'net' | 'ratio';
export type FlowDirection = 'up' | 'down';
export type FlowView = 'bars' | 'matrix' | 'table';

export interface InstrumentRef {
  instrument_id: string;
  symbol: string;
  exchange: string;
  name_zh: string;
  direct_event_count?: number;
  official_evidence_count?: number;
  company_rank_score?: number;
  latest_mentioned_at?: string | null;
  latest_official_at?: string | null;
}

export interface RepresentativeNews {
  id: string;
  cluster_id?: string;
  title_zh: string;
  summary: string;
  source: string;
  source_id?: string;
  published_at: string;
  canonical_url: string;
}

export interface ThemeRankingItem {
  rank: number;
  theme_id: string;
  name_zh: string;
  heat_score: number;
  summaries?: {
    event_count: number;
    source_count: number;
    tracking_candidate_count: number;
    taiwan_mapping_count: number;
  };
  direct_mentions: InstrumentRef[];
  supply_chain_candidates: InstrumentRef[];
  representative_news?: RepresentativeNews;
}

export interface ThemeRankingData {
  generated_at: string;
  themes: ThemeRankingItem[];
  [key: string]: unknown;
}

export interface MomentumTheme {
  rank: number;
  theme_id: string;
  name_zh: string;
  qualification_status: string;
  momentum_score: number;
  lifecycle_stage: string;
  heat_score: number;
  heat_change_24h: number | null;
  direct_symbols: InstrumentRef[];
  related_symbols: InstrumentRef[];
  [key: string]: unknown;
}

export interface MomentumLatestData {
  generated_at: string;
  observed_hour: string;
  themes: MomentumTheme[];
  [key: string]: unknown;
}

export interface MomentumHistoryTheme {
  theme_id: string;
  rank: number;
  momentum_score: number;
  lifecycle_stage: string;
  heat_score: number;
  qualification_status?: string;
  [key: string]: unknown;
}

export interface MomentumHistoryPoint {
  observed_hour: string;
  themes: MomentumHistoryTheme[];
}

export interface MomentumHistoryData {
  generated_at: string;
  observations: MomentumHistoryPoint[];
  [key: string]: unknown;
}

export interface ThemeEvent {
  id: string;
  title_zh: string;
  summary: string;
  source: string;
  source_id: string;
  published_at: string;
  url?: string;
  primary_theme_id?: string;
  matched_themes?: Array<{ theme_id: string; name_zh: string }>;
  direct_symbols?: InstrumentRef[];
  related_symbols?: InstrumentRef[];
  related_symbol_codes?: string[];
  [key: string]: unknown;
}

export interface NewsItem {
  id: string;
  title_zh: string;
  source: string;
  published_at: string;
  url?: string;
  theme_name_zh?: string;
  theme_id?: string;
  symbols: InstrumentRef[];
}

export interface InstitutionalRankingEntry {
  code: string;
  name: string;
  exchange: string;
  instrument_id: string;
  in_universe: boolean;
  is_etf: boolean;
  ratio_out_of_range?: boolean;
  three_inst_ratio?: number;
  change?: number;
  rank?: number;
  foreign?: number;
  trust?: number;
  dealer?: number;
  total?: number;
}

export interface InstitutionalRankingsData {
  generated_at: string;
  rankings: Record<string, { entries: InstitutionalRankingEntry[] }>;
}

export interface InstitutionalFlowItem {
  date: string;
  foreign_net: number;
  trust_net: number;
  dealer_net: number;
  total_net: number;
}

export interface BrokerStat {
  name: string;
  buy: number;
  sell: number;
  dt: number | null;
  ov: number | null;
  top: Array<[string, string]>;
}

export type BrokerStatsData = BrokerStat[];

export interface BrokerMapBranch {
  id: string;
  name: string;
  net: number;
  ratio: number;
  stocks: Array<[string, string, number]>;
}

export interface BrokerMapData {
  schema_version: number;
  generated_at: string;
  source: string;
  unit: 'lots' | string;
  stock_code: string;
  stock_name: string;
  summary?: {
    buy: number;
    sell: number;
    net: number;
    broker_count: number;
  };
  brokers: BrokerMapBranch[];
}

export interface BrokerCoverageData {
  schema_version: number;
  generated_at: string;
  source_updated: string | null;
  source: string;
  source_scope: string;
  requested_symbols: number;
  attempted_symbols: number;
  failed_symbols: number;
  successful_symbols: number;
  symbols_with_data: number;
  attempt_coverage: number;
  data_coverage: number;
  data_coverage_denominator: 'requested_symbols' | string;
  failed_symbol_codes: string[];
  no_data_symbol_codes: string[];
  not_attempted_symbol_codes: string[];
  status: 'complete' | 'incomplete' | string;
}

export interface FinancialQuarter {
  period: string;
  revenue: number;
  gross_margin: number;
  operating_margin: number;
  net_margin: number;
  eps: number;
}

export interface FinancialStatementRow {
  [key: string]: number | string | null | undefined;
}

export interface StockStatements {
  income: Record<string, FinancialStatementRow>;
  balance: Record<string, FinancialStatementRow>;
  cash_flow: Record<string, FinancialStatementRow>;
}

export interface StockFundamentals {
  quarters: FinancialQuarter[];
  health: {
    cash: number;
    current_ratio: number;
    debt_ratio: number;
    net_income_2026Q2?: number;
    net_income_2026Q1?: number;
    operating_cash_flow_2026Q2?: number;
    operating_cash_flow_2026Q1?: number;
  };
  valuation: { ttm_eps: number };
  statements: StockStatements;
  basis: string;
  currency: string;
  source: string;
  fetched_at: string;
  fiscal_quarter: string;
  missing: string[];
}

export interface SourceSite {
  source_id: string;
  name: string;
  source_class?: string;
  adapter?: string;
  fetch_method?: string;
  status: 'ok' | 'delayed' | 'failed' | string;
  items?: number;
  error?: string | null;
}

export interface SourceStatusData {
  generated_at: string;
  successful_sites: number;
  failed_count: number;
  sites: SourceSite[];
}

export interface WaytoAgiUpdate {
  date: string;
  title: string;
  summary: string;
  url: string;
}

export interface WaytoAgiData {
  generated_at: string;
  latest_date: string;
  count_today: number;
  count_7d: number;
  updates_today: WaytoAgiUpdate[];
  updates_7d?: WaytoAgiUpdate[];
}

export interface RadarData {
  themeRanking: ThemeRankingData;
  momentumLatest: MomentumLatestData;
  momentumHistory: MomentumHistoryData;
  events: ThemeEvent[];
  sourceStatus: SourceStatusData;
  waytoagi: WaytoAgiData;
}

export type WatchlistExchange = 'TWSE' | 'TPEX';
export type WatchlistRelation = 'direct' | 'related';
export type WatchlistDirection = 'up' | 'flat' | 'down' | 'unknown';
export type InstitutionalDirection = 'positive' | 'negative' | 'flat' | 'insufficient';
export type StockFlagKey =
  | 'heat_rising'
  | 'multi_theme'
  | 'institutional_positive'
  | 'fundamentals_improving'
  | 'high_daytrade'
  | 'overnight_risk'
  | 'cashflow_weak'
  | 'high_leverage'
  | 'data_sparse';

export interface WatchlistInstrument {
  instrument_id: string;
  symbol: string;
  exchange: WatchlistExchange;
  name_zh: string;
}

export interface WatchlistTheme {
  theme_id: string;
  name_zh: string;
  relation: WatchlistRelation;
  heat_score: number | null;
  heat_change_24h: number | null;
  momentum_score: number | null;
}

export interface StockFlag {
  key: StockFlagKey;
  type: 'risk' | 'positive' | 'info';
}

export interface ScoreComponent {
  raw: number | null;
  normalized: number | null;
  base_weight: number;
  effective_weight: number;
  available: boolean;
}

export interface ScoreSummary {
  rank: number;
  score: number;
  components: Record<string, ScoreComponent>;
  risk_adjustment?: Record<string, {
    value: number | null;
    applied: number;
    missing_reason?: string | null;
  }>;
}

export interface WatchlistInstitutional {
  direction: InstitutionalDirection;
  as_of: string | null;
  observation_count: number;
  five_day_net: number | null;
}

export interface WatchlistTradingActivity {
  as_of: string | null;
  day_trading_volume: number | null;
  total_volume: number | null;
  day_trading_volume_ratio: number | null;
  overnight_risk: number | null;
  overnight_missing_reason: string | null;
}

export interface WatchlistFundamentals {
  score: number | null;
  fiscal_quarter: string | null;
  comparison_basis: 'YoY' | 'QoQ' | null;
  revenue_growth: number | null;
  revenue_direction: WatchlistDirection;
  eps_growth: number | null;
  eps_direction: WatchlistDirection;
  gross_margin: number | null;
  operating_margin: number | null;
  operating_cash_flow: number | null;
  operating_cash_flow_margin: number | null;
  debt_ratio: number | null;
}

export interface WatchlistCoverage {
  short_ratio: number;
  long_ratio: number;
  missing: string[];
}

export interface WatchlistStock {
  instrument: WatchlistInstrument;
  themes: WatchlistTheme[];
  short: ScoreSummary;
  long: ScoreSummary;
  institutional: WatchlistInstitutional;
  trading_activity: WatchlistTradingActivity;
  fundamentals: WatchlistFundamentals;
  flags: StockFlag[];
  coverage: WatchlistCoverage;
}

export interface SearchableStock {
  instrument: WatchlistInstrument;
  themes: WatchlistTheme[];
  selected_top50: boolean;
  short_rank: number | null;
  long_rank: number | null;
  flags: StockFlag[];
}

export interface StockWatchlistData {
  schema_version: 'nexus_stock_watchlist.v1';
  methodology_version: string;
  generated_at: string;
  candidate_as_of: string;
  sources: Record<string, unknown>;
  methodology: Record<string, unknown>;
  coverage: {
    eligible_count: number;
    selected_count: number;
    metrics: string[];
    missing_reasons: string[];
  };
  short: { count: number; items: WatchlistStock[] };
  long: { count: number; items: WatchlistStock[] };
  searchable: SearchableStock[];
}

export interface StockRoute {
  code: string;
  exchange?: string;
  tab: StockTab;
}
