"""Static consistency checks for the on-demand Repair Ingestion-Time
Inversions workflow (ADR-0168). Same category of checks
`test_data_quality_rescan_workflow.py` already established: the
workflow's real execution (against a real restored market-data-catalog
artifact) cannot happen inside this test suite (see
`tests/scripts/test_repair_ingestion_time_inversions.py` for the real,
executable coverage of the underlying script itself).
"""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "repair_ingestion_time_inversions.yml"


def _load() -> dict:
    assert WORKFLOW_PATH.exists(), f"workflow file not found: {WORKFLOW_PATH}"
    text = WORKFLOW_PATH.read_text()
    doc = yaml.safe_load(text)
    assert isinstance(doc, dict)
    return doc


def _steps(doc: dict) -> list[dict]:
    jobs = doc["jobs"]
    assert "repair" in jobs
    return jobs["repair"]["steps"]


def _run_text(steps: list[dict]) -> str:
    return "\n".join(step.get("run", "") for step in steps)


def test_workflow_is_valid_yaml_manual_dispatch_only_with_an_apply_input():
    """This is a specific, one-time repair for an already-identified
    defect (ADR-0168), not ongoing defense-in-depth -- unlike
    data_quality_rescan.yml (ADR-0145), it has no recurring schedule.
    `apply` defaults to false so an accidental trigger cannot mutate
    the real production catalog without a deliberate override."""
    doc = _load()
    # PyYAML parses the bare `on:` key as the boolean True.
    triggers = doc.get(True, doc.get("on"))
    assert triggers is not None
    assert "workflow_dispatch" in triggers
    assert "schedule" not in triggers
    apply_input = triggers["workflow_dispatch"]["inputs"]["apply"]
    assert apply_input["type"] == "boolean"
    assert apply_input["default"] is False


def test_workflow_grants_only_read_permissions():
    doc = _load()
    perms = doc["permissions"]
    assert perms.get("contents") == "read"
    assert perms.get("actions") == "read"


def test_runs_the_real_repair_script_gated_on_the_apply_input():
    steps = _steps(_load())
    text = _run_text(steps)
    assert "repair_ingestion_time_inversions.py" in text
    assert '--db-path "$MARKET_DATA_DIR"' in text
    assert "inputs.apply" in text
    assert "--apply" in text


def test_restores_and_reuploads_the_same_market_data_catalog_artifact_the_daily_cycle_produces():
    steps = _steps(_load())
    run_text = _run_text(steps)
    assert "market-data-catalog" in run_text

    upload_steps = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact")]
    uploaded_names = {s["with"]["name"] for s in upload_steps}
    assert "market-data-catalog" in uploaded_names
    for step in upload_steps:
        assert step.get("if") == "always()", (
            f"{step.get('name')} must upload with if: always() so a failed "
            "run does not silently lose already-written state"
        )


def test_this_workflow_never_touches_the_paper_trading_store():
    """This is a market-data-catalog-only operation, same scoping
    `data_quality_rescan.yml` already established."""
    doc = _load()
    steps = _steps(doc)
    run_text = _run_text(steps)
    upload_steps = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact")]
    uploaded_names = {s["with"]["name"] for s in upload_steps}
    assert "paper-trading-store" not in uploaded_names
    assert "paper-trading-store" not in run_text


def test_fails_loudly_when_no_prior_catalog_artifact_exists():
    steps = _steps(_load())
    restore_step = next(s for s in steps if s.get("name", "").startswith("Restore market-data-catalog"))
    run_text = restore_step.get("run", "")
    assert "FATAL" in run_text and "exit 1" in run_text


def test_restore_step_defends_against_a_wrapped_artifact_zip():
    """Same ADR-0115 (external review N-14) defense
    `paper_trading_cycle.yml`/`data_quality_rescan.yml`'s restore steps
    already carry."""
    steps = _steps(_load())
    restore_step = next(s for s in steps if s.get("name", "").startswith("Restore market-data-catalog"))
    run_text = restore_step.get("run", "")
    assert "catalog.duckdb" in run_text
    assert "find" in run_text and "-maxdepth 1" in run_text
