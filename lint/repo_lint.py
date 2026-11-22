#!/usr/bin/env python3
"""Repo lint: every rule here exists because the mistake already happened once.

Each rule names the docs/MISTAKES.md entry (M0xx) it prevents. Stdlib only, so
it runs the same in the git hooks, in CI and from Claude Code hooks.

  python3 lint/repo_lint.py check            # changed files vs origin/master + repo rules
  python3 lint/repo_lint.py check --all      # every tracked file + repo rules (CI)
  python3 lint/repo_lint.py check --staged   # staged files (pre-commit)
  python3 lint/repo_lint.py check FILE...    # just these files
  python3 lint/repo_lint.py facts            # counts to quote instead of guessing (M015)
  python3 lint/repo_lint.py install-hooks    # git config core.hooksPath .githooks
  python3 lint/repo_lint.py hook claude-post # Claude Code PostToolUse (Edit/Write)
  python3 lint/repo_lint.py hook claude-bash # Claude Code PreToolUse (git commit/push)

Suppress one line with a trailing comment `lint-ok: <rule-id>` and a reason.
Known, accepted findings live in lint/baseline.json (each with a reason); they
print as "known" and do not fail. New findings fail.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
LINT_DIR = ROOT / "lint"
MAX_BYTES = 1_000_000
SKIP_GLOBS = (
    "job/data/*", "*/node_modules/*", "front/dist/*", "*.lock", "*package-lock.json",
    "*.min.js", "*.png", "*.jpg", "*.jpeg", "*.webp", "*.gif", "*.ico", "*.pdf",
    "*.woff", "*.woff2", "*.ttf", "*.zip", "*.gz",
)


@dataclass(frozen=True)
class Finding:
    rule: str
    mistake: str
    path: str
    line: int
    message: str
    key: str = ""

    def baseline_key(self) -> str:
        return self.key or f"{self.path}:{self.message}"

    def render(self) -> str:
        loc = f"{self.path}:{self.line}" if self.line else self.path
        return f"{loc}: [{self.rule} / {self.mistake}] {self.message}"


@dataclass
class FileRule:
    id: str
    mistake: str
    globs: tuple[str, ...]
    check: Callable[[str, str], Iterable[tuple[int, str]]]
    exclude: tuple[str, ...] = ()

    def applies(self, path: str) -> bool:
        if any(fnmatch.fnmatch(path, g) for g in self.exclude):
            return False
        return any(fnmatch.fnmatch(path, g) for g in self.globs)


@dataclass
class RepoRule:
    id: str
    mistake: str
    check: Callable[[], Iterable[Finding]]


def _load_json(name: str) -> dict:
    return json.loads((LINT_DIR / name).read_text(encoding="utf-8"))


def _roles() -> dict:
    return json.loads((ROOT / "db" / "roles.json").read_text(encoding="utf-8"))


def _suppressed(line: str, rule_id: str) -> bool:
    return f"lint-ok: {rule_id}" in line or "lint-ok: all" in line


def _lines(text: str) -> Iterable[tuple[int, str]]:
    return enumerate(text.splitlines(), start=1)


# =============================================================== file rules

# ---- M022 secrets -----------------------------------------------------------
_PG_URL = re.compile(r"postgres(?:ql)?://([^:/\s@'\"`]+):([^@\s'\"`]+)@")
_TOKENS = [
    (re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{24,}"), "API key (sk-...)"),
    (re.compile(r"\bghp_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}"), "GitHub token"),
    (re.compile(r"\bsb_secret_[A-Za-z0-9_-]{16,}"), "Supabase secret key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "JWT"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "private key"),
]
_FAKE_PASSWORDS = ("hunter2", "secret", "password", "pass", "pw", "example", "changeme", "test")


def _placeholder(pw: str) -> bool:
    low = pw.lower()
    return (
        any(c in pw for c in "<[{$*") or "..." in pw or "密碼" in pw or "xxx" in low
        or low in _FAKE_PASSWORDS or low.startswith(("your", "new", "the_"))
        or len(pw) < 8  # real Supabase passwords are long; short ones are test fixtures
    )


def check_secrets(path: str, text: str):
    for no, line in _lines(text):
        for match in _PG_URL.finditer(line):
            if not _placeholder(match.group(2)):
                yield no, "database URL with a real-looking password; keep it in runner.env / Vercel env"
        for pattern, label in _TOKENS:
            if pattern.search(line):
                yield no, f"{label} committed; move it to an env file that is gitignored"


SECRET_FILES = (
    ".env", "*/.env", ".env.*", "*/.env.*", "*runner.env", "*analyst.env", "*vercel-secrets.env",
    "job/feeds/follow.opml", "job/feeds/*.private.opml", "*.pem", "*.p12", "*cookies.json",
)


# ---- M009 / M008 supabase host + project ref -----------------------------------
# a real 20-char project ref, or an instruction placeholder like db.<ref> / db.[ref] / db.xxx
_DIRECT_HOST = re.compile(r"\bdb\.([a-z0-9]{20}|<[^>]*>|\[[^\]]*\]|x{3,}|YOUR[-_A-Z]*)\.supabase\.co\b")
_PROJECT_HOST = re.compile(r"\b([a-z0-9]{20})\.supabase\.(?:co|in)\b")


def check_direct_host(path: str, text: str):
    for no, line in _lines(text):
        for match in _DIRECT_HOST.finditer(line):
            if match:
                yield no, ("direct host db.<ref>.supabase.co is IPv6-only and fails on the Mac; "
                           "use the Session pooler host (see db/roles.json connection)")


def check_project_ref(path: str, text: str):
    roles = _roles()
    current = roles["project"]["ref"]
    retired = set(roles["project"].get("retired_refs", []))
    for no, line in _lines(text):
        for ref in retired:
            if ref in line:
                yield no, f"retired Supabase project {ref}; the radar lives in {current}"
        for match in _PROJECT_HOST.finditer(line):
            ref = match.group(1)
            if ref != current and ref not in retired:
                yield no, f"unknown Supabase project {ref}; current project is {current} (db/roles.json)"


# ---- M010 DB role registry -------------------------------------------------------
_URL_USER = re.compile(r"postgres(?:ql)?://([A-Za-z_][A-Za-z0-9_]*)(?:\.[A-Za-z0-9<>\-]+)?[:@]")
_ROLE_STMT = re.compile(
    r"\b(?:create\s+role|alter\s+role|drop\s+role(?:\s+if\s+exists)?)\s+([a-z_][a-z0-9_]*)"
    r"|\bgrant\s+[a-z_][a-z0-9_]*\s+to\s+([a-z_][a-z0-9_]*)"
    r"|\brevoke\s+[a-z_][a-z0-9_]*\s+from\s+([a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)
_ROLE_LIKE = re.compile(r"^(?:radar|theme_radar|site_metrics)_[a-z0-9_]+$")
_PROMPT_ROLE = re.compile(r"\b([a-z_][a-z0-9_]*)\s*(?:的)?\s*(?:連線字串|connection string|login)", re.IGNORECASE)
_BUILTIN_ROLES = {"postgres", "authenticated", "anon", "service_role", "public", "authenticator", "pg_read_all_data"}


def check_db_roles(path: str, text: str):
    roles = _roles()
    logins = set(roles["login_roles"])
    groups = set(roles["group_roles"])
    known = logins | groups | set(roles.get("local_test_roles", []))
    for no, line in _lines(text):
        for match in _URL_USER.finditer(line):
            user = match.group(1)
            if user == "postgres" and "postgres.<" not in line:
                yield no, "connection string uses the postgres superuser; use a login role from db/roles.json"
            elif user in groups:
                yield no, f"{user} is a NOLOGIN group role; connect as one of its login roles ({', '.join(roles['group_roles'][user]['logins'])})"
            elif _ROLE_LIKE.match(user) and user not in logins:
                yield no, f"unknown DB login {user}; add it to db/roles.json or use an existing login"
        for match in _ROLE_STMT.finditer(line):
            role = next(g for g in match.groups() if g)
            if "_" not in role or role.lower() in _BUILTIN_ROLES or role.startswith(("pg_", "supabase")):
                continue
            if role not in known:
                yield no, f"role {role} is not in db/roles.json (wrong name? radar_writer vs theme_radar_app vs radar_api)"
        for match in _PROMPT_ROLE.finditer(line):
            if match.group(1) in groups:
                yield no, f"asks for a {match.group(1)} connection string, but {match.group(1)} cannot log in"


# ---- M005 wording ------------------------------------------------------------------
def _wording():
    data = _load_json("wording.json")
    return data


def check_euphemism(path: str, text: str):
    data = _wording()
    for no, line in _lines(text):
        for term, fix in data["euphemisms"].items():
            if term in line:
                yield no, f"「{term}」不要用委婉說法，直接寫 {fix}"


def check_taiwan_terms(path: str, text: str):
    data = _wording()
    simplified = set(data["simplified_chars"])
    for no, line in _lines(text):
        for term, fix in data["mainland_terms"].items():
            if term in line:
                yield no, f"大陸用語「{term}」，台灣用「{fix}」"
        bad = sorted({c for c in line if c in simplified})
        if bad:
            yield no, f"簡體字 {''.join(bad)}；UI 一律繁體（台灣）"


# ---- M004 color convention -----------------------------------------------------------
_HEX = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def _hue_family(value: str) -> str | None:
    low = value.lower()
    if "red" in low or "--up" in low or "rose" in low:
        return "red"
    if "green" in low or "--down" in low or "emerald" in low or "teal" in low:
        return "green"
    match = _HEX.search(value)
    if not match:
        return None
    h = match.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    if r > g + 40 and r > b + 20:
        return "red"
    if g > r + 40 and g >= b - 10:
        return "green"
    return None


_VAR_DEF = re.compile(r"--(up|down)\s*:\s*([^;]+);")
_CHART_COLOR = re.compile(r"\b(upColor|borderUpColor|wickUpColor|downColor|borderDownColor|wickDownColor)\s*:\s*([^,}\n]+)")
_CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_UP_SEL = re.compile(r"(is-up|\.up\b|positive|is-bull|\.bull\b|gain|is-rise)", re.IGNORECASE)
_DOWN_SEL = re.compile(r"(is-down|\.down\b|negative|is-bear|\.bear\b|loss|is-fall)", re.IGNORECASE)
_TV_WIDGET = re.compile(r"s3\.tradingview\.com|embed-widget-|new\s+TradingView\.widget")


def check_colors(path: str, text: str):
    for no, line in _lines(text):
        for match in _VAR_DEF.finditer(line):
            want = "red" if match.group(1) == "up" else "green"
            got = _hue_family(match.group(2))
            if got and got != want:
                yield no, f"--{match.group(1)} must be {want} (台股 紅漲綠跌), got {match.group(2).strip()}"
        for match in _CHART_COLOR.finditer(line):
            want = "red" if "Up" in match.group(1) or match.group(1) == "upColor" else "green"
            got = _hue_family(match.group(2))
            if got and got != want:
                yield no, f"{match.group(1)} must be {want} (紅漲綠跌), got {match.group(2).strip()}"
        if _TV_WIDGET.search(line):
            yield no, "TradingView embed widget cannot be recoloured (shows 綠漲紅跌); use the own KLineChart"
    if path.endswith(".css"):
        for match in _CSS_RULE.finditer(text):
            selector, body = match.group(1), match.group(2)
            no = text.count("\n", 0, match.start(2)) + 1
            if "lint-ok: color-convention" in body:
                continue
            uses_green = re.search(r"var\(--(green|down)\)", body)
            uses_red = re.search(r"var\(--(red|up)\)", body)
            if _UP_SEL.search(selector) and not _DOWN_SEL.search(selector) and uses_green and not uses_red:
                yield no, f"up/bull selector `{selector.strip()[:60]}` painted green; up is red"
            if _DOWN_SEL.search(selector) and not _UP_SEL.search(selector) and uses_red and not uses_green:
                yield no, f"down/bear selector `{selector.strip()[:60]}` painted red; down is green"


# ---- M017 front reads only /api -------------------------------------------------------
_STATIC_FETCH = re.compile(r"""fetch\(\s*[`'"]([^`'"]*)[`'"]""")
_JSON_IMPORT = re.compile(r"""from\s+['"]([^'"]*(?:/data/|job/)[^'"]*\.json)['"]""")


def check_front_api_only(path: str, text: str):
    for no, line in _lines(text):
        for match in _STATIC_FETCH.finditer(line):
            url = match.group(1)
            if url.endswith(".json") or "/data/" in url or "raw.githubusercontent" in url:
                yield no, f"front fetches static data {url!r}; every page reads /api (relational tables)"
        for match in _JSON_IMPORT.finditer(line):
            yield no, f"front bundles pipeline data {match.group(1)!r}; read it through /api"


# ---- M001 pipeline dual import ----------------------------------------------------------
def check_dual_import(path: str, text: str):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return
    if re.search(r"sys\.path\.(insert|append)\(", text):
        return  # the file puts the repo root on sys.path itself
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ImportFrom) and (node.module or "").startswith("scripts")):
            continue
        guarded = False
        cur = node
        while cur in parents:
            parent = parents[cur]
            if isinstance(parent, ast.Try) and cur in parent.body:
                names = []
                for handler in parent.handlers:
                    t = handler.type
                    names += [getattr(e, "id", "") for e in (t.elts if isinstance(t, ast.Tuple) else [t])] if t else ["*"]
                if any(n in ("ModuleNotFoundError", "ImportError", "*") for n in names):
                    guarded = True
                    break
            cur = parent
        if not guarded:
            yield node.lineno, (f"`from {node.module} import` dies when the Mac runs the script by path; "
                                "wrap it in try/except ModuleNotFoundError with the bare-module fallback")


