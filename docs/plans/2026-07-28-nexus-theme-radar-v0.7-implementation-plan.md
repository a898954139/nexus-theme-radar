# Nexus Theme Radar v0.7 Implementation Plan

> **Planning only. Do not execute this plan without new explicit authorization.**

**Goal:** Add a deterministic structured-theme matcher, qualify a bounded taxonomy delta with reproducible evidence, and onboard TechNews plus DIGITIMES public RSS while preserving v0.6 relevance, clustering, thresholds, and JSON compatibility.

**Architecture:** Extend the existing matcher in `scripts/theme_relevance.py`, keep orchestration and generic RSS normalization in `scripts/update_theme_radar.py`, use `scripts/source_adapters.py` for the existing bounded-response primitive, and keep source/taxonomy changes registry-driven.

## 1. Preconditions and global gates

Before implementation:

1. Obtain explicit implementation authorization.
2. Re-run:

   ```bash
   git status --short --branch
   git fetch origin
   git rev-list --left-right --count origin/master...master
   git rev-parse HEAD
   ```

3. Do not reset, clean, or overwrite pre-existing untracked research/handoff files.
4. Reconcile the six snapshot-only remote commits through an authorized branch-history decision.
5. Capture fresh endpoint evidence and frozen fixtures described in the design.
6. Run the baseline:

   ```bash
   .venv/bin/python -m pytest -q
   .venv/bin/python -m py_compile scripts/source_adapters.py scripts/theme_relevance.py scripts/update_theme_radar.py
   ```

Every task below follows RED → minimum GREEN → full verification → independent review → scoped local commit. Do not push between slices. Commit messages are intended messages, not authorization to commit.

