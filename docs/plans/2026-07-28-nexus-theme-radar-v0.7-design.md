# Nexus Theme Radar v0.7 Design

**Status:** Approved design, planning complete; implementation remains unauthorized
**Date:** 2026-07-28
**Planning baseline:** local `master` at `6fcadc534110510db757cf071600ce778998a71c`, six freshly fetched remote-only snapshot commits behind `origin/master`, no local-only commits

## 1. Product goal and approved scope

v0.7 addresses two coupled causes of sparse useful output:

```text
insufficient discovery-source coverage
+
insufficient taxonomy coverage
```

The approved release is:

```text
hybrid deterministic taxonomy matcher
+ benchmark-gated taxonomy delta
+ TechNews public RSS
+ DIGITIMES public RSS metadata only
+ unchanged Taiwan relevance and clustering
= one unified v0.7 release
```

The release has four independently reviewable local slices:

```text
Slice A — matcher + legacy compatibility + benchmark harness + diagnostics
Slice B — benchmark-qualified taxonomy delta
Slice C — TechNews onboarding
Slice D — DIGITIMES metadata-only onboarding
```

No slice is released independently. Implementation, commits, pushes, Actions, production refreshes, and deployment require separate authorization.

## 2. Baseline and evidence authority

The local code baseline contains:

- ten legacy themes in `config/theme_taxonomy.tw.json`, all using `keywords`;
- active MoneyDJ, Cnyes, and Yahoo Finance Taiwan RSS discovery sources;
- MOPS/TWSE OpenAPI as official evidence, not a discovery publisher;
- one generic RSS normalization path in `scripts/update_theme_radar.py`;
- selected threshold `0.3` and candidate threshold `0.5`;
- Taiwan relevance before clustering;
- source-isolated fetching and bounded RSS responses;
- additive source, relevance, clustering, and threshold diagnostics.

The six freshly fetched `origin/master`-only commits modify only generated snapshot files under `data/`. They are not merged into this planning baseline.

The Gemini draft and follow-up report are untrusted hypothesis sources. Their URLs, timestamps, record counts, precision claims, funnel values, and `VALIDATED` labels are not evidence. Approved decisions override their conflicting recommendations.

## 3. Hybrid matcher contract

### 3.1 Schema selection

A theme uses exactly one matching mode:

1. **Legacy mode:** `keywords` is present and none of `required_any`, `optional`, or `excluded` is present.
2. **Structured mode:** `required_any`, `optional`, and `excluded` are present. `required_any` must be a non-empty list; `optional` and `excluded` must be lists and may be empty.

Mixing `keywords` with structured keys in one theme is invalid. This removes precedence ambiguity. The ten existing themes remain legacy themes in v0.7; v0.7 does not migrate them.

### 3.2 Phrase matching

Both modes use the existing source-neutral, deterministic phrase matcher:

- case-insensitive matching;
- ASCII terms respect existing token boundaries;
- Traditional Chinese and other non-ASCII phrases use substring matching;
- only the existing matchable text fields and weights participate:

```text
title:    3.0
title_zh: 3.0
summary:  1.5
content:  1.0
```

Publisher name, `source_id`, source class, authority rank, URL, and registry metadata never participate in theme scoring.

Each distinct matching phrase contributes the maximum weight of any field in which it occurs. The score remains:

```text
min(1.0, sum(distinct phrase weights) / 9.0)
```

The score is rounded exactly as the current matcher does. Thresholds remain selected `0.3` and candidate `0.5`.

### 3.3 Structured precedence

Structured matching is evaluated in this exact order:

1. Search all `excluded` phrases. If any matches, veto the theme immediately.
2. Search `required_any`. If none matches, the theme does not match.
3. Search `optional`.
4. Score the distinct matched `required_any` and `optional` phrases using the existing field weights and denominator.

Consequences:

- `excluded` always wins, even when required and optional phrases also match.
- One or more `required_any` matches are mandatory.
- `optional` can strengthen an already eligible match but can never trigger a match.
- Input phrase order and record order cannot change the result.
- Match signals and reasons remain deterministically sorted.

### 3.4 Legacy compatibility

Legacy mode is the current `_score_theme` behavior without reinterpretation:

- any matching `keywords` phrase can trigger;
- matching, weighting, score calculation, signal ordering, primary-theme ordering, symbol enrichment, and decisions remain unchanged;
- current taxonomy loaded unchanged produces byte-equivalent matcher results for a frozen regression corpus;
- structured fields are not synthesized for legacy themes at runtime.

## 4. Benchmark contract

### 4.1 Repository model

The future benchmark owns these paths:

```text
scripts/benchmark_theme_taxonomy.py
tests/test_theme_benchmark.py
tests/fixtures/theme_benchmark/v0.7/manifest.json
tests/fixtures/theme_benchmark/v0.7/real-records.json
tests/fixtures/theme_benchmark/v0.7/synthetic-cases.json
```

`real-records.json` contains captured RSS metadata only. Each record includes:

```text
record_id
source_id
endpoint
captured_at
published_at
canonical_url
title
description
raw_fixture_sha256
expected_theme_ids
adjudication
adjudicated_by
adjudicated_at
notes
```

`manifest.json` records the endpoint, access time, HTTP/content metadata, fixture SHA-256, capture command/version, record count, labeling rules, and benchmark version.

`synthetic-cases.json` is explicitly marked `provenance: synthetic` and covers semantic boundaries and impossible-to-source combinations. Synthetic cases may prove matcher rules but never count toward measured precision, recall, volume, source overlap, or theme qualification.

### 4.2 Frozen-data rules

- Direct endpoint captures are immutable once admitted to a benchmark version.
- Captures contain RSS metadata only, not copyrighted article bodies.
- Every real record must trace to a captured fixture hash.
- Duplicates are labeled before metrics; the same syndicated event cannot inflate positive support.
- Training/tuning records and held-out qualification records are identified separately.
- Missing or disputed labels fail closed as `unadjudicated` and do not count.
- No future-dated, invented, or report-only URL qualifies as real evidence.

### 4.3 Per-theme qualification

Each candidate is assessed independently. A target theme count is not a gate.

A candidate may enter release configuration only when the frozen real-record benchmark proves all of the following:

1. at least five unique positive event clusters;
2. positives span at least two publication dates and at least two publishers among current and approved sources;
3. at least ten real negative or near-miss records exercise its documented boundaries;
4. held-out precision is at least `0.85`;
5. held-out recall is at least `0.70`;
6. zero optional-only matches;
7. zero excluded-veto violations;
8. zero known boundary violations involving a locked neighboring theme;
9. all seed symbols used for Taiwan supply-chain retention have an evidence-backed role;
10. results are identical under shuffled record and phrase input.

If the available real corpus cannot meet the sample minima, the result is `insufficient_evidence`, not a failure to be overcome with synthetic records. Thresholds may not be weakened to force qualification.

The benchmark emits per-theme:

```text
qualified | rejected | insufficient_evidence
real_positive_clusters
real_negative_records
true_positive / false_positive / true_negative / false_negative
precision / recall
optional_only_violations
excluded_veto_violations
boundary_violations
fixture hashes
```

## 5. Candidate taxonomy boundaries

### `semicon_foundry_advanced`

In scope: advanced foundry nodes, node-specific capacity or pricing, fab expansion, High-NA EUV adoption, backside power delivery, and other front-end advanced-process events.

Out of scope:

- CoWoS, which remains in `cowos_supply_chain`;
- FOPLP and packaging-only narratives;
- traditional OSAT, wire bonding, QFP/BGA, and generic testing;
- mature-node or generic foundry stories without an advanced-node signal.

### `semicon_equipment`

In scope: semiconductor-specific lithography, etch, deposition, wafer cleaning, coating/developing, metrology, inspection, advanced packaging equipment, and fab tool orders.

Out of scope: generic machine tools, factory automation without semiconductor context, medical equipment, PCB drilling, display equipment, and solar equipment.

### `semicon_materials`

In scope: semiconductor-grade photoresist, specialty gases and chemicals, silicon wafers, targets, CMP slurry/pads, advanced packaging substrates or materials when the semiconductor use is explicit.

Out of scope: generic petrochemicals, construction materials, display films, PCB CCL, battery materials, and commodity chemicals.

### `ic_design_edge_ai`

In scope: explicit Edge AI, NPU, AI MCU, AI ASIC, accelerator IP, or RISC-V accelerator events tied to IC design or licensable silicon IP.

Out of scope: generic `AI`, `chip`, `IC design`, MCU, driver IC, USB/controller, or consumer semiconductor wording without an explicit on-device AI/accelerator signal.

### Deferred candidates

These do not ship in v0.7:

```text
high_speed_interconnect
apple_supply_chain
auto_electronics_ev
space_leo_satellite
```

## 6. Source onboarding contracts

### 6.1 Shared contract

Both approved sources use the existing generic RSS path and one source-neutral normalization and matcher pipeline.

Required source behavior:

- public RSS only, no authentication, cookies, browser automation, or JavaScript execution;
- configured timeout and `max_response_bytes`;
- parse failure and transport failure isolated to that source;
- metadata normalized into the existing article contract;
- publication time converted deterministically to UTC;
- canonical publisher URL preserved after safe fragment/tracking-parameter normalization;
- attribution preserved through source name, source ID, and URL;
- no article-page request;
- no source-specific score boost.

