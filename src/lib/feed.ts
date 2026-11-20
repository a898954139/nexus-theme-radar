// Derivations for the feed (訊息流) homepage. Everything here is computed from
// payloads the site already loads; nothing is written by hand. When an input
// is missing the derived block is null and the page leaves it out.

import type { MacroFocus } from './focusThemes';
import type { FocusEvent, MarketIndicator, PreMarketData, ThemeFocusData } from '../types';

export type FeedTab = 'hot' | 'bull' | 'bear' | 'geo' | 'rates' | 'tech' | 'energy' | 'tw';

export const FEED_TABS: Array<{ id: FeedTab; label: string }> = [
  { id: 'hot', label: '熱門' },
  { id: 'bull', label: '利多' },
  { id: 'bear', label: '利空' },
  { id: 'geo', label: '地緣政治' },
  { id: 'rates', label: '央行利率' },
  { id: 'tech', label: '科技供應鏈' },
  { id: 'energy', label: '能源' },
  { id: 'tw', label: '台股' },
];

/** Transmission path -> topic tab. Unknown paths only appear under 熱門. */
const PATH_TAB: Record<string, FeedTab> = {
  military_conflict: 'geo',
  taiwan_strait: 'geo',
  shipping_lane: 'geo',
  tariff: 'geo',
  fed_rates: 'rates',
  fx_capital: 'rates',
  export_control: 'tech',
  supply_chain: 'tech',
  ai_capex: 'tech',
  hormuz_energy: 'energy',
  tw_fundamental: 'tw',
};

function pathKey(path: MacroFocus): string {
  return path.lead.pathId ?? path.key;
}

export function pathsForTab(paths: MacroFocus[], tab: FeedTab): MacroFocus[] {
  if (tab === 'hot') return paths;
  if (tab === 'bull') return paths.filter((path) => path.bull > 0).sort((a, b) => b.bull - a.bull);
  if (tab === 'bear') return paths.filter((path) => path.bear > 0).sort((a, b) => b.bear - a.bear);
  return paths.filter((path) => PATH_TAB[pathKey(path)] === tab);
}

export function eventDirection(event: FocusEvent): -1 | 0 | 1 {
  return event.direction === 1 || event.direction === -1 ? event.direction : 0;
}

export interface RiskAppetite {
  score: number;
  label: string;
  bull: number;
  bear: number;
  neutral: number;
  windowHours: number;
}

/** News-side risk appetite, 0-10: the bullish share of directional events in
 *  the pre-market window. 5 when nothing directional happened. It reads the
 *  wire only; the market lean is shown next to it, not mixed in. */
export function riskAppetite(data: PreMarketData | null): RiskAppetite | null {
  if (!data) return null;
  let bull = 0;
  let bear = 0;
  let neutral = 0;
  for (const event of data.events) {
    const direction = eventDirection(event);
    if (direction === 1) bull += 1;
    else if (direction === -1) bear += 1;
    else neutral += 1;
  }
  const directional = bull + bear;
  const score = directional === 0 ? 5 : Math.round((10 * bull) / directional);
  const label = score <= 2 ? '強烈偏空' : score <= 4 ? '偏空' : score === 5 ? '多空拉鋸' : score <= 7 ? '偏多' : '強烈偏多';
  return { score, label, bull, bear, neutral, windowHours: data.window_hours };
}

export interface FeedHeadline {
  stance: string;
  sentence: string;
}

function indicator(data: PreMarketData | null, id: string): MarketIndicator | undefined {
  return data?.market?.indicators.find((item) => item.id === id && !item.missing);
}

function signedPct(value: number): string {
  return `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toFixed(2)}%`;
}

export function feedHeadline(data: PreMarketData | null, paths: MacroFocus[]): FeedHeadline {
  const lean = data?.market?.market.lean ?? null;
  const stance = lean === '偏空' ? '今天偏空' : lean === '偏多' ? '今天偏多' : '今天方向不明';
  const parts: string[] = [];
  const top = paths.slice(0, 2).map((path) => path.label);
  if (top.length > 0) parts.push(`${top.join('、')}是近 ${data?.window_hours ?? 72} 小時最重的消息線`);
  const avg = data?.market?.market.avg_pct;
  const basis = data?.market?.market.basis;
  if (avg !== null && avg !== undefined && basis) parts.push(`${basis}平均 ${signedPct(avg)}`);
  if (data?.market?.divergence) parts.push('新聞情緒與盤勢方向相反');
  return { stance, sentence: parts.length > 0 ? `${parts.join('；')}。` : '盤前資料暫時無法取得。' };
}

export interface FlowBar {
  name: string;
  value: number;
  width: number;
}

export interface AnalysisItem {
  id: string;
  title: string;
  body: string;
  meta: string;
}

export interface FeedAnalysis {
  lead: AnalysisItem & { bars: FlowBar[]; asOf: string | null; windowDays: number };
  items: AnalysisItem[];
}

function lots(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  const abs = Math.abs(value) / 1000;
  return `${sign}${abs >= 100 ? abs.toFixed(0) : abs.toFixed(1)}k 張`;
}

