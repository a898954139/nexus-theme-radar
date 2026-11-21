// Brief datasets:
//   GET /api/v1/pre-market   -> PreMarketData (api/_lib/preMarketContract.js; copy of front/src/lib/preMarketContract.js)
//   GET /api/v1/stock-audit  -> StockAuditReport (src/services/stockAudit.ts)
import { latestSnapshot } from './common.js';

function group(rows, keyOf) {
  const out = new Map();
  for (const r of rows) {
    const k = keyOf(r);
    if (!out.has(k)) out.set(k, []);
    out.get(k).push(r);
  }
  return out;
}

export const preMarket = {
  async load({ query }) {
    const h = await latestSnapshot(query, 'pm_snapshot');
    if (!h) return null;
    const id = [h.snapshot_id];
    const q = (table, order) => query(`select * from radar.${table} where snapshot_id = $1 order by ${order}`, id);
    const [sources, events, sectorsOf, related, impacts, pulse, points, sectors, panels, entries, indicators] =
      await Promise.all([
        q('pm_source', 'position'),
        q('pm_event', 'position'),
        q('pm_event_sector', 'event_position, position'),
        q('pm_event_related', 'event_position, position'),
        q('pm_event_impact', 'event_position, position'),
        q('pm_pulse', 'position'),
        q('pm_pulse_point', 'pulse_position, position'),
        q('pm_sector', 'position'),
        q('pm_flow_panel', 'position'),
        q('pm_flow_entry', "panel_position, side, position"),
        q('pm_indicator', 'position'),
      ]);
    const sectorsBy = group(sectorsOf.rows, (r) => r.event_position);
    const relatedBy = group(related.rows, (r) => r.event_position);
    const impactsBy = group(impacts.rows, (r) => r.event_position);
    const pointsBy = group(points.rows, (r) => r.pulse_position);
    const entriesBy = group(entries.rows, (r) => `${r.panel_position}:${r.side}`);
    const body = {
      schema_version: h.schema_version,
      generated_at: h.generated_at,
      window_hours: h.window_hours,
      ...(h.direction_rule_version !== null ? { direction_rule_version: h.direction_rule_version } : {}),
      sources: sources.rows.map((s) => s.name),
      events: events.rows.map((e) => ({
        id: e.event_id,
        tier: e.tier,
        score: e.score,
        actLabel: e.act_label,
        speaker: e.speaker,
        publishedAt: e.published_at,
        titleZh: e.title_zh,
        titleEn: e.title_en,
        channel: e.channel,
        pathLabel: e.path_label,
        sectors: (sectorsBy.get(e.position) ?? []).map((s) => s.sector),
        url: e.url,
        related: (relatedBy.get(e.position) ?? []).map((r) => ({ title: r.title, url: r.url })),
        pathId: e.path_id,
        direction: e.direction,
        directionReason: e.direction_reason,
        horizon: e.horizon,
        impacts: (impactsBy.get(e.position) ?? []).map((i) => ({ sector: i.sector, direction: i.direction })),
        ...(e.has_backtest ? {
          pathBacktest: {
            target: e.bt_target,
            hitRate: e.bt_hit_rate,
            n: e.bt_n,
            avgSignedExcessT1: e.bt_avg_signed_excess_t1,
            foreignHitRateT1: e.bt_foreign_hit_rate_t1,
            avgForeignT1: e.bt_avg_foreign_t1,
            window: [e.bt_window_start, e.bt_window_end],
          },
        } : {}),
        ...(e.has_flow_after ? {
          flowAfter: { target: e.fa_target, baseDate: e.fa_base_date, foreignT1: e.fa_foreign_t1, excessT1: e.fa_excess_t1 },
        } : {}),
      })),
      pulse: pulse.rows.map((p) => ({
        id: p.pulse_id,
        label: p.label,
        value: p.value_text,
        delta: p.delta_text,
        up: p.up,
        series: (pointsBy.get(p.position) ?? []).map((x) => x.value),
      })),
      sectors: sectors.rows.map((s) => ({ name: s.name, chg: s.chg })),
      flows: {
        as_of: h.flows_as_of,
        panels: panels.rows.map((p) => ({
          id: p.panel_id,
          title: p.title,
          unit: p.unit,
          buy: (entriesBy.get(`${p.position}:buy`) ?? []).map((x) => ({ rank: x.rank, name: x.name, value: x.value })),
          sell: (entriesBy.get(`${p.position}:sell`) ?? []).map((x) => ({ rank: x.rank, name: x.name, value: x.value })),
        })),
      },
    };
    if (h.has_market) {
      body.market = {
        generated_at: h.market_generated_at,
        indicators: indicators.rows.map((i) => (i.missing
          ? { id: i.indicator_id, label: i.label, missing: true, reason: i.reason }
          : {
            id: i.indicator_id, label: i.label, missing: false, value: i.value, change: i.change,
            change_pct: i.change_pct, unit: i.unit, as_of: i.as_of, session: i.session, source: i.source,
          })),
        news: h.has_news
          ? { net: h.news_net, bull: h.news_bull, bear: h.news_bear, lean: h.news_lean, window_hours: h.news_window_hours }
          : null,
        market: { lean: h.market_lean, avg_pct: h.market_avg_pct, basis: h.market_basis },
        divergence: h.has_divergence
          ? { message: h.divergence_message, news_lean: h.divergence_news_lean, market_lean: h.divergence_market_lean }
          : null,
        ...(h.has_sectors_as_of ? { sectors_as_of: h.sectors_as_of } : {}),
      };
    }
    return body;
  },
};

