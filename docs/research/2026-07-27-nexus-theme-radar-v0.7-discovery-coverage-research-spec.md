# Nexus Theme Radar v0.7 — High-Quality Discovery Coverage Research Spec

**Status:** Ready for Gemini Deep Research

**Date:** 2026-07-27

**Repository:** `/Users/anthony/Desktop/dev/nexus-theme-radar`

**Research type:** Source/provider census and onboarding recommendation — no implementation

## 1. Decisions to make

This research must solve **two coupled coverage constraints**. Adding sources alone is insufficient because the current 10-theme taxonomy rejects most otherwise useful records.

1. Identify the smallest set of **public, no-login, automatable discovery sources** that can materially increase Taiwan-equity event input without weakening Nexus Theme Radar v0.6 quality gates.
2. Design a bounded **Taiwan-equity theme taxonomy expansion** that converts the additional useful input into retained, classified events without turning the product into a generic stock-news feed.

The research must end with:

- an exact recommendation for **2–3 sources/endpoints to activate in v0.7**;
- an exact recommendation for **new or revised taxonomy categories** to ship with those sources;
- a measured stage-by-stage funnel showing `raw → current taxonomy matched → proposed taxonomy matched → Taiwan relevant → clustered cards`;
- deferred and rejected source/theme lists with evidence.

This is not a generic list of Taiwanese financial websites or stock sectors. Every recommended source must have a verified machine-consumable delivery path. Every recommended theme must be a distinct, event-driven, Taiwan-investable narrative with explicit positive signals, generic-term exclusions, and Taiwan symbol mappings.

## 2. Current production baseline

As of the v0.6 production refresh:

```text
Active discovery sources:
- MoneyDJ RSS
- Cnyes RSS
- Yahoo Finance Taiwan RSS

Active official evidence source:
- MOPS via TWSE OpenAPI, 12 datasets

Planned registry entries:
- TrendForce
- TWSE
- TPEx
- Goodinfo

Current configuration:
- 10 Taiwan-equity themes
- 30 configured Taiwan symbol aliases
- selected threshold: 0.3
- candidate threshold: 0.5
- deterministic event clustering enabled
- Taiwan relevance gate enabled

Latest production window:
- raw discovery records: 165 / 72 hours
- retained pre-cluster records: 11
- representative event cards: 10
- tracking candidates: 3
- excluded records: 6
- confirmation state: 10 unconfirmed
```

Relevant production URLs:

```text
Repository: https://github.com/a898954139/nexus-theme-radar
Live site: https://a898954139.github.io/nexus-theme-radar/
Source registry: https://raw.githubusercontent.com/a898954139/nexus-theme-radar/master/config/source_registry.tw.json
Theme taxonomy: https://raw.githubusercontent.com/a898954139/nexus-theme-radar/master/config/theme_taxonomy.tw.json
Current events: https://raw.githubusercontent.com/a898954139/nexus-theme-radar/master/data/theme-events.json
Source status: https://raw.githubusercontent.com/a898954139/nexus-theme-radar/master/data/source-status.json
```

## 3. Locked research scope

Only research sources that are all of the following:

1. publicly accessible without account login;
2. available without paid subscription or licensed data contract;
3. automatable through RSS, Atom, JSON API, stable static JSON, sitemap/news sitemap, or a narrowly scoped stable public HTML endpoint;
4. suitable for scheduled server-side retrieval from GitHub Actions;
5. relevant to Taiwan-listed equities, Taiwan supply chains, or the configured themes;
6. legally and operationally reasonable to poll at a conservative cadence;
7. capable of producing records with a stable URL and usable publication timestamp.

### In scope

- Taiwan professional financial media;
- Taiwan technology and semiconductor industry media;
- industry-research providers with genuinely public feeds or public news endpoints;
- public corporate/industry association news feeds when they add cross-company theme discovery;
- public government or official news feeds only when they function as discovery content rather than duplicating MOPS evidence;
- public Traditional Chinese or English sources with clear Taiwan supply-chain relevance.

### Out of scope

