# Nexus Theme Radar v0.6 Implementation Plan

> **For Hermes:** Execute through ECC `/ecc:orch-change-feature` because v0.5 behavior exists and v0.6 intentionally changes its allocation, projection, and presentation behavior. Use Codex as implementation lane, independent reviewer after each slice, and Anthony ECC Overlay gates throughout.

**Goal:** Balance official evidence, cluster duplicate discovery reports into one representative event, and exclude unsupported overseas-market noise while preserving Taiwan supply-chain events.

**Architecture:** Extend the existing deterministic producer pipeline with three pure processing stages. Dataset allocation remains in `scripts/source_adapters.py`; Taiwan relevance and event clustering remain in `scripts/update_theme_radar.py`. Existing JSON contracts stay compatible through additive fields only.

**Tech Stack:** Python 3.11, pytest, JSON configuration, existing vanilla JavaScript frontend, GitHub Actions and GitHub Pages.

---

## Strict TDD and evidence discipline

Every behavioral change follows RED → GREEN → REFACTOR. Run the failing test before production edits, preserve the exact failure under `/tmp/nexus-theme-radar-v06/`, and do not use a test written after implementation as RED evidence. Each slice must finish with focused GREEN, full-suite verification, independent review, and its scoped local commit.

## Preconditions

1. Work from `/Users/anthony/Desktop/dev/nexus-theme-radar`.
2. Confirm `master` is clean and aligned with `origin/master`.
3. Read:
   - `AGENTS.md`
   - `docs/plans/2026-07-27-nexus-theme-radar-v0.6-design.md`
   - `docs/prompts/NEXUS_THEME_RADAR_V0.6_EXECUTOR_PROMPT.md`
   - `scripts/source_adapters.py`
   - `scripts/update_theme_radar.py`
   - `tests/test_mops_adapter.py`
   - `tests/test_update_theme_radar.py`
4. Start the overlay session:

```bash
/Users/anthony/Documents/Agentic/bin/gitnexus session start \
  --task nexus-theme-radar-v0.6 \
  --title "Improve evidence balance, event clustering, and Taiwan relevance"
```

5. Capture baseline evidence:

```bash
git status --short --branch
git rev-parse HEAD
.venv/bin/python -m pytest -q
```

Expected baseline: clean worktree and full suite green.

---

## Slice A — Balanced Official Evidence

### Task A1: Add allocation policy to MOPS catalog

**Objective:** Make dataset priority, weight, and minimum reservation explicit and reviewable.

**Files:**
- Modify: `config/mops_datasets.tw.json`
- Modify: `tests/test_mops_adapter.py`

**Step 1: Write failing catalog-policy tests**

Add tests asserting:

- every active dataset has `allocation_tier`, `allocation_weight`, and `minimum_reservation`;
- allowed tiers are `critical`, `high`, and `normal`;
- weight is a positive integer;
- reservation is a non-negative integer;
- `t187ap04_L`, `22`, `23`, `26`, `27` are critical;
- `t187ap38_L` and `45_L` are normal;
- duplicate/invalid allocation configuration fails validation.

**Step 2: Run RED**

```bash
.venv/bin/python -m pytest -q \
  tests/test_mops_adapter.py -k 'allocation_policy or catalog'
```

Expected: FAIL because allocation fields/validation do not exist.

Save output to the v0.6 RED evidence log.

**Step 3: Add minimal policy fields**

Update the 12 catalog records only. Do not add datasets.

Recommended initial policy:

```text
critical: weight 5, reservation 20
high:     weight 3, reservation 10
normal:   weight 1, reservation 5
```

The exact constants may be adjusted only if small-cap tests prove starvation. Keep them simple and documented.

**Step 4: Extend catalog validation**

Modify `validate_dataset_catalog` in `scripts/source_adapters.py` to reject missing/invalid allocation fields.

**Step 5: Run GREEN**

Run the focused command from Step 2. Expected: PASS.

### Task A2: Implement deterministic weighted allocation

**Objective:** Replace global newest-first truncation with minimum reservation plus weighted shared-pool allocation.

**Files:**
- Modify: `scripts/source_adapters.py`
- Modify: `tests/test_mops_adapter.py`

**Step 1: Write failing allocator tests**

Cover:

