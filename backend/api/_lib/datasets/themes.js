// Theme datasets (newest snapshot of each):
//   GET /api/v1/theme-events              -> { generated_at, ..., items: ThemeEvent[] }
//   GET /api/v1/theme-ranking             -> ThemeRankingData
//   GET /api/v1/theme-momentum            -> MomentumLatestData
//   GET /api/v1/theme-momentum-history[?hours=720] -> MomentumHistoryData
import { BadRequest, compact, latestSnapshot } from './common.js';

const MARKET_ID = 'TW_EQUITY';

function groupBy(rows, keyOf) {
  const out = new Map();
  for (const row of rows) {
    const key = keyOf(row);
    if (!out.has(key)) out.set(key, []);
    out.get(key).push(row);
  }
  return out;
}

function equitySymbol(s) {
  return {
    instrument_id: s.instrument_id,
    market_id: MARKET_ID,
    asset_class: 'equity',
    symbol: s.symbol,
    exchange: s.exchange,
    name_zh: s.name_zh,
    evidence: s.evidence,
    reason: s.reason,
  };
}

function news(row, withCluster) {
  if (row.news_id === null) return null;
  return {
    ...(withCluster && row.news_cluster_id !== null ? { cluster_id: row.news_cluster_id } : {}),
    id: row.news_id,
    title_zh: row.news_title_zh,
    summary: row.news_summary,
    source_id: row.news_source_id,
    source: row.news_source,
    published_at: row.news_published_at,
    canonical_url: row.news_url,
  };
}

export const events = {
  async load({ query }) {
    const h = await latestSnapshot(query, 'theme_event_snapshot');
    if (!h) return null;
    const id = [h.snapshot_id];
    const [items, themes, symbols, sources] = await Promise.all([
      query('select * from radar.theme_event_item where snapshot_id = $1 order by position', id),
      query('select * from radar.theme_event_theme where snapshot_id = $1 order by event_position, position', id),
      query(
        `select s.event_position, s.role, s.instrument_id, s.evidence, s.reason, i.symbol, i.exchange, i.name_zh
           from radar.theme_event_symbol s join radar.instrument i using (instrument_id)
          where s.snapshot_id = $1 order by s.event_position, s.role, s.position`,
        id,
      ),
      query('select * from radar.theme_event_source where snapshot_id = $1 order by event_position, position', id),
    ]);
    const themesBy = groupBy(themes.rows, (r) => r.event_position);
    const symbolsBy = groupBy(symbols.rows, (r) => `${r.event_position}:${r.role}`);
    const sourcesBy = groupBy(sources.rows, (r) => r.event_position);
    return {
      generated_at: h.generated_at,
      market_id: h.market_id,
      market_scope: [h.market_id],
      window_hours: h.window_hours,
      max_items: h.max_items,
      total_items: h.total_items,
      total_items_available: h.total_items_available,
      taxonomy_version: h.taxonomy_version,
      items: items.rows.map((e) => {
        const related = (symbolsBy.get(`${e.position}:related`) ?? []).map(equitySymbol);
        return {
          id: e.article_id,
          title_zh: e.title_zh,
          summary: e.summary,
          source: e.source,
          source_id: e.source_id,
          market_id: MARKET_ID,
          market_scope: [MARKET_ID],
          published_at: e.published_at,
          matched_themes: (themesBy.get(e.position) ?? []).map((t) => compact({
            theme_id: t.theme_id, name_zh: t.name_zh, score: t.score, reason: t.reason,
          })),
          direct_symbols: (symbolsBy.get(`${e.position}:direct`) ?? []).map(equitySymbol),
          related_symbols: related,
          related_symbol_codes: related.map((s) => s.symbol),
          cluster_sources: (sourcesBy.get(e.position) ?? []).map((s) => ({
            source_id: s.source_id, source: s.source, title: s.title, url: s.url, published_at: s.published_at,
          })),
          ...compact({
            source_class: e.source_class,
            url: e.url,
            extraction_method: e.extraction_method,
            fetched_at: e.fetched_at,
            primary_theme_id: e.primary_theme_id,
            theme_score: e.theme_score,
            decision: e.decision,
            tw_relevance_status: e.tw_relevance_status,
            tw_relevance_reason: e.tw_relevance_reason,
            cluster_id: e.cluster_id,
            cluster_size: e.cluster_size,
            confirmation_status: e.confirmation_status,
            official_evidence_count: e.official_evidence_count,
          }),
        };
      }),
    };
  },
};

