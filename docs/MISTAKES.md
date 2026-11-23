# Mistakes log

Every mistake this project has shipped or nearly shipped, why it happened, and
what now stops it from happening again. This file is the input to
`lint/repo_lint.py`: each lint rule cites an entry here, and
`lint:mistakes-log` fails if a rule cites a missing entry.

**When a new mistake happens:** follow `skills/mistake-to-lint/SKILL.md`
(add an entry here → add or extend a rule → add a failing sample to
`tests/test_repo_lint.py` → baseline any existing debt with a reason).

Enforcement levels:

- `lint:<rule>` blocks in pre-commit, pre-push, CI (`repo-lint.yml`) and the
  Claude Code hooks (`.claude/settings.json`).
- `test:<file>` is pinned by a pytest regression test.
- `process` cannot be checked from the repo; the rule lives in `CLAUDE.md`
  ("Verification rules") so every Claude session reads it.

---

### M000 Rules drift from the log

The log and the rules can disagree as either grows.
Enforced by: `lint:mistakes-log`.

### M001 `from scripts.x import` passes pytest, kills the scheduled run

pytest runs from the repo root, so `scripts.` resolves; the scheduler runs the
file by path, where it does not (`ModuleNotFoundError: No module named 'scripts'`).
Shipped to master twice (see `skills/pipeline-changes/SKILL.md`).
Enforced by: `lint:job-dual-import` (needs try/except ModuleNotFoundError or an
explicit `sys.path.insert`), `test:tests/test_fundamentals_pipeline.py`.

### M002 Published payload field added without updating exact-key validators

Front-end validators compared key counts exactly; a new field failed the whole
payload and the page silently rendered its fallback.
Enforced by: `test:tests/test_homepage_theme_momentum_entry.py` (historical;
the site now reads `/api/v1`).

### M003 Three migrations shared version 20261118090000 (#23)

Supabase records one row per version, so only one of the three would apply.
Enforced by: `lint:migration-unique-version`.

### M004 Up/down colours inconsistent (#24, #25, #46, #47)

The pre-market board used green for bullish while report cards used red; later
the TradingView embed could not be recoloured and kept 綠漲紅跌. Site rule:
red = up/bullish, green = down/bearish (Taiwan convention).
Enforced by: `lint:color-convention` (`--up` red / `--down` green, chart
`upColor`/`downColor`, up/bull selectors never painted green and vice versa, no
TradingView embed widget).

### M005 Euphemisms and mainland wording on the site (#42)

UI said 偏防守 instead of 偏空 and used mainland terms (信息, 芯片, 美聯儲 ...).
Enforced by: `lint:wording-euphemism` (front, backend, job text and prompts) and
`lint:wording-taiwan` (mainland terms + simplified-only characters in front and
backend). Term lists: `lint/wording.json`.

### M006 Data silently went stale (flows stuck at 10/30, pre-market sectors since August)

