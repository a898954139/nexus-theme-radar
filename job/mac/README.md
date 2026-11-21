# Mac scheduler (the only scheduler)

Every recurring nexus-theme-radar job runs on the owner's Mac through launchd.
This is the **job layer** (`job/`); see the repository README for the
front / backend / job / db split.
GitHub workflows keep `workflow_dispatch` only (manual fallback), and pg_cron
has no radar jobs. One file decides what runs when: [`jobs.conf`](jobs.conf).

| Path on the Mac | What |
|---|---|
| `~/.nexus-radar/runner` | dedicated clone of `master`; jobs run from its `job/` folder (not the iCloud dev clone) |
| `~/.nexus-radar/runner/job/.venv` | Python venv for the job layer |
| `~/.nexus-radar/runner/job/data/` | phase 1: local pipeline state (previous snapshots / history the scripts read). Not committed anywhere. |
| `~/.config/nexus-theme-radar/runner.env` | `THEME_RADAR_DATABASE_URL` (radar_writer login), `FINNHUB_API_KEY`, optional `NTR_HC_PING_KEY`. Mode 600. |
| `~/.config/nexus-theme-radar/analyst.env` | `RADAR_ANALYST_DATABASE_URL` for the 07:30 report (already created by the PRD setup) |
| `~/Library/LaunchAgents/com.nexus.themeradar.*.plist` | generated; never edit by hand |
| `~/Library/Logs/nexus-radar/<job>.log` | one log per job, rotated at 5 MB by `prune-logs` |
| `~/Library/Application Support/nexus-radar/state.json` | last start / exit / seconds per job |

## Schedule (Asia/Taipei)

| Job | When | Replaces |
|---|---|---|
| ingest | every 5 min | pg_cron → Vercel `/api/cron/ingest` (3 jobs, removed) |
| pre-market | 06:05, 07:05, 08:05, then hourly :35 | `update-pre-market.yml` |
| analysis-prepare | Mon–Fri 06:10 (06:40 retry; first success freezes the list) | `prepare-analysis-queue.yml` |
| analysis-report | Mon–Fri 07:30 | local Claude scheduled task |
| theme-radar | hourly :17 | `update-theme-radar.yml` |
| institutional-flows | Mon–Fri 17:20 | `update-institutional-flows.yml` |
| backtest-paths | Mon–Fri 17:50 | `backtest-paths.yml` |
| analysis-warm | Mon–Fri 20:10 | `prepare-analysis-queue.yml` warm slot |
| broker-data | Mon–Fri 21:30 | `update-broker-data.yml` |
| prune-logs | daily 03:15 | pg_cron `cron.job_run_details` purge |
| sync | hourly :50 | — (fast-forwards the runner, reloads changed schedules) |

## Commands

```bash
cd ~/.nexus-radar/runner/job
.venv/bin/python mac/ntr.py status        # loaded? last run? exit code
.venv/bin/python mac/ntr.py run theme-radar
tail -f ~/Library/Logs/nexus-radar/theme-radar.log
.venv/bin/python mac/ntr.py install       # after editing jobs.conf by hand
.venv/bin/python mac/ntr.py uninstall     # rollback: stops every job
```

To change a schedule: edit `jobs.conf`, merge to `master`; the next `sync`
(hourly :50) reloads the LaunchAgents. `sync` never reloads itself; run
`install` once if you change `sync`'s own line.

## Behaviour

- launchd never starts a job while its previous run is still going; `ntr.py
  run` also holds a per-job lock, so a manual run and a scheduled one never overlap.
- Jobs that write `data/` (and `sync`) share one lock and wait up to 60 min.
  `@nolock` in `jobs.conf` lists the ones that don't touch `data/`.
- If the Mac was asleep at a scheduled time, launchd runs the job once when it
  wakes (missed runs are coalesced, not replayed).
- Each run pings `https://hc-ping.com/<NTR_HC_PING_KEY>/ntr-<job>` (`/start`,
  success, `/fail` with the last 60 log lines) when the key is set; checks are
  created automatically. Set the `ntr-ingest` check to period 5 min / grace
  15 min: it doubles as the "Mac is alive" heartbeat.

## Risk: the Mac is a laptop

Lid closed or asleep = no data. Mitigations, in order of value:

1. Keep it on power and stop sleep on AC: `sudo pmset -c sleep 0 disksleep 0`
   (display sleep is fine). Closed lid still sleeps unless an external display
   is attached.
2. `sudo pmset repeat wakeorpoweron MTWRFSU 05:55:00` wakes it before the
   pre-market run (not guaranteed with the lid closed).
3. Healthchecks.io alerts (above) tell you when it stopped, from outside the Mac.
4. Cloud fallback stays available but off: `gh workflow run update-theme-radar.yml`
   (and the other workflows) still works by hand. Those runs commit `data/`
   to `master`; the Mac's next `sync` then refuses to fast-forward until the
   runner's `data/` is reset (`git -C ~/.nexus-radar/runner checkout -- job/data && ntr.py sync`).

## Rollback

1. `ntr.py uninstall` (stops every Mac job immediately).
2. Revert the PR that removed the workflow `schedule:` blocks (cloud jobs resume).
3. News ingest has no cloud fallback any more (the Vercel `/api/cron/ingest`
   endpoint was removed with the layer split); run `ntr.py run ingest` by hand.

## Phase 2 (not done yet)

Drop `data/` as pipeline state: each script reads its previous state from the
`radar` tables instead of `data/*.json`, then `data/` is untracked. Before
untracking, copy the runner's `data/` aside: pulling a `git rm --cached`
commit deletes the working files.