Global post-task verification:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m py_compile scripts/source_adapters.py scripts/theme_relevance.py scripts/update_theme_radar.py scripts/benchmark_theme_taxonomy.py
git diff --check
```

Independent review must return `APPROVED` or `REQUEST_CHANGES` with `file:line` evidence and must be performed by a reviewer separate from the implementation pass.

## 2. Slice A — Matcher, compatibility, benchmark, diagnostics

### Task A1 — Validate dual taxonomy schemas

**Files**

- Modify: `scripts/theme_relevance.py`
- Add: `tests/test_theme_relevance.py`

**Failing test:** Add loader tests proving legacy themes accept `keywords`, structured themes require non-empty `required_any` plus list-valued `optional`/`excluded`, mixed schemas fail, duplicate IDs fail, and the current ten-theme file loads unchanged.

**RED**

```bash
.venv/bin/python -m pytest -q tests/test_theme_relevance.py -k 'schema or legacy'
```

Expected failure: the current loader requires `keywords` for every theme and does not reject mixed schemas.

**Minimum implementation:** In `load_theme_taxonomy` within `scripts/theme_relevance.py`, validate exactly one of the two schemas. Preserve existing `related_industries`, `seed_symbols`, ID, and list validation. Add no migration and no new dependency.

**GREEN**

```bash
.venv/bin/python -m pytest -q tests/test_theme_relevance.py -k 'schema or legacy'
```

**Full/static:** Run the global verification commands.

**Independent review:** Review loader compatibility, invalid-shape failures, and unchanged current taxonomy loading.

**Intended commit:** `feat: validate hybrid theme schemas`

### Task A2 — Implement structured matcher semantics

**Files**

- Modify: `scripts/theme_relevance.py`
- Modify: `tests/test_theme_relevance.py`

**Failing test:** Add tests for:

- `optional` alone returns no match;
- any `required_any` phrase enables a match;
- `excluded` vetoes required and optional matches;
- required and optional phrases use existing field weights;
- publisher/source fields do not affect score;
- shuffled phrase and record inputs produce identical results, signals, and reasons.

**RED**

```bash
.venv/bin/python -m pytest -q tests/test_theme_relevance.py -k 'structured or optional or excluded or deterministic'
```

Expected failure: `_score_theme` only understands `keywords`.

**Minimum implementation:** Split `_score_theme` into small legacy and structured paths using the existing `_contains_keyword`, field weights, denominator, rounding, match ordering, and immutable return style. Evaluate `excluded`, then `required_any`, then `optional`.

**GREEN**

```bash
.venv/bin/python -m pytest -q tests/test_theme_relevance.py -k 'structured or optional or excluded or deterministic'
```

**Full/static:** Run the global verification commands.

**Independent review:** Verify precedence, no source-derived score input, deterministic ordering, and no legacy-path edits beyond dispatch.

**Intended commit:** `feat: add deterministic structured theme matching`

### Task A3 — Lock legacy behavior and thresholds

**Files**

- Modify: `tests/test_theme_relevance.py`
- Modify: `tests/test_update_theme_radar.py`
- Add: `tests/fixtures/theme_benchmark/v0.7/legacy-regression.json`

**Failing test:** Freeze representative records for all ten themes and noise/overlap cases. Assert exact `matched_themes`, primary theme, scores, signals, reasons, symbol enrichment, decision, selected threshold `0.3`, and candidate threshold `0.5` before and after hybrid dispatch.

**RED**

```bash
.venv/bin/python -m pytest -q tests/test_theme_relevance.py tests/test_update_theme_radar.py -k 'legacy_regression or thresholds_unchanged'
```

Expected failure: the regression fixture and equivalence assertions do not exist.

**Minimum implementation:** No production change is expected. If the test reveals drift, repair only schema dispatch so legacy themes execute the original algorithm.

**GREEN**

```bash
.venv/bin/python -m pytest -q tests/test_theme_relevance.py tests/test_update_theme_radar.py -k 'legacy_regression or thresholds_unchanged'
```

**Full/static:** Run the global verification commands.

**Independent review:** Compare the legacy path against the pre-v0.7 implementation and inspect fixture provenance.

**Intended commit:** `test: lock legacy matcher compatibility`

### Task A4 — Add provenance-safe benchmark harness

**Files**

- Add: `scripts/benchmark_theme_taxonomy.py`
- Add: `tests/test_theme_benchmark.py`
- Add: `tests/fixtures/theme_benchmark/v0.7/manifest.json`
- Add: `tests/fixtures/theme_benchmark/v0.7/real-records.json`
- Add: `tests/fixtures/theme_benchmark/v0.7/synthetic-cases.json`

**Failing test:** Add tests that reject missing hashes/provenance, prevent synthetic records entering measured denominators, deduplicate real records by event cluster, compute per-theme confusion matrices, enforce each qualification gate independently, return `insufficient_evidence` below sample minima, and produce byte-stable output under shuffled input.

**RED**

```bash
.venv/bin/python -m pytest -q tests/test_theme_benchmark.py
```

Expected failure: the benchmark module and fixtures do not exist.

**Minimum implementation:** Build a pure, offline JSON harness that imports the production matcher, validates manifest/fixture hashes, separates real and synthetic lanes, and emits deterministic per-theme results. It must not fetch the network or edit taxonomy.

**GREEN**

```bash
.venv/bin/python -m pytest -q tests/test_theme_benchmark.py
.venv/bin/python scripts/benchmark_theme_taxonomy.py --manifest tests/fixtures/theme_benchmark/v0.7/manifest.json
```

**Full/static:** Run the global verification commands.

**Independent review:** Audit provenance, denominators, held-out separation, deduplication, qualification arithmetic, and deterministic serialization.

**Intended commit:** `test: add provenance-gated taxonomy benchmark`

### Task A5 — Add matcher diagnostics without changing JSON contracts

**Files**

- Modify: `scripts/update_theme_radar.py`
- Modify: `tests/test_update_theme_radar.py`

**Failing test:** Assert `theme-events.json` and `tracking-candidates.json` retain every existing top-level/item field and add only:

```text
matcher_contract
taxonomy_version
legacy_theme_count
structured_theme_count
theme_match_distribution
theme_veto_distribution
```

Also assert maps are key-sorted, counts are permutation-invariant, and thresholds remain unchanged.

**RED**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py -k 'matcher_diagnostics or additive_json'
```

Expected failure: the new diagnostic fields do not exist.

**Minimum implementation:** Accumulate matcher diagnostics during `build_theme_payloads` without removing or changing existing fields. Do not add frontend requirements.

