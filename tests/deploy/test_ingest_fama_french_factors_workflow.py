"""Static consistency checks for the real Kenneth French 3-factor
ingestion workflow -- same category of checks the other
`workflow_dispatch`-only real ingestion workflows in this repository
already establish; the real execution (against a real, external
academic data host) cannot happen inside this test suite, see
`tests/scripts/test_ingest_fama_french_factors.py` for the real,
executable coverage of the underlying script."""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ingest_fama_french_factors.yml"


def _load() -> dict:
    assert WORKFLOW_PATH.exists(), f"workflow file not found: {WORKFLOW_PATH}"
    doc = yaml.safe_load(WORKFLOW_PATH.read_text())
    assert isinstance(doc, dict)
    return doc


def _steps() -> list[dict]:
    return _load()["jobs"]["ingest"]["steps"]


def test_workflow_is_valid_yaml_manual_dispatch_only_and_read_only():
    doc = _load()
    triggers = doc.get(True, doc.get("on"))
    assert triggers is not None
    assert "workflow_dispatch" in triggers
    assert "schedule" not in triggers
    assert doc["permissions"]["contents"] == "read"


def test_frequency_input_offers_daily_and_monthly_defaulting_to_daily():
    doc = _load()
    frequency_input = doc[True]["workflow_dispatch"]["inputs"]["frequency"] if True in doc else doc["on"]["workflow_dispatch"]["inputs"]["frequency"]
    assert set(frequency_input["options"]) == {"daily", "monthly"}
    assert frequency_input["default"] == "daily"


def test_runs_the_real_ingestion_script_with_the_requested_frequency():
    run_text = "\n".join(s.get("run", "") for s in _steps())
    assert "ingest_fama_french_factors.py" in run_text
    assert "--frequency" in run_text
    assert "${{ inputs.frequency }}" in run_text


def test_uploads_both_the_catalog_and_manifest_with_always_and_ignore_missing():
    upload_steps = [s for s in _steps() if s.get("uses", "").startswith("actions/upload-artifact")]
    assert len(upload_steps) == 2
    for step in upload_steps:
        assert step.get("if") == "always()"
        assert step["with"].get("if-no-files-found") == "ignore"
