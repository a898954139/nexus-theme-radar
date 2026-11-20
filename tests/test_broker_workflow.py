from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_broker_workflow_attempts_the_full_universe_and_calls_publish() -> None:
    workflow = (ROOT / ".github" / "workflows" / "update-broker-data.yml").read_text()

    assert "python scripts/update_broker_data.py" in workflow
    assert "--min-attempt-coverage 1.0" in workflow
    assert "--min-universe-size 2280" in workflow
    assert "git add data/broker-stats.json data/broker-coverage.json data/broker-map" in workflow
    # The site reads /api/v1 only: the run publishes to the radar tables and
    # no longer redeploys GitHub Pages.
    assert "python scripts/radar_publish.py --data-dir data --dataset broker --require" in workflow
    assert "deploy-pages.yml" not in workflow


def test_pages_is_a_redirect_and_publishes_no_data() -> None:
    workflow = (ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text()

    assert "workflow_call:" not in workflow
    assert "copy_runtime_data.sh" not in workflow
    assert "https://nexus-theme-radar.vercel.app/" in workflow
    script = (ROOT / "scripts" / "copy_runtime_data.sh").read_text()
    assert "broker" not in script
    assert "data/" not in script.split("set -eu", 1)[1]
