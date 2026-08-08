import { useEffect, useState } from 'react';
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
    const apply = (next: SiteCounts | null) => {
      if (active) setCounts(next);
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
