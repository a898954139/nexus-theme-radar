# Nexus Theme Radar v0.6 Design

**Status:** Approved for planning

**Date:** 2026-07-27

**Repository:** `/Users/anthony/Desktop/dev/nexus-theme-radar`

**Production baseline:** `538f81ffadb30b606bfe81696b0791ea5b74ad41`

**Feature baseline:** `ee00774d1fef2f99443c0894d39692d3e779a2ef`

## 1. Executive decision

v0.6 fixes three quality problems observed after the v0.5 production full refresh:

1. the bounded official-evidence snapshot is dominated by one high-volume dataset;
2. multiple articles about one event occupy separate cards;
3. non-Taiwan market stories enter the Taiwan Equity Theme Radar without a defensible Taiwan-equity connection.

The release is implemented as three sequential slices but published once after all slices pass a unified release gate:

```text
Slice A: balanced official evidence
    ↓
Slice B: deterministic event clustering
    ↓
Slice C: Taiwan relevance gate
    ↓
full verification → one push → updater full refresh → Pages verification
```

Each slice gets its own RED/GREEN evidence, independent commit, and scoped review. No slice is pushed independently.

## 2. Production evidence motivating v0.6

The v0.5 production refresh completed with all four sources healthy and all 12 MOPS datasets successful. The bounded evidence output exposed a material distribution defect:

```text
MOPS fetched records:       2,333
official records in window: 2,249
published evidence cap:       500
published dataset mix:        500 × t187ap45_L
```

The dashboard also showed ten events, including several articles about the same 長鑫科技 listing event and overseas market stories without an explicit Taiwan-equity mapping. All ten events were `unconfirmed`, partly because the evidence snapshot excluded every dataset except dividends.

These observations are acceptance evidence, not an invitation to expand scope.

## 3. Locked product rules

### 3.1 Overseas-event rule

Keep an overseas event when it maps to at least one Taiwan-listed symbol or a configured Taiwan supply-chain theme. Exclude it when it is only an overseas market/company story with no Taiwan mapping.

### 3.2 Cluster presentation rule

One real-world event renders as one representative card. Other reports are retained as source references inside that card.

### 3.3 Representative selection rule

Choose the representative deterministically in this order:

1. official source;
2. Taiwan professional financial media;
3. other trusted media;
4. content completeness;
5. publication recency;
6. canonical URL as the final stable tie-breaker.

### 3.4 Evidence allocation rule

Use event-value weighting:

- material information, penalties, disclosure violations, and trading-status events receive the highest priority;
- insider-transfer, forecast variance, control-right, and business-scope events receive high priority;
- shareholder meetings and dividends receive the lowest priority;
- unused reserved capacity returns to a shared weighted pool;
- total public evidence remains bounded at 500 by default.

### 3.5 Release rule

Implement the three slices separately, then publish them together. Do not push after Slice A or Slice B.

## 4. Non-goals

v0.6 does not include:

- new discovery providers;
- new MOPS datasets;
- changes to the 12-dataset v0.5 catalog;
- TPEx onboarding as a separate source;
- LLM-based clustering or relevance decisions;
- database storage or historical backfill;
- UI redesign or a new official-evidence page;
- broad taxonomy expansion;
- changes to selected threshold `0.3` or candidate threshold `0.5`;
- cleanup of inherited AI News Radar code unrelated to the Taiwan Theme Radar path.

## 5. Architecture

Keep the existing one-workflow, one-updater architecture:

```text
source registry
    ├─ RSS discovery adapters
    └─ TWSE OpenAPI official adapter
              ↓
source-neutral records
              ↓
┌─────────────────────────────────────────────┐
│ A. weighted evidence allocator              │
│ B. deterministic discovery-event clusterer │
│ C. Taiwan relevance classifier             │
└─────────────────────────────────────────────┘
              ↓
evidence matching and confirmation
              ↓
backward-compatible JSON outputs
```

Do not create a speculative plugin framework. Focused pure functions in the existing updater/adapter modules are sufficient.

## 6. Slice A — Balanced Official Evidence

### 6.1 Goal

Ensure a high-volume low-priority dataset cannot consume the complete evidence snapshot, while retaining deterministic ordering and a hard global limit.

### 6.2 Dataset tiers

```text
critical:
  t187ap04_L  material information
  t187ap22_L  FSC/SFB penalties
  t187ap23_L  disclosure/material-information violations
  t187ap26_L  trading suspension after control/business change
  t187ap27_L  altered-trading classification

high:
  t187ap12_L  insider transfer declaration
  t187ap13_L  declared but untransferred insider shares
  t187ap16_L  actual/forecast earnings variance
  t187ap24_L  control-right change
  t187ap25_L  major business-scope change

normal:
  t187ap38_L  shareholder meeting announcement
  t187ap45_L  dividend distribution
```

Weights and minimum reservations must be explicit, reviewable configuration or constants. They must not depend on source completion order.

### 6.3 Allocation algorithm

