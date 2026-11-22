// Stock datasets:
//   GET /api/v1/stock-watchlist                     -> StockWatchlistData (exact keys)
//   GET /api/v1/fundamentals?instrument_id=TWSE:2330 | ?symbol=2330[&exchange=] -> StockFundamentals
import { BadRequest, INSTRUMENT_ID, NotFound, STOCK_CODE, latestSnapshot } from './common.js';

const SHORT = ['theme_attention', 'institutional_short_activity', 'daytrade_activity', 'fundamental_defense'];
const LONG = ['fundamental_quality', 'institutional_support', 'theme_persistence', 'trading_stability'];

function group(rows, keyOf) {
  const out = new Map();
  for (const r of rows) {
    const k = keyOf(r);
    if (!out.has(k)) out.set(k, []);
    out.get(k).push(r);
  }
  return out;
}

export const watchlist = {
  async load({ query }) {
    const h = await latestSnapshot(query, 'watchlist_snapshot');
    if (!h) return null;
    const id = [h.snapshot_id];
    const [values, day, weights, members, themes, flags, items, components, missing] = await Promise.all([
      query('select kind, value from radar.watchlist_header_value where snapshot_id = $1 order by kind, position', id),
      query('select * from radar.watchlist_day_trading_source where snapshot_id = $1 order by market', id),
      query('select weight_set, component, weight from radar.watchlist_weight where snapshot_id = $1 order by weight_set, position', id),
      query(
        `select m.instrument_id, m.selected_top50, m.short_rank, m.long_rank, i.symbol, i.exchange, i.name_zh
           from radar.watchlist_member m join radar.instrument i using (instrument_id)
          where m.snapshot_id = $1 order by m.position`, id),
      query('select * from radar.watchlist_member_theme where snapshot_id = $1 order by instrument_id, position', id),
      query('select * from radar.watchlist_member_flag where snapshot_id = $1 order by instrument_id, position', id),
      query('select * from radar.watchlist_item where snapshot_id = $1', id),
      query('select * from radar.watchlist_item_component where snapshot_id = $1', id),
      query('select * from radar.watchlist_item_missing where snapshot_id = $1 order by instrument_id, position', id),
    ]);
    const list = (kind) => values.rows.filter((v) => v.kind === kind).map((v) => v.value);
    const weightSet = (set) => Object.fromEntries(weights.rows.filter((w) => w.weight_set === set).map((w) => [w.component, w.weight]));
    const themesBy = group(themes.rows, (r) => r.instrument_id);
    const flagsBy = group(flags.rows, (r) => r.instrument_id);
    const compBy = group(components.rows, (r) => `${r.instrument_id}:${r.horizon}`);
    const missingBy = group(missing.rows, (r) => r.instrument_id);
    const memberBy = new Map(members.rows.map((m) => [m.instrument_id, m]));

    const instrument = (m) => ({ instrument_id: m.instrument_id, symbol: m.symbol, exchange: m.exchange, name_zh: m.name_zh });
    const themeList = (iid) => (themesBy.get(iid) ?? []).map((t) => ({
      theme_id: t.theme_id, name_zh: t.name_zh, relation: t.relation,
      heat_score: t.heat_score, heat_change_24h: t.heat_change_24h, momentum_score: t.momentum_score,
    }));
    const flagList = (iid) => (flagsBy.get(iid) ?? []).map((f) => ({ key: f.flag_key, type: f.flag_type }));
    const comps = (iid, horizon, names) => {
      const rows = new Map((compBy.get(`${iid}:${horizon}`) ?? []).map((c) => [c.component, c]));
      return Object.fromEntries(names.map((n) => {
        const c = rows.get(n);
        return [n, c ? { raw: c.raw, normalized: c.normalized, base_weight: c.base_weight, effective_weight: c.effective_weight, available: c.available } : null];
      }));
    };
    const detail = items.rows.map((it) => {
      const m = memberBy.get(it.instrument_id);
      return {
        instrument: instrument(m),
        themes: themeList(it.instrument_id),
        short: {
          rank: it.short_rank,
          score: it.short_score,
          components: comps(it.instrument_id, 'short', SHORT),
          risk_adjustment: {
            overnight_risk_adjustment: { value: it.overnight_value, applied: it.overnight_applied, missing_reason: it.overnight_missing_reason },
          },
        },
        long: { rank: it.long_rank, score: it.long_score, components: comps(it.instrument_id, 'long', LONG) },
        institutional: {
          direction: it.institutional_direction,
          as_of: it.institutional_as_of,
          observation_count: it.institutional_observation_count,
          five_day_net: it.institutional_five_day_net,
        },
        trading_activity: {
          as_of: it.trading_as_of,
          day_trading_volume: it.day_trading_volume,
          total_volume: it.total_volume,
          day_trading_volume_ratio: it.day_trading_volume_ratio,
          overnight_risk: it.overnight_risk,
          overnight_missing_reason: it.overnight_missing_reason_trading,
        },
        fundamentals: {
          score: it.fundamental_score,
          fiscal_quarter: it.fiscal_quarter,
          comparison_basis: it.comparison_basis,
          revenue_growth: it.revenue_growth,
          revenue_direction: it.revenue_direction,
          eps_growth: it.eps_growth,
          eps_direction: it.eps_direction,
          gross_margin: it.gross_margin,
          operating_margin: it.operating_margin,
          operating_cash_flow: it.operating_cash_flow,
          operating_cash_flow_margin: it.operating_cash_flow_margin,
          debt_ratio: it.debt_ratio,
        },
        flags: flagList(it.instrument_id),
        coverage: {
          short_ratio: it.coverage_short_ratio,
          long_ratio: it.coverage_long_ratio,
          missing: (missingBy.get(it.instrument_id) ?? []).map((r) => r.metric),
        },
      };
    });
    const shortItems = detail.slice().sort((a, b) => a.short.rank - b.short.rank);
    // moat_v1: the long list is a subset of the short list; short-only names have no long rank.
    const longItems = detail.filter((d) => d.long.rank !== null && d.long.rank !== undefined).sort((a, b) => a.long.rank - b.long.rank);
    const dayTrading = Object.fromEntries(day.rows.map((d) => [d.market, {
      as_of: d.as_of, finality: d.finality, numerator_url: d.numerator_url,
      denominator_url: d.denominator_url, status: d.status, error: d.error,
    }]));
    return {
      schema_version: h.schema_version,
      methodology_version: h.methodology_version,
      generated_at: h.generated_at,
      candidate_as_of: h.candidate_as_of,
      sources: {
        momentum: { generated_at: h.momentum_generated_at, observed_hour: h.momentum_observed_hour },
        institutional: { as_of: list('institutional_as_of') },
        fundamentals: { fiscal_quarters: list('fundamentals_fiscal_quarter') },
        day_trading_activity: dayTrading,
      },
      methodology: {
        missing_values: h.methodology_missing_values,
        top50: h.methodology_top50,
        short_weights: weightSet('short'),
        long_weights: weightSet('long'),
        fundamental_quality_weights: weightSet('fundamental_quality'),
      },
      coverage: {
        eligible_count: h.eligible_count,
        selected_count: h.selected_count,
        metrics: list('coverage_metric'),
        missing_reasons: list('coverage_missing_reason'),
      },
      short: { count: shortItems.length, items: shortItems },
      long: { count: longItems.length, items: longItems },
      searchable: members.rows.map((m) => ({
        instrument: instrument(m),
        themes: themeList(m.instrument_id),
        selected_top50: m.selected_top50,
        short_rank: m.short_rank,
        long_rank: m.long_rank,
        flags: flagList(m.instrument_id),
      })),
    };
  },
};

