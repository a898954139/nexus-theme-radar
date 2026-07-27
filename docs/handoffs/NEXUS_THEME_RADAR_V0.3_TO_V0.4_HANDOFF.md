# Nexus Theme Radar v0.3 → v0.4 Handoff

## Status

**v0.3 complete and deployed.**

- Repository: <https://github.com/a898954139/nexus-theme-radar>
- Live site: <https://a898954139.github.io/nexus-theme-radar/>
- Default branch: `master`
- Current release commit: `7fbbb3f22a0746e1ea4d13c62913408f6be2fe6d`
- Local repository: `/Users/anthony/Desktop/dev/nexus-theme-radar`
- Local state at handoff: clean, `master` tracking `origin/master`

## Product Positioning

- Product: **Taiwan Equity Theme Radar**
- Architecture: **Cross-Market Intelligence Engine**
- Taiwan equities are the current market implementation, not a permanent core constraint.
- Core terminology should remain market-neutral:
  - `market_id`
  - `instrument`
  - `theme_key`
  - `event`
  - `signal`
  - `source`
  - `adapter`

Avoid introducing core assumptions named around `stock`, `Taiwan only`, AI News Radar categories, or a single-market pipeline.

## v0.3 Delivered

### Live source pipeline

Current active RSS sources:

| Source | Status | Last verified item count |
|---|---:|---:|
| MoneyDJ | Active | 20 |
| Yahoo Finance Taiwan | Active | 50 |

Last verified pipeline result:

```text
raw_items: 70
theme_events: 3
tracking_candidates: 0
failed_sources: 0
source health: 2/2
```

Generated files:

```text
data/theme-events.json
data/tracking-candidates.json
data/source-status.json
```

Primary updater:

```text
scripts/update_theme_radar.py
```

Production command:

```bash
python scripts/update_theme_radar.py \
  --output-dir data \
  --window-hours 72 \
  --max-events 500 \
  --max-candidates 200
```

### UI taxonomy

The primary UI tabs are:

```text
全部
AI 基建
半導體
散熱
PCB / ABF
記憶體
光通訊
電源 / 重電
國防 / 無人機
機器人
```

Internal keys:

```text
all
ai_infrastructure
semiconductors
thermal_cooling
pcb_abf_hdi
memory_hbm
optical_cpo
power_grid
defense_drone
robotics
```

Compatibility aliases currently handled in the frontend include:

```text
ai_server → ai_infrastructure
cowos_supply_chain → semiconductors
power_supply → power_grid
energy_grid → power_grid
```

### Selected versus all behavior

Both modes now use `data/theme-events.json`.

```text
全量 = all theme events
精選 = theme_score >= 0.3 AND related_symbols is non-empty
```

The old selected-mode dependency on `data/stories-merged.json` was removed from the primary list and counts.

Legacy AI News Radar hotspot and TOP3/persona panels are hidden in the Taiwan dashboard. They must not be re-enabled until they are rebuilt from the Taiwan Theme Radar event contract.

Current live result:

```text
全量: 3
精選: 1
```

### GitHub Actions and Pages

Workflow:

```text
.github/workflows/update-theme-radar.yml
```

Workflow name:

```text
Nexus/Taiwan Theme Radar
```

Capabilities verified:

- hourly scheduled execution at minute 17
- manual `workflow_dispatch`
- updater execution
- generated JSON commit and push
- GitHub Pages deployment from `master` `/`

Evidence:

- Manual updater run: <https://github.com/a898954139/nexus-theme-radar/actions/runs/30243796525>
- Latest v0.3 Pages deployment: <https://github.com/a898954139/nexus-theme-radar/actions/runs/30246882642>

## v0.3 Verification Evidence

Verified before release:

```text
focused v0.3 tests: 5 passed
full test suite: 252 passed
node --check assets/app.js: passed
git diff --check: passed
Pages deployment: passed
live UI smoke test: passed
```

Live UI validation confirmed:

- `全量` displays Taiwan theme events only.
- `精選` displays one qualified Taiwan theme event.
- No Debian, ESP32, Claude 5, Open-weight AI, or other legacy AI News Radar content appears.
- Legacy hotspot and TOP3 panels are hidden.

## Important Technical Debt

The repository still contains inherited AI News Radar files and functions, including legacy JSON outputs, skills, documentation, classic/legacy views, and unused frontend helpers.

