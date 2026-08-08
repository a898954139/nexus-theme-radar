# Taiwan industry and supply-chain reference data

This layer answers two different questions without conflating them:

1. Which Taiwan companies currently exist in the official listed, OTC, and emerging-stock universe?
2. Which public StatementDog topic pages describe a real upstream, midstream, and downstream supply chain, and where does each Taiwan company appear?

The hourly radar reads the checked-in snapshot. `load_theme_taxonomy()` keeps
the ten curated themes and automatically adds source-derived matcher themes
for the public chains (197 generated topics in this snapshot); three exact-name
chains are merged into their curated themes. The StatementDog crawl itself is
manual because the third-party HTML is rate-limited.

## Snapshot coverage

The checked-in 2026-08-08 snapshot contains:

| Measure | Count |
| --- | ---: |
| StatementDog numeric tag pages inspected | 1,987 |
| Pages with upstream/midstream/downstream structure | 201 |
| Supply-chain segments | 930 |
| Upstream segments | 267 |
| Midstream segments | 381 |
| Downstream segments | 282 |
| Taiwan company memberships across all segments | 3,513 |
| Unique Taiwan symbols named by the supply chains | 761 |
| Current official four-digit companies | 2,337 |
| Current official companies mapped to at least one chain | 755 |

The 2,337-company official universe is 1,087 TWSE, 890 TPEX, and 360 emerging-stock companies. It is intentionally separate from the 755 companies that StatementDog currently places in at least one structured supply chain.

The hourly `TW_EQUITY` heat payload uses TWSE and TPEX members because its
public company contract accepts those two exchanges; ESB remains available in
the full registry and audit data.

Six source symbols are retained in the source audit but excluded from the current official registry because they do not appear in the three official company-profile datasets: `1704`, `3454`, `5277`, `5281`, `6286`, and `6806`.

## Files

### `config/industry_supply_chains.tw.json`

Each industry contains:

- the StatementDog tag ID and canonical public URL;
- the public industry name;
- every upstream, midstream, and downstream segment label;
- Taiwan company code, displayed name, displayed benefit level, and source ordering within each segment;
- a flattened unique Taiwan-symbol list for fast lookup.

The file contains Taiwan companies only. Foreign companies are not copied into the project registry. Subscriber-only benefit explanations are also excluded.

### `config/symbol_registry.tw.json`

Every current four-digit company contains:

- `instrument_id`, symbol, exchange, short and full Chinese company names;
- official exchange industry code and Chinese industry label;
- listing date and StatementDog company URL;
- every matching supply-chain membership, including industry, stage, segment, displayed benefit level, and source rank.

The registry includes companies with zero StatementDog memberships so full-market coverage and supply-chain coverage remain independently measurable.
`statementdog_company_url` is null when a current official symbol has no numeric
company page in the inspected StatementDog sitemap; the updater does not invent
an unverified company URL.

At runtime, taxonomy-derived symbols are resolved from this registry. Registry
company names are not added to the direct-news substring alias list; only exact
four-digit code mentions and the curated aliases are used for direct mentions.

### `docs/INDUSTRY_SUPPLY_CHAIN_CATALOG.md`

This generated Markdown index lists all 201 supply chains with their source
tag, upstream/midstream/downstream segment counts, and unique Taiwan-company
count. Use it for browsing; use the JSON files for programmatic joins.

### `config/symbol_aliases.tw.json`

This remains the deliberately small news-mention alias seed. The direct-symbol extractor performs substring matching across aliases, so copying all 2,337 company names into that file would create false positives and add unnecessary per-item work. New companies should enter the alias seed when an active Radar theme needs direct name matching, not merely because they exist in the official company registry.

## Sources

- StatementDog sitemap: `https://statementdog.com/sitemap.xml.gz`
- Public industry pages: `https://statementdog.com/tags/<id>`
- TWSE listed-company profiles: `https://openapi.twse.com.tw/v1/opendata/t187ap03_L`
- TPEX OTC-company profiles: `https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O`
- TPEX emerging-company profiles: `https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_R`

StatementDog is used only for public taxonomy and membership facts. TWSE and TPEX remain authoritative for whether a Taiwan symbol is current and which market it belongs to.

## Refresh command

Use the repository virtual environment:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe scripts\update_industry_registry.py `
  --workers 2 `
  --delay-seconds 0.75 `
  --checkpoint "$env:TEMP\nexus-theme-radar-statementdog-checkpoint.json"
```

The updater:

1. reads every numeric tag URL from the sitemap;
2. distinguishes real upstream/midstream/downstream pages from news tags and other benefit groupings;
3. retries bounded network failures and records per-page errors;
4. refuses to publish a partial crawl unless `--allow-partial` is explicitly supplied;
5. joins Taiwan memberships to the current official company universe;
6. validates every page count, symbol count, flattened symbol list, and cross-file membership before replacing either output.

The hourly updater then loads the checked-in taxonomy and automatically expands
its matcher set from this snapshot. A source-derived topic uses the public
industry name as its required signal, the upstream/midstream/downstream labels
as optional context, and the current TWSE/TPEX members as its `seed_symbols`.

A successful zero-error run removes its checkpoint. An interrupted or failed
run keeps the checkpoint so the next invocation retries only unfinished pages.

This command is manual by design. StatementDog is a third-party HTML source with rate limiting, so it is not part of the hourly GitHub Actions pipeline.
