import { useEffect, useState } from 'react';
import { nextCounts } from '../lib/counts';
import { SiteCounts, recordPageView, sendHeartbeat } from '../services/metricsService';

const HEARTBEAT_INTERVAL_MS = 45 * 1000;

/**
 * Counts one view on mount, then heartbeats while the tab is visible.
 *
 * Only the index page calls this. Heartbeats pause in background tabs so a tab
 * left open overnight drops out of the online count rather than inflating it.
 *
 * Returns null until a request succeeds, and reverts to null if the endpoint
 * stops responding, so the UI can show a placeholder instead of a stale number.
 */
export function useSiteMetrics(enabled: boolean): SiteCounts | null {
  const [counts, setCounts] = useState<SiteCounts | null>(null);

  useEffect(() => {
    if (!enabled) return;

    let active = true;
    // A failed poll keeps whatever is already displayed: applying its null
    // blanked the counter mid-session until the next success.
    const apply = (incoming: SiteCounts | null) => {
      if (active) setCounts((current) => nextCounts(current, incoming));
    };

    recordPageView().then(apply);

    const beat = () => {
      if (document.visibilityState === 'visible') {
        sendHeartbeat().then(apply);
      }
    };

    const timer = window.setInterval(beat, HEARTBEAT_INTERVAL_MS);
    // Returning to a backgrounded tab should refresh immediately rather than
    // waiting out the remainder of the interval.
    document.addEventListener('visibilitychange', beat);

    return () => {
      active = false;
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', beat);
    };
  }, [enabled]);

  return counts;
}
