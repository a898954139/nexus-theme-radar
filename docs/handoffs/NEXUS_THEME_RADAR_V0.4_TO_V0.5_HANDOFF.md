# Nexus Theme Radar v0.4 → v0.5 Handoff

## Status

**v0.4 Cnyes slice is complete and deployed. v0.5 is approved for architecture upgrade plus MOPS public-disclosure onboarding.**

- Repository: <https://github.com/a898954139/nexus-theme-radar>
- Live site: <https://a898954139.github.io/nexus-theme-radar/>
- Default branch: `master`
- Current production snapshot commit: `a3cb5b625868a278d1fd4aa293aa6af0e6c6eb35`
- v0.4 feature commit: `c8e3d8fec1a6f72223aa67fa8234318212b3410c`
- Local repository: `/Users/anthony/Desktop/dev/nexus-theme-radar`
- Local state at handoff creation: clean, `master` tracking `origin/master`

## v0.4 Production Baseline

Active discovery sources:

| Source | Adapter | Last verified production count |
|---|---|---:|
| MoneyDJ | RSS | 20 |
| Cnyes / 鉅亨網 | RSS | 100 |
| Yahoo Finance Taiwan | RSS | 50 |

Last verified production state:

```text
source health: 3/3
theme events: 15
tracking candidates: 4
failed sources: 0
full UI mode: 15
selected UI mode: 10
```

Production evidence:

- v0.4 updater run: <https://github.com/a898954139/nexus-theme-radar/actions/runs/30249907722>
- v0.4 Pages deployment: <https://github.com/a898954139/nexus-theme-radar/actions/runs/30249923326>

Current output contracts:

```text
data/theme-events.json
data/tracking-candidates.json
data/source-status.json
```

Current thresholds must remain unchanged:

```text
frontend selected: theme_score >= 0.3 AND related_symbols is non-empty
producer candidates: theme_score >= 0.5 AND related_symbols is non-empty
```

## Product Decision for v0.5

v0.5 combines two changes in one controlled release:

1. upgrade the updater from RSS-only iteration to a registry-driven multi-adapter architecture;
2. onboard MOPS public disclosures as the first official-confirmation source.

Anthony explicitly selected:

```text
MOPS scope: all available public-information categories
publication rule: ingest and normalize all supported public disclosures,
but only theme-relevant records may project into the public dashboard
```

The product must distinguish:

```text
discovery sources    → MoneyDJ, Cnyes, Yahoo Finance Taiwan
official evidence    → MOPS / TWSE public-disclosure datasets
```

Official data is not merely another news feed. It is an evidence and confirmation layer.

## Required v0.5 Architecture

Keep one GitHub Actions workflow and one production command. Do not create one workflow per source.

```text
GitHub Actions: Nexus/Taiwan Theme Radar
                    ↓
         scripts/update_theme_radar.py
                    ↓
       load active source registry entries
                    ↓
 registry-driven adapter dispatcher + bounded concurrency
        ├─ rss adapter
        └─ twse_openapi / mops adapter
                    ↓
       normalize to source-neutral records
                    ↓
       failure-isolated source result envelope
                    ↓
    ┌───────────────┴────────────────┐
    │                                │
discovery/event pipeline      official evidence pipeline
    │                                │
    └──────── evidence matching ─────┘
                    ↓
      theme classification + symbol mapping
                    ↓
       only theme-relevant records reach UI
```

### Adapter dispatcher

Replace the RSS-specific selection/loop with a generic dispatcher keyed by registry configuration.

Conceptual contract:

```python
FETCHERS = {
    "rss": fetch_rss_source,
    "twse_openapi": fetch_twse_openapi_source,
}
```

Do not over-engineer a plugin framework. A small explicit mapping is sufficient for v0.5.

### Bounded concurrency

One GitHub Actions job should launch active source fetches with bounded concurrency:

```text
max workers: 3–5
per-source timeout: 15–30 seconds
retry: at most 2 attempts for transient network errors
```

Requirements:

- one source failure must not abort the remaining sources;
- results must be deterministic after sorting/normalization;
- source status must expose adapter, endpoint or dataset identifier, item count, elapsed time, and error;
- do not create unbounded threads or one job per MOPS endpoint.

### Source result envelope

Each adapter should return the same outer shape:

```json
{
  "records": [],
  "status": {
    "source_id": "mops",
    "adapter": "twse_openapi",
    "status": "ok",
    "items": 0,
    "datasets_ok": 0,
    "datasets_failed": 0,
    "error": null,
    "elapsed_ms": 0
  }
}
```

Exact Python types may differ, but the behavior must be tested.

## MOPS Source Strategy

### Preferred public interface

Use the official TWSE OpenAPI catalog rather than scraping the interactive MOPS website.

Verified catalog:

```text
Swagger UI: https://openapi.twse.com.tw/
Swagger JSON: https://openapi.twse.com.tw/v1/swagger.json
Base URL: https://openapi.twse.com.tw/v1
```

Research evidence captured on 2026-07-27:

```text
all API paths: 143
/opendata paths: 94
t187 public-disclosure paths: 91
swagger SHA-256:
2c2cecccb7a220ac9e263228a7659aa49b1ada5aea397650e601ad3dfcc48043
```

The interactive MOPS pages may return a security block to direct scripted requests. Do not build v0.5 around browser scraping when official OpenAPI datasets are available.

### Scope interpretation: “all public information types”

Do not hardcode only `t187ap04_L` significant announcements.

Implement a versioned dataset catalog covering all selected MOPS/TWSE public-disclosure OpenAPI datasets relevant to company disclosure, including available families such as:

- daily significant announcements;
- company master/basic information;
- monthly revenue;
- financial statements and financial-analysis datasets;
- dividends and shareholder meetings;
- director, supervisor, major shareholder and insider holdings/changes;
- governance, penalties, disclosure violations and operational-control changes;
- public-company datasets exposed through `t187..._P` / `t187..._X` families;
- ESG disclosure datasets when the endpoint is public and stable.

Exclude unrelated exchange services from the MOPS adapter, for example:

- broker lists;
- warrant trading datasets;
- market quote/order-book datasets;
- ETF/fund datasets unrelated to company disclosure;
- generic exchange announcements not representing company public information.

The dataset catalog must be explicit and reviewable. Do not select endpoints solely because their path starts with `/opendata/`.

### Dataset catalog contract

Recommended file:

```text
config/mops_datasets.tw.json
```

Recommended shape:

```json
{
  "version": "v0.5",
  "catalog_url": "https://openapi.twse.com.tw/v1/swagger.json",
  "datasets": [
    {
      "dataset_id": "t187ap04_L",
      "path": "/opendata/t187ap04_L",
      "category": "material_information",
      "status": "active",
      "refresh_class": "hourly",
      "public_projection": "theme_relevant_only"
    }
  ]
}
```

The executor must inspect real payload fields before finalizing mappings. Do not invent field names from endpoint titles.

### Refresh classes

“All public information types” does not mean all 91 datasets must be downloaded every hour.

The same GitHub Actions workflow should run one updater, but the updater may apply deterministic refresh classes:

```text
hourly  → significant announcements and other genuinely time-sensitive disclosures
daily   → company master, governance, insider/shareholder and ESG snapshots
monthly/quarter-aware → revenue and financial statement datasets
```

Store refresh cadence in the dataset catalog. On each run, fetch datasets due for that cadence. Manual `workflow_dispatch` should support a full-refresh option if this can be added without breaking the existing command; otherwise defer full-refresh CLI design and document the limitation.

Do not add a database or persistent scheduler in v0.5. Git history and generated snapshot metadata are sufficient for this static MVP.

## Normalized Official Evidence Contract

Create a separate bounded output for normalized official records:

```text
data/official-evidence.json
```

Recommended top-level shape:

```json
{
  "generated_at": "...",
  "market_id": "TW_EQUITY",
  "window_hours": 72,
  "total_items": 0,
  "total_items_available": 0,
  "items": []
}
```

Recommended item shape:

```json
{
  "evidence_id": "mops-...",
  "source_id": "mops",
  "source_class": "official_disclosure",
  "adapter": "twse_openapi",
  "dataset_id": "t187ap04_L",
  "category": "material_information",
  "market_id": "TW_EQUITY",
  "instrument_id": "TWSE:2330",
  "symbol": "2330",
  "company_name": "...",
  "title": "...",
  "summary": "...",
  "published_at": "...",
  "effective_at": "...",
  "canonical_url": "...",
  "raw_reference": "...",
  "fetched_at": "..."
}
```

Rules:

- fields unavailable in a dataset may be `null`; do not fabricate values;
- keep dataset provenance for every record;
- use stable IDs based on source + dataset + natural source identifiers;
- normalize ROC dates and mixed date formats explicitly and test boundaries;
- sort deterministically;
- bound public output size and time window;
- do not publish raw full datasets or unrestricted historical dumps to Pages.

## Discovery-to-Official Evidence Matching

v0.5 should establish a minimal deterministic confirmation layer.

Recommended confirmation states:

```text
confirmed    → matching official evidence exists
unconfirmed  → no matching evidence found in the current official window
conflicting  → official evidence materially contradicts the discovery record
not_required → discovery event type does not require MOPS confirmation
unavailable  → official source failed or was stale
```

Minimum viable matching order:

1. exact `instrument_id` / symbol match;
2. compatible event time window;
3. normalized company name or direct-symbol evidence;
4. category/title keyword overlap as supporting evidence only.

Do not use an LLM as the release gate for confirmation. Deterministic code decides whether evidence is attached.

Recommended additions to projected theme events:

```json
{
  "confirmation_status": "confirmed",
  "official_evidence_ids": ["mops-..."],
  "official_evidence_count": 1
}
```

Backward compatibility requirement:

- existing frontend must continue working when these fields are absent or newly present;
- existing `theme-events.json`, `tracking-candidates.json`, and `source-status.json` top-level contracts must remain compatible;
- `official-evidence.json` is additive.

## Public Projection Rule

All supported official disclosure records may be fetched and normalized, but only theme-relevant records may enter the public event/candidate lists.

```text
all supported official records
          ↓
data/official-evidence.json (bounded verification layer)
          ↓
taxonomy + symbol relevance gates
          ↓
only relevant records/projected evidence appear in theme-events/candidates
```

Do not dump all financial reports, governance records, ESG rows, shareholder records or MOPS data into the primary dashboard.

## Registry Changes

Update `config/source_registry.tw.json` so MOPS becomes active only after at least one real official OpenAPI dataset fetch succeeds.

Recommended direction:

```json
{
  "source_id": "mops",
  "source_class": "official_disclosure",
  "fetch_method": "twse_openapi",
  "status": "active",
  "catalog_path": "config/mops_datasets.tw.json",
  "base_url": "https://openapi.twse.com.tw/v1"
}
```

Do not activate TWSE or TPEx as separate sources in v0.5. TWSE OpenAPI is the transport used for MOPS public-disclosure datasets; dedicated TWSE/TPEx market-data onboarding remains a later product slice.

## GitHub Actions

Keep the existing workflow:

```text
.github/workflows/update-theme-radar.yml
```

Keep hourly scheduling at minute 17 unless implementation evidence shows a platform constraint.

The production command should remain one updater invocation. It may add backward-compatible arguments, but should not require multiple workflow jobs to build one coherent snapshot.

Ensure `git add data/` includes the new `data/official-evidence.json` output. Preserve the current failure-isolation behavior and Pages deployment model.

## TDD Requirements

No production implementation before a failing test.

Required RED → GREEN coverage:

1. registry dispatches RSS and `twse_openapi` through different adapters;
2. one adapter failure does not abort other adapters;
3. bounded concurrency does not change deterministic output ordering;
4. dataset catalog validates duplicate IDs, invalid paths, unsupported cadence and inactive datasets;
5. real frozen MOPS fixtures normalize representative categories;
6. ROC/Gregorian date handling is correct;
7. official evidence output is bounded and backward-compatible;
8. irrelevant official rows do not enter the public theme list;
9. matching attaches official evidence and correct confirmation state;
10. official-source failure produces `unavailable`, not false `unconfirmed`;
11. current MoneyDJ, Cnyes and Yahoo behavior remains green;
12. selected `0.3` and candidate `0.5` thresholds remain unchanged.

Fixtures should be captured from real official responses, minimized, and documented with endpoint, capture date and payload hash. Do not create idealized fixtures whose fields were invented by the implementer.

## Suggested Files

Expected scope; executor may adjust only with evidence:

```text
Modify:
  config/source_registry.tw.json
  scripts/update_theme_radar.py
  tests/test_update_theme_radar.py
  .github/workflows/update-theme-radar.yml
  docs/SOURCE_COVERAGE.md

Create:
  config/mops_datasets.tw.json
  scripts/source_adapters.py or scripts/theme_radar_sources.py
  tests/fixtures/mops/*.json
  tests/test_mops_adapter.py
  data/official-evidence.json
```

