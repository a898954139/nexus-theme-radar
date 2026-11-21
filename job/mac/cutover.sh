#!/usr/bin/env bash
# nexus-theme-radar：分層（front / backend / job / db）上線 + 所有排程收回 Mac。可重複執行。
#
#   One-shot cut-over (2026-11-21). Kept for the record and for --rollback.
#   bash ~/Downloads/ntr-mac-cutover.sh            # 完整切換
#   bash ~/Downloads/ntr-mac-cutover.sh --check    # 只做前置檢查 + 建 backend 專案並驗證，不合併、不動排程
#   bash ~/Downloads/ntr-mac-cutover.sh --rollback # 卸載 Mac 排程（程式碼回滾請 Claude revert PR）
#
# 步驟
#   0 前置檢查            1 runner clone（PR 分支）+ job/.venv + secrets + DB 檢查
#   2 backend Vercel 專案 nexus-theme-radar-api（Root Directory=backend，複製 API env）
#   3 部署 backend 並驗證 15 個 /api/v1 端點         ← --check 到這裡為止
#   4 等雲端 Actions 跑完 → 合併 PR（分層 + 拿掉 workflow schedule）
#   5 等網站新版上線，經 rewrite 驗證 /api/v1          6 pg_cron unschedule
#   7 runner 對齊 master，試跑 ingest / pre-market / theme-radar
#   8 載入 launchd        9 電源設定（可選）          10 盤點其他 LaunchAgents
# 不印任何 secret；輸出同時寫到 ~/Downloads/ntr-mac-cutover-result.txt
#
# ROLLBACK
#   Mac：~/.nexus-radar/runner/job/.venv/bin/python ~/.nexus-radar/runner/job/mac/ntr.py uninstall
#   網站 + 雲端排程：revert 合併的 PR（舊專案會自動重新部署舊版，API 回到舊專案）
set -euo pipefail
umask 077

GH_REPO=a898954139/nexus-theme-radar
GH_ORG=a898954139
REPO_URL=https://github.com/$GH_REPO
PR_BRANCH=claude/project-thread-b5btsw
SCOPE=a898954139-3687s-projects
FRONT_PROJECT=nexus-theme-radar
API_PROJECT=nexus-theme-radar-api
SITE_URL=https://nexus-theme-radar.vercel.app
API_URL=https://$API_PROJECT.vercel.app          # 必須與 repo 根目錄 vercel.json 的 rewrite 相同
RADAR_REF=xdixmdglgzaiugvfxmuw
LINKED_CLONE="$HOME/Dev/iCloud-dev/nexus-theme-radar"   # 只讀它的 supabase/.temp
RUNNER="$HOME/.nexus-radar/runner"
JOB="$RUNNER/job"
CFG="$HOME/.config/nexus-theme-radar"
ENV_FILE="$CFG/runner.env"
RESULT="$HOME/Downloads/ntr-mac-cutover-result.txt"
MODE=${1:-full}
API_ENV_KEYS="RADAR_API_DATABASE_URL RADAR_API_DATABASE_CA RADAR_TRACKING_API_KEYS RADAR_API_MAX_AGE_MINUTES RADAR_TRACKING_API_MAX_AGE_MINUTES"
ENDPOINTS="institutional-rankings institutional-flows?symbol=2330 broker-stats broker-coverage broker-map?symbol=2330 theme-focus source-status theme-events theme-ranking theme-momentum theme-momentum-history stock-watchlist fundamentals?symbol=2330 pre-market stock-audit"

