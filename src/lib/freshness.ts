import { StockWatchlistData } from '../types';

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

/** Latest institutional and day-trading dates the watchlist was scored on. */
export function watchlistSourceDates(payload: StockWatchlistData | null): { institutional: string | null; dayTrading: string | null; dayTradingStatus: string | null } {
  const sources = record(payload?.sources);
  const asOf = record(sources?.institutional)?.as_of;
  const dates = Array.isArray(asOf) ? asOf.filter((value): value is string => typeof value === 'string').sort() : [];
  const twse = record(record(sources?.day_trading_activity)?.TWSE);
  return {
    institutional: dates[dates.length - 1] ?? null,
    dayTrading: typeof twse?.as_of === 'string' ? twse.as_of : null,
    dayTradingStatus: typeof twse?.status === 'string' ? twse.status : null
  };
}

/** Calendar days between two ISO dates (or timestamps); null when either is missing. */
export function daysBetween(older: string | null | undefined, newer: string | null | undefined): number | null {
  if (!older || !newer) return null;
  const gap = (new Date(newer).getTime() - new Date(older).getTime()) / 86_400_000;
  return Number.isFinite(gap) ? Math.floor(gap) : null;
}