1. Filter by evidence window and deduplicate by `evidence_id`.
2. Group records by `dataset_id`.
3. Sort each group by event timestamp and `evidence_id`, newest first.
4. Allocate a minimum reservation to each non-empty configured dataset.
5. Return unused reservations to a shared pool.
6. Fill the shared pool using deterministic weighted round-robin across non-empty groups.
7. Stop at `max_items`.
8. Apply a final deterministic ordering for the published payload.

The algorithm must behave correctly when `max_items` is smaller than the sum of reservations. In that case, priority and stable dataset order determine which reservations survive.

### 6.4 Additive diagnostics

Add top-level diagnostics without changing existing required fields:

```json
{
  "datasets_represented": 8,
  "dataset_distribution": {
    "t187ap04_L": 4,
    "t187ap45_L": 60
  },
  "allocation_policy": "event_value_weighted_v1"
}
```

Do not place internal weights on every evidence item.

### 6.5 Slice A success criteria

- output remains `<= max_items`;
- no single normal-priority dataset monopolizes the snapshot when other datasets have eligible rows;
- all eligible non-empty critical datasets are represented when capacity permits;
- unused reservations are redistributed;
- output is identical across input permutations;
- legacy top-level and item fields remain present;
- matching tests demonstrate evidence from non-dividend datasets remains available.

## 7. Slice B — Deterministic Event Clustering

### 7.1 Goal

Collapse reports about one real-world event into one representative card while preserving source coverage and avoiding false merges.

### 7.2 Cluster compatibility gates

Two records can cluster only when all mandatory gates pass:

1. their primary matched theme is compatible;
2. their publication times fall within the configured cluster window;
3. they share at least one strong entity signal:
   - overlapping Taiwan symbol;
   - normalized company/entity name;
   - configured product/technology/policy entity;
4. normalized title token similarity crosses a deterministic threshold.

A theme keyword alone is insufficient.

### 7.3 Required non-merge boundaries

Do not merge:

- different companies merely sharing a theme;
- prediction versus realized result;
- IPO/listing event versus later price-performance coverage;
- earnings release versus analyst target-price commentary;
- separate events on different dates;
- broad market wrap versus company-specific corporate action.

### 7.4 Representative ranking

Each candidate receives a deterministic tuple, not an opaque model score:

```text
source authority
content completeness
published_at
canonical URL
```

Source authority is registry/config driven. MOPS or another official record cannot become a discovery card by itself; the v0.5 rule remains: official rows are evidence, not discovery content. The official-source ranking applies only if a future/allowed discovery record is explicitly marked official.

### 7.5 Cluster output

The representative keeps the existing event contract and receives additive fields:

```json
{
  "cluster_id": "cluster-...",
  "cluster_size": 4,
  "cluster_event_ids": ["..."],
  "cluster_sources": [
    {
      "source_id": "moneydj",
      "source": "MoneyDJ",
      "title": "...",
      "url": "...",
      "published_at": "..."
    }
  ]
}
```

`cluster_sources` includes the representative and alternates in deterministic authority order. Existing frontend source rendering should be reused or minimally extended; do not redesign cards.

### 7.6 Slice B success criteria

- repeated reports of the same event yield one card;
- the representative follows the locked source-priority rule;
- all alternate URLs remain reachable through the card source list;
- unrelated events with similar keywords remain separate;
- clustering is independent of fetch completion/input order;
- `theme-events.json` and `tracking-candidates.json` remain backward compatible;
- candidate threshold remains `0.5` and selected threshold remains `0.3`.

## 8. Slice C — Taiwan Relevance Gate

### 8.1 Goal

Keep Taiwan company events and overseas supply-chain events with a defensible Taiwan mapping; remove unsupported overseas market noise.

### 8.2 Relevance states

```text
direct       → direct Taiwan company/symbol reference
supply_chain → overseas event mapped through a configured theme to Taiwan symbols
excluded     → no defensible Taiwan-equity mapping
```

### 8.3 Deterministic decision order

1. `direct` when the record names/maps a symbol in `config/symbol_aliases.tw.json`.
2. `direct` when a valid Taiwan `related_symbols` entry already exists.
3. `supply_chain` when the record matches a configured theme whose `seed_symbols` resolve to Taiwan symbols.
4. `excluded` otherwise.

A generic theme match must not automatically map every article to every seed symbol. Supply-chain retention requires a strong named entity/product/technology signal from that theme, not only broad words such as `科技`, `AI`, or `記憶體` in isolation.

### 8.4 Output contract

Retained events receive additive fields:

```json
{
  "tw_relevance_status": "direct",
  "tw_relevance_reason": "explicit symbol alias: 台積電",
  "tw_related_symbols": ["TWSE:2330"]
}
```

Excluded records do not enter `theme-events.json` or `tracking-candidates.json`. Source health and fetched raw counts remain unchanged.

### 8.5 Slice C success criteria

- direct Taiwan-company stories remain;
- overseas CPO/AI-server/memory/etc. stories remain only when a Taiwan supply-chain mapping is explicit and testable;
- pure Hong Kong, China A-share, Korean-market, overseas IPO, target-price, and generic market-wrap stories without Taiwan mapping are excluded;
- relevance decisions are deterministic and explainable;
- exclusions do not alter source-health accounting;
- existing thresholds remain unchanged.

