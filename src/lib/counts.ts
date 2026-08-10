import { SiteCounts } from '../services/metricsService';

/**
 * Folds a poll result into the displayed counts.
 *
 * A failed request returns null, and applying that directly would blank numbers
 * the page is already showing -- one dropped heartbeat made the counter vanish
 * until the next success 45 seconds later. Analytics being briefly unreachable
 * is not news to a visitor, so the last known values stay on screen instead.
 */
export function nextCounts(current: SiteCounts | null, incoming: SiteCounts | null): SiteCounts | null {
  return incoming ?? current;
}
