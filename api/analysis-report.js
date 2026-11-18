// GET /api/analysis-report?symbol=2330
//
// Server-side read of today's pre-market report (issue #8). Uses a login that
// holds only radar_reader; the credential lives in the Vercel server env
// (RADAR_READER_DATABASE_URL) and never reaches the browser bundle.
//
// "Today" is the Taipei calendar date. A report from an earlier edition is
// never returned as today's: if the local task did not run, the status is
// `not_produced`, not yesterday's report.
//
// Response: { status, report_date, data_as_of?, symbol?, rank?, report? }
//   status: produced | not_produced | not_in_list | no_batch | unavailable
import pg from 'pg';

const SYMBOL = /^[0-9A-Z]{4,6}$/;
const PUBLIC_REPORT_KEYS = [
  'symbol', 'report_date', 'data_as_of', 'framework_version', 'generated_at',
  'bias', 'actionability', 'conclusion', 'market_structure', 'key_levels',
  'primary_scenario', 'alternative_scenario', 'confirmation', 'invalidation',
  'no_trade_warning', 'news_context'
];

let pool = null;

export function taipeiDate(now = new Date()) {
  // en-CA formats as YYYY-MM-DD.
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now);
}

export function publicReport(report) {
  const out = {};
  for (const key of PUBLIC_REPORT_KEYS) out[key] = report?.[key] ?? null;
  return out;
}

export async function loadDailyReport(client, symbol, today) {
  const batch = await client.query(
    'select data_as_of::text as data_as_of from radar.analysis_batch where report_date = $1',
    [today]
  );
  if (batch.rowCount === 0) return { status: 'no_batch', report_date: today };
  const dataAsOf = batch.rows[0].data_as_of;
  if (!symbol) {
    const list = await client.query(
      `select q.rank, q.symbol, q.name_zh, q.selected_by,
              (select r.bias from radar.analysis_report r
                where r.report_date = q.report_date and r.symbol = q.symbol
                order by r.generated_at desc limit 1) as bias,
              (select r.actionability from radar.analysis_report r
                where r.report_date = q.report_date and r.symbol = q.symbol
                order by r.generated_at desc limit 1) as actionability
         from radar.analysis_queue q where q.report_date = $1 order by q.rank`,
      [today]
    );
    return { status: 'list', report_date: today, data_as_of: dataAsOf, items: list.rows };
  }
  const queued = await client.query(
    'select rank, name_zh from radar.analysis_queue where report_date = $1 and symbol = $2',
    [today, symbol]
  );
  if (queued.rowCount === 0) return { status: 'not_in_list', report_date: today, data_as_of: dataAsOf, symbol };
  const report = await client.query(
    `select report from radar.analysis_report
      where report_date = $1 and symbol = $2
      order by generated_at desc limit 1`,
    [today, symbol]
  );
  const base = { report_date: today, data_as_of: dataAsOf, symbol, rank: queued.rows[0].rank };
  if (report.rowCount === 0) return { ...base, status: 'not_produced' };
  const body = publicReport(report.rows[0].report);
  if (body.report_date !== today) return { ...base, status: 'not_produced' };
  return { ...base, status: 'produced', report: body };
}

export default async function handler(req, res) {
  const today = taipeiDate();
  const raw = typeof req.query?.symbol === 'string' ? req.query.symbol.trim().toUpperCase() : '';
  if (raw && !SYMBOL.test(raw)) {
    res.status(400).json({ status: 'bad_request', report_date: today });
    return;
  }
  const url = process.env.RADAR_READER_DATABASE_URL;
  if (!url) {
    res.status(503).json({ status: 'unavailable', report_date: today });
    return;
  }
  try {
    // TLS mode comes from the connection string (sslmode=...), not from code.
    pool ??= new pg.Pool({ connectionString: url, max: 2 });
    const payload = await loadDailyReport(pool, raw || null, today);
    res.setHeader('Cache-Control', 's-maxage=60, stale-while-revalidate=300');
    res.status(200).json(payload);
  } catch (error) {
    console.error('analysis_report_api_failed', error?.code ?? error?.name ?? 'error');
    res.status(503).json({ status: 'unavailable', report_date: today });
  }
}