1. 1,000 dividend rows plus material/penalty/control rows produce a mixed bounded output.
2. Every eligible non-empty critical dataset receives its reservation when capacity allows.
3. Unused reservation returns to the shared pool.
4. A cap smaller than total reservation remains deterministic and follows tier/ID priority.
5. Input permutations produce byte-equivalent item ID order.
6. Unknown dataset IDs use lowest-priority fallback behavior.
7. `total_items_available` still reflects all eligible rows.

**Step 2: Run RED**

```bash
.venv/bin/python -m pytest -q \
  tests/test_mops_adapter.py -k 'balanced or allocation or reservation or weighted'
```

Expected: FAIL under existing `ordered[:max_items]` behavior.

**Step 3: Implement minimal pure helpers**

Suggested helpers in `scripts/source_adapters.py`:

```python
def allocate_evidence_records(records, policies, max_items): ...
def evidence_distribution(items): ...
```

Do not introduce classes or dependencies.

**Step 4: Wire allocator into `build_official_evidence_payload`**

The function must accept the catalog policy or a dataset-policy mapping. Preserve existing callers with an explicit default/fallback where necessary for compatibility tests.

**Step 5: Add diagnostics**

Return:

- `allocation_policy = "event_value_weighted_v1"`
- `datasets_represented`
- `dataset_distribution`

**Step 6: Run GREEN**

Run the tests from Step 2 and existing MOPS tests.

### Task A3: Prove matching sees non-dividend evidence

**Objective:** Prevent allocation from silently degrading confirmation matching.

**Files:**
- Modify: `tests/test_mops_adapter.py`
- Modify: `tests/test_update_theme_radar.py` if integration coverage belongs there

**Step 1: Write failing integration test**

Construct a source update with:

- >500 dividend rows;
- one material-information record matching a discovery event;
- one penalty/control record;
- a 500-item cap.

Assert:

- the material record remains in official evidence;
- the discovery event becomes `confirmed`;
- dividends do not occupy all 500 slots.

**Step 2: Run RED, then minimal repair**

If Task A2 already makes it pass, retain the test as integration proof. Otherwise fix only the allocation-to-matching wiring.

**Step 3: Verify Slice A**

```bash
.venv/bin/python -m pytest -q tests/test_mops_adapter.py tests/test_update_theme_radar.py
.venv/bin/python -m pytest -q
.venv/bin/python -m py_compile scripts/source_adapters.py scripts/update_theme_radar.py
git diff --check
```

**Step 4: Independent review**

Review only:

- `config/mops_datasets.tw.json`
- `scripts/source_adapters.py`
- direct Slice A tests

Valid verdict: `APPROVED` or `REQUEST_CHANGES` with `file:line` evidence.

**Step 5: Commit Slice A**

```bash
git add config/mops_datasets.tw.json scripts/source_adapters.py \
  tests/test_mops_adapter.py tests/test_update_theme_radar.py
git commit -m "feat: balance official evidence allocation"
```

Do not push.

---

## Slice B — Deterministic Event Clustering

### Task B1: Add source-authority configuration

**Objective:** Make representative selection reviewable and independent of hardcoded source names.

**Files:**
- Modify: `config/source_registry.tw.json`
- Modify: `tests/test_update_theme_radar.py`

**Step 1: Write failing registry tests**

Assert active discovery sources expose a valid `authority_tier` or numeric `authority_rank`. MOPS remains evidence-only and must not be projected as a discovery representative.

Recommended ranking:

```text
official discovery source: 0
Taiwan professional financial media: 10
other trusted media: 20
missing/unknown: 99
```

MoneyDJ and Cnyes should outrank generic/unknown sources. Yahoo Finance Taiwan may share the professional-media tier or be ranked immediately after them; document the choice.

**Step 2: Run RED**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py -k authority
```

**Step 3: Add minimal config and loader validation**

Keep existing source registry compatibility for older entries by assigning missing rank `99` at runtime.

### Task B2: Implement cluster compatibility and IDs

**Objective:** Deterministically decide which enriched discovery events represent the same real-world event.

**Files:**
- Modify: `scripts/update_theme_radar.py`
- Modify: `tests/test_update_theme_radar.py`

**Step 1: Write RED tests**

Fixtures should cover:

- multiple 長鑫上市 reports cluster together;
- 長鑫上市 and later price-performance article remain separate;
- two different PCB companies do not merge;
- same company earnings and analyst target-price commentary do not merge;
- same event input permutations produce the same `cluster_id` and member order;
- missing timestamp/entity prevents unsafe clustering.

**Step 2: Run RED**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py -k cluster
```

