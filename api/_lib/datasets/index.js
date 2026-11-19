// Dataset registry for GET /api/v1/[dataset]. Each entry:
//   params?(URLSearchParams) -> validated params (throws BadRequest)
//   load({ query, params })  -> response body, or null when no snapshot exists
// Adding a dataset = a typed table set (supabase/migrations), a mapper in
// scripts/radar_tables.py, and a reader here.
import * as broker from './broker.js';
import * as institutionalFlows from './institutionalFlows.js';
import * as institutionalRankings from './institutionalRankings.js';
import * as sourceStatus from './sourceStatus.js';
import * as themeFocus from './themeFocus.js';

export const DATASETS = {
  'institutional-rankings': institutionalRankings,
  'institutional-flows': institutionalFlows,
  'broker-stats': broker.stats,
  'broker-coverage': broker.coverage,
  'broker-map': broker.map,
  'theme-focus': themeFocus,
  'source-status': sourceStatus,
};
