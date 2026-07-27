# Nexus Theme Radar v0.5 → v0.6 Handoff

## Status

**v0.5 is implemented, published, and live. v0.6 design and execution prompt are ready for a new session.**

```text
Repository: /Users/anthony/Desktop/dev/nexus-theme-radar
Remote: https://github.com/a898954139/nexus-theme-radar
Branch: master
Production HEAD: 538f81ffadb30b606bfe81696b0791ea5b74ad41
v0.5 feature commit: ee00774d1fef2f99443c0894d39692d3e779a2ef
Live site: https://a898954139.github.io/nexus-theme-radar/
```

v0.5 release evidence:

- feature pushed to `master`;
- full-refresh Action succeeded: <https://github.com/a898954139/nexus-theme-radar/actions/runs/30263716677>;
- Pages deployment succeeded: <https://github.com/a898954139/nexus-theme-radar/actions/runs/30263737936>;
- production source health: 4/4;
- MOPS dataset health: 12/12;
- local v0.5 full suite before release: 282 passed.

## v0.6 Approved Scope

v0.6 is one unified release implemented as three sequential slices:

1. balanced official evidence;
2. deterministic event clustering;
3. Taiwan relevance gate.

Each slice receives TDD, review and one local commit. Do not push after individual slices. Push once only after final Jarvis verification.

Authoritative documents:

```text
docs/plans/2026-07-27-nexus-theme-radar-v0.6-design.md
docs/plans/2026-07-27-nexus-theme-radar-v0.6-implementation-plan.md
docs/prompts/NEXUS_THEME_RADAR_V0.6_EXECUTOR_PROMPT.md
```

## Locked Product Decisions

### Overseas stories

Keep an overseas event when it maps to a Taiwan-listed symbol or a configured Taiwan supply-chain theme. Exclude unsupported overseas market/company stories.

### Duplicate events

One real-world event displays as one representative card. Other reports are retained in the card source list.

### Representative source

Use this deterministic priority:

```text
official discovery source
→ Taiwan professional financial media
→ other trusted media
→ content completeness
→ publication recency
→ canonical URL
```

MOPS remains evidence-only and may not become a discovery card.

### Evidence cap

Use event-value weighting:

- critical: material information, penalties, disclosure violations, trading-status changes;
- high: insider transfers, forecast variance, control/business changes;
- normal: shareholder meetings and dividends;
- minimum reservation per non-empty dataset;
- unused capacity returns to a weighted shared pool;
- global evidence cap remains 500 by default.

### Release model

Three slices are implemented and committed separately, then released together.

## Production Defects to Reproduce

The v0.5 full refresh produced:

```text
MOPS fetched records:         2,333
official records in window:   2,249
published evidence:             500
published evidence mix:       500 × t187ap45_L
theme events:                    10
tracking candidates:              0
confirmation:          10 unconfirmed
```

Observed dashboard issues:

- `t187ap45_L` dividend records monopolized bounded evidence;
- multiple 長鑫科技 articles represented the same broad listing event;
- pure China A-share, Hong Kong and Korean-market stories entered a Taiwan-equity product without a clear Taiwan mapping.

Do not solve these by adding providers, datasets, LLM calls or a database.

## Mandatory Workflow

Use ECC behavior-change workflow:

```text
/ecc:orch-change-feature
```

Start Anthony ECC Overlay from the target repo:

```bash
cd /Users/anthony/Desktop/dev/nexus-theme-radar

/Users/anthony/Documents/Agentic/bin/gitnexus session start \
  --task nexus-theme-radar-v0.6 \
  --title "Improve evidence balance, event clustering, and Taiwan relevance"
```

The design and implementation plan satisfy Gate 1. No push/deploy is authorized in the executor session.

## New Session Startup Checklist

1. Verify clean baseline:

```bash
git status --short --branch
git fetch origin
git rev-list --left-right --count origin/master...master
git rev-parse HEAD
```

Expected:

```text
clean master
0 0 divergence
HEAD 538f81ffadb30b606bfe81696b0791ea5b74ad41
```

2. Read the three authoritative v0.6 documents.
3. Start GitNexus session.
4. Run baseline full suite in `.venv`.
5. Dispatch the v0.6 executor prompt through Codex/ECC.
6. Preserve RED/GREEN evidence under `/tmp/nexus-theme-radar-v06/`.
7. Verify each local slice commit independently.
8. Stop before push and return control to Jarvis.

## Required Local Commits

```text
feat: balance official evidence allocation
feat: cluster duplicate theme events
feat: gate events by taiwan relevance
```

No extra opportunistic commit or broad cleanup.

## Backward Compatibility

Preserve:

```text
data/theme-events.json
data/tracking-candidates.json
data/source-status.json
data/official-evidence.json
existing frontend
one updater workflow
one updater command
selected threshold 0.3
candidate threshold 0.5
12 active MOPS datasets
```

## Explicit Non-Goals

- no new providers;
- no new MOPS datasets;
- no TPEx source;
- no LLM release gate;
- no database/backfill;
- no UI redesign;
- no broad taxonomy or inherited AI News Radar cleanup;
- no threshold changes.

## Verification and Handoff

Before returning to Jarvis:

```bash
.venv/bin/python -m pytest -q tests/test_update_theme_radar.py tests/test_mops_adapter.py
.venv/bin/python -m pytest -q
.venv/bin/python -m py_compile scripts/update_theme_radar.py scripts/source_adapters.py
node --check assets/app.js
git diff --check

/Users/anthony/Documents/Agentic/bin/gitnexus status sync
/Users/anthony/Documents/Agentic/bin/gitnexus diff summary \
  --task nexus-theme-radar-v0.6
/Users/anthony/Documents/Agentic/bin/gitnexus handoff create \
  --task nexus-theme-radar-v0.6
```

The executor must report commit SHAs, RED/GREEN evidence, evidence distribution, cluster statistics, Taiwan relevance exclusions, source/dataset health, independent review verdicts, residual risks and the GitNexus handoff path.

## Release Ownership

Jarvis independently verifies the three commits and generated output. Only Jarvis may authorize the unified push, full-refresh Action and Pages verification.
