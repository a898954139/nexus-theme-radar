# Nexus Theme Radar v0.5 Executor Prompt

Copy the prompt below into the implementation executor.

---

Implement and release **Nexus Theme Radar v0.5: registry-driven multi-adapter architecture plus MOPS official-evidence onboarding**.

You are an internal implementation department. Anthony communicates only with Jarvis. Do not ask Anthony to manually verify implementation details that can be tested or inspected by the executor and Jarvis.

## Repository and baseline

```text
Repository: https://github.com/a898954139/nexus-theme-radar
Local repo: /Users/anthony/Desktop/dev/nexus-theme-radar
Branch: master
Production baseline commit: a3cb5b625868a278d1fd4aa293aa6af0e6c6eb35
v0.4 feature commit: c8e3d8fec1a6f72223aa67fa8234318212b3410c
Live site: https://a898954139.github.io/nexus-theme-radar/
```

Read before editing:

```text
AGENTS.md
docs/handoffs/NEXUS_THEME_RADAR_V0.4_TO_V0.5_HANDOFF.md
config/source_registry.tw.json
scripts/update_theme_radar.py
tests/test_update_theme_radar.py
tests/test_v03_cleanup.py
.github/workflows/update-theme-radar.yml
docs/SOURCE_COVERAGE.md
```

The handoff is authoritative for v0.5 scope, architecture, contracts, exclusions and acceptance criteria.

## Mandatory workflow

Use the installed ECC feature workflow:

```text
/ecc:orch-add-feature
```

If Codex exec mode cannot invoke the slash command directly, follow the installed ECC add-feature stages explicitly. Do not replace ECC with a parallel generic workflow.

Apply Anthony ECC Overlay from the target repo:

```bash
cd /Users/anthony/Desktop/dev/nexus-theme-radar

/Users/anthony/Documents/Agentic/bin/gitnexus session start \
  --task nexus-theme-radar-v0.5 \
  --title "Add multi-adapter architecture and MOPS official evidence"
```

After meaningful changes:

```bash
/Users/anthony/Documents/Agentic/bin/gitnexus status sync
```

Before commit/handoff:

```bash
/Users/anthony/Documents/Agentic/bin/gitnexus diff summary \
  --task nexus-theme-radar-v0.5
```

Do not push until Jarvis independently verifies the work.

## Product decision

v0.5 must deliver both:

1. a registry-driven multi-adapter fetching architecture;
2. MOPS public disclosures as the first official confirmation/evidence source.

Anthony selected:

```text
MOPS scope: all available public-information categories
Publication: ingest/normalize all supported official records,
but only theme-relevant records may project into the public dashboard
```

Do not reduce v0.5 to significant announcements only.

## Architecture contract

Keep one GitHub Actions workflow and one updater command.

```text
GitHub Actions
  → scripts/update_theme_radar.py
  → source registry
  → explicit adapter dispatcher
      ├─ rss
      └─ twse_openapi
  → bounded concurrent source fetching
  → common source-result envelope
  → discovery pipeline + official evidence pipeline
  → deterministic evidence matching
  → bounded JSON outputs
  → commit data/ → GitHub Pages
```

Use a small explicit adapter map, not a speculative plugin framework.

Required behavior:

- bounded concurrency, normally 3–5 workers;
- per-source timeout 15–30 seconds;
- at most two retries for transient network failures;
- one source or dataset failure must not abort healthy sources;
- deterministic output ordering regardless of completion order;
- source status exposes source ID, adapter, endpoint/catalog, counts, duration and errors;
- no one GitHub job per source or per MOPS dataset.

## Official interface

Prefer the official TWSE OpenAPI catalog. Do not scrape interactive MOPS pages when official datasets are available.

```text
Swagger UI: https://openapi.twse.com.tw/
Swagger JSON: https://openapi.twse.com.tw/v1/swagger.json
Base URL: https://openapi.twse.com.tw/v1
```

Intake evidence on 2026-07-27:

```text
all paths: 143
/opendata paths: 94
t187 public-disclosure paths: 91
swagger SHA-256:
2c2cecccb7a220ac9e263228a7659aa49b1ada5aea397650e601ad3dfcc48043
```

Re-fetch and verify the catalog yourself. Record HTTP status, content type, catalog hash and endpoint counts. If the catalog changed, document the new hash and inspect the delta rather than copying assumptions from the handoff.

## MOPS dataset catalog

Create an explicit reviewable catalog, preferably:

```text
config/mops_datasets.tw.json
```

Cover all selected company public-disclosure categories available through the official interface, including applicable datasets for:

- significant announcements;
- company/basic master data;
- monthly revenue;
- financial statements and financial analysis;
- dividends and shareholder meetings;
- major shareholder, director/supervisor and insider holdings/changes;
- governance, penalties, disclosure violations and operational-control changes;
- public-company `P` / `X` dataset families;
- ESG company-disclosure datasets.

Explicitly exclude unrelated exchange data such as broker lists, warrants, quotes/order books and unrelated fund datasets.

Each catalog entry should include:

```text
dataset_id
path
category
status
refresh_class
public_projection
```

Do not invent payload field names. Probe real endpoints and map only observed fields.

## Refresh strategy

