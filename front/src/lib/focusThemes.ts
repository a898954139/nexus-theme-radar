// Builds the "what to watch today" lists at the top of the pre-market page.
//
// Two different kinds of 題材 feed the page, and they are kept apart on purpose
// because their scores are not comparable:
//   - macro paths: international events grouped by transmission path
//     (Fed/利率, 能源/荷姆茲 ...). These carry a direction, the sectors the rule
//     called, a horizon and a backtest hit rate.
//   - industry themes: the Taiwan theme radar (記憶體與 HBM, AI ...). These carry
//     heat and the stocks the watchlist ranks highest for short / long holding.
// The bridge between them is a small sector map: an industry theme borrows the
// direction of whatever macro calls hit its sectors.

import type {
  FocusEvent,
  InstrumentRef,
  MomentumTheme,
  PathBacktestBadge,
  PathBacktestTable,
  PreMarketData,
  RadarData,
  RepresentativeNews,
  StockWatchlistData,
  WatchlistStock,
} from '../types';

export type Lean = 'bull' | 'bear' | 'mixed' | 'none';

export interface SectorCall {
  sector: string;
  direction: 1 | -1;
  weight: number;
}

export interface MacroFocus {
  key: string;
  label: string;
  score: number;
  lean: Lean;
  bull: number;
  bear: number;
  total: number;
  calls: SectorCall[];
  /** Sectors on the path when no rule made a directional call. */
  sectors: string[];
  horizon: 'short' | 'long' | null;
  backtest: PathBacktestBadge | null;
  /** Hit rate of every backtested sector on this path (radar.path_backtest). */
  sectorBacktest: Record<string, PathBacktestBadge>;
  lead: FocusEvent;
  events: FocusEvent[];
  hasCritical: boolean;
  latestAt: string;
}

export interface StockPick {
  symbol: string;
  exchange: string;
  name: string;
  rank: number | null;
}

export interface ThemeFocus {
  themeId: string;
  name: string;
  heat: number;
  momentum: number | null;
  stage: string;
  shortPick: StockPick | null;
  longPick: StockPick | null;
  stocks: StockPick[];
  news: RepresentativeNews | null;
  macroLean: Lean;
  macroCalls: SectorCall[];
  eventCount: number | null;
  sourceCount: number | null;
}

const HALF_LIFE_HOURS = 24;

function directionOf(event: FocusEvent): -1 | 0 | 1 {
  return event.direction === 1 || event.direction === -1 ? event.direction : 0;
}

function ageHours(iso: string, now: number): number {
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return 72;
  return Math.max(0, (now - at) / 3_600_000);
}

/** Exponential recency weight: a 24h-old event counts half. A pre-market read
 *  is about tonight, so a two-day-old critical item must not outrank today. */
function recency(iso: string, now: number): number {
  return Math.pow(0.5, ageHours(iso, now) / HALF_LIFE_HOURS);
}

function leanOf(net: number, bull: number, bear: number): Lean {
  if (bull === 0 && bear === 0) return 'none';
  if (bull > 0 && bear > 0 && Math.abs(net) < 0.15 * (bull + bear)) return 'mixed';
  return net > 0 ? 'bull' : net < 0 ? 'bear' : 'mixed';
}

/** The path's headline badge: the sector the carried badge named, else the
 *  strongest directional call that has a backtest, else the largest sample. */
function headlineBacktest(
  rows: Record<string, PathBacktestBadge>,
  carried: PathBacktestBadge | null,
  calls: SectorCall[],
): PathBacktestBadge | null {
  if (carried && rows[carried.target]) return rows[carried.target];
  const called = calls.find((call) => rows[call.sector]);
  if (called) return rows[called.sector];
  return Object.values(rows).sort((a, b) => b.n - a.n)[0] ?? carried;
}

