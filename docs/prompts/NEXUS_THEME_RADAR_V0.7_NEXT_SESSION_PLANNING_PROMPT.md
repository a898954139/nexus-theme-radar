# Nexus Theme Radar v0.7 — Next Session Planning Prompt

Continue Nexus Theme Radar v0.7 from the approved design state. **This session is planning-only. Do not implement.**

## Repository

```text
/Users/anthony/Desktop/dev/nexus-theme-radar
```

## Authorization

Anthony approved the v0.7 design direction but explicitly said:

```text
批准，但不要實作。
```

You may inspect and write planning documents only. You must not modify production code, tests, configuration, workflows, frontend assets or generated data. Do not create implementation commits, push, run deployment workflows or deploy Pages.

## Read first

```text
AGENTS.md
docs/handoffs/NEXUS_THEME_RADAR_V0.6_TO_V0.7_PLANNING_HANDOFF.md
docs/research/2026-07-27-nexus-theme-radar-v0.7-discovery-coverage-research-spec.md
docs/research/2026-07-27-nexus-theme-radar-v0.7-gemini-followup-report.md
config/theme_taxonomy.tw.json
config/source_registry.tw.json
scripts/source_adapters.py
scripts/update_theme_radar.py
tests/test_update_theme_radar.py
```

Also inspect these pre-existing untracked files without deleting, overwriting or automatically staging them:

```text
docs/prompts/NEXUS_THEME_RADAR_V0.7_GEMINI_DEEP_RESEARCH_PROMPT.md
docs/research/2026-07-27-nexus-theme-radar-v0.7-discovery-coverage-research-spec.md
docs/research/2026-07-27-nexus-theme-radar-v0.7-gemini-followup-report.md
docs/research/2026-07-27-nexus-theme-radar-v0.7-gemini-research-draft.md
```

## Start with repository verification

Run:

```bash
cd /Users/anthony/Desktop/dev/nexus-theme-radar
git status --short --branch
git fetch origin
git rev-list --left-right --count origin/master...master
git rev-parse HEAD
```

Expected handoff baseline:

```text
branch: master
local HEAD: 6fcadc534110510db757cf071600ce778998a71c
local master behind origin/master by 6 commits; local master has no local-only commits
```

If repository state differs, report the evidence and adjust the planning baseline without resetting or cleaning anything. The six remote-only commits observed at handoff were generated snapshot commits. Inspect them, but do not merge, rebase, pull, reset or otherwise mutate branch history in this planning-only session unless Anthony separately authorizes synchronization.

## Approved v0.7 design

The release solves two coupled constraints:

```text
insufficient discovery-source coverage
+
insufficient taxonomy coverage
```

Approved design:

```text
hybrid deterministic taxonomy matcher
+ benchmark-gated taxonomy delta
+ TechNews RSS
+ DIGITIMES RSS metadata only
+ unchanged Taiwan relevance and clustering
+ unified v0.7 release
```

### Matcher contract

Structured themes use:

```text
required_any
optional
excluded
```

Rules:

1. `excluded` vetoes the theme.
2. At least one `required_any` match is mandatory.
3. `optional` cannot trigger a match by itself.
4. Existing ten themes keep legacy `keywords` compatibility in v0.7.
5. All sources use one source-neutral matcher.
6. Preserve selected threshold `0.3` and candidate threshold `0.5`.

### Taxonomy benchmark candidates

```text
semicon_foundry_advanced
semicon_equipment
semicon_materials
ic_design_edge_ai
```

Only benchmark-qualified themes may ship. Do not force a target count.

Keep CoWoS in existing `cowos_supply_chain`. Do not fold CoWoS/FOPLP into `semicon_foundry_advanced`.

Defer:

```text
high_speed_interconnect
apple_supply_chain
auto_electronics_ev
space_leo_satellite
```

### Source scope

```text
TechNews: https://technews.tw/feed/
DIGITIMES: https://www.digitimes.com.tw/rss/news.xml
```

