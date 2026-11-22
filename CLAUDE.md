# Claude Code Notes

Before changing this project, read:

- `skills/ai-news-radar/SKILL.md`
- `docs/SOURCE_COVERAGE.md`
- `README.md`
- `skills/pipeline-changes/SKILL.md` — before touching anything the hourly
  pipeline run executes
- `docs/MISTAKES.md` — every mistake made so far; `skills/mistake-to-lint/SKILL.md`
  when you find a new one

## Layers (one repo, deployed separately)

| Folder | What | Runs on |
|---|---|---|
| `front/` | Vite site, static | Vercel project at the repo root (`vercel.json`) |
| `backend/` | API (`backend/api`), reads the radar tables | its own Vercel project, root `backend/`; front rewrites `/api/*` to it |
| `job/` | pipelines (`job/scripts`), config, `job/data` state, schedule | the owner's Mac via launchd (`job/mac/jobs.conf`) |
| `db/` | Supabase migrations (`db/supabase`) | shared contract |

A layer never imports another layer's code (`tests/test_layer_boundaries.py`).
Schedules live only in `job/mac/jobs.conf`: no GitHub `schedule:` (workflows
are manual `workflow_dispatch` fallbacks), never pg_cron.
Python commands run from `job/` (`cd job && .venv/bin/python scripts/...`).
Cross-layer tests stay in the root `tests/`.

Do not commit private OPML files, API keys, cookies, browser exports, or `.env`
values. Keep the public repo usable without secrets.

The product direction is a two-layer AI news tool:

- Default layer: curated AI-focused view for ordinary AI enthusiasts.
- Advanced layer: custom OPML/source configuration and source health details for maintainers.

When adding sources, prefer official RSS/Atom feeds or OPML first. Add custom
fetchers only for stable, public, high-signal sources.

## Repo lint (past mistakes as checks)

`lint/repo_lint.py` encodes `docs/MISTAKES.md` as rules. It runs in the git
hooks (`python3 lint/repo_lint.py install-hooks`; the Claude Code SessionStart
hook does it for you), in CI (`repo-lint.yml`), after every Claude Edit/Write
and before every `git commit`/`git push` Claude runs (`.claude/settings.json`).
A block means the change repeats a logged mistake: fix it, or baseline it with
a reason (see the skill). New mistake → new entry + rule, same PR.

## Verification rules (process mistakes M010, M011, M015, M016, M020, M021)

- Counts and names (jobs, LaunchAgents, tables, endpoints, logins): copy from
  `python3 lint/repo_lint.py facts`, never from memory.
- DB roles, hosts and connection strings: copy from `db/roles.json`. Always the
  Session pooler, never the IPv6-only Direct connection host; never a NOLOGIN group role as
  a user. The backend must use read-only `radar_api`.
- Mock or placeholder data in a screenshot or preview: say so in the image and
  in the first line of the message, or do not send it.
- Scripts the user runs read secrets from `~/.config/nexus-theme-radar/*.env`;
  do not prompt for them mid-run. Check Mac permissions before starting an RC run.
- Instructions to the user: one option, exact command or click path, values
  already filled in. Do it yourself when you can.