export function buildMacroFocus(
  data: PreMarketData,
  now = Date.parse(data.generated_at) || Date.now(),
  backtestTable: PathBacktestTable | null = null,
): MacroFocus[] {
  const groups = new Map<string, FocusEvent[]>();
  for (const event of data.events) {
    const key = event.pathId || event.pathLabel || 'other';
    const list = groups.get(key);
    if (list) list.push(event); else groups.set(key, [event]);
  }

  const result: MacroFocus[] = [];
  for (const [key, events] of groups) {
    let score = 0;
    let net = 0;
    let bullW = 0;
    let bearW = 0;
    let bull = 0;
    let bear = 0;
    const sectorNet = new Map<string, number>();
    const sectorSeen = new Map<string, number>();
    const horizons = { short: 0, long: 0 };
    let lead = events[0];
    let leadW = -1;
    let latestAt = events[0].publishedAt;

    for (const event of events) {
      const dir = directionOf(event);
      const tierBoost = event.tier === 'critical' ? 1.6 : event.tier === 'watch' ? 1.25 : 1;
      const w = event.score * recency(event.publishedAt, now) * tierBoost;
      // Directional events are what a trader can act on, so they weigh more in
      // both the ranking and the choice of lead headline.
      const actionable = dir !== 0 ? 1.5 : 1;
      score += w * actionable;
      if (dir === 1) { bull += 1; bullW += w; }
      if (dir === -1) { bear += 1; bearW += w; }
      net += dir * w;
      for (const impact of event.impacts ?? []) {
        if (impact.direction === 1 || impact.direction === -1) {
          sectorNet.set(impact.sector, (sectorNet.get(impact.sector) ?? 0) + impact.direction * w);
        }
      }
      for (const sector of event.sectors) sectorSeen.set(sector, (sectorSeen.get(sector) ?? 0) + w);
      if (event.horizon === 'short' || event.horizon === 'long') horizons[event.horizon] += w;
      if (w * actionable > leadW) { lead = event; leadW = w * actionable; }
      if (Date.parse(event.publishedAt) > Date.parse(latestAt)) latestAt = event.publishedAt;
    }

    const calls: SectorCall[] = [...sectorNet.entries()]
      .filter(([, value]) => Math.abs(value) > 1e-6)
      .map(([sector, value]) => ({ sector, direction: (value > 0 ? 1 : -1) as 1 | -1, weight: Math.abs(value) }))
      .sort((a, b) => b.weight - a.weight);
    const sectors = [...sectorSeen.entries()].sort((a, b) => b[1] - a[1]).map(([sector]) => sector);
    const carried = [...events]
      .filter((event) => event.pathBacktest)
      .sort((a, b) => (b.pathBacktest!.n - a.pathBacktest!.n))[0]?.pathBacktest ?? null;
    // Prefer the table (current as soon as the 17:50 backtest finishes) over
    // the copy the last pre-market run carried on its events.
    const tableRows = backtestTable?.paths?.[key] ?? null;
    const sectorBacktest = tableRows ?? (carried ? { [carried.target]: carried } : {});
    const backtest = tableRows ? headlineBacktest(tableRows, carried, calls) : carried;
    const sorted = [...events].sort((a, b) => Date.parse(b.publishedAt) - Date.parse(a.publishedAt));

    result.push({
      key,
      label: events[0].pathLabel || key,
      score,
      lean: leanOf(net, bullW, bearW),
      bull,
      bear,
      total: events.length,
      calls,
      sectors,
      horizon: horizons.short === 0 && horizons.long === 0 ? null : horizons.long > horizons.short ? 'long' : 'short',
      backtest,
      sectorBacktest,
      lead,
      events: sorted,
      hasCritical: events.some((event) => event.tier === 'critical'),
      latestAt,
    });
  }
  return result.sort((a, b) => b.score - a.score);
}

// Industry theme -> pre-market sectors. Matched on the theme name so new
// statementdog tags with a familiar name still pick up a mapping.
const THEME_SECTOR_RULES: Array<[RegExp, string[]]> = [
  [/記憶體|HBM|DRAM/i, ['半導體', '科技股全體', '電子出口股']],
  [/CoWoS|封裝|晶圓|半導體|IC/i, ['半導體', 'IC設計', '科技股全體', '電子出口股']],
  [/^AI$|AI ?伺服器|伺服器|資料中心/i, ['AI伺服器', '半導體', '電子代工', '科技股全體']],
  [/PCB|ABF|HDI|載板/i, ['PCB', '電子零組件', '科技股全體']],
  [/矽光子|CPO|光通訊/i, ['光通訊', '科技股全體']],
  [/散熱/, ['散熱', '科技股全體']],
  [/機器人|自動化/, ['工具機', '電子零組件']],
  [/國防|無人機|軍工|航太/, ['航太國防']],
  [/綠能|太陽能|風電|儲能/, ['油電燃氣']],
  [/航運|貨櫃|散裝/, ['航運', '貨櫃航運', '散裝航運', '航空貨運']],
  [/航空/, ['航空貨運', '航運']],
  [/金融|銀行|壽險/, ['金融', '壽險']],
  [/鋼/, ['鋼鐵']],
  [/汽車|電動車/, ['汽車零組件']],
];

function sectorsForTheme(name: string): string[] {
  const out = new Set<string>();
  for (const [pattern, sectors] of THEME_SECTOR_RULES) {
    if (pattern.test(name)) sectors.forEach((sector) => out.add(sector));
  }
  return [...out];
}

function pickFrom(stock: WatchlistStock, horizon: 'short' | 'long'): StockPick {
  return {
    symbol: stock.instrument.symbol,
    exchange: stock.instrument.exchange,
    name: stock.instrument.name_zh,
    rank: stock[horizon]?.rank ?? null,
  };
}