Do **not** perform a broad deletion in v0.4. Only remove inherited code when:

1. it blocks or conflicts with a v0.4 requirement;
2. a test proves it is unused by the Taiwan dashboard; and
3. the diff remains narrow and reviewable.

The current `tracking-candidates.json` producer threshold is:

```python
theme_score >= 0.5 and related_symbols
```

This is stricter than the frontend selected threshold (`0.3`). Do not silently align these thresholds during RSS onboarding. Treat candidate semantics as a separate product decision.

## v0.4 Goal

Add more **media-style RSS discovery sources** without coupling source-specific logic into the core event pipeline.

### First priority

```text
Cnyes / 鉅亨網
```

Cnyes is currently registered as planned in:

```text
config/source_registry.tw.json
```

Its current placeholder configuration is:

```json
{
  "source_id": "cnyes",
  "fetch_method": "public_feed_or_registry_adapter",
  "status": "planned"
}
```

### Explicitly not the first v0.4 slice

Do not include these in the initial Cnyes slice:

```text
MOPS
TWSE
TPEx
TrendForce
Goodinfo
```

Source roles remain:

- MoneyDJ / Yahoo / Cnyes: media-style discovery.
- MOPS / TWSE / TPEx: official confirmation and evidence.
- TrendForce / Goodinfo: pending extraction-strategy validation.

## v0.4 Implementation Constraints

1. Follow Anthony's ECC + Overlay workflow.
2. Jarvis remains coordinator and verifier; Codex is the default implementation lane, Claude is review/fallback.
3. Use TDD: prove source parsing and registry behavior with failing tests before implementation.
4. Keep changes surgical; no broad AI News Radar cleanup.
5. Prefer a generic RSS adapter driven by source registry configuration.
6. Preserve per-source status and failure isolation: one failed feed must not abort other sources.
7. Preserve the generated JSON contracts consumed by the current UI.
8. Do not alter selected/candidate thresholds as part of RSS onboarding.
9. Do not push until Jarvis independently verifies tests, generated output, source status, UI behavior, and the diff.
10. Use Git identity:

```text
a898954139 <69338830+a898954139@users.noreply.github.com>
```

## Suggested v0.4 Acceptance Criteria

- Cnyes has a verified public feed or a narrowly scoped adapter with documented evidence.
- `config/source_registry.tw.json` marks Cnyes active only after a real fetch succeeds.
- The updater reports three healthy sources when all are available.
- Cnyes records normalize into the same article/event contract as MoneyDJ and Yahoo.
- Duplicate stories across sources do not create incorrect duplicate UI events beyond current pipeline semantics.
- Existing MoneyDJ and Yahoo behavior remains green.
- `theme-events.json`, `tracking-candidates.json`, and `source-status.json` remain backward-compatible.
- Relevant tests and full suite pass.
- Manual GitHub Actions dispatch succeeds.
- Live Pages dashboard loads the new data without legacy AI content returning.

## Recommended First Investigation

Before editing code:

1. Identify and validate the actual Cnyes RSS/feed URL.
2. Record HTTP status, content type, feed format, item count, timestamps, GUID/link stability, and encoding.
3. Compare Cnyes fields against the current `fetch_rss_source()` assumptions.
4. Decide whether Cnyes can use the generic RSS path or needs a minimal adapter.
5. Write a failing fixture-based parser/registry test.

Do not mark Cnyes active based only on an assumed URL or homepage inspection.

## Resume Commands

```bash
cd /Users/anthony/Desktop/dev/nexus-theme-radar

git status --short
git branch --show-current
git remote -v
git log --oneline -5

/Users/anthony/Documents/Agentic/bin/gitnexus session start \
  --task nexus-theme-radar-v0.4 \
  --title "Add Cnyes RSS discovery source"
```

Then inspect:

```text
config/source_registry.tw.json
scripts/update_theme_radar.py
tests/test_update_theme_radar.py
tests/test_v03_cleanup.py
.github/workflows/update-theme-radar.yml
```

## Definition of Done for the Next Executor

The next executor must report:

- exact Cnyes endpoint and verification evidence;
- files changed;
- RED and GREEN test evidence;
- updater output summary;
- source health output;
- full-suite result;
- GitHub Actions result if pushed;
- Pages/live UI result if deployed;
- residual risks and deferred sources.

No success claim may rely only on executor output; Jarvis must independently verify all release evidence.