The flows job fetched only "today", so any missed run left a permanent gap
(#26); pre-market sector sources had died months earlier and nobody noticed.
Enforced by: `test:tests/test_institutional_flows.py` (catch-up). Freshness
alerts are `process` until healthchecks (`NTR_HC_PING_KEY`) is configured.

### M007 Theme membership misclassified ("2027 年" parsed as a stock code, TSMC under PCB) (#34, #35)

Enforced by: `test:tests/test_theme_membership.py`.

### M008 Code kept pointing at the retired Supabase project (c15e054)

The visitor counter, and the pg_cron setup script, still targeted the old
project `abtdxucfppnjdqkwqiqh` after the radar moved to `xdixmdglgzaiugvfxmuw`.
Enforced by: `lint:supabase-project-ref` (only the ref in `db/roles.json`;
retired refs fail).

### M009 User told to use the Direct connection host (2026-11-21)

`db.<ref>.supabase.co` is IPv6-only and does not resolve from the Mac; the
cutover failed until the Session pooler host was used.
Enforced by: `lint:supabase-direct-host`; canonical host/format in
`db/roles.json` → `connection`.

### M010 Wrong DB role names in instructions and prompts (2026-11-21)

Threads alternated between `radar_writer` (a NOLOGIN group role), `theme_radar_app`
(the actual login) and `radar_api`, including inside `cutover.sh`'s prompt,
which asked for a "radar_writer 連線字串".
Enforced by: `lint:db-role-registry` (every role in SQL/docs/scripts must be in
`db/roles.json`; a group role can never be a connection-string user or the
subject of a "連線字串/login" prompt). `process`: quote roles only from
`db/roles.json`.

### M011 Backend API runs on a writable login

During the cut-over `RADAR_API_DATABASE_URL` was set to the writer login
`theme_radar_app` instead of read-only `radar_api`; the Mac runner uses the
`postgres` superuser.
Enforced by: `process` (Vercel/Mac env values are not in the repo).
`db/roles.json` records the required login per env var; `lint:db-role-registry`
rejects `postgres` as a connection-string user in the repo. **Open PRD follow-up.**

### M012 Vercel CLI deploy uploaded 656 MB and hit the free upload limit (2026-11-19)

Pipeline data was not excluded from the deploy.
Enforced by: `lint:vercelignore`.

### M013 Schedules scattered across GitHub Actions, pg_cron and cloud tasks

Three schedulers, and pg_cron was never recreated on the new project.
Enforced by: `lint:no-github-schedule`, `lint:no-pg-cron`, `lint:jobs-conf`
(parses, every script exists, @nolock jobs do not write `data/`),
`test:tests/test_mac_scheduler.py`.

### M014 Data-flow breakpoints (2026-11-22)

Ingest wrote `radar.article` every 5 minutes but theme-radar re-fetched RSS;
backtest results were written to `radar.path_backtest` but the page read JSON;
APIs existed that no page called.
Enforced by: `lint:table-has-reader` (every written table needs a reader),
`lint:dataset-has-caller` (every endpoint needs a caller in `front/src`),
`lint:front-api-only` (front never fetches static JSON). Current breakpoints
are listed with reasons in `lint/baseline.json` and drop out as they are fixed.

### M015 Reported counts without checking ("13 Mac jobs" when there were 11)

Enforced by: `process` + `python3 lint/repo_lint.py facts`, which prints the
real counts (jobs, LaunchAgents, tables, endpoints, workflows). Quote those.

### M016 Screenshots used fake price data without saying so up front

The cloud could not reach Yahoo, so the K-line screenshot showed made-up prices.
Enforced by: `process` (CLAUDE.md: label mock data in the image and the first
line of the message, or do not send it).

### M017 Front-end read static JSON instead of the API

Pages kept `fetch('./data/*.json')` after the relational cut-over was planned.
Enforced by: `lint:front-api-only`.

### M018 Basic-score percentile computed over a changing candidate list

The candidate set changes every hour, so percentiles (and scores) jumped hourly
even when the stock did not change. Fixed 2026-11-22: percentiles run over the
fixed fundamentals universe (`job/data/fundamentals`, scripts/moat_screen.py).
Enforced by: `test:tests/test_moat_screen.py` (`test_fundamental_score_uses_the_fixed_universe_not_the_candidate_list`).

### M019 Sentiment skew: radar mostly negative while TAIEX was bullish

Enforced by: `process` (needs a runtime metric: bullish share of directional
events vs. TAIEX direction). Not lintable from source.

### M020 Remote Control runs blocked by Mac auto mode; scripts needed secrets only the user had

Enforced by: `process` (CLAUDE.md: scripts read secrets from
`~/.config/nexus-theme-radar/*.env`, never prompt mid-run; check permissions
before starting an RC run).

### M021 Confusing instructions to the user

Users were asked to do things Claude could do (create a repo), given role and
connection-string jargon, and sent long multi-option replies.
Enforced by: `process` (CLAUDE.md: give the exact command or click path, one
option, values copied from `db/roles.json`).

### M022 Secrets in the repo (preventive)

Enforced by: `lint:secrets` (database URLs with real passwords, API keys,
tokens, private keys, `.env`/`runner.env`/private OPML files).

### M023 Units mislabelled: 三大法人 shares shown as 張 (#46)

Enforced by: `process`; add a test when the flows view is next touched.

### M024 A layer imported another layer's code

Enforced by: `test:tests/test_layer_boundaries.py`.

### M025 Wide grid overflowed under the right rail (護城河篩選, 題材 × 法人)

PR #52 shipped the moat rule table with ~800px of fixed grid columns
(`minmax(130px, …) 70px 44px … minmax(220px, …)`). The main column sits next to
the 280-320px rail, so on a 1280-1440px laptop it is ~600-670px wide; the table
spilled under the rail and the 「為什麼這樣設」 column was clipped. The 題材 × 法人
table on 題材動能 had the same problem. Root cause: responsiveness was done only
with viewport `@media (max-width: 719px)`, which never fires at laptop width
even though the column is narrow; nobody checked the sum of the fixed tracks.
Fixed 2026-11-23: `.fd-main` is a named container (`fdmain`), wide rows collapse
in `@container fdmain (max-width: …)`, moat block replaced by a ? popover.
Enforced by: `lint:responsive-grid` (a `grid-template-columns` whose fixed
minimum tracks + gaps exceed 600px must use `minmax(0, …)`, be collapsed by an
`@container` rule in the same file, or declare `min-width` as an explicit
horizontal-scroll table).

### M026 Market-moving company/person news dropped: matcher only knew sector words (2026-11-23)

黃仁勳 left and then returned as NVIDIA CEO (TAIEX swung 1,200+ points). Ingest
stored about 120 such headlines in two days, but the theme matcher only had
sector keywords (AI 伺服器, CoWoS, 散熱 ...) and no NVIDIA/輝達/黃仁勳 entry, so
"黃仁勳回鍋輝達執行長" scored 0 and was dropped before the TW-relevance step,
where nothing counts drops. The pre-market path table matched NVIDIA only with
order/ban words, so the English headline had no path either. Fixed: curated
theme `nvidia_supply_chain` (輝達供應鏈) and NVIDIA leadership patterns in
`us_tech_rally`.
Enforced by: `test:tests/test_theme_membership.py`
(`test_nvidia_and_jensen_huang_news_reaches_the_tw_supply_chain`),
`test:tests/test_pre_market.py` (`test_nvidia_leadership_news_has_a_path`).
