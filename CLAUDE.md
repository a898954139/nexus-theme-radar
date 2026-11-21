# Claude Code Notes

Before changing this project, read:

- `skills/ai-news-radar/SKILL.md`
- `docs/SOURCE_COVERAGE.md`
- `README.md`
- `skills/pipeline-changes/SKILL.md` — before touching anything the hourly
  pipeline run executes

## Layers (one repo, deployed separately)

| Folder | What | Runs on |
|---|---|---|
| `front/` | Vite site, static | Vercel project at the repo root (`vercel.json`) |
| `backend/` | API (`backend/api`), reads the radar tables | its own Vercel project, root `backend/`; front rewrites `/api/*` to it |
| `job/` | pipelines (`job/scripts`), config, `job/data` state, schedule | the owner's Mac via launchd (`job/mac/jobs.conf`) |
| `db/` | Supabase migrations (`db/supabase`) | shared contract |

A layer never imports another layer's code (`tests/test_layer_boundaries.py`).
Schedules live only in `job/mac/jobs.conf` (the remaining GitHub `schedule:`
blocks are removed at the Mac cut-over); never add pg_cron jobs.
Python commands run from `job/` (`cd job && .venv/bin/python scripts/...`).
Cross-layer tests stay in the root `tests/`.

Do not commit private OPML files, API keys, cookies, browser exports, or `.env`
values. Keep the public repo usable without secrets.

The product direction is a two-layer AI news tool:

- Default layer: curated AI-focused view for ordinary AI enthusiasts.
- Advanced layer: custom OPML/source configuration and source health details for maintainers.

When adding sources, prefer official RSS/Atom feeds or OPML first. Add custom
fetchers only for stable, public, high-signal sources.