“All public information types” does not mean downloading every heavy dataset hourly.

Use deterministic catalog-driven cadence:

```text
hourly           → genuinely time-sensitive disclosures
daily            → company master, governance, holdings, ESG snapshots
monthly/quarter-aware → revenue and financial statements
```

Keep the existing single hourly workflow. The updater decides which datasets are due.

Do not add a database, external scheduler or historical backfill system in v0.5.

## Outputs

Preserve backward compatibility for:

```text
data/theme-events.json
data/tracking-candidates.json
data/source-status.json
```

Add:

```text
data/official-evidence.json
```

Official evidence records must retain:

```text
evidence_id
source_id
source_class
adapter
dataset_id
category
market_id
instrument_id / symbol when observed
company_name when observed
title / summary when derivable from real fields
published_at / effective_at when observed
canonical_url or stable official reference
raw_reference
fetched_at
```

Use null for unavailable fields. Never fabricate content.

Requirements:

- stable IDs based on real source identifiers;
- explicit ROC/Gregorian date normalization;
- deterministic sorting;
- bounded window and max item count;
- no raw full official dump published to Pages;
- all official records may enter the bounded evidence layer, but only theme-relevant records may enter public event/candidate lists.

## Confirmation layer

Establish deterministic discovery-to-official matching.

States:

```text
confirmed
unconfirmed
conflicting
not_required
unavailable
```

Matching order:

1. exact instrument/symbol;
2. compatible time window;
3. normalized company name/direct-symbol evidence;
4. category/title overlap only as supporting evidence.

Do not use an LLM as the release gate.

Additive event fields may include:

```json
{
  "confirmation_status": "confirmed",
  "official_evidence_ids": ["mops-..."],
  "official_evidence_count": 1
}
```

If the official adapter fails or is stale, status must be `unavailable`, not false `unconfirmed`.

## TDD: mandatory RED → GREEN

No production implementation before a failing test.

At minimum, capture RED and GREEN evidence for:

1. RSS and `twse_openapi` dispatch through different adapters;
2. adapter failure isolation;
3. deterministic ordering under bounded concurrency;
4. dataset catalog validation;
5. representative real MOPS fixture normalization across multiple categories;
6. ROC/Gregorian date handling;
7. bounded `official-evidence.json` output;
8. irrelevant official rows excluded from the public dashboard projection;
9. official evidence matching and confirmation states;
10. source failure producing `unavailable`;
11. existing MoneyDJ, Cnyes and Yahoo behavior;
12. unchanged thresholds: selected `0.3`, candidates `0.5`.

Fixtures must come from real official API responses. Minimize them and document:

```text
endpoint
capture date
payload SHA-256
```

Do not create idealized fixtures with invented fields.

## Scope discipline

Expected files:

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

Keep changes surgical. Prefer one focused adapter module. Do not build a large framework.

Explicitly out of scope:

```text
TWSE market-data onboarding as a separate product source
TPEx
TrendForce
Goodinfo
Jin10
database storage
historical backfill
UI redesign or separate official page
broad AI News Radar cleanup
unrelated taxonomy changes
threshold changes
browser scraping where OpenAPI is available
```

## Verification gates

Before reporting implementation complete, run and report:

```bash
# focused RED/GREEN commands with output
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py tests/test_mops_adapter.py

# full suite
.venv/bin/python -m pytest -q

# syntax/static checks
.venv/bin/python -m py_compile scripts/update_theme_radar.py scripts/source_adapters.py
node --check assets/app.js
git diff --check

# production-like dry run to a temporary directory
.venv/bin/python scripts/update_theme_radar.py \
  --output-dir <temp-dir> \
  --window-hours 72 \
  --max-events 500 \
  --max-candidates 200
```

Inspect and report:

- discovery source health;
- MOPS adapter health;
- per-dataset successes/failures;
- raw discovery count;
- official evidence count;
- theme event count;
- tracking candidate count;
- confirmation-state distribution;
- output schema compatibility;
- no changes to production `data/` before release unless explicitly preparing the verified generated snapshot.

Run an independent read-only review with a bounded file allowlist. A valid review verdict is only:

```text
APPROVED
```

or:

```text
REQUEST_CHANGES with file:line evidence
```

## Release ownership

Do not push or deploy autonomously unless Jarvis explicitly authorizes release after independent verification.

Git identity must be:

```text
a898954139 <69338830+a898954139@users.noreply.github.com>
```

The repo pre-push hook may use system Python without dependencies. Do not bypass it merely because it fails. First prove the complete `.venv` suite passes and classify whether the failure is a hook runtime mismatch or task regression.

## Required final executor report

Return:

1. completion status;
2. exact official endpoints/catalog hash;
3. dataset catalog coverage and exclusions;
4. fixture provenance and hashes;
5. architecture and files changed;
6. RED evidence;
7. GREEN and full-suite evidence;
8. dry-run summary and per-source/per-dataset health;
9. official evidence and confirmation-state counts;
10. independent review verdict;
11. residual risks and deferred sources;
12. GitNexus handoff path.

No success claim may rely on process status or self-report alone. Jarvis will independently inspect files, diff, tests, payloads, workflow and live Pages behavior.

---