**Step 3: Add focused helpers**

Suggested helpers:

```python
def normalized_event_tokens(record): ...
def event_entities(record): ...
def events_are_cluster_compatible(left, right, *, window_hours): ...
def stable_cluster_id(records): ...
```

Avoid fuzzy/ML dependencies. Use deterministic token overlap with explicit stop words and minimum meaningful token length.

### Task B3: Implement representative ranking and cluster projection

**Objective:** Produce one representative card and retain alternate source references.

**Files:**
- Modify: `scripts/update_theme_radar.py`
- Modify: `tests/test_update_theme_radar.py`
- Modify: `assets/app.js` only if current source rendering cannot display `cluster_sources`
- Add/update frontend tests if the repo has an applicable test surface

**Step 1: Write RED tests**

Assert:

- professional Taiwan source wins over generic source;
- completeness wins within one authority tier;
- recency and URL resolve ties deterministically;
- `cluster_sources` retains all members and canonical URLs;
- `cluster_size` and `cluster_event_ids` are exact;
- candidates are based on representatives, not duplicate members.

**Step 2: Run RED**

Run clustering tests.

**Step 3: Implement minimal cluster projection**

Call clustering after theme enrichment and relevance gating, before output caps.

For Slice B before Slice C exists, use a pass-through relevance function or land B after introducing C's helper tests on the same branch. Do not reorder the final architecture.

**Step 4: Reuse frontend source list**

Map `cluster_sources` into the existing card source rendering. Do not redesign the card.

**Step 5: Verify Slice B**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py
.venv/bin/python -m pytest -q
node --check assets/app.js
git diff --check
```

**Step 6: Independent review**

Review only source-authority config, cluster helpers/projection, frontend hunk, and direct tests.

**Step 7: Commit Slice B**

```bash
git add config/source_registry.tw.json scripts/update_theme_radar.py \
  tests/test_update_theme_radar.py assets/app.js
git commit -m "feat: cluster duplicate theme events"
```

Only stage `assets/app.js` if actually changed. Do not push.

---

## Slice C — Taiwan Relevance Gate

### Task C1: Implement direct Taiwan mapping

**Objective:** Retain records explicitly naming or mapping a configured Taiwan symbol.

**Files:**
- Modify: `scripts/update_theme_radar.py`
- Modify: `tests/test_update_theme_radar.py`

**Step 1: Write RED tests**

Cover:

- 台積電 alias maps to `TWSE:2330` and `direct`;
- explicit `related_symbols` remains `direct`;
- TPEX aliases remain valid Taiwan-equity symbols;
- missing alias/symbol does not become direct.

**Step 2: Run RED**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py -k 'taiwan_relevance or direct_mapping'
```

**Step 3: Implement minimal resolver**

Load and reuse `config/symbol_aliases.tw.json`. Do not duplicate aliases.

### Task C2: Implement supply-chain retention

**Objective:** Retain overseas events with a strong configured Taiwan supply-chain mapping.

**Files:**
- Modify: `scripts/update_theme_radar.py`
- Modify: `tests/test_update_theme_radar.py`

**Step 1: Write RED tests**

Cover:

- Nvidia/Broadcom CPO production event with strong CPO terms maps to configured optical/CPO Taiwan symbols and is retained as `supply_chain`;
- an AI-server component event with strong product terms maps to AI-server seed symbols;
- broad `科技股` or generic `AI` article does not qualify;
- pure 長鑫 IPO/listing and price-record articles without a Taiwan mapping are excluded;
- pure Hong Kong/Korean market wraps are excluded.

**Step 2: Run RED**

Run relevance tests.

**Step 3: Implement strong-signal theme mapping**

Use matched theme data but require one of the theme's meaningful product/technology keywords after removing generic stop terms. Resolve only configured `seed_symbols` present in the symbol alias catalog.

### Task C3: Wire relevance before clustering and preserve accounting

**Objective:** Enforce final data-flow order without corrupting source-health metrics.

**Files:**
- Modify: `scripts/update_theme_radar.py`
- Modify: `tests/test_update_theme_radar.py`

**Step 1: Write RED integration test**

Input a mixed discovery batch containing:

