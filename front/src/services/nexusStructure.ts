// Nexus core technical read for one stock: GET /api/v1/nexus-structure?symbol=
// (backend/api/_lib/datasets/nexusStructure.js, computed by the Mac job nexus-structure).
export const NEXUS_STRUCTURE_PATH = '/api/v1/nexus-structure';

export type NexusBias = '偏多' | '偏空' | '中性' | '分歧';
export type NexusTimeframe = 'D1' | 'W1';

export interface NexusTimeframeRead {
  bias: Exclude<NexusBias, '分歧'>;
  last_event: string | null;
  last_event_dir: number | null;
  last_event_price: number | null;
  last_event_date: string | null;
  inside_zone: boolean;
  bar_count: number;
}

export interface NexusLevel {
  timeframe: NexusTimeframe;
  kind: 'fvg' | 'ob' | 'swing_high' | 'swing_low';
  side: 'support' | 'resistance' | 'inside';
  dir: number;
  low: number;
  high: number;
  formed_on: string | null;
  state: string;
}

export interface NexusBreak {
  timeframe: NexusTimeframe;
  label: string;
  dir: number;
  price: number;
  strong: boolean;
  confirmed_on: string;
}

export interface NexusStructure {
  instrument: { instrument_id: string; symbol: string; exchange: string; name_zh: string | null };
  analyzed_at: string;
  method_version: string;
  detector_revision: string | null;
  as_of: string;
  close: number;
  bias: NexusBias;
  timeframes: { D1: NexusTimeframeRead | null; W1: NexusTimeframeRead | null };
  pva: { status: string; reason: string | null; P: number | null; V: number | null; A: number | null; anchor: number | null; ATR: number | null };
  levels: NexusLevel[];
  breaks: NexusBreak[];
  summary: string;
}

const BIASES = new Set(['偏多', '偏空', '中性', '分歧']);

export function isNexusStructure(value: unknown): value is NexusStructure {
  const v = value as NexusStructure;
  return !!v && typeof v === 'object'
    && typeof v.as_of === 'string' && typeof v.close === 'number' && BIASES.has(v.bias)
    && !!v.timeframes && !!v.timeframes.D1 && Array.isArray(v.levels) && Array.isArray(v.breaks)
    && typeof v.summary === 'string' && !!v.pva;
}

const cache = new Map<string, Promise<NexusStructure | null>>();

async function load(search: URLSearchParams): Promise<NexusStructure | null> {
  try {
    const response = await fetch(`${NEXUS_STRUCTURE_PATH}?${search}`);
    if (!response.ok || !(response.headers.get('content-type') ?? '').includes('application/json')) return null;
    const body: unknown = await response.json();
    return isNexusStructure(body) ? body : null;
  } catch {
    return null;
  }
}

/**
 * null on 404 (stock never analyzed), API off, or a malformed payload: callers then render nothing.
 * One request per stock per page load, shared by the card and the K-line overlay.
 */
export function fetchNexusStructure(symbol: string, exchange: string | undefined): Promise<NexusStructure | null> {
  const search = new URLSearchParams({ symbol });
  if (exchange === 'TWSE' || exchange === 'TPEX') search.set('exchange', exchange);
  const key = search.toString();
  let pending = cache.get(key);
  if (!pending) {
    pending = load(search).then((value) => { if (value === null) cache.delete(key); return value; });
    cache.set(key, pending);
  }
  return pending;
}
