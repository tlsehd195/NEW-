"""Static consistency checks for the full walk-forward + PBO/DSR
validation workflow (ADR-0193) -- same category of checks the other
`workflow_dispatch`-only real-data workflows in this repository already
establish; the real execution (against real Release-hosted catalogs)
cannot happen inside this test suite, see
`tests/strategy_research/test_run_long_horizon_validation_wiring.py`
for the real, executable coverage of the underlying script's own
wiring."""
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


def test_workflow_is_valid_yaml_manual_dispatch_only_and_read_only():
    doc = _load()
    triggers = doc.get(True, doc.get("on"))
    assert triggers is not None
    assert "workflow_dispatch" in triggers
    assert "schedule" not in triggers
    assert doc["permissions"]["contents"] == "read"


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
    # Default --end matches TEST_1's own start -- every prior real
    # Stage-3/4 run used this exact boundary (see
    # STRATEGY-VALIDATION-REPORT.md's Phase 33 addendum); this test
    # exists so an accidental default change can't silently point a
    # future run at a different, un-reviewed range.
    assert inputs["end"]["default"] == "2023-04-28"


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
    # would kill the job when the release simply has no insider catalog
    # yet -- it branches on the download's own success instead.
    insider_step = next(s for s in _steps() if "insider_catalog.zip" in s.get("run", "") and "gh release download" in s.get("run", ""))
    assert "if gh release download" in insider_step["run"]


def test_runs_the_real_validation_script_with_both_required_db_paths_and_the_insider_flag_variable():
    run_text = "\n".join(s.get("run", "") for s in _steps())
    assert "run_long_horizon_validation.py" in run_text
    assert "--db-path ./data/price_catalog" in run_text
    assert "--fundamentals-db-path ./data/fundamentals_catalog" in run_text
    assert "$INSIDER_FLAG" in run_text
    assert "--data-status REAL" in run_text
    assert "${{ inputs.universe }}" in run_text
    assert "${{ inputs.start }}" in run_text
    assert "${{ inputs.end }}" in run_text


def test_uploads_the_report_with_always_and_warn_on_missing():
    upload_steps = [s for s in _steps() if s.get("uses", "").startswith("actions/upload-artifact")]
    assert len(upload_steps) == 1
    step = upload_steps[0]
    assert step.get("if") == "always()"
    assert step["with"]["if-no-files-found"] == "warn"
    assert step["with"]["path"] == "./validation_report.json"
