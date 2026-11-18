/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Public build flag, not a secret. 'api' = read /api/pre-market first. */
  readonly VITE_PRE_MARKET_SOURCE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