**GREEN**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py -k 'matcher_diagnostics or additive_json'
```

**Full/static:** Run the global verification commands.

**Independent review:** Diff serialized payload keys/types against v0.6 fixtures and verify diagnostics do not affect selection.

**Intended commit:** `feat: expose additive matcher diagnostics`

### Slice A acceptance gate

- All structured semantics tests pass.
- The ten legacy themes are regression-equivalent.
- Synthetic/real provenance separation is enforced.
- Benchmark qualification is per theme and deterministic.
- Existing JSON fields and thresholds are unchanged.
- No source or candidate theme is active.

## 3. Slice B — Benchmark-qualified taxonomy delta

### Task B1 — Capture and adjudicate real benchmark evidence

**Files**

- Modify: `tests/fixtures/theme_benchmark/v0.7/manifest.json`
- Modify: `tests/fixtures/theme_benchmark/v0.7/real-records.json`
- Modify: `tests/fixtures/theme_benchmark/v0.7/synthetic-cases.json`
- Modify: `tests/test_theme_benchmark.py`

**Failing test:** Add a completeness test requiring every admitted real record to have a direct captured-fixture hash, canonical URL, timestamps, source, adjudication, and split assignment; require boundary examples for all four candidates.

**RED**

```bash
.venv/bin/python -m pytest -q tests/test_theme_benchmark.py -k 'fixture_completeness or candidate_boundaries'
```

Expected failure: independently reproduced real records are absent or incomplete.

**Minimum implementation:** Capture only public RSS metadata from approved/current endpoints, freeze hashes, manually adjudicate, and add synthetic boundary cases separately. Do not use Gemini sample URLs as captured evidence.

**GREEN**

```bash
.venv/bin/python -m pytest -q tests/test_theme_benchmark.py -k 'fixture_completeness or candidate_boundaries'
```

**Full/static:** Run the global verification commands.

**Independent review:** Trace every real record to its manifest hash and inspect labels for leakage or duplicate inflation.

**Intended commit:** `test: freeze v0.7 taxonomy benchmark evidence`

### Task B2 — Add only qualified themes

**Files**

- Modify: `config/theme_taxonomy.tw.json`
- Modify: `tests/test_theme_relevance.py`
- Modify: `tests/test_theme_benchmark.py`

**Failing test:** For each candidate independently, assert configuration membership equals the harness `qualified` result; enforce CoWoS ownership and all documented positive/negative boundaries. Assert deferred IDs are absent.

**RED**

```bash
.venv/bin/python -m pytest -q tests/test_theme_relevance.py tests/test_theme_benchmark.py -k 'qualified_taxonomy or boundary or deferred'
```

Expected failure: qualified candidates are not configured; unqualified candidates must continue to fail closed.

**Minimum implementation:** Add structured entries only for candidates reported `qualified`. Copy no report-only claims. Keep all ten legacy entries unchanged. Do not force four additions.

**GREEN**

```bash
.venv/bin/python -m pytest -q tests/test_theme_relevance.py tests/test_theme_benchmark.py -k 'qualified_taxonomy or boundary or deferred'
```

**Full/static:** Run the global verification commands and the benchmark command from A4.

**Independent review:** Compare every new phrase, exclusion, industry, and seed symbol to qualified benchmark evidence; reject unsupported configuration.

**Intended commit:** `feat: add benchmark-qualified taxonomy themes`

### Task B3 — Prove relevance and clustering compatibility

**Files**

- Modify: `tests/test_update_theme_radar.py`

**Failing test:** Add integration cases proving:

- direct and configured supply-chain Taiwan relevance decisions are unchanged;
- unsupported overseas records remain excluded;
- matching occurs before relevance;
- relevance occurs before clustering;
- cross-source duplicates still cluster identically;
- different themes/companies/phases remain separate;
- thresholds remain `0.3`/`0.5`.

**RED**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py -k 'v07_relevance or v07_cross_source or thresholds_unchanged'
```

Expected failure: v0.7 integration fixtures do not exist.

**Minimum implementation:** No production change is expected. Repair only accidental matcher integration regressions; do not redesign relevance or clustering.

