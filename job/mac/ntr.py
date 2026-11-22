#!/usr/bin/env python3
"""Run every nexus-theme-radar scheduled job from one place: launchd on the Mac.

Run from the job layer (job/) of the runner clone:

    .venv/bin/python mac/ntr.py list                 # parsed schedule, Taipei time
    .venv/bin/python mac/ntr.py install              # write + load LaunchAgents
    .venv/bin/python mac/ntr.py uninstall            # unload + remove them (rollback)
    .venv/bin/python mac/ntr.py status               # loaded?, last run, exit code
    .venv/bin/python mac/ntr.py run <job>            # run one job now (what launchd calls)
    .venv/bin/python mac/ntr.py sync                 # fast-forward code, reload schedule
    .venv/bin/python mac/ntr.py prune-logs

The schedule lives only in job/mac/jobs.conf. Secrets live only in
~/.config/nexus-theme-radar/{runner,analyst}.env (mode 600), never in the repo.
Standard library only: launchd runs this before anything is imported.
"""

from __future__ import annotations

import argparse
import collections
import fcntl
import json
import os
import plistlib
import re
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

# The job layer root (job/): jobs run from here, the venv lives here.
REPO = Path(__file__).resolve().parents[1]
CONF_PATH = REPO / "mac" / "jobs.conf"
LABEL_PREFIX = "com.nexus.themeradar."
HOME = Path.home()
CONFIG_DIR = HOME / ".config" / "nexus-theme-radar"
ENV_FILES = ("runner.env", "analyst.env")
STATE_DIR = HOME / "Library" / "Application Support" / "nexus-radar"
LOG_DIR = HOME / "Library" / "Logs" / "nexus-radar"
LAUNCH_DIR = HOME / "Library" / "LaunchAgents"
EXPECTED_TZ = "Asia/Taipei"
HC_BASE = "https://hc-ping.com"
DATA_LOCK_WAIT_SECONDS = 60 * 60
DEFAULT_TIMEOUT_SECONDS = 90 * 60
LOG_ROTATE_BYTES = 5 * 1024 * 1024
SELF_RELOAD_EXEMPT = {"sync"}  # booting out the running job would kill it

WEEKDAYS = (1, 2, 3, 4, 5)  # launchd: 0/7 = Sunday


class ConfError(ValueError):
    pass


@dataclass
class Job:
    name: str
    command: str
    interval_seconds: int | None = None
    calendar: list[dict[str, int]] = field(default_factory=list)
    data_lock: bool = True
    timeout_override: int | None = None

    @property
    def label(self) -> str:
        return LABEL_PREFIX + self.name

    @property
    def timeout_seconds(self) -> int:
        if self.timeout_override:
            return self.timeout_override
        if self.interval_seconds:
            return max(60, self.interval_seconds - 30)
        return DEFAULT_TIMEOUT_SECONDS


# --------------------------------------------------------------------------- conf

_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_NAME = re.compile(r"^[a-z][a-z0-9-]*$")


def _times(spec: str) -> list[tuple[int, int]]:
    out = []
    for part in spec.split(","):
        match = _TIME.match(part.strip())
        if not match:
            raise ConfError(f"bad time {part!r}")
        out.append((int(match.group(1)), int(match.group(2))))
    return out


def parse_when(when: str) -> tuple[int | None, list[dict[str, int]], int | None]:
    interval: int | None = None
    timeout: int | None = None
    calendar: list[dict[str, int]] = []
    for clause in filter(None, (c.strip() for c in when.split(";"))):
        kind, _, rest = clause.partition(" ")
        rest = rest.strip()
        if kind == "every":
            match = re.match(r"^(\d+)m$", rest)
            if not match or int(match.group(1)) < 1:
                raise ConfError(f"bad interval {clause!r}")
            interval = int(match.group(1)) * 60
        elif kind == "timeout":
            match = re.match(r"^(\d+)m$", rest)
            if not match or int(match.group(1)) < 1:
                raise ConfError(f"bad timeout {clause!r}")
            timeout = int(match.group(1)) * 60
        elif kind == "daily":
            calendar += [{"Hour": h, "Minute": m} for h, m in _times(rest)]
        elif kind == "weekdays":
            calendar += [{"Weekday": d, "Hour": h, "Minute": m} for h, m in _times(rest) for d in WEEKDAYS]
        elif kind == "hourly":
            match = re.match(r"^:([0-5]\d)$", rest)
            if not match:
                raise ConfError(f"bad hourly {clause!r}")
            calendar.append({"Minute": int(match.group(1))})
        else:
            raise ConfError(f"unknown schedule {clause!r}")
    if interval and calendar:
        raise ConfError(f"mixes 'every' with calendar times: {when!r}")
    if not interval and not calendar:
        raise ConfError(f"empty schedule {when!r}")
    return interval, calendar, timeout


