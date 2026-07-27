# Nexus Theme Radar v0.6 Executor Prompt

Implement **Nexus Theme Radar v0.6: balanced official evidence, deterministic event clustering, and Taiwan relevance gating**.

You are an internal implementation department. Anthony communicates only with Jarvis. Do not ask Anthony to perform verification that can be executed or inspected by the executor and Jarvis.

## Repository and baseline

```text
Repository: https://github.com/a898954139/nexus-theme-radar
Local repo: /Users/anthony/Desktop/dev/nexus-theme-radar
Branch: master
Production baseline: 538f81ffadb30b606bfe81696b0791ea5b74ad41
v0.5 feature commit: ee00774d1fef2f99443c0894d39692d3e779a2ef
Live site: https://a898954139.github.io/nexus-theme-radar/
```

Read before editing:

```text
AGENTS.md
docs/plans/2026-07-27-nexus-theme-radar-v0.6-design.md
docs/plans/2026-07-27-nexus-theme-radar-v0.6-implementation-plan.md
config/source_registry.tw.json
config/mops_datasets.tw.json
config/theme_taxonomy.tw.json
config/symbol_aliases.tw.json
scripts/source_adapters.py
scripts/update_theme_radar.py
tests/test_mops_adapter.py
tests/test_update_theme_radar.py
assets/app.js
.github/workflows/update-theme-radar.yml
```

The v0.6 design is authoritative for product behavior. The implementation plan is authoritative for task order, TDD gates, verification and commit structure.

## Mandatory workflow

Use the installed ECC behavior-change workflow:

```text
/ecc:orch-change-feature
```

If Codex exec mode cannot invoke the slash command directly, follow the installed ECC `orch-change-feature` stages explicitly through the shared `orch-pipeline`. Do not replace ECC with a generic parallel workflow.

The approved design and implementation plan satisfy ECC Gate 1. ECC Gate 2 is not pre-approved beyond creating the three required local implementation commits. Do not push or deploy.

Apply Anthony ECC Overlay from the target repository:

```bash
cd /Users/anthony/Desktop/dev/nexus-theme-radar

/Users/anthony/Documents/Agentic/bin/gitnexus session start \
  --task nexus-theme-radar-v0.6 \
  --title "Improve evidence balance, event clustering, and Taiwan relevance"
```

After meaningful changes:

```bash
/Users/anthony/Documents/Agentic/bin/gitnexus status sync
```

Before final handoff:

```bash
/Users/anthony/Documents/Agentic/bin/gitnexus diff summary \
  --task nexus-theme-radar-v0.6
```

After each local commit:

```bash
/Users/anthony/Documents/Agentic/bin/gitnexus commit sync --sha HEAD
/Users/anthony/Documents/Agentic/bin/gitnexus status sync
```

Do not push or deploy until Jarvis independently verifies and authorizes release.

## Current production defects

The v0.5 production full refresh proved:

```text
sources healthy:              4/4
MOPS datasets healthy:       12/12
MOPS fetched records:         2,333
official records in window:   2,249
published evidence:             500
published evidence dataset:   t187ap45_L only
theme events:                    10
tracking candidates:              0
confirmation:          10 unconfirmed
```

The dashboard also showed repeated reports of one 長鑫科技 listing event and overseas market stories without an explicit Taiwan-equity mapping.

v0.6 fixes those defects without adding sources or datasets.

## Locked scope

Implement three sequential slices:

```text
Slice A: balanced official evidence
Slice B: deterministic event clustering
Slice C: Taiwan relevance gate
```

Create one local commit per slice. Do not push between slices. Final release is unified.

## Slice A — Balanced official evidence

Replace global newest-first truncation with deterministic event-value weighted allocation.

Dataset tiers:

```text
critical:
  t187ap04_L
  t187ap22_L
  t187ap23_L
  t187ap26_L
  t187ap27_L

high:
  t187ap12_L
  t187ap13_L
  t187ap16_L
  t187ap24_L
  t187ap25_L

normal:
  t187ap38_L
  t187ap45_L
```

Required behavior:

