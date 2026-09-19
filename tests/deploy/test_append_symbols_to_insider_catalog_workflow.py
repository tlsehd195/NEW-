"""Static consistency checks for the insider-transaction catalog
append workflow -- fills a real, specific gap (e.g. shard 8's AVB
failure, ADR-0172) without re-running the full sharded collection
(ADR-0171). Real execution (SEC EDGAR network calls) cannot happen in
this test suite; see tests/scripts/test_ingest_insider_transactions_*
and tests/scripts/test_merge_insider_transaction_catalogs.py for the
real, executable coverage of the underlying scripts this workflow
wires together."""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "append_symbols_to_insider_catalog.yml"


def _load() -> dict:
    assert WORKFLOW_PATH.exists(), f"workflow file not found: {WORKFLOW_PATH}"
    doc = yaml.safe_load(WORKFLOW_PATH.read_text())
    assert isinstance(doc, dict)
    return doc


def _steps() -> list[dict]:
    return _load()["jobs"]["append"]["steps"]


def test_workflow_is_valid_yaml_manual_dispatch_only_and_read_only():
    doc = _load()
    triggers = doc.get(True, doc.get("on"))
    assert triggers is not None
    assert "workflow_dispatch" in triggers
    assert "schedule" not in triggers
    assert doc["permissions"]["contents"] == "read"


def test_required_inputs_are_symbols_user_agent_and_source_run_id():
    doc = _load()
    inputs = doc[True]["workflow_dispatch"]["inputs"] if True in doc else doc["on"]["workflow_dispatch"]["inputs"]
    assert inputs["symbols"]["required"] is True
    assert inputs["user_agent"]["required"] is True
    assert inputs["source_run_id"]["required"] is True
    assert inputs["source_artifact_name"]["default"] == "insider-transactions-catalog"


def test_downloads_the_source_run_s_combined_catalog_by_run_id():
    steps = _steps()
    download_step = next(s for s in steps if s.get("uses", "").startswith("actions/download-artifact"))
    assert download_step["with"]["name"] == "${{ inputs.source_artifact_name }}"
    assert download_step["with"]["run-id"] == "${{ inputs.source_run_id }}"
    assert "github-token" in download_step["with"]


def test_ingests_the_requested_symbols_then_merges_into_the_downloaded_catalog():
    run_text = "\n".join(s.get("run", "") for s in _steps())
    assert "ingest_insider_transactions.py" in run_text
    assert "--symbols ${{ inputs.symbols }}" in run_text
    assert "merge_insider_transaction_catalogs.py" in run_text
    assert "--target-db-path ./data/insider_final" in run_text
    assert "--shard-db-path ./data/insider_new_symbols" in run_text


def test_uploads_updated_catalog_and_manifest_with_always_and_ignore_missing():
    upload_steps = [s for s in _steps() if s.get("uses", "").startswith("actions/upload-artifact")]
    assert len(upload_steps) == 2
    for step in upload_steps:
        assert step.get("if") == "always()"
        assert step["with"].get("if-no-files-found") == "ignore"
