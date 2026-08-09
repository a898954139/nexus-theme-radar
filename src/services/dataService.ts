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
  StockFundamentals,
  ThemeEvent,
  ThemeRankingData,
  WaytoAgiData
} from '../types';

async function readJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Unable to load ${path}: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function loadRadarData(): Promise<RadarData> {
  const [themeRanking, momentumLatest, momentumHistory, events, sourceStatus, waytoagi] = await Promise.all([
    readJson<ThemeRankingData>('./data/public-theme-ranking-v0.8.json'),
    readJson<MomentumLatestData>('./data/public-theme-momentum-latest-v0.9.json'),
    readJson<MomentumHistoryData>('./data/public-theme-momentum-history-v0.9.json'),
    readJson<{ items: ThemeEvent[] }>('./data/theme-events.json'),
    readJson<SourceStatusData>('./data/source-status.json'),
    readJson<WaytoAgiData>('./data/waytoagi-7d.json')
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

async function readInstitutionalData(): Promise<InstitutionalRankingsData> {
  return readJson<InstitutionalRankingsData>('./data/institutional-rankings.json');
}

export async function fetchInstitutionalRankings(
  days: number,
  direction: 'up' | 'down',
  metric: FlowMetric = 'net'
) {
  const data = await readInstitutionalData();
  const prefix = metric === 'net' ? 'top_three_inst_netbuy' : 'top_three_inst_change';
  const key = `${prefix}_${days}_${direction}`;
  return data.rankings[key]?.entries ?? [];
}

function resolveInstrumentKey(symbol: string, exchange?: string): string[] {
  if (symbol.includes(':')) return [symbol];
  if (exchange) return [`${exchange}:${symbol}`];
  return [`TWSE:${symbol}`, `TPEX:${symbol}`];
}

export async function fetchInstitutionalFlows(symbol: string, exchange?: string): Promise<InstitutionalFlowItem[]> {
  const data = await readJson<{ symbols: Record<string, InstitutionalFlowItem[]> }>('./data/institutional-flows.json');
  for (const key of resolveInstrumentKey(symbol, exchange)) {
    if (data.symbols[key]) return data.symbols[key];
  }
  return [];
}

export async function fetchBrokerStats(): Promise<BrokerStatsData> {
  return readJson<BrokerStatsData>('./data/broker-stats.json');
}

export async function fetchBrokerCoverage(): Promise<BrokerCoverageData> {
  return readJson<BrokerCoverageData>('./data/broker-coverage.json');
}

export async function fetchBrokerMap(symbol: string): Promise<BrokerMapData | null> {
  const index = await readJson<{
    symbols: Record<string, {
      file: string;
      name?: string;
      broker_count?: number;
      summary?: { buy: number; sell: number; net: number };
    }>;
  }>('./data/broker-map/index.json');
  const metadata = index.symbols?.[symbol];
  if (!metadata?.file) return null;
  const brokers = await readJson<BrokerMapData['brokers']>(`./data/broker-map/${metadata.file}`);
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

export async function fetchStockFundamentals(symbol: string, exchange?: string): Promise<StockFundamentals | null> {
  const index = await readJson<{ symbols: Record<string, { file: string }> }>('./data/fundamentals-index.json');
  for (const key of resolveInstrumentKey(symbol, exchange)) {
    const filename = index.symbols[key]?.file;
    if (filename) {
      return readJson<StockFundamentals>(`./data/fundamentals/${encodeURIComponent(filename)}`);
    }
  }
  return null;
}
