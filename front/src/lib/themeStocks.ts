import { InstrumentRef } from '../types';

export type ThemeStockKind = 'direct' | 'supply';

export interface ThemeStockEntry {
  instrument: InstrumentRef;
  kind: ThemeStockKind;
}

export function mergeInstrumentRefs(...lists: Array<readonly InstrumentRef[]>): InstrumentRef[] {
  const seen = new Set<string>();
  return lists.flat().filter((instrument) => {
    if (seen.has(instrument.instrument_id)) return false;
    seen.add(instrument.instrument_id);
    return true;
  });
}

export function buildThemeStockEntries(direct: readonly InstrumentRef[], supply: readonly InstrumentRef[]): ThemeStockEntry[] {
  const seen = new Set<string>();
  return [
    ...direct.map((instrument) => ({ instrument, kind: 'direct' as const })),
    ...supply.map((instrument) => ({ instrument, kind: 'supply' as const }))
  ].filter(({ instrument }) => {
    if (seen.has(instrument.instrument_id)) return false;
    seen.add(instrument.instrument_id);
    return true;
  });
}