Prefer one focused adapter module. Do not split every source into its own package in v0.5 unless tests prove the current file is unmaintainable.

## Explicit Non-Goals

Do not include in v0.5:

- dedicated TWSE market-data source onboarding;
- TPEx source onboarding;
- TrendForce;
- Goodinfo;
- Jin10;
- database storage;
- full historical archive or backfill;
- UI redesign or a separate official-announcement page;
- broad inherited AI News Radar cleanup;
- changes to theme taxonomy unrelated to MOPS evidence;
- changes to selected/candidate thresholds;
- browser scraping when official OpenAPI data is available.

## Acceptance Criteria

v0.5 is complete only when:

- one GitHub Actions workflow drives one updater command;
- updater supports registry-driven RSS and MOPS/TWSE OpenAPI adapters;
- active sources can fetch with bounded concurrency and per-source failure isolation;
- the explicit MOPS dataset catalog covers all approved public-disclosure categories available through the selected official interface;
- cadence prevents all heavy datasets from being pulled hourly without reason;
- real MOPS fixtures normalize into a source-neutral official-evidence contract;
- `data/official-evidence.json` is generated and bounded;
- theme-irrelevant official records do not flood the dashboard;
- discovery events can attach deterministic official evidence and confirmation status;
- MoneyDJ, Cnyes and Yahoo remain healthy;
- existing JSON contracts and frontend behavior remain compatible;
- focused tests and full suite pass;
- manual GitHub Actions run succeeds;
- generated production status reports healthy discovery and official sources, or accurately exposes partial official dataset failures;
- Pages deployment succeeds;
- live UI shows no legacy AI content and no MOPS data flood;
- Jarvis independently verifies diff, tests, generated payloads, Actions and live behavior before success is declared.

## Implementation Constraints

1. Follow Anthony's ECC + Overlay workflow.
2. Jarvis remains coordinator/verifier; Codex is default implementation lane, Claude is review/fallback.
3. Use `/ecc:orch-add-feature` because this is a multi-file feature with new behavior.
4. Apply strict TDD and preserve RED/GREEN evidence.
5. Keep changes surgical; no broad cleanup.
6. Do not commit secrets, cookies, browser sessions or paid data.
7. Do not push until Jarvis independently verifies local gates.
8. Git identity:

```text
a898954139 <69338830+a898954139@users.noreply.github.com>
```

9. Run Anthony ECC Overlay commands from the target repository:

```bash
/Users/anthony/Documents/Agentic/bin/gitnexus session start \
  --task nexus-theme-radar-v0.5 \
  --title "Add multi-adapter architecture and MOPS official evidence"

/Users/anthony/Documents/Agentic/bin/gitnexus status sync
/Users/anthony/Documents/Agentic/bin/gitnexus diff summary --task nexus-theme-radar-v0.5
```

10. The repository pre-push hook currently invokes system Python and may fail from missing dependencies even when `.venv` tests pass. Classify this as a hook runtime mismatch only after the full `.venv` suite passes; never bypass a task regression.

## Resume Commands

```bash
cd /Users/anthony/Desktop/dev/nexus-theme-radar

git status --short --branch
git branch --show-current
git remote -v
git log --oneline -5

/Users/anthony/Documents/Agentic/bin/gitnexus session start \
  --task nexus-theme-radar-v0.5 \
  --title "Add multi-adapter architecture and MOPS official evidence"
```

Then inspect:

```text
AGENTS.md
config/source_registry.tw.json
scripts/update_theme_radar.py
tests/test_update_theme_radar.py
tests/test_v03_cleanup.py
.github/workflows/update-theme-radar.yml
docs/SOURCE_COVERAGE.md
docs/handoffs/NEXUS_THEME_RADAR_V0.4_TO_V0.5_HANDOFF.md
```

## Definition of Done for the Next Executor

The next executor must report:

- exact official catalog and dataset endpoints used;
- dataset catalog coverage and excluded endpoint classes;
- real fixture provenance and hashes;
- architecture files changed;
- RED and GREEN test evidence;
- per-adapter and per-dataset source health;
- output counts for discovery, official evidence, theme events and candidates;
- confirmation-state distribution;
- full-suite result;
- independent review verdict;
- GitHub Actions and Pages evidence if released;
- residual risks and deferred sources.

No success claim may rely only on executor output. Jarvis must independently verify all release evidence.