- paywalled or login-gated content;
- API keys, cookies, browser sessions, private tokens, or personal feeds;
- sources whose only viable integration is browser automation;
- fragile anti-bot bypasses, CAPTCHA solving, proxy rotation, or headless-browser scraping;
- social timelines, X/Twitter, Facebook, Telegram, Discord, LINE, or account-bound feeds;
- Google News/Bing News scraping as a provider;
- LLM-generated or LLM-gated release decisions;
- new official-evidence datasets;
- TWSE/TPEx/MOPS evidence expansion;
- Goodinfo if no stable, permitted, public machine-readable endpoint can be verified;
- generic market buckets such as `台股`, `科技`, `AI`, `半導體`, `熱門股`, `盤勢`, or `個股新聞` as standalone themes;
- taxonomy categories based only on publisher navigation labels without event-level sample evidence;
- implementation code, architecture refactors, UI changes, or threshold changes.

## 4. Research questions

### A. Candidate discovery

Find candidate sources that improve one or more current weak areas:

- Taiwan company-specific events;
- semiconductors and advanced packaging;
- AI servers and data-center supply chains;
- memory/HBM;
- PCB/ABF/HDI;
- optical/CPO;
- thermal/liquid cooling;
- power supply, heavy electrical and energy grid;
- robotics;
- defense and drones.

Do not assume the existing planned registry entries are valid. Verify TrendForce and any other candidate independently.

### B. Endpoint verification

For every serious candidate, identify and verify:

- exact endpoint URL;
- delivery format;
- whether authentication is required;
- HTTP status from a fresh request;
- content type and encoding;
- whether the response can be parsed without JavaScript execution;
- publication timestamp availability and timezone;
- canonical article URL availability;
- pagination or item-limit behavior;
- approximate items per day;
- most recent item timestamp at research time;
- category/topic filtering options;
- stable item identifier options;
- duplicate/syndication relationship with current sources;
- robots.txt, terms, licensing, and attribution concerns;
- rate-limit or conservative polling recommendation;
- evidence that the endpoint is official rather than a third-party mirror.

A homepage, search-result page, undocumented URL guess, or historical mention of an RSS feed is not endpoint verification.

### C. Coverage value

Estimate each candidate's incremental value against the current three discovery sources:

- unique Taiwan-relevant events per 72-hour window;
- theme/category distribution;
- company-specific versus generic market content;
- overlap with MoneyDJ, Cnyes, and Yahoo Finance Taiwan;
- likely retained-event yield after the v0.6 Taiwan relevance gate;
- expected representative-card contribution after clustering;
- source authority and content completeness;
- whether the source is primary reporting, research-derived reporting, press-release syndication, or aggregation.

When exact measurements are impossible, label estimates clearly and explain the sampling method. Do not present guesses as measured values.

### D. Operational feasibility

For each candidate, determine:

- expected adapter type: generic RSS/Atom, generic JSON, sitemap, or source-specific public HTML parser;
- GitHub Actions compatibility;
- expected maintenance burden;
- timeout and response-size characteristics;
- failure modes;
- whether adding it requires a new dependency;
- whether the source can be integrated through the existing registry-driven architecture without provider-specific logic leaking into the core pipeline.

### E. Taxonomy coverage and expansion

Use the current `config/theme_taxonomy.tw.json` as the baseline. The current taxonomy contains only:

```text
ai_server
cowos_supply_chain
thermal_cooling
pcb_abf_hdi
optical_cpo
memory_hbm
power_supply
robotics
defense_drone
energy_grid
```

For records sampled from both current and candidate sources:

1. replay or approximate the current deterministic matching logic;
2. measure how many Taiwan-relevant records fail solely because no current theme matches;
3. group unmatched records by real event narrative, not publisher category;
4. propose new themes only when the sample proves recurring volume, Taiwan investability, and a coherent symbol supply chain;
5. determine whether each gap requires a new theme, additional strong keywords for an existing theme, aliases, or no change;
6. test proposed themes against negative examples to estimate false-positive risk;
7. report the expected retained-event gain attributable to taxonomy expansion separately from the gain attributable to new sources.

Research at minimum whether the following **candidate gap families** deserve distinct themes, should extend an existing theme, or should be rejected:

- foundry and advanced-node capex;
- semiconductor equipment and materials;
- IC design and edge AI chips;
- data-center networking and high-speed switching;
- server ODM, racks and data-center infrastructure beyond the narrow `ai_server` keywords;
- passive components and MLCC;
- connectors, cables and high-speed interconnect;
- consumer electronics and Apple supply chain;
- automotive electronics, EV and charging;
- smart manufacturing and industrial automation;
- cybersecurity and enterprise software;
- satellite and low-earth-orbit communications;
- biotech, medical devices and healthcare technology;
- green energy, solar and wind where not covered by `energy_grid`;
- shipping, aerospace, defense and other event-driven Taiwan themes discovered in the sample.