export const ranking = {
  async load({ query }) {
    const h = await latestSnapshot(query, 'theme_ranking_snapshot');
    if (!h) return null;
    const [themes, symbols] = await Promise.all([
      query('select * from radar.theme_ranking_theme where snapshot_id = $1 order by rank, theme_id', [h.snapshot_id]),
      query(
        `select s.*, i.symbol, i.exchange, i.name_zh
           from radar.theme_ranking_symbol s join radar.instrument i using (instrument_id)
          where s.snapshot_id = $1 order by s.theme_id, s.role, s.position`,
        [h.snapshot_id],
      ),
    ]);
    const by = groupBy(symbols.rows, (r) => `${r.theme_id}:${r.role}`);
    const ref = (s) => ({
      instrument_id: s.instrument_id,
      symbol: s.symbol,
      exchange: s.exchange,
      name_zh: s.name_zh,
      direct_event_count: s.direct_event_count,
      ...(s.role === 'supply_chain'
        ? { official_evidence_count: s.official_evidence_count, company_rank_score: s.company_rank_score }
        : {}),
      latest_mentioned_at: s.latest_mentioned_at,
      ...(s.role === 'supply_chain' ? { latest_official_at: s.latest_official_at } : {}),
    });
    return {
      schema_version: h.schema_version,
      ranking_rule_version: h.ranking_rule_version,
      company_rule_version: h.company_rule_version,
      generated_at: h.generated_at,
      market_id: h.market_id,
      market_scope: [h.market_id],
      window_hours: h.window_hours,
      max_themes: h.max_themes,
      qualified_theme_count: h.qualified_theme_count,
      displayed_theme_count: h.displayed_theme_count,
      threshold_note: h.threshold_note,
      generation_status: h.generation_status,
      failed_source_count: h.failed_source_count,
      official_evidence_status: h.official_evidence_status,
      themes: themes.rows.map((t) => ({
        rank: t.rank,
        theme_id: t.theme_id,
        name_zh: t.name_zh,
        heat_score: t.heat_score,
        summaries: {
          event_count: t.event_count,
          source_count: t.source_count,
          tracking_candidate_count: t.tracking_candidate_count,
          taiwan_mapping_count: t.taiwan_mapping_count,
        },
        direct_mentions: (by.get(`${t.theme_id}:direct`) ?? []).map(ref),
        supply_chain_candidates: (by.get(`${t.theme_id}:supply_chain`) ?? []).map(ref),
        representative_news: news(t, true),
      })),
    };
  },
};

const MOMENTUM_THEME_FIELDS = [
  'event_count', 'source_count', 'tracking_candidate_count', 'taiwan_mapping_count',
  'direct_mapping_event_count', 'single_source_concentration', 'latest_qualifying_event_at',
];

function momentumCore(t) {
  const out = {
    rank: t.rank,
    theme_id: t.theme_id,
    qualification_status: t.qualification_status,
    near_threshold_reason: t.near_threshold_reason,
    momentum_score: t.momentum_score,
    lifecycle_stage: t.lifecycle_stage,
    heat_score: t.heat_score,
  };
  for (const key of MOMENTUM_THEME_FIELDS) out[key] = t[key];
  return out;
}

export const momentum = {
  async load({ query }) {
    const h = await latestSnapshot(query, 'theme_momentum_snapshot');
    if (!h) return null;
    const [themes, symbols] = await Promise.all([
      query('select * from radar.theme_momentum_theme where snapshot_id = $1 order by rank, theme_id', [h.snapshot_id]),
      query(
        `select s.*, i.symbol, i.exchange, i.name_zh
           from radar.theme_momentum_symbol s join radar.instrument i using (instrument_id)
          where s.snapshot_id = $1 order by s.theme_id, s.role, s.position`,
        [h.snapshot_id],
      ),
    ]);
    const by = groupBy(symbols.rows, (r) => `${r.theme_id}:${r.role}`);
    return {
      schema_version: h.schema_version,
      ranking_rule_version: h.ranking_rule_version,
      inclusion_rule_version: h.inclusion_rule_version,
      heat_rule_version: h.heat_rule_version,
      generated_at: h.generated_at,
      observed_hour: h.observed_hour,
      market_id: h.market_id,
      market_scope: [h.market_id],
      window_hours: h.window_hours,
      freshness_status: h.freshness_status,
      theme_count: h.theme_count,
      themes: themes.rows.map((t) => ({
        ...momentumCore(t),
        name_zh: t.name_zh,
        heat_change_24h: t.heat_change_24h,
        source_change_24h: t.source_change_24h,
        representative_news: news(t, false),
        direct_symbols: (by.get(`${t.theme_id}:direct`) ?? []).map(equitySymbol),
        related_symbols: (by.get(`${t.theme_id}:related`) ?? []).map(equitySymbol),
      })),
    };
  },
};

export const momentumHistory = {
  params(search) {
    const raw = search.get('hours');
    const hours = raw === null ? 720 : Number(raw);
    if (!Number.isInteger(hours) || hours < 1 || hours > 1440) throw new BadRequest('bad_hours');
    return { hours };
  },
  async load({ query, params: { hours } }) {
    const h = await latestSnapshot(query, 'theme_momentum_snapshot',
      'snapshot_id, generated_at, ranking_rule_version, inclusion_rule_version, heat_rule_version, market_id');
    if (!h) return null;
    const { rows } = await query(
      `with newest as (select max(observed_hour) as hour from radar.theme_momentum_hourly)
       select m.* from radar.theme_momentum_hourly m, newest
        where m.observed_hour > newest.hour - make_interval(hours => $1)
        order by m.observed_hour, m.rank, m.theme_id`,
      [hours],
    );
    const byHour = groupBy(rows, (r) => r.observed_hour);
    const hoursList = [...byHour.keys()];
    return {
      schema_version: 'nexus_public_theme_momentum_history.v0.9',
      ranking_rule_version: h.ranking_rule_version,
      inclusion_rule_version: h.inclusion_rule_version,
      heat_rule_version: h.heat_rule_version,
      generated_at: h.generated_at,
      market_id: h.market_id,
      market_scope: [h.market_id],
      retention_hours: hours,
      oldest_observed_hour: hoursList[0] ?? null,
      newest_observed_hour: hoursList[hoursList.length - 1] ?? null,
      observation_count: hoursList.length,
      observations: hoursList.map((hour) => ({ observed_hour: hour, themes: byHour.get(hour).map(momentumCore) })),
    };
  },
};
