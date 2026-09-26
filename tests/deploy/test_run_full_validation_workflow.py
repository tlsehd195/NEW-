"""Static consistency checks for the full walk-forward + PBO/DSR
validation workflow (ADR-0193) -- same category of checks the other
`workflow_dispatch`-only real-data workflows in this repository already
establish; the real execution (against real Release-hosted catalogs)
cannot happen inside this test suite, see
`tests/strategy_research/test_run_long_horizon_validation_wiring.py`
for the real, executable coverage of the underlying script's own
wiring."""
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "run_full_validation.yml"


def _load() -> dict:
    assert WORKFLOW_PATH.exists(), f"workflow file not found: {WORKFLOW_PATH}"
    doc = yaml.safe_load(WORKFLOW_PATH.read_text())
    assert isinstance(doc, dict)
    return doc


def _steps() -> list[dict]:
    return _load()["jobs"]["validate"]["steps"]


def _dispatch_inputs() -> dict:
    doc = _load()
    triggers = doc[True] if True in doc else doc["on"]
    return triggers["workflow_dispatch"]["inputs"]


def test_workflow_is_valid_yaml_manual_dispatch_only():
    doc = _load()
    triggers = doc.get(True, doc.get("on"))
    assert triggers is not None
    assert "workflow_dispatch" in triggers
    assert "schedule" not in triggers
    # write, not read: this job commits the validation report straight
    # into the repo (see test_commits_the_report_into_the_repo_durably
    # below) -- a Claude session or the account owner coming back within
    # the 90-day artifact window is not a real safeguard.
    assert doc["permissions"]["contents"] == "write"


def test_has_concurrency_group_and_a_job_timeout():
    doc = _load()
    assert doc["concurrency"]["group"] == "${{ github.workflow }}-${{ github.ref }}"
    assert doc["concurrency"]["cancel-in-progress"] is False
    assert doc["jobs"]["validate"]["timeout-minutes"] > 0


def test_required_inputs_present_with_sensible_defaults():
    inputs = _dispatch_inputs()
    assert inputs["release_tag"]["required"] is True
    assert inputs["universe"]["default"] == "RESEARCH_UNIVERSE"
    assert inputs["start"]["default"] == "2010-01-01"
    # Default --end is the earliest locked window's start (TEST_2's,
    # ADR-0209/ADR-0211). The old 2023-04-28 default (TEST_1's start)
    # overlapped TEST_2 once it was locked, so a default dispatch was
    # refused by run_long_horizon_validation.py's own locked-window
    # guard. Asserted against the registry itself so a future earlier
    # TEST_3 fails this test instead of silently breaking the default.
    from strategy_research.locked_windows import earliest_locked_window_start, overlaps_any_locked_window

    end_default = datetime.strptime(inputs["end"]["default"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start_default = datetime.strptime(inputs["start"]["default"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    assert end_default == earliest_locked_window_start()
    assert overlaps_any_locked_window(start_default, end_default) == ()


def test_downloads_required_catalogs_from_the_release_not_as_workflow_artifacts():
    run_text = "\n".join(s.get("run", "") for s in _steps())
    assert "gh release download" in run_text
    assert "price_catalog.zip" in run_text
    assert "fundamentals_catalog.zip" in run_text
    # Never actions/download-artifact for the input catalogs -- that
    # would defeat the entire point of using a Release (artifacts
    # expire; Release assets do not).
    download_artifact_steps = [s for s in _steps() if s.get("uses", "").startswith("actions/download-artifact")]
    assert not download_artifact_steps


def test_insider_catalog_download_is_optional_and_does_not_fail_the_job():
    run_text = "\n".join(s.get("run", "") for s in _steps())
    assert "insider_catalog.zip" in run_text
    assert "INSIDER_FLAG" in run_text
    # The optional-download step must not use `set -e` semantics that
    # would kill the job when neither release has an insider catalog
    # yet -- it branches on each download's own success instead.
    insider_step = next(s for s in _steps() if "insider_catalog.zip" in s.get("run", "") and "gh release download" in s.get("run", ""))
    assert "if gh release download" in insider_step["run"]


def test_insider_catalog_falls_back_to_the_auto_published_release():
    """ingest_insider_transactions_full.yml publishes its own catalog
    to a fixed 'insider-transactions-catalog' release automatically, on
    every successful merge -- this workflow must try that tag when the
    account owner's own --release-tag doesn't carry one, so
    insider_buying works without a manual upload step at all."""
    insider_step = next(s for s in _steps() if "insider_catalog.zip" in s.get("run", "") and "gh release download" in s.get("run", ""))
    assert "insider-transactions-catalog" in insider_step["run"]


def test_runs_the_real_validation_script_with_both_required_db_paths_and_the_insider_flag_variable():
    steps = _steps()
    run_text = "\n".join(s.get("run", "") for s in steps)
    assert "run_long_horizon_validation.py" in run_text
    assert "--db-path ./data/price_catalog" in run_text
    assert "--fundamentals-db-path ./data/fundamentals_catalog" in run_text
    assert "$INSIDER_FLAG" in run_text
    assert "--data-status REAL" in run_text
    # Independent audit finding (2026-09-24): a workflow_dispatch input
    # must never be interpolated directly into a run: block -- passed
    # via env: and referenced as a shell variable instead.
    assert '--universe "$UNIVERSE_INPUT"' in run_text
    assert '--start "$START_INPUT" --end "$END_INPUT"' in run_text
    validation_step = next(s for s in steps if "run_long_horizon_validation.py" in s.get("run", ""))
    assert validation_step["env"]["UNIVERSE_INPUT"] == "${{ inputs.universe }}"
    assert validation_step["env"]["START_INPUT"] == "${{ inputs.start }}"
    assert validation_step["env"]["END_INPUT"] == "${{ inputs.end }}"


def test_uploads_the_report_with_always_and_warn_on_missing():
    upload_steps = [s for s in _steps() if s.get("uses", "").startswith("actions/upload-artifact")]
    assert len(upload_steps) == 1
    step = upload_steps[0]
    assert step.get("if") == "always()"
    assert step["with"]["if-no-files-found"] == "warn"
    assert step["with"]["path"] == "./validation_report.json"


def test_commits_the_report_into_the_repo_durably():
    """The 90-day artifact above is a quick-access convenience, not the
    durable copy -- this step must exist and actually push, so the raw
    result survives regardless of whether any human or Claude session
    ever revisits this run within 90 days."""
    commit_step = next(s for s in _steps() if "git commit" in s.get("run", ""))
    assert commit_step.get("if") == "always()"
    run_text = commit_step["run"]
    assert "docs/research/reports" in run_text
    assert "git push" in run_text
    # Guards against committing a stale/missing report from a failed run.
    assert "if [ ! -f ./validation_report.json ]" in run_text