def parse_conf(text: str) -> list[Job]:
    logical: list[str] = []
    buffer = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if not buffer and (not line.strip() or line.lstrip().startswith("#")):
            continue
        if line.endswith("\\"):
            buffer += line[:-1].strip() + " "
            continue
        logical.append((buffer + line.strip()).strip())
        buffer = ""
    if buffer:
        raise ConfError("file ends with a line continuation")

    nolock: set[str] = set()
    jobs: list[Job] = []
    for line in logical:
        if line.startswith("@nolock"):
            nolock.update(line.split()[1:])
            continue
        parts = [p.strip() for p in line.split("|", 2)]
        if len(parts) != 3 or not all(parts):
            raise ConfError(f"expected 'name | when | command': {line!r}")
        name, when, command = parts
        if not _NAME.match(name):
            raise ConfError(f"bad job name {name!r}")
        if any(j.name == name for j in jobs):
            raise ConfError(f"duplicate job {name!r}")
        interval, calendar, timeout = parse_when(when)
        jobs.append(Job(name, command, interval, calendar, timeout_override=timeout))
    unknown = nolock - {j.name for j in jobs}
    if unknown:
        raise ConfError(f"@nolock names unknown jobs: {sorted(unknown)}")
    for job in jobs:
        job.data_lock = job.name not in nolock
    return jobs


def load_jobs(path: Path = CONF_PATH) -> list[Job]:
    return parse_conf(path.read_text(encoding="utf-8"))


def describe(job: Job) -> str:
    if job.interval_seconds:
        return f"every {job.interval_seconds // 60}m"
    days = {"wd": [], "daily": [], "hourly": []}
    for entry in job.calendar:
        if "Hour" not in entry:
            days["hourly"].append(f":{entry['Minute']:02d}")
        elif "Weekday" in entry:
            stamp = f"{entry['Hour']:02d}:{entry['Minute']:02d}"
            if stamp not in days["wd"]:
                days["wd"].append(stamp)
        else:
            days["daily"].append(f"{entry['Hour']:02d}:{entry['Minute']:02d}")
    parts = []
    if days["daily"]:
        parts.append("daily " + ",".join(days["daily"]))
    if days["wd"]:
        parts.append("Mon-Fri " + ",".join(days["wd"]))
    if days["hourly"]:
        parts.append("hourly " + ",".join(days["hourly"]))
    return "; ".join(parts)


# --------------------------------------------------------------------------- launchd

def render_plist(job: Job, *, repo: Path, python: Path, path_env: str) -> bytes:
    log = str(LOG_DIR / f"{job.name}.log")
    plist: dict = {
        "Label": job.label,
        "ProgramArguments": [str(python), str(repo / "mac" / "ntr.py"), "run", job.name],
        "WorkingDirectory": str(repo),
        "EnvironmentVariables": {"PATH": path_env, "PYTHONUNBUFFERED": "1", "LANG": "en_US.UTF-8"},
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "ProcessType": "Background",
        "RunAtLoad": False,
    }
    if job.interval_seconds:
        plist["StartInterval"] = job.interval_seconds
    else:
        plist["StartCalendarInterval"] = job.calendar
    return plistlib.dumps(plist, sort_keys=True)


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _check_timezone(allow_other: bool) -> None:
    zone = os.path.realpath("/etc/localtime")
    if zone.endswith(EXPECTED_TZ) or allow_other:
        return
    sys.exit(f"Mac time zone is {zone!r}, not {EXPECTED_TZ}; jobs.conf times are Taipei time. "
             "Fix System Settings > General > Date & Time, or pass --allow-other-tz.")