### 6.2 TechNews

```text
source_id: technews
endpoint: https://technews.tw/feed/
fetch_method: rss
content_mode: rss_metadata
```

Only RSS title, description/summary, publication timestamp, link/GUID, and feed attribution are consumed. Activation requires a fresh direct probe and a committed, hashed fixture.

### 6.3 DIGITIMES

```text
source_id: digitimes_tw
endpoint: https://www.digitimes.com.tw/rss/news.xml
fetch_method: rss
content_mode: rss_metadata_only
```

The adapter may consume only RSS title, description, publication timestamp, canonical link/GUID, and attribution. It must ignore embedded full-content fields and must never fetch an article URL. A metadata-only regression test is a release blocker.

## 7. Additive diagnostics

Existing top-level and item fields remain unchanged. v0.7 adds top-level fields to both `theme-events.json` and `tracking-candidates.json`:

```json
{
  "matcher_contract": "hybrid_required_any_v1",
  "taxonomy_version": "v0.7",
  "legacy_theme_count": 10,
  "structured_theme_count": 0,
  "theme_match_distribution": {},
  "theme_veto_distribution": {}
}
```

`structured_theme_count` reflects only benchmark-qualified themes. Distribution maps are deterministically key-sorted. Existing threshold diagnostics remain `0.3` and `0.5`.

Each source-status site may add:

```json
{
  "content_mode": "rss_metadata_only",
  "max_response_bytes": 8388608
}
```

No existing field is renamed, removed, or changes type.

## 8. Processing order

The eventual processing order is locked:

1. load and validate registry, taxonomy, and benchmark-qualified theme set;
2. dispatch active sources with per-source timeout, byte limit, and failure envelope;
3. parse RSS and normalize metadata, timestamps, canonical URLs, and attribution;
4. combine successful discovery records while retaining source statuses;
5. deduplicate by normalized canonical URL;
6. apply the configured time window;
7. run the source-neutral hybrid matcher;
8. apply selected threshold `0.3`;
9. apply unchanged Taiwan relevance classification;
10. remove Taiwan-relevance exclusions;
11. run unchanged deterministic cross-source clustering;
12. apply candidate threshold `0.5` to cluster representatives;
13. attach official evidence using the unchanged confirmation path;
14. add diagnostics and write existing JSON outputs.

## 9. Release slices and gates

### Slice A — Matcher, compatibility, benchmark, diagnostics

Ships no new theme and no new source. It must prove legacy equivalence, structured semantics, provenance separation, deterministic benchmark output, and additive JSON compatibility.

### Slice B — Qualified taxonomy delta

Only candidates with `qualified` benchmark results are added. A zero-theme Slice B is valid when evidence is insufficient.

### Slice C — TechNews

Activates TechNews only after direct endpoint, fixture, timestamp, canonical URL, response-bound, failure-isolation, duplicate-clustering, and attribution gates pass.

### Slice D — DIGITIMES

Activates DIGITIMES only after the same source gates plus an explicit metadata-only/no-article-request proof.

All four slices release together after full verification and independent review.

## 10. Locked compatibility and non-goals

Locked compatibility:

- selected threshold `0.3`;
- candidate threshold `0.5`;
- Taiwan relevance behavior;
- clustering behavior and representative selection;
- MOPS evidence catalog and confirmation behavior;
- existing top-level JSON contracts and frontend compatibility;
- one updater workflow and one updater command;
- existing ten theme behavior.

Not planned or implemented:

- CTEE, TrendForce, UDN, CNA, or Technice activation;
- browser scraping, article-body extraction, or paywall bypass;
- LLM classification;
- database storage or historical backfill;
- threshold changes;
- Taiwan relevance or clustering redesign;
- UI redesign;
- new MOPS datasets;
- migration of all ten themes to structured schema;
- broad symbol-master expansion;
- any deferred taxonomy candidate.

## 11. Evidence gates still open

Implementation and release remain blocked until:

1. the implementation baseline is reconciled with the six fetched snapshot-only remote commits through an explicitly authorized branch-history decision, without silently overwriting work;
2. both approved RSS endpoints are freshly probed for HTTP status, content type, encoding, parseability, timestamps, canonical links, response size, attribution, and operational terms;
3. repository-controlled, hashed RSS fixtures are captured from those probes;
4. real benchmark records are captured, deduplicated, adjudicated, and separated from synthetic cases;
5. each of the four taxonomy candidates receives an independent qualification result;
6. cross-source duplicate examples with current sources are captured;
7. DIGITIMES metadata-only behavior is proven without article requests;
8. timeout and response-size values are validated against observed feeds;
9. full regression, static checks, independent review, and unified release verification pass;
10. Anthony explicitly authorizes implementation.
