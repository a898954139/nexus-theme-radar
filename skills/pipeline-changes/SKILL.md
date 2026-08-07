---
name: pipeline-changes
description: "Use when changing anything the hourly GitHub Actions run executes — scripts/update_theme_radar.py, any scripts/*.py it imports, the workflow file, or the published JSON schema. Covers the two ways this repo's pipeline breaks silently: an import that only resolves locally, and a published-payload field the page validators reject. Also use when a scheduled run fails, when the site renders a fallback, or before pushing anything under scripts/."
---

# Changing the hourly pipeline

Local green does not mean CI green here. The two failure modes below have each
already shipped a break to `master` that passed every local test.

## Before you push: run the entrypoint the way CI does

The workflow runs (`.github/workflows/update-theme-radar.yml`):

```bash
python scripts/update_theme_radar.py --output-dir data --window-hours 72 ...
```

Invoking the file by path puts `scripts/` on `sys.path[0]`, so **the `scripts.`
package path does not exist during a real run**. pytest runs from the repo
root, where it does. A module importing a sibling as `from scripts.x import y`
therefore passes every local test and kills the hourly run:

```
ModuleNotFoundError: No module named 'scripts'
```

Every module the entrypoint pulls in needs the dual import `update_theme_radar`
already carries:

```python
try:
    from scripts.theme_symbol_fundamentals import attach_symbol_fundamentals
except ModuleNotFoundError:
    from theme_symbol_fundamentals import attach_symbol_fundamentals
```

The check that catches this — run it before pushing any change under `scripts/`:

```bash
.venv/bin/python scripts/update_theme_radar.py --help
```

Exit 0 means the import graph resolves the way CI resolves it. `tests/test_fundamentals_pipeline.py`
pins this by importing from inside `scripts/`; keep that test passing.

## Adding a field to the published JSON

`data/public-theme-momentum-latest-v0.9.json` is validated by **two separate
front-ends**, both with exact key-count checks (`hasExactKeys` / `hasHomepageMomentumKeys`,
i.e. `keys.length === requiredKeys.length`). An undeclared field does not
degrade one card — it fails the whole payload, and the page renders its
fallback with no console error and a 200 on every request.

Adding a per-theme field means updating all three:

| File | What to update |
|---|---|
| `scripts/update_theme_radar.py` | where the field is written |
| `assets/theme-momentum.js` | `themeKeys` in `validateLatest` |
| `assets/app.js` | the key list in `validateHomepageMomentumLatestTheme` |

Then confirm the real file still validates:

```bash
.venv/bin/python -m pytest tests/test_homepage_theme_momentum_entry.py tests/test_theme_momentum_stock_fundamentals.py -q
```

Both suites assert against `data/public-theme-momentum-latest-v0.9.json` itself,
so a field added to the writer but not the validators turns them red.

## When a scheduled run fails

Ask which commit it started failing on before assuming an infrastructure fault.
Runner-acquisition errors and a real crash look similar in the Actions UI, and
"GitHub is broken" has twice been the wrong answer here:

```bash
gh run list --repo a898954139/nexus-theme-radar \
  --workflow update-theme-radar.yml --limit 15 \
  --json createdAt,status,conclusion,headSha,event
```

A clean run of successes that turns to failures at one SHA is your change. Two
signals separate the cases:

- **`steps recorded: 0`** and no log — the job never started; that is a real
  runner problem, and re-running is the only move.
- **A named failing step** — read it, it is a genuine error:

```bash
gh run view <id> --repo a898954139/nexus-theme-radar --log-failed
```

Do not manually dispatch a run to "check" while a scheduled one is pending —
concurrency cancels one of them, and the cancellation then looks like a fresh
failure.

## Scraped sources stay contained

Goodinfo is a scraped third party inside a pipeline whose actual job is theme
momentum. Anything reaching it must:

- fetch only what the quarterly throttle says is due (`symbols_due_for_refresh`)
- stay under a per-run fetch budget, and log what it deferred
- treat every failure as "no fundamentals for this symbol", never propagate

A metric that cannot be parsed is **omitted and recorded in `missing`**. Never
default it to `0` — downstream that reads as a real measurement, and the model
consuming it is explicitly forbidden from inventing support.

Fetching is on by default; `THEME_RADAR_FUNDAMENTALS=0` disables it without
disturbing statements already in the committed cache. Tests that exercise the
momentum pipeline must set that variable to `0` (see the autouse fixture in
`tests/test_update_theme_radar.py`) or they will hit the live site.

## Running the tests

Always use the venv. The system pytest lacks `feedparser`/`requests`, so it
fails at collection with 17 errors — including inside the pre-push hook:

```bash
.venv/bin/python -m pytest -q
PATH="$PWD/.venv/bin:$PATH" git push origin master
```
