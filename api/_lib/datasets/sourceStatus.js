// GET /api/v1/source-status -> SourceStatusData (src/types.ts)
import { compact, latestSnapshot } from './common.js';

export async function load({ query }) {
  const h = await latestSnapshot(query, 'source_status_snapshot');
  if (!h) return null;
  const { rows } = await query(
    `select * from radar.source_status_site where snapshot_id = $1 order by position`,
    [h.snapshot_id],
  );
  return {
    generated_at: h.generated_at,
    fetched_raw_items: h.fetched_raw_items,
    items_before_topic_filter: h.items_before_topic_filter,
    successful_sites: h.successful_sites,
    failed_count: h.failed_count,
    failed_sites: rows.filter((s) => s.status === 'failed').map((s) => s.source_id),
    sites: rows.map((s) => ({
      source_id: s.source_id,
      name: s.name,
      status: s.status,
      error: s.error,
      ...compact({
        source_class: s.source_class,
        adapter: s.adapter,
        fetch_method: s.fetch_method,
        items: s.items,
        trial: s.trial,
        not_modified: s.not_modified,
        runs_7d: s.runs_7d,
        success_rate_7d: s.success_rate_7d,
        elapsed_ms: s.elapsed_ms,
      }),
    })),
  };
}
