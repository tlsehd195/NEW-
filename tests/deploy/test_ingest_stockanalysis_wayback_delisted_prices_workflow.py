"""Static consistency checks for the real Wayback-Machine-based
delisted-price ingestion workflow. Real execution (against
raw.githubusercontent.com and archive.org) cannot happen in this test
suite; see tests/scripts/test_select_delisted_candidates_since.py and
tests/scripts/test_ingest_stockanalysis_wayback_delisted_prices.py for
the real, executable coverage of the underlying scripts."""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ingest_stockanalysis_wayback_delisted_prices.yml"


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


def test_symbols_input_defaults_to_empty_for_auto_selection():
    doc = _load()
    symbols_input = doc[True]["workflow_dispatch"]["inputs"]["symbols"] if True in doc else doc["on"]["workflow_dispatch"]["inputs"]["symbols"]
    assert symbols_input["default"] == ""


def test_fetches_the_live_sp500_csv_only_when_no_explicit_symbols_given():
    fetch_step = next(s for s in _steps() if "S&P 500" in s.get("name", ""))
    assert fetch_step.get("if") == "inputs.symbols == ''"
    assert "raw.githubusercontent.com" in fetch_step.get("run", "")


def test_selects_candidates_with_the_real_2020_cutoff():
    run_text = "\n".join(s.get("run", "") for s in _steps())
    assert "select_delisted_candidates_since.py" in run_text
    assert "--since 2020-01-01" in run_text


def test_runs_the_real_ingestion_script_with_the_selected_symbols():
    run_text = "\n".join(s.get("run", "") for s in _steps())
    assert "ingest_stockanalysis_wayback_delisted_prices.py" in run_text
    assert "--symbols ${{ steps.symbols.outputs.symbols }}" in run_text


def test_uploads_catalog_and_manifest_with_always_and_ignore_missing():
    upload_steps = [s for s in _steps() if s.get("uses", "").startswith("actions/upload-artifact")]
    assert len(upload_steps) == 2
    for step in upload_steps:
        assert step.get("if") == "always()"
        assert step["with"].get("if-no-files-found") == "ignore"