1. filter by window and deduplicate;
2. group by dataset;
3. sort deterministically;
4. allocate minimum reservations;
5. return unused reservation to a shared pool;
6. fill the shared pool using deterministic weighted round-robin;
7. enforce the global cap;
8. output deterministic final order.

Recommended initial policy:

```text
critical: weight 5, reservation 20
high:     weight 3, reservation 10
normal:   weight 1, reservation 5
```

Store policy explicitly in `config/mops_datasets.tw.json` unless direct test evidence proves a simpler reviewable location is better.

Add additive top-level evidence diagnostics:

```text
allocation_policy
datasets_represented
dataset_distribution
```

Do not change the 12-dataset catalog or evidence item contract.

Slice A commit:

```text
feat: balance official evidence allocation
```

## Slice B — Deterministic event clustering

One real-world event must render as one representative card. Alternate reports remain available in the card source list.

Cluster only when mandatory deterministic gates pass:

1. compatible primary theme;
2. compatible event-time window;
3. shared strong entity signal: symbol, company/entity, product, technology or policy;
4. title token similarity above an explicit threshold.

A theme keyword alone is insufficient.

Do not merge:

- different companies sharing a theme;
- prediction and realized result;
- listing/IPO event and later price-performance coverage;
- earnings and analyst target-price commentary;
- separate dates/events;
- broad market wrap and company action.

Representative selection order is locked:

1. official discovery source;
2. Taiwan professional financial media;
3. other trusted media;
4. content completeness;
5. publication recency;
6. canonical URL tie-breaker.

MOPS rows remain evidence-only and may not become discovery cards.

Add source authority to `config/source_registry.tw.json`. Missing authority must default to the lowest rank.

Add additive event fields:

```text
cluster_id
cluster_size
cluster_event_ids
cluster_sources
```

Reuse the existing frontend source rendering. Do not redesign cards.

Slice B commit:

```text
feat: cluster duplicate theme events
```

## Slice C — Taiwan relevance gate

Keep an overseas event when it maps to a Taiwan-listed symbol or a configured Taiwan supply-chain theme. Exclude unsupported overseas market/company stories.

States:

```text
direct
supply_chain
excluded
```

Decision order:

1. direct symbol/company alias from `config/symbol_aliases.tw.json`;
2. valid existing Taiwan `related_symbols` mapping;
3. strong configured theme/product signal mapping to Taiwan `seed_symbols`;
4. excluded otherwise.

Do not infer supply-chain relevance from generic terms such as `科技`, `AI`, or `記憶體` alone.

Required examples:

```text
retain direct:
  Taiwan company event naming 台積電, 廣達, 欣興, etc.

retain supply_chain:
  Nvidia/Broadcom CPO production event with strong CPO/optical signal
  and configured Taiwan optical/CPO seed symbols

exclude:
  pure China A-share listing or market-cap record
  pure Hong Kong or Korean market wrap
  overseas target-price article without Taiwan mapping
  generic technology investment commentary
```

Retained events receive additive fields:

```text
tw_relevance_status
tw_relevance_reason
tw_related_symbols
```

Excluded records do not enter `theme-events.json` or `tracking-candidates.json`. Source health and raw fetched counts remain unchanged.

Slice C commit:

```text
feat: gate events by taiwan relevance
```

## Locked processing order

```text
fetch discovery records
→ exact dedupe
→ theme enrichment
→ Taiwan relevance gate
→ deterministic clustering
→ event/candidate bounding
→ balanced official-evidence allocation
→ official evidence matching
→ JSON output
```

Official records remain outside discovery projection.

## Backward compatibility

Preserve:

```text
data/theme-events.json
data/tracking-candidates.json
data/source-status.json
data/official-evidence.json
existing frontend
one GitHub Actions workflow
one updater command
selected threshold 0.3
candidate threshold 0.5
```

All new JSON fields must be additive.

## Explicit non-goals

Do not include:

- new providers or datasets;
- TPEx as a separate source;
- LLM clustering/relevance;
- database or historical backfill;
- UI redesign;
- broad taxonomy expansion;
- unrelated AI News Radar cleanup;
- threshold changes.