## 9. Data-flow order

The locked processing order is:

```text
fetch discovery records
→ exact record dedupe
→ theme enrichment
→ Taiwan relevance gate
→ deterministic event clustering
→ max event/candidate bounding
→ balanced official-evidence allocation
→ official evidence matching
→ JSON output
```

Reasons:

- relevance must run before clustering so irrelevant overseas records cannot become representatives;
- clustering must run before event bounding so duplicates do not consume the event cap;
- evidence allocation must finish before matching so every match is made against the exact public bounded evidence contract;
- official records remain outside discovery projection.

## 10. Configuration decisions

Prefer two focused additive config blocks rather than new files unless implementation evidence shows otherwise:

- evidence allocation policy belongs in `config/mops_datasets.tw.json` because it is dataset-specific;
- source authority belongs in `config/source_registry.tw.json` because it is source-specific;
- Taiwan symbol/entity mapping continues to use `config/symbol_aliases.tw.json` and `config/theme_taxonomy.tw.json`.

Do not duplicate symbol aliases inside source or MOPS config.

## 11. Error handling and fail-closed behavior

- Unknown evidence dataset IDs receive no privileged allocation and fall into a lowest-priority deterministic fallback bucket.
- Invalid allocation configuration fails catalog validation before network fetching.
- Missing source authority uses the lowest authority tier, never the highest.
- Missing/invalid timestamps prevent clustering with another event.
- Missing Taiwan mapping produces `excluded`, not an inferred Taiwan relationship.
- A failed official source still produces `unavailable`, not `unconfirmed`.
- One source/dataset failure remains isolated as in v0.5.

## 12. Testing strategy

Strict TDD applies to each slice.

### Slice A RED/GREEN coverage

- high-volume dividend rows cannot monopolize output;
- minimum reservation and shared remainder work;
- critical/high/normal priority order works under small caps;
- output is deterministic across shuffled inputs;
- diagnostics exactly match selected items;
- legacy evidence contract remains compatible.

### Slice B RED/GREEN coverage

- duplicate 長鑫-style listing reports collapse to one representative;
- authority ranking selects the expected representative;
- alternate sources are retained;
- different company/event/phase records do not merge;
- clustering is deterministic across input permutations;
- existing MoneyDJ/Cnyes/Yahoo behavior remains green.

### Slice C RED/GREEN coverage

- direct Taiwan company event is retained;
- overseas CPO event with Taiwan supply-chain mapping is retained;
- pure A-share listing and price-performance stories without Taiwan mapping are excluded;
- generic overseas market wrap is excluded;
- source status/raw counts remain unchanged;
- selected `0.3` and candidate `0.5` thresholds remain unchanged.

### Final release verification

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py tests/test_mops_adapter.py
.venv/bin/python -m pytest -q
.venv/bin/python -m py_compile scripts/update_theme_radar.py scripts/source_adapters.py
node --check assets/app.js
git diff --check
```

Run a production-like full-refresh dry-run in a temporary directory and report:

- per-source and per-dataset health;
- evidence distribution and datasets represented;
- event count before/after clustering;
- excluded Taiwan-relevance count and reason distribution;
- theme and source distribution;
- confirmation-state distribution;
- candidate count;
- contract compatibility.

## 13. Commit and release structure

Create three implementation commits locally:

```text
feat: balance official evidence allocation
feat: cluster duplicate theme events
feat: gate events by taiwan relevance
```

Do not push between them. After final review and all gates pass, push once, manually dispatch one full refresh, wait for the snapshot commit and Pages deployment, then inspect the live dashboard and JSON contracts.

## 14. Residual risks

- The current symbol-alias catalog is intentionally small; valid Taiwan supply-chain events can be excluded until aliases are explicitly expanded.
- Deterministic title/entity clustering cannot capture every paraphrase without increasing false-merge risk. Precision is preferred over recall.
- A 72-hour evidence window may still contain large shareholder/dividend volumes; balanced allocation solves representation, not source volume.
- `confirmed` rates depend on discovery articles naming the Taiwan company/event clearly enough for deterministic corroboration.
- The inherited pre-push hook runs system Python and may fail from missing dependencies. The repository `.venv` full suite is the authoritative verification environment; bypass is allowed only after classifying the hook failure as environment-only.

## 15. Definition of done

v0.6 is complete only when:

- all three slices are implemented in order with preserved RED/GREEN evidence;
- each slice has an independent local commit;
- full suite and static gates pass after the final slice;
- final independent review returns `APPROVED`;
- one production full-refresh Action succeeds;
- Pages deployment succeeds;
- live evidence is distributed across relevant datasets rather than one dataset;
- duplicate events render as one card with alternate sources;
- unsupported overseas-market stories are absent;
- overseas events with explicit Taiwan supply-chain mappings remain;
- source health remains accurate;
- existing contracts, frontend, workflow count, updater command, and thresholds remain compatible;
- GitNexus session/status/diff/commit/handoff gates are complete.
