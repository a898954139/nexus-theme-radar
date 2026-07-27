# Taiwan Equity Theme Radar MVP Architecture

This fork keeps the original static radar machinery and replaces the AI relevance layer with a Taiwan-equity theme layer.

v0.2 is intentionally Taiwan-first but market-agnostic at the contract layer. `TW_EQUITY` is the first market adapter, not the whole system; generated payloads use `market_id`, `market_scope`, `instrument`, `theme`, `event`, and `signal` style fields so future `US_EQUITY` and `FOREX` adapters can be added without rewriting the static pipeline.

## Scope

In scope for MVP:

- Static GitHub Pages front-end.
- GitHub Actions-compatible JSON generation.
- Deterministic sample/demo generation without fragile crawlers.
- Taiwan source registry and theme taxonomy contracts.
- Theme relevance scoring from article text.
- Direct Taiwan stock-code and company-alias mention extraction.
- Theme-to-instrument seed mapping for tracking candidates.
- Deterministic decision labels: `track_watch`, `quarantined`, `skip_noise`; duplicate records are collapsed before signal generation.

Out of scope for MVP:

- Live MoneyDJ/Cnyes/MOPS crawlers.
- Price/volume confirmation.
- Fundamental analysis from Goodinfo.
- Automatic discovery of new themes or new symbols.
- Login-gated, paid, cookie-based, or social sources.

## Data flow

```text
source registry
  → future fetchers / current sample records
  → normalized records
  → scripts/symbol_mapping.py + config/symbol_aliases.tw.json
  → direct_symbols + symbol_evidence
  → scripts/theme_relevance.py
  → matched_themes + primary_theme_id + theme_score
  → related_symbols instrument objects + related_symbol_codes compatibility list
  → decision (`track_watch` / `quarantined` / `skip_noise`)
  → data/theme-events.json
  → data/tracking-candidates.json
  → GitHub Pages static endpoints
  → front-end and NexusDashboard HTTP GET
```

## Static API endpoints

GitHub Pages serves JSON files as static HTTP resources:

```text
GET /data/theme-events.json
GET /data/tracking-candidates.json
GET /data/source-status.json
```

`theme-events.json` is the front-end hot payload. It is bounded by `--window-hours` and `--max-events`.

`tracking-candidates.json` is the downstream system payload for NexusDashboard. It contains only matched items with sufficient theme score and related symbols. Direct mentions retain their company name, source-field evidence, and match reason so downstream users can distinguish article evidence from taxonomy expansion.

## Local generation

Production-like RSS run:

```bash
python scripts/update_theme_radar.py \
  --output-dir data \
  --window-hours 72 \
  --max-events 500 \
  --max-candidates 200
```

Deterministic sample fixture run:

```bash
python scripts/generate_theme_demo.py \
  --output-dir data \
  --window-hours 48 \
  --max-events 50 \
  --max-candidates 20
```

## Validation

```bash
python -m py_compile scripts/symbol_mapping.py scripts/theme_relevance.py scripts/update_theme_radar.py scripts/generate_theme_demo.py
python -m pytest tests/test_theme_relevance.py -q
python -m pytest -q
node --check assets/app.js
git diff --check
```

## Symbol mapping

`config/symbol_aliases.tw.json` is a compact seed covering the current taxonomy symbols, not an exhaustive Taiwan listing. Explicit `NNNN.TW` mentions are accepted outside the seed with an empty `name_zh`; bare four-digit mentions are accepted only when the code exists in the seed. The matched suffix is retained in evidence, while years and unrelated bare four-digit values are ignored.

Every related symbol is emitted as an instrument object:

```json
{
  "instrument_id": "TWSE:2330",
  "market_id": "TW_EQUITY",
  "asset_class": "equity",
  "symbol": "2330",
  "exchange": "TWSE",
  "name_zh": "台積電"
}
```

`related_symbol_codes` remains as a lightweight compatibility field for current static UI/search consumers.

## v0.2 acceptance criteria

- Registry, taxonomy, article, event, and candidate payloads carry `market_id` or `market_scope`.
- Public hot payloads remain bounded static JSON: `theme-events.json` and `tracking-candidates.json`.
- Direct mentions and taxonomy expansion both emit instrument-aware objects, not stock-only strings.
- `TW_EQUITY` source registry, theme taxonomy, and symbol aliases are separate adapter data.
- `US_EQUITY` and `FOREX` are future adapter placeholders only; v0.2 does not fetch or score them.
- One deterministic sample path and one RSS path can produce article → theme → instrument → decision payloads.
- Duplicate URLs are deduped before event/candidate generation.

## Future adapter placeholders

```text
US_EQUITY
  asset_class: equity
  timezone: America/New_York
  future inputs: SEC filings, earnings calendar, US ticker universe, sector taxonomy, price/volume feedback

FOREX
  asset_class: fx
  timezone: UTC
  future inputs: economic calendar, central banks, macro taxonomy, currency pairs, DXY/yields/commodities feedback
```
