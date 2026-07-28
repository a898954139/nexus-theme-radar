# Nexus Theme Radar v0.6 → v0.7 Planning Handoff

## Status

**v0.6 is implemented, published, and live. v0.7 product design is approved, but implementation is explicitly not authorized.**

```text
Repository: /Users/anthony/Desktop/dev/nexus-theme-radar
Remote: https://github.com/a898954139/nexus-theme-radar.git
Branch: master
Local HEAD: 6fcadc534110510db757cf071600ce778998a71c
Remote divergence at handoff: local master is 6 commits behind origin/master; local master has no local-only commits
Live site: https://a898954139.github.io/nexus-theme-radar/
```

Current worktree contains four untracked v0.7 research artifacts. They predate this handoff and must not be deleted, overwritten, staged, or treated as verified production evidence without inspection:

```text
docs/prompts/NEXUS_THEME_RADAR_V0.7_GEMINI_DEEP_RESEARCH_PROMPT.md
docs/research/2026-07-27-nexus-theme-radar-v0.7-discovery-coverage-research-spec.md
docs/research/2026-07-27-nexus-theme-radar-v0.7-gemini-followup-report.md
docs/research/2026-07-27-nexus-theme-radar-v0.7-gemini-research-draft.md
```

## Authorization Boundary

Anthony approved the v0.7 design direction with the explicit instruction:

```text
批准，但不要實作。
```

Therefore the next session may:

- inspect repository state and existing planning/research documents;
- preserve and formalize the approved design;
- produce or refine the implementation plan;
- identify evidence gaps, contradictions and release gates;
- update planning-only documentation if needed.

The next session must not:

- modify production code, tests, configuration, workflows, frontend or generated data;
- activate new sources or taxonomy entries;
- create implementation commits;
- push, dispatch Actions, run a production full refresh or deploy Pages;
- silently reinterpret research claims as verified facts.

Implementation remains blocked until Anthony gives a new explicit execution instruction.

## v0.7 Approved Product Direction

v0.7 is a unified release addressing two coupled constraints:

```text
insufficient discovery-source coverage
+
insufficient taxonomy coverage
```

Approved architecture:

```text
hybrid deterministic taxonomy matcher
+ benchmark-gated taxonomy delta
+ TechNews public RSS
+ DIGITIMES public RSS metadata only
+ existing Taiwan relevance and clustering pipeline
+ one unified release after all slices pass
```

### Hybrid matcher

New structured themes use:

```text
required_any
optional
excluded
```

Rules:

1. `excluded` is checked first and vetoes that theme.
2. At least one `required_any` phrase is mandatory.
3. `optional` may strengthen evidence but may not trigger a match alone.
4. Existing thresholds remain unchanged.
5. Existing ten themes retain `keywords` backward compatibility in v0.7.
6. All sources use one source-neutral matcher; no source-specific taxonomy.

### Approved taxonomy candidates

Benchmark candidates:

```text
semicon_foundry_advanced
semicon_equipment
semicon_materials
ic_design_edge_ai
```

Only candidates that pass a reproducible frozen-record benchmark may remain in the release configuration. A target count is not a release gate.

Deferred from v0.7:

```text
high_speed_interconnect
apple_supply_chain
auto_electronics_ev
space_leo_satellite
```

Important boundary decisions:

- `CoWoS` remains owned by the existing `cowos_supply_chain` theme; do not absorb it into `semicon_foundry_advanced`.
- `semicon_foundry_advanced` covers advanced foundry nodes/capacity/pricing/fab expansion/backside power, not traditional OSAT or mature process.
- `semicon_equipment` excludes generic industrial, medical, PCB-drilling and solar equipment.
- `semicon_materials` excludes generic petrochemical, construction, display, PCB CCL and battery materials.
- `ic_design_edge_ai` requires explicit NPU/Edge AI/AI MCU/ASIC/IP/RISC-V accelerator evidence; generic chip or IC-design wording is insufficient.

### Source onboarding

Approved source scope:

```text
TechNews: https://technews.tw/feed/
DIGITIMES: https://www.digitimes.com.tw/rss/news.xml
```

Source constraints:

- public RSS only;
- no login, cookies, browser automation, paywall bypass or article-body scraping;
- DIGITIMES uses RSS title, description, timestamp and canonical URL only;
- response-size and timeout guards are required during eventual implementation;
- attribution and canonical URLs must be preserved;
- one source failure must not block other sources;
- publisher identity must not increase theme score.

## Approved Release Slices

Planning should preserve four independently reviewable local slices, released together:

```text
Slice A — structured matcher, legacy compatibility, benchmark harness and diagnostics
Slice B — benchmark-qualified taxonomy delta only
Slice C — TechNews RSS onboarding
Slice D — DIGITIMES RSS metadata-only onboarding
```

No push between slices. Eventual release ownership remains with Jarvis after independent verification.

## Locked Non-Goals

v0.7 does not include:

- CTEE, TrendForce, UDN, CNA or Technice activation;
- browser scraping or paywall bypass;
- LLM classification or release gates;
- database or historical backfill;
- threshold changes;
- Taiwan relevance or clustering rule changes;
- UI redesign;
- new MOPS datasets;
- migration of all ten legacy themes to the structured schema;
- all proposed taxonomy families;
- broad symbol-master expansion.

## Research Evidence Warning

The Gemini follow-up report contains useful candidate ideas but also contains material evidence-quality problems. The next session must not label its article samples, timestamps, URLs, precision claims or taxonomy candidates as verified merely because the report uses `VALIDATED` language.

Observed concerns include:

- many article URLs and future-dated sample records are not independently proven by repository evidence;
- several claimed metrics are explicitly `UNKNOWN` or retracted elsewhere in the same report;
- the report recommends CTEE and TrendForce, which conflicts with the subsequently approved TechNews + DIGITIMES scope;
- the report's `phrases_must / phrases_any / phrases_exclude` shape does not match the approved `required_any / optional / excluded` schema;
- the report merges CoWoS/FOPLP into foundry coverage, conflicting with the approved boundary that keeps CoWoS in `cowos_supply_chain`;
- it proposes `high_speed_interconnect` as active, while the approved design defers it.

Treat the research report as an untrusted research draft. Use it only to generate hypotheses and frozen benchmark candidates. Any claim promoted into the design or implementation plan must be reproduced from direct endpoint probes or repository-controlled fixtures.

## Locked Compatibility Requirements

Preserve:

```text
selected threshold: 0.3
candidate threshold: 0.5
Taiwan relevance gate behavior
clustering behavior
MOPS evidence catalog
existing top-level JSON contracts
existing frontend layout
one updater workflow
one updater command
```

All v0.7 output changes must be additive.

## Planning Success Criteria

The next planning session is complete only when:

1. the approved design is saved as a repository document;
2. the implementation plan uses exact repository file paths and strict RED → GREEN TDD tasks;
3. each slice has explicit acceptance tests, verification commands and intended local commit message;
4. benchmark fixtures distinguish real captured records from synthetic test cases;
5. source activation requires fresh direct endpoint verification;
6. contradictions from the Gemini report are explicitly excluded or resolved;
7. the final state remains planning-only with no implementation diff;
8. the user receives a concise summary of planning artifacts and unresolved evidence gates.

## Required Next-Session Startup

```bash
cd /Users/anthony/Desktop/dev/nexus-theme-radar

git status --short --branch
git fetch origin
git rev-list --left-right --count origin/master...master
git rev-parse HEAD
```

Then read:

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

Inspect the pre-existing untracked files before writing anything. Do not clean the worktree.

Because `origin/master` contains six newer generated snapshot commits, inspect those commits and choose a safe planning baseline before writing. Do not merge, rebase, pull, reset or otherwise mutate branch history during the planning-only session unless Anthony separately authorizes repository synchronization.

## Expected Planning Artifacts

Preferred paths:

```text
docs/plans/2026-07-28-nexus-theme-radar-v0.7-design.md
docs/plans/2026-07-28-nexus-theme-radar-v0.7-implementation-plan.md
```

If the approved design already exists under another path, update or reference it instead of duplicating it.

## Stop Condition

After design and implementation-plan artifacts are ready, stop and report:

- artifact paths;
- locked scope and non-goals;
- unresolved evidence gates;
- confirmation that no implementation, commit, push or deployment occurred.

Do not ask for implementation approval unless Anthony explicitly asks to proceed beyond planning.