Constraints:

- public RSS only;
- no login, cookies, browser automation, paywall bypass or article-body scraping;
- DIGITIMES uses RSS metadata only;
- attribution and canonical URL are preserved;
- response-size/timeout guards and failure isolation are required in the eventual implementation;
- publisher identity must not increase theme score.

### Release slices

```text
Slice A — matcher + legacy compatibility + benchmark harness + diagnostics
Slice B — benchmark-qualified taxonomy delta
Slice C — TechNews onboarding
Slice D — DIGITIMES metadata-only onboarding
```

Each future slice must be independently reviewable and locally committed, but all slices release together. Do not execute any slice in this session.

## Research quality rule

Treat the Gemini follow-up report as an **untrusted research draft**, not verified evidence.

Do not carry forward its article URLs, timestamps, record counts, precision claims or `VALIDATED` labels unless independently reproduced from direct endpoint probes or repository-controlled fixtures.

Resolve these conflicts in favor of the approved design:

- approved sources are TechNews + DIGITIMES, not CTEE + TrendForce;
- approved schema is `required_any / optional / excluded`, not `phrases_must / phrases_any / phrases_exclude`;
- CoWoS stays in `cowos_supply_chain`;
- `high_speed_interconnect` is deferred;
- synthetic test cases must be labeled synthetic and may not count as measured benchmark evidence.

## Required planning work

Create or refine these planning artifacts:

```text
docs/plans/2026-07-28-nexus-theme-radar-v0.7-design.md
docs/plans/2026-07-28-nexus-theme-radar-v0.7-implementation-plan.md
```

Do not duplicate an existing authoritative v0.7 design if one is already present; update or reference it.

### Design document requirements

The design must include:

1. product goal and approved scope;
2. exact hybrid matcher semantics and precedence;
3. legacy compatibility behavior;
4. benchmark data model, fixture provenance and qualification gates;
5. taxonomy boundaries for all four candidates;
6. TechNews and DIGITIMES onboarding contracts;
7. diagnostics and additive JSON fields;
8. processing order;
9. four release slices;
10. locked non-goals and compatibility rules;
11. evidence gaps that must be closed before implementation/release.

### Implementation-plan requirements

Write a strict TDD plan with exact repository paths and small tasks. Each code-producing task must specify:

1. failing test to add;
2. exact RED command and expected failure;
3. minimum implementation location and behavior;
4. exact GREEN command;
5. full-suite/static verification;
6. independent review gate;
7. intended scoped local commit message.

Include explicit tests for:

- legacy theme behavior unchanged;
- `optional` cannot trigger alone;
- `excluded` veto precedence;
- structured matcher shuffled-input determinism;
- benchmark fixture provenance and synthetic/real separation;
- per-theme qualification gates;
- TechNews/DIGITIMES timestamp and canonical URL normalization;
- DIGITIMES metadata-only behavior;
- source failure isolation and response-size guards;
- cross-source duplicate clustering compatibility;
- Taiwan relevance behavior unchanged;
- selected/candidate thresholds unchanged;
- additive JSON compatibility.

## Locked non-goals

Do not plan or implement:

- CTEE, TrendForce, UDN, CNA or Technice activation;
- browser scraping, article-body extraction or paywall bypass;
- LLM classification;
- database or historical backfill;
- threshold changes;
- relevance/clustering redesign;
- UI redesign;
- new MOPS datasets;
- all-ten-theme schema migration;
- broad symbol-master expansion.

## Completion gate

Before finishing, verify:

```bash
git status --short
git diff --check -- docs/plans docs/handoffs docs/prompts docs/research
```

The final response must report:

1. planning status;
2. design and implementation-plan paths;
3. locked scope;
4. unresolved evidence gates;
5. changed documentation files;
6. explicit confirmation that no implementation, commit, push, Action dispatch or deployment occurred.

Stop after planning. Do not proceed into implementation even if the plan is complete.