This is a research seed list, not an instruction to create every category.

Each proposed theme must include:

```text
theme_id
name_zh
problem/gap solved
positive keywords and phrases
strong signals eligible for overseas supply-chain relevance
negative/generic exclusions
related industries
minimum 5–15 Taiwan seed symbols when evidence supports them
symbol rationale by supply-chain role
sample matching records
sample negative records
estimated 72-hour incremental matched records
estimated false-positive risk
relationship to existing themes: new / merge / extend / reject
```

Do not recommend generic single-word signals such as `AI`, `科技`, `半導體`, `電子`, `能源`, `市場`, `概念股`, or `供應鏈` by themselves.

## 5. Mandatory candidate set

Research these explicitly, but do not force them into the final recommendation:

1. TrendForce public Taiwan/industry news or research feed;
2. TechNews 科技新報 and related public feeds/endpoints;
3. DIGITIMES publicly accessible news surfaces, only if a no-login automatable endpoint exists;
4. 工商時報／財經 or industry feeds, only if a stable public endpoint exists;
5. 經濟日報／產業 feeds, only if a stable public endpoint exists;
6. Central News Agency business/technology feeds where Taiwan-equity relevance is material;
7. public semiconductor, electronics, PCB, optical, energy, robotics, defense, or industry-association feeds discoverable during research.

Also discover additional candidates. Do not limit research to this seed list.

## 6. Evaluation model

Score each verified candidate from 0–5 on:

| Dimension | Meaning |
|---|---|
| Taiwan relevance | Direct usefulness for Taiwan-listed equities and supply chains |
| Incremental uniqueness | Adds events not already covered by current sources |
| Theme depth | Adds specialized industry information rather than generic market news |
| Endpoint reliability | Stable, parseable, timestamped and machine-readable |
| Automation safety | No login, token, CAPTCHA, browser or anti-bot workaround |
| Freshness | Timely enough for a 72-hour event radar |
| Authority | Original/professional reporting or authoritative public material |
| Maintenance cost | 5 means low maintenance; 0 means fragile/high maintenance |
| Legal/terms clarity | Public retrieval and attribution risk are acceptable |

Calculate:

```text
recommended_score =
  Taiwan relevance × 3
+ Incremental uniqueness × 3
+ Theme depth × 2
+ Endpoint reliability × 3
+ Automation safety × 3
+ Freshness × 2
+ Authority × 2
+ Maintenance cost × 2
+ Legal/terms clarity × 2
```

The numeric score supports the decision but does not override a hard blocker. Login requirements, CAPTCHA, browser-only delivery, unclear endpoint ownership, or unacceptable terms risk must exclude a source from the active v0.7 recommendation.

## 7. Required output

Return one complete Markdown report with these sections.

### 1. Executive recommendation

- exact 2–3 recommended active sources;
- exact endpoint for each;
- why this is the minimum viable v0.7 set;
- expected combined coverage gain;
- main risks;
- sources explicitly not recommended.

### 2. Current coverage-gap analysis

Explain why the current production output is sparse and identify which themes/source classes are under-covered.

### 3. Full candidate inventory

A table containing:

```text
source
publisher
exact endpoint
format
status verified at
latest item timestamp
items sampled
estimated items/day
Taiwan relevance
main themes
current-source overlap
adapter type
auth/login
robots/terms risk
polling recommendation
score
decision: activate / reserve / watch / reject
```

### 4. Endpoint evidence cards

For every `activate` or `reserve` candidate, provide:

- fresh HTTP/request evidence;
- representative response fields or feed tags;
- three recent sample records with title, timestamp and URL;
- parsing notes;
- deduplication/canonicalization notes;
- operational risks;
- recommended registry fields.

Do not reproduce full copyrighted articles. Titles, metadata, short snippets and endpoint structures are sufficient.

### 5. Incremental coverage and filter-funnel analysis

Compare candidates against MoneyDJ, Cnyes and Yahoo Finance Taiwan using a recent common sample window where possible. Report:

- total sampled items;
- Taiwan-relevant items;
- current-taxonomy matched items;
- Taiwan-relevant but current-taxonomy unmatched items;
- proposed-taxonomy matched items;
- likely retained items after Taiwan relevance;
- unique events after URL/title normalization;
- representative cards after clustering;
- overlap by current source;
- current and proposed theme distribution;
- company-specific event ratio;
- estimated representative cards contributed per 72 hours.