# ---- M013 one scheduler ------------------------------------------------------------------
def check_workflow_schedule(path: str, text: str):
    for no, line in _lines(text):
        if re.match(r"^\s*schedule\s*:", line):
            yield no, "GitHub `schedule:` trigger; every schedule lives in job/mac/jobs.conf (workflows are workflow_dispatch fallbacks)"


def check_pg_cron(path: str, text: str):
    for no, line in _lines(text):
        if re.search(r"\bcron\.schedule\s*\(", line) and not line.lstrip().startswith("--"):
            yield no, "pg_cron schedule; every schedule lives in job/mac/jobs.conf"


FILE_RULES: list[FileRule] = [
    FileRule("secrets", "M022", ("*",), check_secrets, exclude=("lint/*", "tests/test_repo_lint.py")),
    FileRule("supabase-direct-host", "M009", ("*",), check_direct_host, exclude=("lint/*", "tests/test_repo_lint.py", "docs/MISTAKES.md", "db/roles.json")),
    FileRule("supabase-project-ref", "M008", ("*",), check_project_ref, exclude=("lint/*", "tests/test_repo_lint.py", "db/roles.json", "docs/MISTAKES.md")),
    FileRule("db-role-registry", "M010", ("*.sh", "*.sql", "*.md", "*.py", "*.js", "*.mjs", "*.ts", "*.yml", "*.conf"), check_db_roles,
             exclude=("lint/*", "tests/test_repo_lint.py", "docs/MISTAKES.md")),
    FileRule("wording-euphemism", "M005", ("front/src/*", "front/*.html", "backend/api/*", "job/scripts/*.py", "job/mac/prompts/*", "job/personas/*"),
             check_euphemism),
    FileRule("wording-taiwan", "M005", ("front/src/*.ts", "front/src/*.tsx", "front/src/*.js", "front/*.html", "backend/api/*.js"),
             check_taiwan_terms),
    FileRule("color-convention", "M004", ("front/src/*", "front/*.html", "front/legacy/*", "front/classic/*", "backend/api/*.js"), check_colors),
    FileRule("front-api-only", "M017", ("front/src/*.ts", "front/src/*.tsx", "front/src/*.js"), check_front_api_only),
    FileRule("job-dual-import", "M001", ("job/scripts/*.py",), check_dual_import),
    FileRule("no-github-schedule", "M013", (".github/workflows/*.yml", ".github/workflows/*.yaml"), check_workflow_schedule),
    FileRule("no-pg-cron", "M013", ("db/*.sql",), check_pg_cron),
]