**GREEN**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py -k 'v07_relevance or v07_cross_source or thresholds_unchanged'
```

**Full/static:** Run the global verification commands.

**Independent review:** Confirm the production diff contains no relevance/clustering algorithm changes.

**Intended commit:** `test: prove v0.7 pipeline compatibility`

### Slice B acceptance gate

- Each candidate is qualified, rejected, or insufficient independently.
- Only qualified IDs are configured.
- CoWoS remains owned by `cowos_supply_chain`.
- Deferred IDs are absent.
- Relevance, clustering, thresholds, and legacy themes are unchanged.

## 4. Slice C — TechNews RSS onboarding

### Task C1 — Freeze TechNews endpoint contract

**Files**

- Add: `tests/fixtures/technews_rss.xml`
- Add: `tests/fixtures/technews_rss.manifest.json`
- Modify: `tests/test_update_theme_radar.py`

**Failing test:** Parse the fixture and assert exact title/description, UTC timestamp, canonical URL, attribution, source ID, extraction method, stable ID, and absence of article-body-derived content.

**RED**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py -k technews
```

Expected failure: the fixture and contract test do not exist.

**Minimum implementation:** Capture a fresh public feed response and manifest. Reuse `normalize_feed_entry`; make only source-neutral timestamp/canonical URL repairs exposed by the fixture.

**GREEN**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py -k technews
```

**Full/static:** Run the global verification commands.

**Independent review:** Verify endpoint provenance, metadata-only capture, timezone conversion, canonical URL preservation, and no source-specific matcher behavior.

**Intended commit:** `test: freeze TechNews RSS contract`

### Task C2 — Activate TechNews with operational guards

**Files**

- Modify: `config/source_registry.tw.json`
- Modify: `tests/test_update_theme_radar.py`

**Failing test:** Assert TechNews is active through generic RSS, has HTTPS endpoint, timeout/byte-bound metadata, source attribution, and additive source-status diagnostics. Simulate timeout, invalid feed, and oversized response while other sources succeed.

**RED**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py -k 'technews and (registry or failure or oversized or status)'
```

Expected failure: TechNews is absent from the active registry.

**Minimum implementation:** Add one registry entry for `technews` using `https://technews.tw/feed/`, `fetch_method: rss`, and `content_mode: rss_metadata`. Reuse existing dispatch isolation and `read_bounded_response`.

**GREEN**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py -k technews
```

**Full/static:** Run the global verification commands.

**Independent review:** Check registry-only onboarding, response guard values, failure isolation, and attribution.

**Intended commit:** `feat: onboard TechNews public RSS`

### Task C3 — Prove TechNews duplicate compatibility

**Files**

- Modify: `tests/test_update_theme_radar.py`

**Failing test:** Use TechNews and one current-source record with different URLs but the same event; assert unchanged cluster compatibility, stable representative selection, both source references, canonical URLs, and shuffled-input determinism.

**RED**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py -k 'technews_cross_source_cluster'
```

Expected failure: the cross-source fixture does not exist.

**Minimum implementation:** No production change is expected. If required, repair only source-neutral normalization; do not loosen cluster gates.

**GREEN**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py -k 'technews_cross_source_cluster'
```

**Full/static:** Run the global verification commands.

**Independent review:** Confirm no authority or publisher identity enters theme score and no clustering threshold changes.

**Intended commit:** `test: prove TechNews clustering compatibility`

### Slice C acceptance gate

- Fresh endpoint and fixture evidence pass.
- TechNews uses generic RSS only.
- Timestamp, canonical URL, attribution, response bound, and failure isolation pass.
- Cross-source clustering remains compatible.
- Publisher identity does not affect theme score.

## 5. Slice D — DIGITIMES metadata-only RSS onboarding

### Task D1 — Freeze DIGITIMES metadata-only contract

**Files**

- Add: `tests/fixtures/digitimes_tw_rss.xml`
- Add: `tests/fixtures/digitimes_tw_rss.manifest.json`
- Modify: `tests/test_update_theme_radar.py`

**Failing test:** Parse the fixture and assert exact title, RSS description, UTC timestamp, canonical URL, attribution, and stable ID. Include an embedded content/body field in the fixture and assert it is ignored. Use a request spy asserting no article URL is requested.

**RED**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py -k 'digitimes and metadata_only'
```

Expected failure: the fixture, metadata-only rule, and no-article-request proof do not exist.

**Minimum implementation:** Capture a fresh public feed fixture. Keep `normalize_feed_entry` limited to RSS title/description/time/link; explicitly ignore full-content extensions. Do not add an article adapter.