- direct Taiwan event;
- overseas supply-chain event;
- unsupported overseas IPO;
- generic overseas market wrap;
- duplicate reports of one retained event.

Assert:

- raw/source counts include all fetched records;
- excluded records do not enter events/candidates;
- retained duplicates cluster into one card;
- output carries relevance diagnostics;
- selected/candidate thresholds remain exact.

**Step 2: Run RED**

Run focused integration test.

**Step 3: Wire final order**

```text
dedupe → enrich → relevance → cluster → bounds → evidence matching
```

Keep official records out of discovery projection.

**Step 4: Add summary diagnostics**

The updater's console summary may add:

- pre-cluster matched count;
- clustered event count;
- excluded event count;
- relevance-state distribution.

Do not break existing summary keys.

**Step 5: Verify Slice C**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py tests/test_mops_adapter.py
.venv/bin/python -m pytest -q
.venv/bin/python -m py_compile scripts/update_theme_radar.py scripts/source_adapters.py
node --check assets/app.js
git diff --check
```

**Step 6: Independent review**

Review relevance helpers, final processing order, direct tests, and any frontend hunk.

**Step 7: Commit Slice C**

```bash
git add scripts/update_theme_radar.py tests/test_update_theme_radar.py \
  assets/app.js

git commit -m "feat: gate events by taiwan relevance"
```

Stage `assets/app.js` only if changed. Do not push.

---

## Final Unified Release Gate

### Task R1: Verify three-commit structure and worktree

```bash
git log --oneline -5
git status --short
git diff HEAD~3..HEAD --check
```

Expected: three scoped v0.6 commits and no unrelated files.

### Task R2: Run all local gates

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py tests/test_mops_adapter.py
.venv/bin/python -m pytest -q
.venv/bin/python -m py_compile scripts/update_theme_radar.py scripts/source_adapters.py
node --check assets/app.js
git diff --check
```

Record exact pass counts.

### Task R3: Production-like full-refresh dry-run

```bash
OUT=$(mktemp -d /tmp/nexus-theme-radar-v06.XXXXXX)
.venv/bin/python scripts/update_theme_radar.py \
  --output-dir "$OUT" \
  --window-hours 72 \
  --max-events 500 \
  --max-candidates 200 \
  --full-refresh
```

Inspect all four JSON outputs. Produce machine-readable audit summaries for:

- evidence distribution;
- datasets represented;
- pre/post cluster count;
- cluster-size distribution;
- representative-source distribution;
- relevance status/reason distribution;
- excluded count;
- confirmation-state distribution;
- event/candidate counts;
- source/dataset health.

### Task R4: Final independent review

Use one bounded allowlist containing only files changed by the three slices. Valid output ends with:

```text
APPROVED
```

or:

```text
REQUEST_CHANGES
```

with `file:line` blockers. Resolve blockers and run one narrow re-review only.

### Task R5: GitNexus finalization

```bash
/Users/anthony/Documents/Agentic/bin/gitnexus status sync
/Users/anthony/Documents/Agentic/bin/gitnexus diff summary \
  --task nexus-theme-radar-v0.6
/Users/anthony/Documents/Agentic/bin/gitnexus commit sync --sha HEAD
/Users/anthony/Documents/Agentic/bin/gitnexus handoff create \
  --task nexus-theme-radar-v0.6
```

Read back the handoff and replace generic text with exact evidence if necessary.

### Task R6: Stop at release gate

Do not push or deploy unless Jarvis explicitly authorizes release after independent verification.

When authorized:

1. fetch/rebase against `origin/master`;
2. rerun full suite;
3. push once;
4. dispatch the existing `update-theme-radar.yml` with `full_refresh=true`;
5. wait for updater snapshot commit;
6. wait for Pages deployment;
7. inspect live dashboard, source-status, evidence distribution, cluster cards, and Taiwan relevance behavior.

---

## Required Executor Report

Return:

1. three slice completion statuses and commit SHAs;
2. exact allocation policy and evidence distribution;
3. clustering rules, representative ranking, and cluster statistics;
4. Taiwan relevance rules and exclusion statistics;
5. RED evidence commands and failures per slice;
6. GREEN focused/full/static results;
7. dry-run source and dataset health;
8. confirmation-state distribution;
9. independent review verdicts;
10. changed files;
11. residual risks;
12. GitNexus handoff path;
13. explicit statement that no push/deploy occurred.