# =============================================================== repo rules

def rule_migration_versions() -> Iterable[Finding]:
    seen: dict[str, str] = {}
    for path in sorted((ROOT / "db" / "supabase" / "migrations").glob("*.sql")):
        version = path.name.split("_", 1)[0]
        rel = path.relative_to(ROOT).as_posix()
        if version in seen:
            yield Finding("migration-unique-version", "M003", rel, 0,
                          f"migration version {version} also used by {seen[version]}; supabase applies only one", key=version)
        seen[version] = rel


def _load_ntr():
    spec = importlib.util.spec_from_file_location("_ntr_for_lint", ROOT / "job" / "mac" / "ntr.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[spec.name] = module  # dataclasses look the module up while it executes
    spec.loader.exec_module(module)
    return module


_SCRIPT_REF = re.compile(r"\b(?:python3?|bash)\s+((?:scripts|mac)/[A-Za-z0-9_./-]+)")
_WRITES_DATA = re.compile(r"--(?:data|output)-dir\s+data\b")


def rule_jobs_conf() -> Iterable[Finding]:
    rel = "job/mac/jobs.conf"
    try:
        jobs = _load_ntr().load_jobs(ROOT / rel)
    except Exception as exc:  # noqa: BLE001 - any parse failure is the finding
        yield Finding("jobs-conf", "M013", rel, 0, f"jobs.conf does not parse: {exc}", key="parse")
        return
    for job in jobs:
        for script in _SCRIPT_REF.findall(job.command):
            if not (ROOT / "job" / script).exists():
                yield Finding("jobs-conf", "M013", rel, 0, f"job {job.name} runs missing {script}", key=f"{job.name}:{script}")
        if not job.data_lock and _WRITES_DATA.search(job.command):
            yield Finding("jobs-conf", "M013", rel, 0,
                          f"job {job.name} writes data/ but is on @nolock; two writers can collide", key=f"nolock-writer:{job.name}")


_CREATE_TABLE = re.compile(r"create\s+table\s+(?:if\s+not\s+exists\s+)?([a-z_]+)\.([a-z_0-9]+)", re.IGNORECASE)


def _tables() -> list[tuple[str, str]]:
    out = set()
    for path in (ROOT / "db" / "supabase" / "migrations").glob("*.sql"):
        out.update((s.lower(), t.lower()) for s, t in _CREATE_TABLE.findall(path.read_text(encoding="utf-8")))
    return sorted(out)


def _read_tree(base: Path, suffixes: tuple[str, ...]) -> dict[str, str]:
    out = {}
    if not base.exists():
        return out
    for path in base.rglob("*"):
        if path.suffix in suffixes and "node_modules" not in path.parts and path.is_file():
            out[path.relative_to(ROOT).as_posix()] = path.read_text(encoding="utf-8", errors="ignore")
    return out


_SQL_WRITE = re.compile(r"(?:insert\s+into|update|merge\s+into|copy)\s+([a-z_]+\.[a-z_0-9]+)", re.IGNORECASE)
_SQL_READ = re.compile(r"(?:from|join)\s+([a-z_]+\.[a-z_0-9]+)", re.IGNORECASE)
_QUOTED = re.compile(r"['\"]([a-z_][a-z_0-9]*)['\"]")
_WORD = re.compile(r"[a-z_][a-z_0-9]*")


def rule_table_has_reader() -> Iterable[Finding]:
    """A table somebody writes but nobody reads is a data-flow breakpoint (M014)."""
    job = _read_tree(ROOT / "job" / "scripts", (".py", ".sql", ".sh"))
    job.update(_read_tree(ROOT / "job" / "mac", (".py", ".sh")))
    backend = _read_tree(ROOT / "backend" / "api", (".js", ".mjs", ".py"))
    front = _read_tree(ROOT / "front" / "src", (".ts", ".tsx", ".js"))
    db_sql = _read_tree(ROOT / "db" / "supabase", (".sql", ".ts", ".js"))
    writes: dict[str, set[str]] = {}   # "schema.table" or bare "table" -> writer files
    for path, text in {**job, **db_sql}.items():
        for name in {m.lower() for m in _SQL_WRITE.findall(text)} | set(_QUOTED.findall(text)):
            writes.setdefault(name, set()).add(path)
    reads: set[str] = set()
    for text in {**front, **job, **db_sql}.values():
        reads.update(m.lower() for m in _SQL_READ.findall(text))
    for text in backend.values():  # backend is read-only (radar_api): any mention is a read
        reads.update(_WORD.findall(text))
    for schema, table in _tables():
        qualified = f"{schema}.{table}"
        writers = writes.get(qualified, set()) | writes.get(table, set())
        if not writers or qualified in reads or table in reads:
            continue
        yield Finding("table-has-reader", "M014", sorted(writers)[0], 0,
                      f"{qualified} is written ({', '.join(sorted(writers)[:2])}) but nothing reads it",
                      key=qualified)


_DATASET_KEY = re.compile(r"^\s*'([a-z0-9-]+)'\s*:", re.MULTILINE)


def rule_dataset_has_caller() -> Iterable[Finding]:
    """An API nobody calls is the other half of a breakpoint (M014)."""
    front = "\n".join(_read_tree(ROOT / "front" / "src", (".ts", ".tsx", ".js")).values())
    index = ROOT / "backend" / "api" / "_lib" / "datasets" / "index.js"
    if index.exists():
        for name in _DATASET_KEY.findall(index.read_text(encoding="utf-8")):
            if f"'{name}'" not in front and f'"{name}"' not in front and f"/api/v1/{name}" not in front:
                yield Finding("dataset-has-caller", "M014", "backend/api/_lib/datasets/index.js", 0,
                              f"/api/v1/{name} has no caller in front/src", key=f"v1/{name}")
    for path in sorted((ROOT / "backend" / "api").rglob("*")):
        if path.suffix not in (".js", ".py") or "_lib" in path.parts or path.name.startswith("["):
            continue
        endpoint = path.relative_to(ROOT / "backend").with_suffix("").as_posix()
        if endpoint not in front:
            yield Finding("dataset-has-caller", "M014", path.relative_to(ROOT).as_posix(), 0,
                          f"/{endpoint} has no caller in front/src", key=endpoint)


def rule_vercelignore() -> Iterable[Finding]:
    path = ROOT / ".vercelignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = {line.strip() for line in text.splitlines()}
    for need in ("job/*", "backend/", "front/node_modules/", ".venv/"):
        if need not in lines and need.rstrip("/*") + "/" not in lines:
            yield Finding("vercelignore", "M012", ".vercelignore", 0,
                          f".vercelignore must exclude {need} (a CLI deploy once uploaded 656 MB and hit the free limit)",
                          key=need)


_MISTAKE_ID = re.compile(r"^###\s+(M\d{3})\b", re.MULTILINE)
_ENFORCED = re.compile(r"`lint:([a-z0-9-]+)`")


def rule_mistakes_log() -> Iterable[Finding]:
    log = ROOT / "docs" / "MISTAKES.md"
    text = log.read_text(encoding="utf-8") if log.exists() else ""
    ids = set(_MISTAKE_ID.findall(text))
    rule_ids = {r.id: r.mistake for r in FILE_RULES} | {r.id: r.mistake for r in REPO_RULES}
    for rid, mistake in rule_ids.items():
        if mistake not in ids:
            yield Finding("mistakes-log", "M000", "docs/MISTAKES.md", 0, f"rule {rid} cites {mistake}, which has no entry", key=rid)
    for rid in sorted(set(_ENFORCED.findall(text)) - set(rule_ids)):
        yield Finding("mistakes-log", "M000", "docs/MISTAKES.md", 0, f"entry cites lint:{rid}, which does not exist", key=f"cite:{rid}")


REPO_RULES: list[RepoRule] = [
    RepoRule("migration-unique-version", "M003", rule_migration_versions),
    RepoRule("jobs-conf", "M013", rule_jobs_conf),
    RepoRule("table-has-reader", "M014", rule_table_has_reader),
    RepoRule("dataset-has-caller", "M014", rule_dataset_has_caller),
    RepoRule("vercelignore", "M012", rule_vercelignore),
    RepoRule("mistakes-log", "M000", rule_mistakes_log),
]


# =============================================================== engine

def _skip(path: str) -> bool:
    return any(fnmatch.fnmatch(path, g) for g in SKIP_GLOBS)


def lint_text(path: str, text: str) -> list[Finding]:
    findings = []
    if any(fnmatch.fnmatch(path, g) for g in SECRET_FILES) and not path.endswith(".example"):
        findings.append(Finding("secrets", "M022", path, 0, "secret/private file must not be committed", key=path))
    lines = text.splitlines()
    for rule in FILE_RULES:
        if not rule.applies(path):
            continue
        for no, message in rule.check(path, text):
            if no and no <= len(lines) and _suppressed(lines[no - 1], rule.id):
                continue
            findings.append(Finding(rule.id, rule.mistake, path, no, message))
    return findings


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout


def tracked_files() -> list[str]:
    return [p for p in _git("ls-files").splitlines() if p]


def staged_files() -> list[str]:
    return [p for p in _git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines() if p]


def changed_files() -> list[str]:
    base = _git("merge-base", "HEAD", "origin/master").strip()
    names = set()
    if base:
        names.update(_git("diff", "--name-only", "--diff-filter=ACMR", base).splitlines())
    names.update(_git("diff", "--name-only", "--diff-filter=ACMR", "HEAD").splitlines())
    names.update(_git("ls-files", "--others", "--exclude-standard").splitlines())
    return sorted(p for p in names if p)


def _read(path: str, staged: bool) -> str | None:
    if staged:
        out = subprocess.run(["git", "show", f":{path}"], cwd=ROOT, capture_output=True, check=False).stdout
        data = out
    else:
        full = ROOT / path
        if not full.is_file() or full.stat().st_size > MAX_BYTES:
            return None
        data = full.read_bytes()
    if len(data) > MAX_BYTES or b"\0" in data[:4096]:
        return None
    return data.decode("utf-8", errors="ignore")


def run(paths: list[str], staged: bool = False, repo_rules: bool = True) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if _skip(path) and not any(fnmatch.fnmatch(path, g) for g in SECRET_FILES):
            continue
        text = _read(path, staged)
        if text is None:
            if any(fnmatch.fnmatch(path, g) for g in SECRET_FILES):
                findings.append(Finding("secrets", "M022", path, 0, "secret/private file must not be committed", key=path))
            continue
        findings.extend(lint_text(path, text))
    if repo_rules:
        for rule in REPO_RULES:
            findings.extend(rule.check())
    return findings


def split_baseline(findings: list[Finding]) -> tuple[list[Finding], list[Finding], list[str]]:
    baseline = _load_json("baseline.json")
    new, known, hit = [], [], set()
    for f in findings:
        entries = baseline.get(f.rule, {})
        k = f.baseline_key()
        match = k if k in entries else (f.path if f.path in entries else None)  # a path entry covers the whole file
        if match:
            known.append(f)
            hit.add((f.rule, match))
        else:
            new.append(f)
    stale = [f"{rule}: {key}" for rule, entries in baseline.items() if not rule.startswith("_")
             for key in entries if (rule, key) not in hit]
    return new, known, stale


def report(findings: list[Finding], full: bool, out=sys.stderr) -> int:
    new, known, stale = split_baseline(findings)
    if known:
        print(f"repo-lint: {len(known)} known finding(s) in lint/baseline.json (not blocking)", file=out)
    if full and stale:
        print("repo-lint: baseline entries no longer found, remove them from lint/baseline.json:", file=out)
        for s in stale:
            print(f"  - {s}", file=out)
    if not new:
        print("repo-lint: OK", file=out)
        return 0
    print(f"repo-lint: {len(new)} problem(s). Each rule cites the past mistake in docs/MISTAKES.md.", file=out)
    for f in new:
        print("  " + f.render(), file=out)
    print("Fix it, or add `lint-ok: <rule>` with a reason on the line, or a reasoned entry in lint/baseline.json.", file=out)
    return 1


# =============================================================== facts (M015)

def facts() -> dict:
    jobs = _load_ntr().load_jobs(ROOT / "job" / "mac" / "jobs.conf")
    tables = _tables()
    index = ROOT / "backend" / "api" / "_lib" / "datasets" / "index.js"
    datasets = _DATASET_KEY.findall(index.read_text(encoding="utf-8")) if index.exists() else []
    endpoints = sorted(
        p.relative_to(ROOT / "backend").with_suffix("").as_posix()
        for p in (ROOT / "backend" / "api").rglob("*") if p.suffix in (".js", ".py") and "_lib" not in p.parts
    )
    workflows = sorted(p.name for p in (ROOT / ".github" / "workflows").glob("*.y*ml"))
    by_schema: dict[str, int] = {}
    for schema, _ in tables:
        by_schema[schema] = by_schema.get(schema, 0) + 1
    return {
        "mac_jobs": {"count": len(jobs), "names": [j.name for j in jobs],
                     "launch_agents": [j.label for j in jobs]},
        "migrations": len(list((ROOT / "db" / "supabase" / "migrations").glob("*.sql"))),
        "tables": {"count": len(tables), "by_schema": by_schema},
        "api_v1_datasets": {"count": len(datasets), "names": datasets},
        "api_endpoints": {"count": len(endpoints), "names": endpoints},
        "github_workflows": {"count": len(workflows), "names": workflows},
        "db_logins": _roles()["login_roles"],
    }


# =============================================================== hooks

def install_hooks() -> int:
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=ROOT, check=True)
    print("repo-lint: git hooks active (core.hooksPath=.githooks)")
    return 0


