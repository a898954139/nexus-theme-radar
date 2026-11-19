// Dataset registry for GET /api/v1/[dataset]. Each entry:
//   params?(URLSearchParams) -> validated params (throws BadRequest)
//   load({ query, params })  -> response body, or null when no snapshot exists
// Adding a dataset = a typed table set (supabase/migrations), a mapper in
// scripts/radar_tables.py, and a reader here.
import * as briefs from './briefs.js';
import * as broker from './broker.js';
import * as institutionalFlows from './institutionalFlows.js';
import * as institutionalRankings from './institutionalRankings.js';
import * as sourceStatus from './sourceStatus.js';
import * as stock from './stock.js';
import * as themeFocus from './themeFocus.js';
import * as themes from './themes.js';

export const DATASETS = {
  'institutional-rankings': institutionalRankings,
  'institutional-flows': institutionalFlows,
  'broker-stats': broker.stats,
  'broker-coverage': broker.coverage,
  'broker-map': broker.map,
  'theme-focus': themeFocus,
  'source-status': sourceStatus,
  'theme-events': themes.events,
  'theme-ranking': themes.ranking,
  'theme-momentum': themes.momentum,
  'theme-momentum-history': themes.momentumHistory,
  'stock-watchlist': stock.watchlist,
  'fundamentals': stock.fundamentals,
  'pre-market': briefs.preMarket,
  'stock-audit': briefs.stockAudit,
};