Provide separate funnel tables for:

```text
current sources + current taxonomy
new sources + current taxonomy
current sources + proposed taxonomy
new sources + proposed taxonomy
combined recommended v0.7 configuration
```

The report must distinguish:

- gain from new sources;
- gain from taxonomy expansion;
- gain from both together;
- records still rejected by Taiwan relevance or clustering.

### 6. Taxonomy gap inventory and recommended taxonomy delta

Provide:

1. current-theme performance table;
2. unmatched Taiwan-relevant narrative clusters;
3. proposed new themes;
4. proposed extensions to existing themes;
5. rejected category ideas;
6. source-by-theme coverage matrix before and after the proposed delta;
7. a machine-readable proposed taxonomy JSON block compatible with the current taxonomy shape.

The proposed JSON must include only evidence-supported themes and keyword changes. It must preserve the existing 10 themes unless the evidence justifies a merge or rename.

### 7. Recommended v0.7 active allowlist

Provide a machine-readable block:

```json
{
  "recommended_active_sources": [
    {
      "source_id": "...",
      "name": "...",
      "source_class": "financial_media|industry_research|official_discovery",
      "market_scope": ["TW_EQUITY"],
      "authority_rank": 0,
      "fetch_method": "rss|atom|json_api|public_html",
      "endpoint": "https://...",
      "poll_interval_minutes": 0,
      "timeout_seconds": 0,
      "max_response_bytes": 0,
      "expected_items_per_day": 0,
      "primary_theme_coverage": ["..."],
      "attribution_requirement": "...",
      "research_evidence_urls": ["..."]
    }
  ],
  "deferred_sources": [],
  "rejected_sources": []
}
```

Use stable lowercase snake-case `source_id` values.

### 8. Proposed release slices

Recommend a bounded implementation sequence that pairs sources with the taxonomy required to retain their useful content. Default preference:

```text
Slice A: taxonomy gap baseline + narrowly evidenced existing-theme keyword improvements
Slice B: first generic feed/API source with highest incremental value + only its required new themes
Slice C: second complementary specialist source + only its required new themes
Slice D: optional third source only if it covers a materially different source and taxonomy gap
```

Do not place all speculative categories into Slice A. Each taxonomy addition must trace to sampled records and a selected source or a measured gap in current sources.

Each slice must be independently releasable and must not change v0.6 thresholds or relevance/clustering behavior.

### 9. Acceptance criteria for implementation planning

Write testable acceptance criteria covering:

- live fetch success;
- deterministic normalization;
- publication timestamp correctness;
- source-status diagnostics;
- shuffled-input determinism;
- compatibility with clustering and Taiwan relevance;
- duplicate handling against current sources;
- failure isolation;
- unchanged legacy JSON contracts;
- no secrets and no browser dependency.

### 10. Unknowns and rejected assumptions

List every material claim that could not be verified. Explicitly reject sources whose viable endpoint remains unproven.

### 11. Source bibliography

Cite all endpoint, terms, robots, documentation, sample and comparison evidence with direct URLs and access dates.

## 8. Quality gates for the research

The report is not acceptable unless:

- every recommended source has a freshly verified exact endpoint;
- every recommended endpoint is public and no-login;
- no recommendation depends on browser automation or anti-bot bypass;
- at least three recent sample records are provided per recommended source;
- overlap with the three current sources is evaluated;
- current-taxonomy rejection loss is measured;
- unmatched Taiwan-relevant records are grouped into narrative/category gaps;
- a bounded proposed taxonomy delta is returned with positive signals, generic exclusions, Taiwan symbols, sample positives and sample negatives;
- the report separates source-driven gain from taxonomy-driven gain;
- measured facts and estimates are clearly separated;
- an exact 2–3-source allowlist is returned;
- rejected source and taxonomy candidates include a concrete reason;
- implementation is not started;
- all citations use direct source URLs where possible.

## 9. Research operating instruction

Use web research and direct endpoint probing. Prefer official publisher documentation, official feeds, official sitemaps, robots.txt and terms pages over third-party directories. Cross-check feed discovery claims with actual HTTP responses.

Do not ask the operator to choose among candidates before completing the census. Produce the evidence, rank the candidates, and make a recommendation.
