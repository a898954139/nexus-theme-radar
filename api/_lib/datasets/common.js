// Helpers shared by the dataset readers (api/_lib/datasets/*.js).

export const INSTRUMENT_ID = /^(TWSE|TPEX):([A-Za-z0-9]{1,10})$/;
export const STOCK_CODE = /^[A-Za-z0-9]{1,10}$/;

export class NotFound extends Error {
  constructor(reason = 'not_found') {
    super(reason);
    this.name = 'NotFound';
    this.reason = reason;
  }
}

export class BadRequest extends Error {
  constructor(reason) {
    super(reason);
    this.name = 'BadRequest';
    this.reason = reason;
  }
}

/** Newest snapshot header of a registered header table, or null. */
export async function latestSnapshot(query, headerTable, columns = '*') {
  if (!/^[a-z_]+$/.test(headerTable)) throw new Error('bad header table');
  const { rows } = await query(
    `select ${columns} from radar.${headerTable} order by generated_at desc, snapshot_id desc limit 1`,
  );
  return rows[0] ?? null;
}

/** Copy only keys whose value is not null/undefined. */
export function compact(object) {
  const out = {};
  for (const [key, value] of Object.entries(object)) {
    if (value !== null && value !== undefined) out[key] = value;
  }
  return out;
}
