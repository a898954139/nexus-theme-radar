Produce today's pre-market analysis reports. This is an unattended scheduled
run: nobody will answer questions, so never stop to ask.

Report date: {{REPORT_DATE}}
Work dir: {{WORK_DIR}}

1. Your working directory is the repository's `job/` folder. Read
   `../skills/daily-analysis-report/SKILL.md` and follow its steps exactly,
   running its commands from here, with the report date and work dir above.
2. For the per-stock judgement, read and apply
   `~/.agents/skills/nexus-market-analysis/SKILL.md`.
3. If `pull` exits 3, stop: there is no list today.
4. If `push` exits 2, fix only the files it lists and push again (at most 3 tries).
5. Finish with the `status` output and one line: pushed count, skipped stocks and why.

Never fetch prices yourself, never invent a missing number, and never touch
files outside the work dir except reading this repository and the skills folder.
