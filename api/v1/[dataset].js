// GET /api/v1/<dataset>[?params] — every page dataset, read from the
// normalized radar tables (registry: api/_lib/datasets/index.js).
//
// One function for all datasets on purpose: Vercel Hobby caps a deployment
// at 12 functions. Static routes such as api/v1/tracking-candidates.js take
// precedence over this dynamic segment.
import { getReaderPool } from '../_lib/db.js';
import { handleDataset } from '../_lib/router.js';

export async function GET(request) {
  const url = new URL(request.url);
  const dataset = decodeURIComponent(url.pathname.replace(/\/+$/, '').split('/').pop() || '');
  const pool = getReaderPool('radar-api-v1');
  const result = await handleDataset({
    dataset,
    search: url.searchParams,
    query: pool ? (sql, values) => pool.query(sql, values) : null,
  });
  return new Response(result.body, { status: result.status, headers: result.headers });
}
