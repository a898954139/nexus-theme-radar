"""ops/mac: the single launchd schedule that replaced Actions + pg_cron jobs."""

from __future__ import annotations

import importlib.util
import plistlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ntr", ROOT / "ops" / "mac" / "ntr.py")
ntr = importlib.util.module_from_spec(SPEC)
sys.modules["ntr"] = ntr
SPEC.loader.exec_module(ntr)


def jobs_by_name():
    return {job.name: job for job in ntr.load_jobs()}


def test_real_conf_parses_and_covers_every_former_schedule():
    jobs = jobs_by_name()
    assert {
        "ingest", "pre-market", "analysis-prepare", "analysis-warm", "analysis-report",
        "theme-radar", "institutional-flows", "backtest-paths", "broker-data", "prune-logs", "sync",
    } <= set(jobs)
    assert jobs["ingest"].interval_seconds == 300
    assert {"Minute": 17} in jobs["theme-radar"].calendar
    assert {"Weekday": 1, "Hour": 17, "Minute": 20} in jobs["institutional-flows"].calendar
    assert {"Weekday": 6, "Hour": 17, "Minute": 20} not in jobs["institutional-flows"].calendar
    assert jobs["broker-data"].timeout_seconds == 180 * 60


def test_every_script_the_schedule_calls_exists():
    for job in ntr.load_jobs():
        for script in re.findall(r"(?:python|bash) ((?:scripts|ops)/[\w/.-]+)", job.command):
            assert (ROOT / script).is_file(), f"{job.name} calls missing {script}"


def test_publish_steps_match_the_workflows_they_replace():
    """A dataset dropped here would silently stop updating its table."""
    jobs = jobs_by_name()
    for workflow, job in [
        ("update-theme-radar.yml", "theme-radar"),
        ("update-pre-market.yml", "pre-market"),
        ("update-institutional-flows.yml", "institutional-flows"),
        ("update-broker-data.yml", "broker-data"),
    ]:
        text = (ROOT / ".github" / "workflows" / workflow).read_text()
        expected = set(re.findall(r"--dataset ([\w-]+)", text))
        assert expected and expected == set(re.findall(r"--dataset ([\w-]+)", jobs[job].command)), job


def test_writers_to_data_share_the_lock():
    jobs = jobs_by_name()
    for name in ("pre-market", "theme-radar", "institutional-flows", "backtest-paths", "sync"):
        assert jobs[name].data_lock, name
    assert not jobs["ingest"].data_lock


def test_plist_render(tmp_path):
    job = jobs_by_name()["theme-radar"]
    plist = plistlib.loads(ntr.render_plist(job, repo=tmp_path, python=tmp_path / "py", path_env="/usr/bin"))
    assert plist["Label"] == "com.nexus.themeradar.theme-radar"
    assert plist["ProgramArguments"][-2:] == ["run", "theme-radar"]
    assert plist["StartCalendarInterval"] == [{"Minute": 17}]
    assert "StartInterval" not in plist
    ingest = plistlib.loads(ntr.render_plist(jobs_by_name()["ingest"], repo=tmp_path, python=tmp_path / "py", path_env="/usr/bin"))
    assert ingest["StartInterval"] == 300 and "StartCalendarInterval" not in ingest


@pytest.mark.parametrize("bad", [
    "a | sometimes | echo",
    "a | every 5m; daily 06:00 | echo",
    "a | daily 25:00 | echo",
    "a | hourly 17 | echo",
    "Bad | daily 06:00 | echo",
    "a | daily 06:00 | echo\na | daily 07:00 | echo",
    "@nolock ghost\na | daily 06:00 | echo",
    "a | daily 06:00 | echo \\",
])
def test_conf_errors(bad):
    with pytest.raises(ntr.ConfError):
        ntr.parse_conf(bad)


def test_continuation_and_comments():
    jobs = ntr.parse_conf("# c\n\nx | weekdays 06:05,06:35 | \\\n  echo a && \\\n  echo b\n")
    assert jobs[0].command == "echo a && echo b"
    assert len(jobs[0].calendar) == 10


def test_env_file(tmp_path):
    path = tmp_path / "runner.env"
    path.write_text("# x\nexport THEME_RADAR_DATABASE_URL='postgresql://u:p@h/db'\nFOO=\"b a r\"\nnot a line\n")
    path.chmod(0o600)
    env = ntr.load_env(tmp_path)
    assert env["FOO"] == "b a r"
    assert env["RADAR_INGEST_DATABASE_URL"] == env["THEME_RADAR_DATABASE_URL"] == "postgresql://u:p@h/db"
    path.chmod(0o644)
    with pytest.raises(PermissionError):
        ntr.load_env(tmp_path)


def test_run_records_state_and_skips_when_already_running(tmp_path, monkeypatch, capsys):
    conf = tmp_path / "jobs.conf"
    conf.write_text("@nolock ok\nok | daily 06:00 | echo hello\nboom | daily 06:00 | echo bad; exit 3\n")
    monkeypatch.setattr(ntr, "CONF_PATH", conf)
    monkeypatch.setattr(ntr, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(ntr, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(ntr, "load_jobs", lambda path=conf: ntr.parse_conf(conf.read_text()))
    assert ntr.main(["run", "ok"]) == 0
    assert ntr.main(["run", "boom"]) == 3
    state = ntr._read_state()
    assert state["ok"]["exit"] == 0 and state["boom"]["exit"] == 3
    assert "hello" in capsys.readouterr().out

    import fcntl
    with open(tmp_path / "state" / "ok.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert ntr.main(["run", "ok"]) == 0
    assert "still active" in capsys.readouterr().out
