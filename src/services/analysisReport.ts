// Today's pre-market analysis report for one symbol (issue #8).
//
// Reads /api/analysis-report (server-side DB read). The view never shows an
// older edition as today's: anything whose report_date is not today's Taipei
// date resolves to `not_produced`.
export const ANALYSIS_REPORT_API = '/api/analysis-report';

export type ReportBias = 'bullish' | 'bearish' | 'neutral';
export type ReportActionability = 'actionable' | 'wait_for_confirmation' | 'no_trade';

export interface ReportLevel { label: string; price: number; kind: 'support' | 'resistance' | 'trigger' | 'invalidation' | 'target'; }

export interface DailyAnalysisReport {
  symbol: string;
  report_date: string;
  data_as_of: string;
  framework_version: string;
  generated_at: string;
  bias: ReportBias;
  actionability: ReportActionability;
  conclusion: string;
  market_structure: string;
  key_levels: ReportLevel[];
  primary_scenario: { summary: string; trigger: string; entry_zone: [number, number] | null; targets: number[] };
  alternative_scenario: { summary: string; trigger: string };
  confirmation: string;
  invalidation: { price: number; condition: string };
  no_trade_warning: string | null;
  news_context: string | null;
}

export type DailyReportStatus = 'produced' | 'not_produced' | 'not_in_list' | 'no_batch' | 'unavailable';

export interface DailyReportPayload {
  status: DailyReportStatus;
  report_date: string;
  data_as_of?: string;
  symbol?: string;
  rank?: number;
  report?: DailyAnalysisReport;
}

export type DailyReportView =
  | { kind: 'produced'; report: DailyAnalysisReport; rank: number | null }
  | { kind: 'not_produced'; today: string }
  | { kind: 'not_in_list'; today: string }
  | { kind: 'no_batch'; today: string }
  | { kind: 'unavailable' };

export function taipeiToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now);
}

const BIASES: ReportBias[] = ['bullish', 'bearish', 'neutral'];
const ACTIONS: ReportActionability[] = ['actionable', 'wait_for_confirmation', 'no_trade'];

function isReport(value: unknown, symbol: string): value is DailyAnalysisReport {
  if (!value || typeof value !== 'object') return false;
  const r = value as Partial<DailyAnalysisReport>;
  return r.symbol === symbol
    && typeof r.report_date === 'string'
    && typeof r.data_as_of === 'string'
    && r.data_as_of < r.report_date
    && BIASES.includes(r.bias as ReportBias)
    && ACTIONS.includes(r.actionability as ReportActionability)
    && typeof r.conclusion === 'string'
    && typeof r.invalidation?.price === 'number'
    && Array.isArray(r.key_levels);
}

/** Pure: decide what the card shows. `today` is the Taipei date. */
export function resolveDailyReportView(payload: DailyReportPayload | null, symbol: string, today: string): DailyReportView {
  if (!payload || payload.status === 'unavailable') return { kind: 'unavailable' };
  if (payload.report_date !== today) return { kind: 'not_produced', today };
  if (payload.status === 'no_batch') return { kind: 'no_batch', today };
  if (payload.status === 'not_in_list') return { kind: 'not_in_list', today };
  if (payload.status === 'produced' && isReport(payload.report, symbol) && payload.report.report_date === today) {
    return { kind: 'produced', report: payload.report, rank: typeof payload.rank === 'number' ? payload.rank : null };
  }
  return { kind: 'not_produced', today };
}

export async function fetchDailyReport(symbol: string, signal?: AbortSignal): Promise<DailyReportPayload | null> {
  try {
    const response = await fetch(`${ANALYSIS_REPORT_API}?symbol=${encodeURIComponent(symbol)}`, { cache: 'no-store', signal });
    if (!response.ok) return null;
    const type = response.headers.get('content-type') ?? '';
    if (!type.includes('application/json')) return null; // static hosting without the API
    return (await response.json()) as DailyReportPayload;
  } catch {
    return null;
  }
}