/** Best-ranked watchlist stock for a theme. Watchlist stocks carry many
 *  related themes, so the same large cap would otherwise top every theme; a
 *  stock already shown for a hotter theme is skipped unless nothing else fits,
 *  and a direct mapping beats a related one. */
function bestFor(items: WatchlistStock[], themeId: string, horizon: 'short' | 'long', used: Set<string>): StockPick | null {
  const candidates = items
    .filter((item) => item.themes.some((theme) => theme.theme_id === themeId))
    .map((item) => {
      const relation = item.themes.find((theme) => theme.theme_id === themeId)?.relation;
      const rank = item[horizon]?.rank ?? 999;
      return { item, key: rank + (relation === 'direct' ? 0 : 5) + (used.has(item.instrument.symbol) ? 1000 : 0) };
    })
    .sort((a, b) => a.key - b.key);
  const hit = candidates[0]?.item;
  if (!hit) return null;
  used.add(hit.instrument.symbol);
  return pickFrom(hit, horizon);
}

function fromRef(ref: InstrumentRef): StockPick {
  return { symbol: ref.symbol, exchange: ref.exchange, name: ref.name_zh, rank: null };
}

export function buildThemeFocus(
  radar: RadarData,
  watchlist: StockWatchlistData | null,
  macro: MacroFocus[],
): ThemeFocus[] {
  const ranking = new Map(radar.themeRanking.themes.map((theme) => [theme.theme_id, theme]));
  const themes: MomentumTheme[] = radar.momentumLatest.themes.length > 0
    ? radar.momentumLatest.themes
    : radar.themeRanking.themes.map((theme) => ({
      rank: theme.rank,
      theme_id: theme.theme_id,
      name_zh: theme.name_zh,
      qualification_status: 'qualified',
      momentum_score: 0,
      lifecycle_stage: '',
      heat_score: theme.heat_score,
      heat_change_24h: null,
      direct_symbols: theme.direct_mentions,
      related_symbols: theme.supply_chain_candidates,
    }));

  // Sector -> net macro call across all paths, for the bridge.
  const sectorNet = new Map<string, number>();
  for (const path of macro) {
    for (const call of path.calls) {
      sectorNet.set(call.sector, (sectorNet.get(call.sector) ?? 0) + call.direction * call.weight);
    }
  }

  const shortItems = watchlist?.short.items ?? [];
  const longItems = watchlist?.long.items ?? [];
  const usedShort = new Set<string>();
  const usedLong = new Set<string>();

  return [...themes]
    .sort((a, b) => b.heat_score - a.heat_score)
    .map((theme) => {
      const ranked = ranking.get(theme.theme_id);
      const shortPick = bestFor(shortItems, theme.theme_id, 'short', usedShort);
      const longPick = bestFor(longItems, theme.theme_id, 'long', usedLong);
      const refs = [
        ...(ranked?.direct_mentions ?? theme.direct_symbols ?? []),
        ...(ranked?.supply_chain_candidates ?? []),
      ];
      const seen = new Set<string>([shortPick?.symbol, longPick?.symbol].filter(Boolean) as string[]);
      const stocks: StockPick[] = [];
      for (const ref of refs) {
        if (seen.has(ref.symbol)) continue;
        seen.add(ref.symbol);
        stocks.push(fromRef(ref));
        if (stocks.length >= 4) break;
      }
      const macroCalls: SectorCall[] = sectorsForTheme(theme.name_zh)
        .filter((sector) => Math.abs(sectorNet.get(sector) ?? 0) > 1e-6)
        .map((sector) => {
          const value = sectorNet.get(sector)!;
          return { sector, direction: (value > 0 ? 1 : -1) as 1 | -1, weight: Math.abs(value) };
        });
      const up = macroCalls.filter((call) => call.direction === 1).reduce((sum, call) => sum + call.weight, 0);
      const down = macroCalls.filter((call) => call.direction === -1).reduce((sum, call) => sum + call.weight, 0);
      const news = (ranked?.representative_news ?? (theme.representative_news as RepresentativeNews | undefined)) || null;
      return {
        themeId: theme.theme_id,
        name: theme.name_zh,
        heat: theme.heat_score,
        momentum: typeof theme.momentum_score === 'number' ? theme.momentum_score : null,
        stage: theme.lifecycle_stage,
        shortPick,
        longPick,
        stocks,
        news,
        macroLean: leanOf(up - down, up, down),
        macroCalls,
        eventCount: typeof theme.event_count === 'number' ? theme.event_count : ranked?.summaries?.event_count ?? null,
        sourceCount: typeof theme.source_count === 'number' ? theme.source_count : ranked?.summaries?.source_count ?? null,
      };
    });
}