function dateLabel(iso: string | null | undefined): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日`;
}

/** 分析與觀點, generated from the theme x flow join and the macro backtests. */
export function feedAnalysis(pre: PreMarketData | null, focus: ThemeFocusData | null, paths: MacroFocus[]): FeedAnalysis | null {
  const items: AnalysisItem[] = [];
  const generated = dateLabel(pre?.generated_at ?? focus?.generated_at);

  const night = indicator(pre, 'tx_night');
  const avg = pre?.market?.market.avg_pct;
  if (night && night.change_pct !== null && night.change_pct !== undefined) {
    const lean = pre?.market?.market.lean ?? '方向未明';
    items.push({
      id: 'night',
      title: `台指夜盤 ${night.value?.toLocaleString('zh-TW')}（${signedPct(night.change_pct)}），開盤${lean}`,
      body: [
        avg !== null && avg !== undefined && pre?.market?.market.basis ? `${pre.market.market.basis}平均 ${signedPct(avg)}。` : '',
        pre?.market?.divergence ? `${pre.market.divergence.message}，別被消息面帶著走。` : '',
      ].join('') || '夜盤是開盤前最直接的方向參考。',
      meta: `Nexus 分析，${generated}`,
    });
  }

  for (const path of paths.filter((item) => item.backtest && item.backtest.hitRate !== null).slice(0, 3)) {
    const bt = path.backtest!;
    const leanWord = path.lean === 'bull' ? '偏多' : path.lean === 'bear' ? '偏空' : '多空交錯';
    items.push({
      id: `path-${path.key}`,
      title: `${path.label}${leanWord}：過去 ${bt.n} 次同類事件，${bt.target}隔日命中 ${Math.round((bt.hitRate ?? 0) * 100)}%`,
      body: `${path.lead.titleZh.replace(/[。！？.!?]+$/, '')}。傳導路徑：${path.lead.channel.replace(/\s*→\s*/g, '，再到')}。`,
      meta: `Nexus 分析，${dateLabel(path.latestAt)}`,
    });
  }

  const themes = (focus?.themes ?? []).filter((theme) => theme.flow.covered_count > 0);
  if (themes.length === 0) {
    if (items.length === 0) return null;
    const [first, ...rest] = items;
    return { lead: { ...first, bars: [], asOf: null, windowDays: 0 }, items: rest };
  }
  const sorted = themes.slice().sort((a, b) => b.flow.foreign_5d - a.flow.foreign_5d);
  const picked = sorted.length <= 7 ? sorted : [...sorted.slice(0, 3), ...sorted.slice(-4)];
  const max = Math.max(1, ...picked.map((theme) => Math.abs(theme.flow.foreign_5d)));
  const bars = picked.map((theme) => ({ name: theme.name_zh, value: theme.flow.foreign_5d, width: (Math.abs(theme.flow.foreign_5d) / max) * 100 }));
  const buyers = sorted.filter((theme) => theme.flow.foreign_5d > 0);
  const sellers = sorted.filter((theme) => theme.flow.foreign_5d < 0).reverse();
  const title = buyers.length > 0
    ? `外資只留在${buyers.slice(0, 2).map((theme) => theme.name_zh).join('與')}：一週外資流向拆解`
    : `外資 ${focus!.flow_window_days} 日全面賣超，賣最多的是${sellers[0]?.name_zh ?? '電子'}`;
  const body = [
    buyers.length > 0 ? `外資 ${focus!.flow_window_days} 日買超 ${buyers.slice(0, 2).map((theme) => `${theme.name_zh} ${lots(theme.flow.foreign_5d)}`).join('、')}` : '',
    sellers.length > 0 ? `同期賣超 ${sellers.slice(0, 2).map((theme) => `${theme.name_zh} ${lots(theme.flow.foreign_5d)}`).join('、')}` : '',
  ].filter(Boolean).join('；') + '。';
  return {
    lead: {
      id: 'flows',
      title,
      body,
      meta: `Nexus 分析，${dateLabel(focus!.generated_at)}`,
      bars,
      asOf: focus!.flow_as_of,
      windowDays: focus!.flow_window_days,
    },
    items: items.slice(0, 3),
  };
}

export function relativeTime(iso: string, now: number): string {
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return '';
  const hours = Math.max(0, (now - at) / 3_600_000);
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} 分鐘前`;
  if (hours < 24) return `${Math.round(hours)} 小時前`;
  return `${Math.round(hours / 24)} 天前`;
}

export function sparkPoints(series: number[], width = 100, height = 28): string {
  if (series.length === 0) return '';
  const mid = (height / 2).toFixed(1);
  if (series.length === 1) return `0,${mid} ${width},${mid}`;
  const min = Math.min(...series);
  const max = Math.max(...series);
  const span = max - min || 1;
  return series
    .map((value, index) => `${((index / (series.length - 1)) * width).toFixed(1)},${(height - ((value - min) / span) * (height - 2) - 1).toFixed(1)}`)
    .join(' ');
}