const INCOME = ['revenue', 'cost_of_sales', 'gross_profit', 'selling_expense', 'admin_expense', 'rd_expense',
  'expected_credit_loss', 'operating_expense', 'operating_income', 'pretax_income', 'net_income', 'eps'];
const BALANCE = ['cash', 'receivables', 'inventory', 'current_assets', 'total_assets', 'current_liabilities',
  'total_liabilities', 'total_equity'];
const CASH_FLOW = ['operating', 'investing', 'financing', 'depreciation', 'capex', 'dividends_paid', 'ending_cash'];
const QUARTER = ['revenue', 'gross_margin', 'operating_margin', 'net_margin', 'eps'];

function present(row, columns) {
  const out = {};
  for (const c of columns) if (row[c] !== null && row[c] !== undefined) out[c] = row[c];
  return out;
}

export function instrumentParams(search) {
  const instrumentId = (search.get('instrument_id') || '').trim();
  const symbol = (search.get('symbol') || '').trim();
  const exchange = (search.get('exchange') || '').trim().toUpperCase();
  if (instrumentId) {
    if (!INSTRUMENT_ID.test(instrumentId)) throw new BadRequest('bad_instrument_id');
    return { candidates: [instrumentId] };
  }
  if (!STOCK_CODE.test(symbol)) throw new BadRequest('instrument_id_or_symbol_required');
  if (exchange && exchange !== 'TWSE' && exchange !== 'TPEX') throw new BadRequest('bad_exchange');
  return { candidates: exchange ? [`${exchange}:${symbol}`] : [`TWSE:${symbol}`, `TPEX:${symbol}`] };
}

export const fundamentals = {
  params: instrumentParams,
  async load({ query, params: { candidates } }) {
    const head = await query(
      `select * from radar.fundamental_set where instrument_id = any($1::text[])
        order by array_position($1::text[], instrument_id) limit 1`,
      [candidates],
    );
    const h = head.rows[0];
    if (!h) throw new NotFound('instrument_not_found');
    const key = [h.instrument_id, h.fetched_at];
    const where = 'where instrument_id = $1 and fetched_at = $2';
    const [quarters, health, income, balance, cashFlow, missing] = await Promise.all([
      query(`select * from radar.fundamental_quarter ${where} order by position`, key),
      query(`select * from radar.fundamental_health_period ${where} order by period`, key),
      query(`select * from radar.fundamental_income ${where} order by period desc`, key),
      query(`select * from radar.fundamental_balance ${where} order by period desc`, key),
      query(`select * from radar.fundamental_cash_flow ${where} order by period desc`, key),
      query(`select note from radar.fundamental_missing ${where} order by position`, key),
    ]);
    const healthOut = present(h, ['cash', 'current_ratio', 'debt_ratio']);
    for (const p of health.rows) {
      if (p.net_income !== null) healthOut[`net_income_${p.period}`] = p.net_income;
      if (p.operating_cash_flow !== null) healthOut[`operating_cash_flow_${p.period}`] = p.operating_cash_flow;
    }
    const byPeriod = (rows, cols) => Object.fromEntries(rows.map((r) => [r.period, present(r, cols)]));
    return {
      instrument_id: h.instrument_id,
      quarters: quarters.rows.map((q) => ({ period: q.period, ...present(q, QUARTER) })),
      health: healthOut,
      valuation: present(h, ['ttm_eps']),
      statements: {
        income: byPeriod(income.rows, INCOME),
        balance: byPeriod(balance.rows, BALANCE),
        cash_flow: byPeriod(cashFlow.rows, CASH_FLOW),
      },
      basis: h.basis,
      currency: h.currency,
      source: h.source,
      fetched_at: h.fetched_at,
      fiscal_quarter: h.fiscal_quarter,
      missing: missing.rows.map((m) => m.note),
    };
  },
};