exec > >(tee "$RESULT") 2>&1
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
step() { printf '\n== %s\n' "$1"; }
ok()   { printf '   OK   %s\n' "$1"; }
warn() { printf '   WARN %s\n' "$1"; }
fail() { printf '   FAIL %s\n' "$1"; printf '\nRESULT: FAIL (%s)\n' "$1"; exit 1; }
printf 'ntr-mac-cutover %s mode=%s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$MODE"
NTR() { "$JOB/.venv/bin/python" "$JOB/mac/ntr.py" "$@"; }
jget() { python3 -c 'import json,sys
d=json.load(sys.stdin)
for k in sys.argv[1].split("."):
    d = d.get(k) if isinstance(d, dict) else None
print("" if d is None else d)' "$1"; }

if [ "$MODE" = "--rollback" ]; then
  step "ROLLBACK: unload every Mac job"
  if [ -x "$JOB/.venv/bin/python" ]; then NTR uninstall || true; fi
  ok "Mac jobs removed. 程式碼 / 雲端排程：請 Claude revert 已合併的 PR"
  printf '\nRESULT: ROLLED BACK\n'; exit 0
fi

# ---------- 0 前置 ----------
step "0 Preflight"
ZONE=$(readlink /etc/localtime || true)
case "$ZONE" in *Asia/Taipei) ok "time zone Asia/Taipei" ;; *) fail "time zone is $ZONE (需 Asia/Taipei)" ;; esac
for bin in git python3 gh supabase curl; do command -v "$bin" >/dev/null || fail "missing command: $bin"; done
gh auth status >/dev/null 2>&1 || fail "gh not logged in (gh auth login)"
python3 -c 'import sys;sys.exit(sys.version_info<(3,10))' || fail "python3 < 3.10"
ok "git gh supabase curl python3"
command -v claude >/dev/null && ok "claude CLI $(command -v claude)" || warn "claude CLI not on PATH: 07:30 analysis-report will fail until it is"
[ -f "$CFG/analyst.env" ] && ok "analyst.env present" || warn "$CFG/analyst.env missing: 07:30 analysis-report will fail"
PR=$(gh pr list -R "$GH_REPO" --head "$PR_BRANCH" --state open --json number --jq '.[] | .number' | head -1 || true)
[ -n "$PR" ] && ok "open PR #$PR on $PR_BRANCH" || warn "no open PR on $PR_BRANCH (already merged?)"

VTOKEN=${VERCEL_TOKEN:-}
if [ -z "$VTOKEN" ]; then
  for f in "$HOME/Library/Application Support/com.vercel.cli/auth.json" "$HOME/.local/share/com.vercel.cli/auth.json"; do
    [ -f "$f" ] && VTOKEN=$(jget token < "$f") && break
  done
fi
[ -n "$VTOKEN" ] || fail "no Vercel token (先 vercel login，或 export VERCEL_TOKEN=...)"
vapi() { curl -sS -m 60 -H "Authorization: Bearer $VTOKEN" -H "Content-Type: application/json" "$@"; }
Q="slug=$SCOPE"
FRONT_ID=$(vapi "https://api.vercel.com/v9/projects/$FRONT_PROJECT?$Q" | jget id)
[ -n "$FRONT_ID" ] || fail "Vercel token cannot read project $FRONT_PROJECT"
ok "Vercel token works ($SCOPE)"

# ---------- 1 runner ----------
step "1 Runner clone ($RUNNER) + job/.venv + secrets"
if [ ! -d "$RUNNER/.git" ]; then
  mkdir -p "$(dirname "$RUNNER")"
  git clone -q "$REPO_URL" "$RUNNER" || fail "git clone"
fi
if [ -n "$PR" ]; then
  git -C "$RUNNER" fetch -q origin "$PR_BRANCH" && git -C "$RUNNER" checkout -q --detach FETCH_HEAD || fail "checkout $PR_BRANCH"
else
  git -C "$RUNNER" fetch -q origin master && git -C "$RUNNER" checkout -q -B master FETCH_HEAD || fail "checkout master"
fi
[ -f "$JOB/mac/ntr.py" ] || fail "runner has no job/mac/ntr.py"
ok "runner @ $(git -C "$RUNNER" rev-parse --short HEAD)"
[ -x "$JOB/.venv/bin/python" ] || python3 -m venv "$JOB/.venv" || fail "venv"
"$JOB/.venv/bin/pip" install -q --upgrade pip >/dev/null 2>&1 || true
"$JOB/.venv/bin/pip" install -q -r "$JOB/requirements.txt" || fail "pip install"
ok "job/.venv ready"

mkdir -p "$CFG"; touch "$ENV_FILE"; chmod 600 "$ENV_FILE"
have() { grep -qE "^(export )?$1=." "$ENV_FILE"; }
ask() {  # $1 name, $2 hint, $3 required(1/0)
  if have "$1"; then ok "$1 set"; return; fi
  printf '   %s（%s）%s: ' "$1" "$2" "$([ "$3" = 1 ] && echo '' || echo '，可直接 Enter 跳過')"
  local v=""; IFS= read -rs v || true; echo
  if [ -z "$v" ]; then [ "$3" = 1 ] && fail "$1 is required"; warn "$1 skipped"; return; fi
  printf '%s=%s\n' "$1" "$v" >> "$ENV_FILE"; ok "$1 saved"
}
ask THEME_RADAR_DATABASE_URL "radar_writer 連線字串，與 GitHub secret THEME_RADAR_DATABASE_URL 相同" 1
ask FINNHUB_API_KEY "盤前看板用，與 GitHub secret 相同" 0
ask NTR_HC_PING_KEY "healthchecks.io 專案的 Ping key，斷線警報用" 0