def _path_env(repo: Path) -> str:
    seen: list[str] = []
    candidates = [str(repo / ".venv" / "bin"), *os.environ.get("PATH", "").split(":"),
                  "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    for entry in candidates:
        if entry and entry not in seen:
            seen.append(entry)
    return ":".join(seen)


def cmd_install(args: argparse.Namespace, *, skip_reload: Iterable[str] = ()) -> int:
    _check_timezone(getattr(args, "allow_other_tz", False))
    jobs = load_jobs()
    python = REPO / ".venv" / "bin" / "python"
    if not python.exists():
        sys.exit(f"missing {python}; create the venv first (python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)")
    for directory in (LAUNCH_DIR, LOG_DIR, STATE_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    path_env = _path_env(REPO)
    wanted = {job.label for job in jobs}
    skip = {LABEL_PREFIX + name for name in skip_reload}
    for stale in LAUNCH_DIR.glob(LABEL_PREFIX + "*.plist"):
        if stale.stem not in wanted:
            _launchctl("bootout", f"{_domain()}/{stale.stem}")
            stale.unlink()
            print(f"removed  {stale.stem}")
    for job in jobs:
        target = LAUNCH_DIR / f"{job.label}.plist"
        content = render_plist(job, repo=REPO, python=python, path_env=path_env)
        changed = not target.exists() or target.read_bytes() != content
        target.write_bytes(content)
        loaded = _launchctl("print", f"{_domain()}/{job.label}").returncode == 0
        if job.label in skip and loaded:
            print(f"kept     {job.name:<20} {describe(job)}{' (reloads at next install)' if changed else ''}")
            continue
        if changed or not loaded:
            _launchctl("bootout", f"{_domain()}/{job.label}")
            result = _launchctl("bootstrap", _domain(), str(target))
            if result.returncode != 0:
                print(f"FAILED   {job.name}: {result.stderr.strip()}", file=sys.stderr)
                return 1
            print(f"loaded   {job.name:<20} {describe(job)}")
        else:
            print(f"ok       {job.name:<20} {describe(job)}")
    return 0


def cmd_uninstall(_: argparse.Namespace) -> int:
    for plist in sorted(LAUNCH_DIR.glob(LABEL_PREFIX + "*.plist")):
        _launchctl("bootout", f"{_domain()}/{plist.stem}")
        plist.unlink()
        print(f"removed  {plist.stem}")
    return 0


def _read_state() -> dict:
    try:
        return json.loads((STATE_DIR / "state.json").read_text())
    except (OSError, ValueError):
        return {}


def _write_state(job: str, entry: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_DIR / "state.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = _read_state()
        state[job] = entry
        tmp = STATE_DIR / "state.json.tmp"
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        tmp.replace(STATE_DIR / "state.json")


def cmd_status(_: argparse.Namespace) -> int:
    state = _read_state()
    bad = 0
    print(f"{'job':<20} {'loaded':<7} {'last start':<20} {'exit':<5} {'secs':<6} schedule")
    for job in load_jobs():
        loaded = _launchctl("print", f"{_domain()}/{job.label}").returncode == 0
        last = state.get(job.name, {})
        code = last.get("exit")
        bad += (not loaded) or (code not in (None, 0))
        print(f"{job.name:<20} {'yes' if loaded else 'NO':<7} {last.get('started', '-'):<20} "
              f"{'-' if code is None else code!s:<5} {last.get('seconds', '-')!s:<6} {describe(job)}")
    return 1 if bad else 0


def cmd_list(_: argparse.Namespace) -> int:
    for job in load_jobs():
        lock = "" if job.data_lock else "  [no data lock]"
        print(f"{job.name:<20} {describe(job)}{lock}\n    {job.command}")
    return 0


# --------------------------------------------------------------------------- run

def parse_env_file(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def load_env(config_dir: Path = CONFIG_DIR) -> dict[str, str]:
    env: dict[str, str] = {}
    for name in ENV_FILES:
        path = config_dir / name
        if not path.exists():
            continue
        if path.stat().st_mode & 0o077:
            raise PermissionError(f"{path} must be chmod 600")
        env.update(parse_env_file(path.read_text(encoding="utf-8")))
    # ingest_runner reads its own variable; on the Mac it is the same theme_radar_app login (member of radar_writer).
    if env.get("THEME_RADAR_DATABASE_URL") and not env.get("RADAR_INGEST_DATABASE_URL"):
        env["RADAR_INGEST_DATABASE_URL"] = env["THEME_RADAR_DATABASE_URL"]
    return env


def _ping(env: dict[str, str], job: str, suffix: str = "", body: str = "") -> None:
    key = env.get("NTR_HC_PING_KEY", "").strip()
    if not key:
        return
    url = f"{HC_BASE}/{key}/ntr-{job}{suffix}?create=1"
    try:
        request = urllib.request.Request(url, data=body.encode()[-10000:] or None, method="POST")
        urllib.request.urlopen(request, timeout=10).close()
    except Exception as error:  # noqa: BLE001 - alerting must never fail the job
        print(f"[ntr] healthcheck ping failed: {type(error).__name__}", flush=True)


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def cmd_run(args: argparse.Namespace) -> int:
    jobs = {job.name: job for job in load_jobs()}
    job = jobs.get(args.job)
    if job is None:
        sys.exit(f"unknown job {args.job!r}; known: {', '.join(jobs)}")
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    own = open(STATE_DIR / f"{job.name}.lock", "w")
    try:
        fcntl.flock(own, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[ntr] {_stamp()} {job.name}: previous run still active, skipping", flush=True)
        return 0

    try:
        env_extra = load_env()
    except PermissionError as error:
        print(f"[ntr] {_stamp()} {job.name}: {error}", flush=True)
        return 1
    env = {**os.environ, **env_extra}
    env["PATH"] = f"{REPO / '.venv' / 'bin'}:{env.get('PATH', '')}"

    data_lock = None
    if job.data_lock:
        data_lock = open(STATE_DIR / "data.lock", "w")
        deadline = time.monotonic() + DATA_LOCK_WAIT_SECONDS
        while True:
            try:
                fcntl.flock(data_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    message = f"{job.name}: data lock busy for {DATA_LOCK_WAIT_SECONDS}s"
                    print(f"[ntr] {_stamp()} {message}", flush=True)
                    _ping(env_extra, job.name, "/fail", message)
                    return 1
                time.sleep(15)

    started = time.monotonic()
    started_at = _stamp()
    print(f"[ntr] {started_at} start {job.name} @ {_git_head()}", flush=True)
    _ping(env_extra, job.name, "/start")
    tail: collections.deque[str] = collections.deque(maxlen=60)
    process = subprocess.Popen(["bash", "-c", job.command], cwd=REPO, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    killed = threading.Event()

    def _kill() -> None:
        killed.set()
        process.kill()

    watchdog = threading.Timer(job.timeout_seconds, _kill)
    watchdog.start()
    try:
        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(line)
            tail.append(line)
        code = process.wait()
    finally:
        watchdog.cancel()
    if killed.is_set():
        code = 124
        tail.append(f"[ntr] killed after {job.timeout_seconds}s\n")
        print(tail[-1], end="", flush=True)
    seconds = round(time.monotonic() - started)
    print(f"[ntr] {_stamp()} end {job.name} exit={code} {seconds}s", flush=True)
    _write_state(job.name, {"started": started_at, "exit": code, "seconds": seconds})
    _ping(env_extra, job.name, "" if code == 0 else "/fail", "".join(tail))
    return code


def _git_head() -> str:
    result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True)
    return result.stdout.strip() or "?"


# --------------------------------------------------------------------------- sync / housekeeping

def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def cmd_sync(args: argparse.Namespace) -> int:
    branch = os.environ.get("NTR_BRANCH", "master")
    fetched = _git("fetch", "--quiet", "origin", branch)
    if fetched.returncode != 0:
        print(f"[ntr] fetch failed: {fetched.stderr.strip()}")
        return 1
    before = _git("rev-parse", "HEAD").stdout.strip()
    target = _git("rev-parse", "FETCH_HEAD").stdout.strip()
    if before == target:
        print(f"[ntr] up to date at {before[:7]}")
        return 0
    merged = _git("merge", "--ff-only", "--quiet", "FETCH_HEAD")
    if merged.returncode != 0:
        # Usually a pulled commit touches a data/ file this Mac has modified.
        print(f"[ntr] fast-forward refused; staying on {before[:7]}:\n{merged.stderr.strip()}")
        return 1
    changed = set(_git("diff", "--name-only", before, target).stdout.split())
    print(f"[ntr] {before[:7]} -> {target[:7]} ({len(changed)} files)")
    if "job/requirements.txt" in changed:
        pip = subprocess.run([str(REPO / ".venv" / "bin" / "pip"), "install", "-q", "-r", "requirements.txt"],
                             cwd=REPO, capture_output=True, text=True)
        print(f"[ntr] pip install exit={pip.returncode} {pip.stderr.strip()[-500:]}")
        if pip.returncode != 0:
            return 1
    if changed & {"job/mac/jobs.conf", "job/mac/ntr.py"}:
        return cmd_install(argparse.Namespace(allow_other_tz=False), skip_reload=SELF_RELOAD_EXEMPT)
    return 0


def cmd_prune_logs(_: argparse.Namespace) -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for log in LOG_DIR.glob("*.log"):
        if log.stat().st_size > LOG_ROTATE_BYTES:
            # launchd keeps the file open in append mode, so truncate in place
            # after keeping one copy instead of renaming.
            (log.with_suffix(".log.1")).write_bytes(log.read_bytes())
            with open(log, "r+b") as handle:
                handle.truncate(0)
            print(f"rotated {log.name}")
    cutoff = time.time() - 30 * 86400
    reports = HOME / ".nexus-radar" / "daily-report"
    if reports.exists():
        for day in reports.iterdir():
            if day.is_dir() and day.stat().st_mtime < cutoff:
                for path in sorted(day.rglob("*"), reverse=True):
                    path.unlink() if path.is_file() else path.rmdir()
                day.rmdir()
                print(f"pruned {day.name}")
    return 0


# --------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    install = sub.add_parser("install")
    install.add_argument("--allow-other-tz", action="store_true")
    sub.add_parser("uninstall")
    sub.add_parser("status")
    sub.add_parser("list")
    run = sub.add_parser("run")
    run.add_argument("job")
    sub.add_parser("sync")
    sub.add_parser("prune-logs")
    args = parser.parse_args(argv)
    handlers = {
        "install": cmd_install, "uninstall": cmd_uninstall, "status": cmd_status, "list": cmd_list,
        "run": cmd_run, "sync": cmd_sync, "prune-logs": cmd_prune_logs,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
