#!/usr/bin/env bash
# Daily pre-market report, local half (skills/daily-analysis-report).
# Scheduled by job/mac/jobs.conf (analysis-report). Runs headless Claude Code
# with a narrow tool allowlist, then checks the result in the DB itself so a
# chatty-but-failed Claude run is still reported as a failure.
#
# Needs RADAR_ANALYST_DATABASE_URL (ntr.py loads ~/.config/nexus-theme-radar/analyst.env).
set -uo pipefail

D=$(TZ=Asia/Taipei date +%F)
W="$HOME/.nexus-radar/daily-report/$D"
PY=.venv/bin/python
CLAUDE_BIN=${NTR_CLAUDE_BIN:-$(command -v claude || true)}

[ -n "${RADAR_ANALYST_DATABASE_URL:-}" ] || { echo "analysis-report: RADAR_ANALYST_DATABASE_URL not set"; exit 1; }
[ -n "$CLAUDE_BIN" ] || { echo "analysis-report: claude CLI not on PATH (set NTR_CLAUDE_BIN)"; exit 1; }

# No frozen list today (holiday, or prepare failed) -> nothing to do. prepare's
# own failure is alerted by the analysis-prepare job.
"$PY" scripts/local_analysis_report.py status --report-date "$D" >/dev/null 2>&1
case $? in
  0) ;;
  3) echo "analysis-report: no batch for $D, skipping"; exit 0 ;;
  *) echo "analysis-report: status check failed"; exit 1 ;;
esac

PROMPT=$(sed -e "s/{{REPORT_DATE}}/$D/g" -e "s#{{WORK_DIR}}#$W#g" mac/prompts/daily-analysis-report.md)

"$CLAUDE_BIN" -p "$PROMPT" \
  --permission-mode acceptEdits \
  --add-dir .. --add-dir "$HOME/.nexus-radar" --add-dir "$HOME/.agents/skills" \
  --allowedTools \
    "Read" "Write" "Edit" "Glob" "Grep" \
    "Bash(.venv/bin/python scripts/local_analysis_report.py:*)" \
    "Bash(.venv/bin/python scripts/analyze_stock_audit_technical.py:*)" \
    "Bash(mkdir:*)" "Bash(ls:*)" "Bash(cat:*)"
rc=$?

done_count=$("$PY" scripts/local_analysis_report.py status --report-date "$D" 2>/dev/null | grep -c ' done$' || true)
echo "analysis-report: claude_exit=$rc reports_done=$done_count report_date=$D"
[ "$done_count" -gt 0 ] || exit 1