( set -a; . "$ENV_FILE"; set +a; cd "$JOB"
  .venv/bin/python - <<'PY' || exit 1
import os, psycopg
with psycopg.connect(os.environ["THEME_RADAR_DATABASE_URL"], connect_timeout=15, prepare_threshold=None) as c:
    row = c.execute("select current_user, pg_has_role(current_user,'radar_writer','member'), to_regclass('radar.pipeline_run') is not null").fetchone()
    print(f"   login={row[0]} radar_writer={row[1]} radar_tables={row[2]}")
    raise SystemExit(0 if row[1] and row[2] else 1)
PY
) || fail "THEME_RADAR_DATABASE_URL cannot write radar (wrong project or role?)"
for s in update_theme_radar update_pre_market ingest_runner radar_publish; do
  (cd "$JOB" && .venv/bin/python "scripts/$s.py" --help >/dev/null) || fail "job/scripts/$s.py --help"
done
NTR list >/dev/null || fail "job/mac/jobs.conf does not parse"
ok "radar_writer login, imports, jobs.conf"

# ---------- 2 backend 專案 ----------
step "2 Vercel project $API_PROJECT (Root Directory = backend)"
API_ID=$(vapi "https://api.vercel.com/v9/projects/$API_PROJECT?$Q" | jget id)
if [ -z "$API_ID" ]; then
  BODY=$(python3 -c 'import json,sys;print(json.dumps({"name":sys.argv[1],"framework":None,"rootDirectory":"backend","gitRepository":{"type":"github","repo":sys.argv[2]}}))' "$API_PROJECT" "$GH_REPO")
  RESP=$(vapi -X POST "https://api.vercel.com/v11/projects?$Q" -d "$BODY")
  API_ID=$(printf '%s' "$RESP" | jget id)
  [ -n "$API_ID" ] || fail "create project: $(printf '%s' "$RESP" | jget error.message)"
  ok "created $API_PROJECT"
else
  ok "$API_PROJECT exists"
fi
ROOTDIR=$(vapi "https://api.vercel.com/v9/projects/$API_ID?$Q" | jget rootDirectory)
if [ "$ROOTDIR" != backend ]; then
  vapi -X PATCH "https://api.vercel.com/v9/projects/$API_ID?$Q" -d '{"rootDirectory":"backend","framework":null}' >/dev/null
  ok "rootDirectory set to backend"
fi

# 從前端專案複製 API 需要的 env（敏感值讀不回來時改問你）
vapi "https://api.vercel.com/v9/projects/$FRONT_PROJECT/env?$Q" > "$TMP/envs.json"
vapi "https://api.vercel.com/v9/projects/$API_ID/env?$Q" > "$TMP/api-envs.json"
[ -f "$CFG/vercel-secrets.env" ] && . "$CFG/vercel-secrets.env"
for key in $API_ENV_KEYS; do
  EID=$(python3 -c 'import json,sys
for e in json.load(open(sys.argv[1])).get("envs",[]):
    if e["key"]==sys.argv[2] and "production" in (e.get("target") or []): print(e["id"]); break' "$TMP/envs.json" "$key")
  VAL=""
  [ -n "$EID" ] && VAL=$(vapi "https://api.vercel.com/v1/projects/$FRONT_PROJECT/env/$EID?$Q" | jget value)
  [ -z "$VAL" ] && [ "$key" = RADAR_TRACKING_API_KEYS ] && VAL=${RADAR_TRACKING_API_KEYS:-}
  if [ -z "$VAL" ] && python3 -c 'import json,sys
sys.exit(0 if any(e["key"]==sys.argv[2] for e in json.load(open(sys.argv[1])).get("envs",[])) else 1)' "$TMP/api-envs.json" "$key"; then
    ok "env $key already on $API_PROJECT (kept)"; continue
  fi
  if [ -z "$VAL" ] && [ "$key" = RADAR_API_DATABASE_URL ]; then
    printf '   RADAR_API_DATABASE_URL 讀不回來（敏感變數）。請貼上 radar_api 唯讀連線字串: '
    IFS= read -rs VAL || true; echo
    [ -n "$VAL" ] || fail "RADAR_API_DATABASE_URL is required for the backend"
  fi
  if [ -z "$VAL" ]; then [ -n "$EID" ] && warn "$key unreadable, not copied" || true; continue; fi
  BODY=$(KEY="$key" VAL="$VAL" python3 -c 'import json,os;print(json.dumps({"key":os.environ["KEY"],"value":os.environ["VAL"],"type":"encrypted","target":["production","preview"]}))')
  R=$(vapi -X POST "https://api.vercel.com/v10/projects/$API_ID/env?upsert=true&$Q" -d "$BODY")
  [ -n "$(printf '%s' "$R" | jget error.message)" ] && fail "env $key: $(printf '%s' "$R" | jget error.message)"
  ok "env $key"
done

# ---------- 3 部署 backend 並驗證 ----------
step "3 Deploy backend from ${PR:+PR branch }${PR:-master} and verify"
REF=${PR:+$PR_BRANCH}; REF=${REF:-master}
BODY=$(python3 -c 'import json,sys;print(json.dumps({"name":sys.argv[1],"project":sys.argv[1],"target":"production","gitSource":{"type":"github","org":sys.argv[2],"repo":sys.argv[3],"ref":sys.argv[4]}}))' "$API_PROJECT" "$GH_ORG" "${GH_REPO#*/}" "$REF")
RESP=$(vapi -X POST "https://api.vercel.com/v13/deployments?$Q" -d "$BODY")
DID=$(printf '%s' "$RESP" | jget id)
[ -n "$DID" ] || fail "deploy: $(printf '%s' "$RESP" | jget error.message)"
for i in $(seq 1 60); do
  STATE=$(vapi "https://api.vercel.com/v13/deployments/$DID?$Q" | jget readyState)
  case "$STATE" in READY) break ;; ERROR|CANCELED) fail "backend deployment $STATE (Vercel → $API_PROJECT → Deployments 看 log)" ;; esac
  sleep 10
