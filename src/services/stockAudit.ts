export const STOCK_AUDIT_DATA_PATH = './data/stock-audit-latest.json';
export const STOCK_AUDIT_SCHEMA_VERSION = 1;

const ISO_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const FORBIDDEN_COPY = [
  /pending\s+(?:verification|update)/i,
  /incomplete/i,
  /pass\s+observation/i,
  /待(?:驗證|更新|確認)/u,
  /(?:驗證|更新|確認)中/u,
  /不完整/u,
  /通過觀察/u
];

export interface StockAuditReference {
  label: string;
  value: number;
  change_pct: number;
  as_of: string;
  source: string;
}

export interface StockAuditForecast {
  summary: string;
  references: StockAuditReference[];
  as_of: string;
}

export interface StockAuditCandle {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface StockAuditFundamentals {
  revenue: number;
  revenue_unit: string;
  period: string;
  eps: number;
  ttm_eps: number;
  pe: number;
  as_of: string;
  source: string;
  analysis: string;
}

export interface StockAuditValuation {
  baseline_label: string;
  baseline_pe: number;
  premium_pct: number;
  percentile: number;
  sample_count: number;
  analysis: string;
  source: string;
}

export interface StockAuditTechnical {
  candles: StockAuditCandle[];
  ma20: number;
  ma60: number;
  support: number;
  resistance: number;
  analysis: string;
}

export type StockAuditTerm = '短線' | '中線' | '長線';

export interface StockAuditOperation {
  term: StockAuditTerm;
  horizon: string;
  entry: number;
  add: number;
  stop: number;
  take_profit: number;
  timing: string;
  add_condition: string;
}

export interface StockAuditQuality {
  sharpe: number;
  sortino: number;
  ttr_days: number;
  index_shape: string;
  period: string;
  method: string;
  source: string;
}

export interface StockAuditStock {
  symbol: string;
  name: string;
  price: number;
  price_as_of: string;
  source: string;
  fundamentals: StockAuditFundamentals;
  valuation: StockAuditValuation;
  technical: StockAuditTechnical;
  operations: StockAuditOperation[];
  quality: StockAuditQuality;
  summary: string;
}

export interface StockAuditReport {
  schema_version: typeof STOCK_AUDIT_SCHEMA_VERSION;
  generated_at: string;
  report_date: string;
  conclusion: string;
  forecast: StockAuditForecast | null;
  stocks: StockAuditStock[];
  source_receipts?: StockAuditSourceReceipt[];
}

export interface StockAuditSourceReceipt {
  url: string;
  fetched_at: string;
  status: number;
}

const REFERENCE_KEYS = ['label', 'value', 'change_pct', 'as_of', 'source'] as const;
const CANDLE_KEYS = ['date', 'open', 'high', 'low', 'close', 'volume'] as const;
const FUNDAMENTALS_KEYS = ['revenue', 'revenue_unit', 'period', 'eps', 'ttm_eps', 'pe', 'as_of', 'source', 'analysis'] as const;
const VALUATION_KEYS = ['baseline_label', 'baseline_pe', 'premium_pct', 'percentile', 'sample_count', 'analysis', 'source'] as const;
const TECHNICAL_KEYS = ['candles', 'ma20', 'ma60', 'support', 'resistance', 'analysis'] as const;
const OPERATION_KEYS = ['term', 'horizon', 'entry', 'add', 'stop', 'take_profit', 'timing', 'add_condition'] as const;
const QUALITY_KEYS = ['sharpe', 'sortino', 'ttr_days', 'index_shape', 'period', 'method', 'source'] as const;
const STOCK_KEYS = ['symbol', 'name', 'price', 'price_as_of', 'source', 'fundamentals', 'valuation', 'technical', 'operations', 'quality', 'summary'] as const;
const FORECAST_KEYS = ['summary', 'references', 'as_of'] as const;
const REPORT_KEYS = ['schema_version', 'generated_at', 'report_date', 'conclusion', 'forecast', 'stocks'] as const;
const REPORT_WITH_RECEIPTS_KEYS = [...REPORT_KEYS, 'source_receipts'] as const;
const SOURCE_RECEIPT_KEYS = ['url', 'fetched_at', 'status'] as const;
const REQUIRED_REFERENCE_GROUPS = ['nasdaq', 'sp500', 'sox', 'large-tech', 'taiwan-night'] as const;
const REQUIRED_TERMS: StockAuditTerm[] = ['短線', '中線', '長線'];
const FILTERED_CONCLUSION = '本期以資料來源、時間戳與價格結構一致性為前提，僅呈現可比較的候選。';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const required = [...expected].sort();
  return actual.length === required.length && actual.every((key, index) => key === required[index]);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isPositiveNumber(value: unknown): value is number {
  return isFiniteNumber(value) && value > 0;
}

function isNonNegativeNumber(value: unknown): value is number {
  return isFiniteNumber(value) && value >= 0;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isSafeCopy(value: unknown): value is string {
  return isNonEmptyString(value) && !FORBIDDEN_COPY.some((pattern) => pattern.test(value));
}

function isValidTimestamp(value: unknown): value is string {
  return typeof value === 'string' && ISO_TIMESTAMP.test(value) && Number.isFinite(Date.parse(value));
}

function isValidDate(value: unknown): value is string {
  if (typeof value !== 'string' || !ISO_DATE.test(value)) return false;
  const timestamp = new Date(`${value}T00:00:00.000Z`);
  return Number.isFinite(timestamp.getTime()) && timestamp.toISOString().slice(0, 10) === value;
}

function taipeiDate(timestamp: string): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Taipei',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).formatToParts(new Date(timestamp));
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function isAtOrBefore(value: string, upperBound: string): boolean {
  return Date.parse(value) <= Date.parse(upperBound);
}

function isHttpSource(value: unknown): value is string {
  if (!isNonEmptyString(value)) return false;
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    return false;
  }
}

function referenceGroup(label: string): typeof REQUIRED_REFERENCE_GROUPS[number] | null {
  const normalized = label.toLocaleLowerCase('zh-TW').replace(/[\s_]+/g, '-');
  if (/(?:nasdaq|那斯達克)/u.test(normalized)) return 'nasdaq';
  if (/(?:s\s*&?\s*p|sp500|s&p500|標普500|標普指數)/u.test(normalized)) return 'sp500';
  if (/(?:sox|費城半導體|半導體指數)/u.test(normalized)) return 'sox';
  if (/(?:large-tech|large technology|mega-cap|大型科技|大型權值|大型科技股|apple|microsoft|nvidia|蘋果|微軟|輝達)/u.test(normalized)) return 'large-tech';
  if (/(?:taiwan.*(?:futures|night)|台指期|台灣期貨|台股期貨|夜盤)/u.test(normalized)) return 'taiwan-night';
  return null;
}

function isReference(value: unknown): value is StockAuditReference {
  return isRecord(value)
    && hasExactKeys(value, REFERENCE_KEYS)
    && isSafeCopy(value.label)
    && isFiniteNumber(value.value)
    && isFiniteNumber(value.change_pct)
    && isValidTimestamp(value.as_of)
    && isHttpSource(value.source);
}

function isForecast(value: unknown): value is StockAuditForecast {
  if (!isRecord(value) || !hasExactKeys(value, FORECAST_KEYS) || !isSafeCopy(value.summary) || !isValidTimestamp(value.as_of)) return false;
  if (!Array.isArray(value.references) || value.references.length < REQUIRED_REFERENCE_GROUPS.length || !value.references.every(isReference)) return false;
  const groups = new Set(value.references.map((reference) => referenceGroup(reference.label)).filter((group): group is typeof REQUIRED_REFERENCE_GROUPS[number] => group !== null));
  return REQUIRED_REFERENCE_GROUPS.every((group) => groups.has(group));
}

function isCandle(value: unknown): value is StockAuditCandle {
  if (!isRecord(value) || !hasExactKeys(value, CANDLE_KEYS) || !isValidDate(value.date)) return false;
  if (!isPositiveNumber(value.open) || !isPositiveNumber(value.high) || !isPositiveNumber(value.low) || !isPositiveNumber(value.close) || !isNonNegativeNumber(value.volume)) return false;
  return value.high >= Math.max(value.open, value.close)
    && value.low <= Math.min(value.open, value.close);
}

function isFundamentals(value: unknown): value is StockAuditFundamentals {
  return isRecord(value)
    && hasExactKeys(value, FUNDAMENTALS_KEYS)
    && isPositiveNumber(value.revenue)
    && isSafeCopy(value.revenue_unit)
    && isSafeCopy(value.period)
    && isFiniteNumber(value.eps)
    && isFiniteNumber(value.ttm_eps)
    && isPositiveNumber(value.pe)
    && isValidTimestamp(value.as_of)
    && isHttpSource(value.source)
    && isSafeCopy(value.analysis);
}

function isValuation(value: unknown): value is StockAuditValuation {
  return isRecord(value)
    && hasExactKeys(value, VALUATION_KEYS)
    && isSafeCopy(value.baseline_label)
    && isPositiveNumber(value.baseline_pe)
    && isFiniteNumber(value.premium_pct)
    && isFiniteNumber(value.percentile)
    && value.percentile >= 0
    && value.percentile <= 100
    && isFiniteNumber(value.sample_count)
    && Number.isInteger(value.sample_count)
    && value.sample_count > 0
    && isSafeCopy(value.analysis)
    && isHttpSource(value.source);
}

function isTechnical(value: unknown): value is StockAuditTechnical {
  if (!isRecord(value) || !hasExactKeys(value, TECHNICAL_KEYS) || !Array.isArray(value.candles) || value.candles.length < 60) return false;
  if (!value.candles.every(isCandle) || !isPositiveNumber(value.ma20) || !isPositiveNumber(value.ma60) || !isPositiveNumber(value.support) || !isPositiveNumber(value.resistance) || !isSafeCopy(value.analysis)) return false;
  for (let index = 1; index < value.candles.length; index += 1) {
    if (value.candles[index - 1].date >= value.candles[index].date) return false;
  }
  return value.support <= value.resistance;
}

function isOperation(value: unknown): value is StockAuditOperation {
  return isRecord(value)
    && hasExactKeys(value, OPERATION_KEYS)
    && (value.term === '短線' || value.term === '中線' || value.term === '長線')
    && isSafeCopy(value.horizon)
    && isPositiveNumber(value.entry)
    && isPositiveNumber(value.add)
    && isPositiveNumber(value.stop)
    && isPositiveNumber(value.take_profit)
    && isSafeCopy(value.timing)
    && isSafeCopy(value.add_condition);
}

function isQuality(value: unknown): value is StockAuditQuality {
  return isRecord(value)
    && hasExactKeys(value, QUALITY_KEYS)
    && isFiniteNumber(value.sharpe)
    && isFiniteNumber(value.sortino)
    && isFiniteNumber(value.ttr_days)
    && Number.isInteger(value.ttr_days)
    && value.ttr_days > 0
    && isSafeCopy(value.index_shape)
    && isSafeCopy(value.period)
    && isSafeCopy(value.method)
    && isHttpSource(value.source);
}

export function isStockAuditStock(value: unknown): value is StockAuditStock {
  if (!isRecord(value) || !hasExactKeys(value, STOCK_KEYS)) return false;
  if (!isNonEmptyString(value.symbol) || !isSafeCopy(value.name) || !isPositiveNumber(value.price) || !isValidTimestamp(value.price_as_of) || !isHttpSource(value.source)) return false;
  if (!isFundamentals(value.fundamentals) || !isValuation(value.valuation) || !isTechnical(value.technical) || !isQuality(value.quality) || !isSafeCopy(value.summary)) return false;
  if (!Array.isArray(value.operations) || value.operations.length !== REQUIRED_TERMS.length || !value.operations.every(isOperation)) return false;
  const terms = new Set(value.operations.map((operation) => operation.term));
  if (!REQUIRED_TERMS.every((term) => terms.has(term))) return false;

  const latestCandle = value.technical.candles[value.technical.candles.length - 1];
  const ma20 = value.technical.candles.slice(-20).reduce((total, candle) => total + candle.close, 0) / 20;
  const ma60 = value.technical.candles.slice(-60).reduce((total, candle) => total + candle.close, 0) / 60;
  const premium = (value.fundamentals.pe / value.valuation.baseline_pe - 1) * 100;
  const recentCandles = value.technical.candles.slice(-20);
  const support = Math.min(...recentCandles.map((candle) => candle.low));
  const resistance = Math.max(...recentCandles.map((candle) => candle.high));
  const operationsOrdered = value.operations.every((operation) => operation.stop < operation.entry && operation.entry < operation.add && operation.add < operation.take_profit);
  return Math.abs(value.price - latestCandle.close) <= 0.0001
    && taipeiDate(value.price_as_of) === latestCandle.date
    && Math.abs(value.technical.ma20 - ma20) <= 0.02
    && Math.abs(value.technical.ma60 - ma60) <= 0.02
    && Math.abs(value.technical.support - support) <= 0.0001
    && Math.abs(value.technical.resistance - resistance) <= 0.0001
    && Math.abs(value.valuation.premium_pct - premium) <= 0.02
    && operationsOrdered;
}

function isSourceReceipt(value: unknown): value is StockAuditSourceReceipt {
  return isRecord(value)
    && hasExactKeys(value, SOURCE_RECEIPT_KEYS)
    && isHttpSource(value.url)
    && isValidTimestamp(value.fetched_at)
    && isFiniteNumber(value.status)
    && Number.isInteger(value.status)
    && value.status >= 200
    && value.status < 600;
}

function parseReport(value: unknown): StockAuditReport | null {
  if (!isRecord(value) || (!hasExactKeys(value, REPORT_KEYS) && !hasExactKeys(value, REPORT_WITH_RECEIPTS_KEYS)) || value.schema_version !== STOCK_AUDIT_SCHEMA_VERSION) return null;
  if (!isValidTimestamp(value.generated_at) || !isValidDate(value.report_date) || !isSafeCopy(value.conclusion) || !Array.isArray(value.stocks)) return null;
  if (Object.prototype.hasOwnProperty.call(value, 'source_receipts') && (!Array.isArray(value.source_receipts) || !value.source_receipts.every(isSourceReceipt))) return null;
  const generatedAt = value.generated_at as string;
  const reportDate = value.report_date as string;
  const conclusion = value.conclusion as string;
  if (reportDate > taipeiDate(generatedAt)) return null;
  const stocks = value.stocks
    .filter(isStockAuditStock)
    .filter((stock) => {
      const latestCandle = stock.technical.candles[stock.technical.candles.length - 1];
      return latestCandle.date === reportDate
        && taipeiDate(stock.price_as_of) === reportDate
        && isAtOrBefore(stock.price_as_of, generatedAt)
        && isAtOrBefore(stock.fundamentals.as_of, generatedAt);
    });
  const parsedForecast = value.forecast === null || isForecast(value.forecast) ? value.forecast : null;
  const forecast = parsedForecast && isAtOrBefore(parsedForecast.as_of, generatedAt)
    && parsedForecast.references.every((reference) => isAtOrBefore(reference.as_of, generatedAt))
    ? parsedForecast
    : null;
  if (Array.isArray(value.source_receipts) && !value.source_receipts.every((receipt) => isAtOrBefore(receipt.fetched_at, generatedAt))) return null;
  const sourceReceipts = Array.isArray(value.source_receipts) ? value.source_receipts : undefined;
  return {
    schema_version: STOCK_AUDIT_SCHEMA_VERSION,
    generated_at: generatedAt,
    report_date: reportDate,
    conclusion: stocks.length === value.stocks.length ? conclusion : FILTERED_CONCLUSION,
    forecast,
    stocks,
    ...(sourceReceipts ? { source_receipts: sourceReceipts } : {})
  };
}

/**
 * Normalize an unknown report at the browser boundary. The report shell must
 * be valid, while individual candidates are fail-closed and filtered.
 */
export function validateStockAuditReport(value: unknown): StockAuditReport {
  const report = parseReport(value);
  if (!report) throw new Error('Invalid stock audit report payload');
  return report;
}

export function isStockAuditReport(value: unknown): value is StockAuditReport {
  return parseReport(value) !== null;
}

async function readAuditJson(cacheBust: boolean): Promise<unknown> {
  const requestPath = cacheBust ? `${STOCK_AUDIT_DATA_PATH}?refresh=${Date.now()}` : STOCK_AUDIT_DATA_PATH;
  const response = await fetch(requestPath, { cache: 'no-store' });
  if (!response.ok) throw new Error(`Unable to load ${STOCK_AUDIT_DATA_PATH}: ${response.status}`);
  return response.json();
}

export async function fetchStockAudit(cacheBust = false): Promise<StockAuditReport> {
  return validateStockAuditReport(await readAuditJson(cacheBust));
}