**GREEN**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py -k 'digitimes and metadata_only'
```

**Full/static:** Run the global verification commands.

**Independent review:** Inspect the request spy and normalized fields; reject any article-body fetch or browser path.

**Intended commit:** `test: lock DIGITIMES metadata-only contract`

### Task D2 — Activate DIGITIMES with operational guards

**Files**

- Modify: `config/source_registry.tw.json`
- Modify: `tests/test_update_theme_radar.py`

**Failing test:** Assert `digitimes_tw` is active via generic RSS at the approved endpoint with `rss_metadata_only`, timeout/byte limits, attribution, additive status fields, and isolated timeout/parse/oversize failures.

**RED**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py -k 'digitimes and (registry or failure or oversized or status)'
```

Expected failure: DIGITIMES is absent from the active registry.

**Minimum implementation:** Add one registry entry for `digitimes_tw` using `https://www.digitimes.com.tw/rss/news.xml`. Reuse the generic RSS fetcher and existing guards.

**GREEN**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py -k digitimes
```

**Full/static:** Run the global verification commands.

**Independent review:** Confirm metadata-only registry intent, generic path reuse, and source isolation.

**Intended commit:** `feat: onboard DIGITIMES metadata-only RSS`

### Task D3 — Prove DIGITIMES pipeline compatibility

**Files**

- Modify: `tests/test_update_theme_radar.py`

**Failing test:** Add a DIGITIMES/current-source duplicate pair and assert:

- canonical URL normalization;
- unchanged Taiwan relevance result;
- unchanged cluster and representative selection;
- both source references retained;
- selected/candidate thresholds unchanged;
- additive JSON compatibility;
- shuffled-input determinism.

**RED**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py -k 'digitimes_pipeline_compatibility'
```

Expected failure: the end-to-end compatibility fixture does not exist.

**Minimum implementation:** No production change is expected. Fix only source-neutral normalization or wiring defects revealed by the test.

**GREEN**

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py -k 'digitimes_pipeline_compatibility'
```

**Full/static:** Run the global verification commands.

**Independent review:** Verify no relevance, clustering, threshold, or frontend behavior change.

**Intended commit:** `test: prove DIGITIMES pipeline compatibility`

### Slice D acceptance gate

- Fresh endpoint and fixture evidence pass.
- No login, cookie, browser, article request, or body extraction exists.
- Timestamp, canonical URL, attribution, response bound, and failure isolation pass.
- Cross-source clustering and Taiwan relevance remain compatible.

## 6. Unified release verification

Do not release a partial slice. After A–D pass:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m py_compile scripts/source_adapters.py scripts/theme_relevance.py scripts/update_theme_radar.py scripts/benchmark_theme_taxonomy.py
.venv/bin/python scripts/benchmark_theme_taxonomy.py --manifest tests/fixtures/theme_benchmark/v0.7/manifest.json
git diff --check
git status --short
```

Review the full diff for:

- no activation of CTEE, TrendForce, UDN, CNA, or Technice;
- no deferred taxonomy IDs;
- no article-body, browser, login, cookie, or paywall code;
- no threshold, relevance, clustering, MOPS dataset, workflow, or frontend redesign;
- no removed/renamed JSON fields;
- no secrets or private feeds;
- fixture provenance and hashes present;
- every configured new theme independently qualified;
- all tests green and independent review approved.

Only after those gates and separate release authorization may the normal owner decide whether to push, dispatch the updater, refresh production data, and deploy. Those actions are outside this plan’s current authorization.

## 7. Open evidence gates

The following are unresolved as of planning:

1. A fresh `git fetch origin` confirms local `master` remains six snapshot-only commits behind; the implementation baseline still requires an explicitly authorized branch-history decision.
2. TechNews and DIGITIMES endpoint claims have not been freshly reproduced into repository-controlled fixtures.
3. Feed content type, encoding, timestamp edge cases, canonical URL behavior, observed response size, terms, and attribution requirements remain unverified.
4. No adjudicated real-record benchmark exists.
5. None of the four taxonomy candidates is currently qualified.
6. Cross-source duplicate fixtures for the two new sources do not exist.
7. DIGITIMES metadata-only/no-article-request behavior is not yet proven.
8. Guard values have not been validated against observed feed sizes and latency.
9. Full regression/static/review evidence does not exist because implementation has not begun.
10. Explicit implementation and release authorization has not been given.