done
[ "$STATE" = READY ] || fail "backend deployment not ready after 10 min"
ok "backend deployment READY"

verify() {  # $1 base url, $2 label
  local pass=0 failed=0 c src
  for e in $ENDPOINTS; do
    c=$(curl -s -m 30 -o "$TMP/body" -D "$TMP/hdr" -w '%{http_code}' "$1/api/v1/$e" || echo 000)
    src=$(grep -i '^x-radar-source:' "$TMP/hdr" | tr -d '\r' | awk '{print $2}' || true)
    if [ "$c" = 200 ] && [ "$src" = db ]; then pass=$((pass+1))
    else failed=$((failed+1)); printf '   %s  %s  %s\n' "$c" "$e" "$(head -c 100 "$TMP/body" | tr '\n' ' ')"; fi
  done
  [ "$failed" -eq 0 ] || return 1
  ok "$2: $pass endpoints 200 from db"
}
verify "$API_URL" "$API_URL" || fail "backend endpoints (若 $API_URL 不是這個專案的網域，請告訴 Claude 改 vercel.json rewrite)"

if [ "$MODE" = "--check" ]; then printf '\nRESULT: CHECK OK (backend 已上線但網站還沒切過去；排程未變更)\n'; exit 0; fi

# ---------- 4 合併 PR ----------
step "4 Wait for in-flight Actions, then merge PR #${PR:-none}"
if [ -n "$PR" ]; then
  for i in $(seq 1 40); do
    BUSY=$(gh run list -R "$GH_REPO" --limit 30 --json status --jq '[.[]|select(.status=="in_progress" or .status=="queued")]|length')
    [ "$BUSY" = 0 ] && break
    printf '   wait: %s Actions runs in flight\n' "$BUSY"; sleep 30
  done
  gh pr ready "$PR" -R "$GH_REPO" >/dev/null 2>&1 || true
  gh pr merge "$PR" -R "$GH_REPO" --squash >/dev/null || fail "merge PR #$PR"
  MERGE_SHA=$(gh pr view "$PR" -R "$GH_REPO" --json mergeCommit --jq .mergeCommit.oid)
  ok "merged PR #$PR (${MERGE_SHA:0:7}): layers + workflow schedules removed"
else
  MERGE_SHA=$(git ls-remote "$REPO_URL" refs/heads/master | cut -f1)
  ok "nothing to merge (master ${MERGE_SHA:0:7})"
fi

# ---------- 5 網站新版 ----------
step "5 Front deployment of ${MERGE_SHA:0:7} and API through the rewrite"
for i in $(seq 1 60); do
  vapi "https://api.vercel.com/v6/deployments?projectId=$FRONT_ID&target=production&limit=5&$Q" > "$TMP/deps.json"
  FSTATE=$(python3 -c 'import json,sys
for d in json.load(open(sys.argv[1])).get("deployments",[]):
    if (d.get("meta") or {}).get("githubCommitSha")==sys.argv[2]: print(d.get("readyState") or d.get("state")); break' "$TMP/deps.json" "$MERGE_SHA")
  case "$FSTATE" in READY) break ;; ERROR|CANCELED) fail "front deployment $FSTATE (rollback: revert PR #$PR)" ;; esac
  sleep 10
