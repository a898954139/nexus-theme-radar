export type PageType = 'index' | 'momentum' | 'flows' | 'stock' | 'sources';
export type DeviceType = 'desktop' | 'mobile';
export type LoadState = 'normal' | 'loading' | 'empty';
export type StockTab = 'fundamentals' | 'flows';
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
  three_inst_ratio: number;
  change: number;
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

export interface StockRoute {
  code: string;
  exchange?: string;
  tab: StockTab;
}