export const stockAudit = {
  async load({ query }) {
    const h = await latestSnapshot(query, 'stock_audit_report');
    if (!h) return null;
    const id = [h.snapshot_id];
    const [refs, stocks, candles, ops, receipts] = await Promise.all([
      query('select * from radar.stock_audit_reference where snapshot_id = $1 order by position', id),
      query('select * from radar.stock_audit_stock where snapshot_id = $1 order by position', id),
      query('select * from radar.stock_audit_candle where snapshot_id = $1 order by stock_position, trade_date', id),
      query('select * from radar.stock_audit_operation where snapshot_id = $1 order by stock_position, position', id),
      query('select * from radar.stock_audit_receipt where snapshot_id = $1 order by position', id),
    ]);
    const candlesBy = group(candles.rows, (r) => r.stock_position);
    const opsBy = group(ops.rows, (r) => r.stock_position);
    return {
      schema_version: h.schema_version,
      generated_at: h.generated_at_text,
      report_date: h.report_date,
      conclusion: h.conclusion,
      forecast: {
        summary: h.forecast_summary,
        references: refs.rows.map((r) => ({ label: r.label, value: r.value, change_pct: r.change_pct, as_of: r.as_of, source: r.source })),
        as_of: h.forecast_as_of,
      },
      stocks: stocks.rows.map((s) => ({
        symbol: s.symbol,
        name: s.name,
        price: s.price,
        price_as_of: s.price_as_of,
        source: s.source,
        fundamentals: {
          revenue: s.f_revenue, revenue_unit: s.f_revenue_unit, period: s.f_period, eps: s.f_eps, ttm_eps: s.f_ttm_eps,
          pe: s.f_pe, as_of: s.f_as_of, source: s.f_source, analysis: s.f_analysis,
        },
        valuation: {
          source: s.v_source, baseline_label: s.v_baseline_label, baseline_pe: s.v_baseline_pe,
          premium_pct: s.v_premium_pct, percentile: s.v_percentile, sample_count: s.v_sample_count, analysis: s.v_analysis,
        },
        technical: {
          candles: (candlesBy.get(s.position) ?? []).map((c) => ({
            date: c.trade_date, open: c.open, high: c.high, low: c.low, close: c.close, volume: c.volume,
          })),
          ma20: s.t_ma20, ma60: s.t_ma60, support: s.t_support, resistance: s.t_resistance, analysis: s.t_analysis,
        },
        operations: (opsBy.get(s.position) ?? []).map((o) => ({
          term: o.term, horizon: o.horizon, entry: o.entry, add: o.add_price, stop: o.stop,
          take_profit: o.take_profit, timing: o.timing, add_condition: o.add_condition,
        })),
        quality: {
          sharpe: s.q_sharpe, sortino: s.q_sortino, ttr_days: s.q_ttr_days, index_shape: s.q_index_shape,
          period: s.q_period, method: s.q_method, source: s.q_source,
        },
        summary: s.summary,
      })),
      source_receipts: receipts.rows.map((r) => ({ url: r.url, fetched_at: r.fetched_at, status: r.status })),
    };
  },
};