done
[ "$FSTATE" = READY ] || fail "front deployment of ${MERGE_SHA:0:7} not ready after 10 min"
c=$(curl -s -m 30 -o /dev/null -w '%{http_code}' "$SITE_URL/") ; [ "$c" = 200 ] || fail "$SITE_URL/ returned $c"
verify "$SITE_URL" "$SITE_URL (rewrite → backend)" || fail "site API through rewrite (rollback: revert PR #$PR)"

# ---------- 6 pg_cron ----------
step "6 Unschedule pg_cron radar jobs"
WORK="$TMP/sb"; mkdir -p "$WORK/supabase/.temp"
cp "$LINKED_CLONE/supabase/.temp/project-ref" "$WORK/supabase/.temp/" 2>/dev/null || true
[ -f "$LINKED_CLONE/supabase/.temp/pooler-url" ] && cp "$LINKED_CLONE/supabase/.temp/pooler-url" "$WORK/supabase/.temp/"
if [ "$(cat "$WORK/supabase/.temp/project-ref" 2>/dev/null)" = "$RADAR_REF" ]; then
  HELP=$(supabase db query --help 2>&1 || true)
  TARGET=--linked; grep -q -- '--remote' <<<"$HELP" && TARGET=--remote
  YES=--agent=no;  grep -q -- '--yes' <<<"$HELP" && YES=--yes
  cat > "$WORK/q.sql" <<'SQL'
do $$
declare j record;
begin
  if to_regclass('cron.job') is null then raise notice 'pg_cron not installed'; return; end if;
  for j in select jobname from cron.job where jobname like 'radar-ingest-%' loop
    perform cron.unschedule(j.jobname);
  end loop;
end $$;
select case when to_regclass('cron.job') is null then 'pg_cron not installed' else 'done' end as status;
SQL
  if OUT=$(supabase db query "$TARGET" "$YES" --agent=no --workdir "$WORK" -o csv -f "$WORK/q.sql" 2>&1); then
    printf '%s\n' "$OUT" | grep -viE 'password|postgresql://|new version|recommend|deprecated|^Target:|posthog' | tail -2
    ok "pg_cron radar jobs removed on $RADAR_REF"
  else
    warn "pg_cron step failed: $(printf '%s' "$OUT" | grep -viE 'password|postgresql://' | tail -1)"
  fi
else
  warn "linked clone is not $RADAR_REF; skipped pg_cron"
fi

# ---------- 7 runner + 試跑 ----------
step "7 Runner on master + smoke runs (寫入 PRD，與雲端排程做的事相同)"
git -C "$RUNNER" checkout -q -- . 2>/dev/null || true
git -C "$RUNNER" fetch -q origin master && git -C "$RUNNER" checkout -q -B master FETCH_HEAD || fail "runner checkout master"
git -C "$RUNNER" branch -q --set-upstream-to=origin/master master 2>/dev/null || true
"$JOB/.venv/bin/pip" install -q -r "$JOB/requirements.txt" || fail "pip install"
ok "runner @ $(git -C "$RUNNER" rev-parse --short HEAD)"
for job in ingest pre-market theme-radar; do
  printf '   run %s ...\n' "$job"
  if NTR run "$job" > "$TMP/$job.log" 2>&1; then ok "$job"; else tail -15 "$TMP/$job.log"; fail "$job smoke run (雲端排程已停：可先 gh workflow run 手動補)"; fi
done

# ---------- 8 launchd ----------
step "8 Load launchd jobs"
NTR install || fail "ntr install"
NTR status || true

# ---------- 9 電源 ----------
step "9 Power (optional, needs sudo)"
pmset -g custom 2>/dev/null | grep -E '^ *(sleep|disksleep) ' | sed 's/^/   now: /' || true
printf '   插電時不睡眠 + 每天 05:55 喚醒？[y/N] '; read -r yn || yn=n
if [ "$yn" = y ] || [ "$yn" = Y ]; then
  sudo pmset -c sleep 0 disksleep 0 && sudo pmset repeat wakeorpoweron MTWRFSU 05:55:00 && ok "pmset set" || warn "pmset failed"
else
  warn "power unchanged: Mac 睡眠時資料會停"
fi

# ---------- 10 盤點 ----------
step "10 Other LaunchAgents (inventory only, not changed)"
ls "$HOME/Library/LaunchAgents" 2>/dev/null | grep -iE 'nexus|radar|claude' | sed 's/^/   /' || true

printf '\nRESULT: OK  (網站=front，API=%s，排程=Mac；狀態：cd %s && .venv/bin/python mac/ntr.py status)\n' "$API_URL" "$JOB"
