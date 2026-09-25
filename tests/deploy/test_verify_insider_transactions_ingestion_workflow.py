"""Static consistency checks for the one-shot Verify SEC Form 4
Insider Transactions Ingestion workflow. Same category of checks the
other `workflow_dispatch`-only verification workflows in this
repository already established -- the real execution (against real
SEC EDGAR endpoints) cannot happen inside this test suite; see
`tests/data_infra/test_ingest_insider_transactions_wiring.py` for the
real, executable coverage of the underlying script's own pure logic.
"""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "verify_insider_transactions_ingestion.yml"


def _load() -> dict:
    assert WORKFLOW_PATH.exists(), f"workflow file not found: {WORKFLOW_PATH}"
    doc = yaml.safe_load(WORKFLOW_PATH.read_text())
    assert isinstance(doc, dict)
    return doc


def _steps(doc: dict) -> list[dict]:
    return doc["jobs"]["verify"]["steps"]


def test_workflow_is_valid_yaml_manual_dispatch_only_and_read_only():
    doc = _load()
    triggers = doc.get(True, doc.get("on"))
    assert triggers is not None
    assert "workflow_dispatch" in triggers
    assert "schedule" not in triggers
    assert doc["permissions"]["contents"] == "read"


def test_user_agent_and_symbols_are_configurable_inputs_defaulting_to_the_known_good_symbol():
    doc = _load()
    inputs = doc.get(True, doc.get("on"))["workflow_dispatch"]["inputs"]
    assert inputs["user_agent"]["required"] is True
    assert inputs["symbols"]["default"] == "JPM"


def test_runs_the_real_ingestion_script_with_the_configured_inputs():
    steps = _steps(_load())
    run_text = "\n".join(s.get("run", "") for s in steps)
    assert "ingest_insider_transactions.py" in run_text
    # Independent audit finding (2026-09-24): a workflow_dispatch input
    # must never be interpolated directly into a run: block -- passed
    # via env: and referenced as a shell variable instead.
    assert "--symbols $SYMBOLS_INPUT" in run_text
    assert '--user-agent "$USER_AGENT_INPUT"' in run_text
    ingest_step = next(s for s in steps if "ingest_insider_transactions.py" in s.get("run", ""))
    assert ingest_step["env"]["SYMBOLS_INPUT"] == "${{ inputs.symbols }}"
    assert ingest_step["env"]["USER_AGENT_INPUT"] == "${{ inputs.user_agent }}"
    assert "--as-of" in run_text


def test_uses_a_fresh_throwaway_db_path_not_a_restored_artifact():
    """This is a correctness/reachability check, not the real
    collection run -- no market-data-catalog-style artifact restore
    step should exist here."""
    steps = _steps(_load())
    run_text = "\n".join(s.get("run", "") for s in steps)
    assert "insider_verification" in run_text
    assert "download-artifact" not in "\n".join(s.get("uses", "") for s in steps)


def test_uploads_the_manifest_without_failing_the_job_if_missing():
    steps = _steps(_load())
    upload_steps = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact")]
    assert len(upload_steps) == 1
    assert upload_steps[0].get("if") == "always()"
    assert upload_steps[0]["with"].get("if-no-files-found") == "ignore"