def _hook_input() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}


def hook_claude_post() -> int:
    data = _hook_input()
    tool_input = data.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not file_path:
        return 0
    try:
        rel = Path(file_path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return 0
    findings = run([rel], repo_rules=False)
    new, _, _ = split_baseline(findings)
    if not new:
        return 0
    print(f"repo-lint blocked {rel}: these repeat past mistakes (docs/MISTAKES.md):", file=sys.stderr)
    for f in new:
        print("  " + f.render(), file=sys.stderr)
    return 2


_GIT_SHIP = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(commit|push)\b")


def hook_claude_bash() -> int:
    data = _hook_input()
    command = (data.get("tool_input") or {}).get("command", "")
    if not _GIT_SHIP.search(command):
        return 0
    findings = run(changed_files())
    new, _, _ = split_baseline(findings)
    if not new:
        return 0
    print("repo-lint: fix these before committing/pushing (each repeats a mistake in docs/MISTAKES.md):", file=sys.stderr)
    for f in new:
        print("  " + f.render(), file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    check = sub.add_parser("check")
    check.add_argument("--all", action="store_true")
    check.add_argument("--staged", action="store_true")
    check.add_argument("--no-repo-rules", action="store_true")
    check.add_argument("files", nargs="*")
    sub.add_parser("facts")
    sub.add_parser("install-hooks")
    hook = sub.add_parser("hook")
    hook.add_argument("kind", choices=["claude-post", "claude-bash"])
    args = parser.parse_args(argv)

    if args.cmd == "facts":
        print(json.dumps(facts(), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "install-hooks":
        return install_hooks()
    if args.cmd == "hook":
        return hook_claude_post() if args.kind == "claude-post" else hook_claude_bash()
    if args.all:
        paths, staged = tracked_files(), False
    elif args.staged:
        paths, staged = staged_files(), True
    elif args.files:
        paths, staged = [Path(f).resolve().relative_to(ROOT).as_posix() for f in args.files], False
    else:
        paths, staged = changed_files(), False
    return report(run(paths, staged=staged, repo_rules=not args.no_repo_rules), full=args.all)


if __name__ == "__main__":
    sys.exit(main())
