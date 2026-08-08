from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_broker_workflow_attempts_the_full_universe_and_calls_publish() -> None:
    workflow = (ROOT / ".github" / "workflows" / "update-broker-data.yml").read_text()

    assert "python scripts/update_broker_data.py" in workflow
    assert "--min-attempt-coverage 1.0" in workflow
    assert "--min-universe-size 2280" in workflow
    assert "git add data/broker-stats.json data/broker-coverage.json data/broker-map" in workflow
    assert "uses: ./.github/workflows/deploy-pages.yml" in workflow
    assert "ref: ${{ needs.update.outputs.commit_sha }}" in workflow


def test_reusable_deploy_checks_out_the_caller_commit() -> None:
    workflow = (ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text()

    assert "workflow_call:" in workflow
    assert "inputs:\n      ref:" in workflow
    assert "ref: ${{ inputs.ref || github.sha }}" in workflow
    assert "broker-stats.json" in workflow
    assert "broker-map" in workflow