## Strict TDD

No production change before a failing test for that behavior.

For every slice:

1. write focused tests;
2. run and preserve RED output;
3. implement the minimum code;
4. run focused GREEN;
5. run full suite;
6. run a fresh independent bounded review;
7. create the scoped local commit;
8. do not push.

Save RED/GREEN evidence under:

```text
/tmp/nexus-theme-radar-v06/
```

At minimum preserve:

```text
slice-a-red.txt
slice-a-green.txt
slice-b-red.txt
slice-b-green.txt
slice-c-red.txt
slice-c-green.txt
full-suite.txt
dry-run-summary.json
executor-report.md
```

## Required tests

### Slice A

- dividend rows cannot monopolize output;
- critical/high/normal allocation works;
- reservations and shared remainder work;
- small-cap behavior is deterministic;
- shuffled inputs produce identical output;
- diagnostics match selected records;
- non-dividend evidence remains matchable.

### Slice B

- duplicate 長鑫-style listing reports collapse;
- source authority chooses the representative;
- alternate reports remain in `cluster_sources`;
- different company/event/phase records do not merge;
- shuffled inputs produce identical clusters;
- candidates operate on representatives.

### Slice C

- direct Taiwan events remain;
- overseas supply-chain events with explicit Taiwan mapping remain;
- unsupported A-share/HK/Korean/IPO/target-price/market-wrap stories are excluded;
- generic theme terms alone do not qualify;
- raw source counts remain unchanged;
- selected/candidate thresholds remain exact.

## Verification gates

After each slice, run focused tests and the full suite. Before final handoff run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_update_theme_radar.py tests/test_mops_adapter.py

.venv/bin/python -m pytest -q

.venv/bin/python -m py_compile \
  scripts/update_theme_radar.py scripts/source_adapters.py

node --check assets/app.js
git diff --check
```

Run a production-like full refresh into a temporary directory:

```bash
OUT=$(mktemp -d /tmp/nexus-theme-radar-v06.XXXXXX)
.venv/bin/python scripts/update_theme_radar.py \
  --output-dir "$OUT" \
  --window-hours 72 \
  --max-events 500 \
  --max-candidates 200 \
  --full-refresh
```

Inspect and report:

- source health;
- per-dataset health;
- evidence distribution and represented datasets;
- event counts before and after clustering;
- cluster-size and representative-source distribution;
- Taiwan relevance state/reason distribution;
- excluded count;
- confirmation-state distribution;
- event/candidate counts;
- JSON compatibility.

## Independent review

Run a fresh read-only review after each slice and one final bounded review after all three commits.

A valid verdict ends only with:

```text
APPROVED
```

or:

```text
REQUEST_CHANGES
```

with actionable `file:line` evidence.

Do not accept process narration, generic suggestions, max-turn exit or silence as approval.

## Commit and release restrictions

Create exactly three local implementation commits:

```text
feat: balance official evidence allocation
feat: cluster duplicate theme events
feat: gate events by taiwan relevance
```

Do not push, dispatch Actions or deploy Pages. Jarvis owns final release after independent verification.

Git identity must remain:

```text
a898954139 <69338830+a898954139@users.noreply.github.com>
```

The pre-push hook may invoke system Python without dependencies. This is irrelevant until release, but do not classify or bypass any hook failure without first proving the `.venv` full suite passes.

## Required final executor report

Return:

1. overall completion status;
2. Slice A/B/C commit SHAs;
3. exact evidence allocation policy and distribution;
4. clustering rules and cluster statistics;
5. representative-source ranking;
6. Taiwan relevance rules and exclusion statistics;
7. RED/GREEN evidence per slice;
8. focused/full/static results;
9. dry-run source/dataset health;
10. confirmation-state distribution;
11. independent review verdicts;
12. changed files;
13. residual risks;
14. GitNexus handoff path;
15. explicit statement that no push/deploy occurred.

Do not claim completion from executor self-report alone. Jarvis will inspect commits, files, tests, generated payloads and handoff evidence independently.
