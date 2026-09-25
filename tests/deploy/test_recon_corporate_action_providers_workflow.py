"""Minimal static consistency checks for the one-shot Corporate Action
Providers recon workflow (2026-09-25, run #44) -- see
`scripts/recon_corporate_action_providers.py`'s own module docstring
for why this exists and what it deliberately does not do yet (no
parsing, no provider wiring, no assumption about the real result)."""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "recon_corporate_action_providers.yml"


def _load() -> dict:
    assert WORKFLOW_PATH.exists(), f"workflow file not found: {WORKFLOW_PATH}"
    doc = yaml.safe_load(WORKFLOW_PATH.read_text())
    assert isinstance(doc, dict)
    return doc


def test_workflow_is_valid_yaml_manual_dispatch_only_and_read_only():
    doc = _load()
    triggers = doc.get(True, doc.get("on"))
    assert triggers is not None
    assert "workflow_dispatch" in triggers
    assert "schedule" not in triggers
    assert doc["permissions"]["contents"] == "read"


def test_runs_the_real_recon_script_with_both_api_keys():
    steps = _load()["jobs"]["recon"]["steps"]
    run_text = "\n".join(s.get("run", "") for s in steps)
    assert "recon_corporate_action_providers.py" in run_text

    recon_step = next(s for s in steps if "recon_corporate_action_providers.py" in s.get("run", ""))
    env = recon_step.get("env", {})
    assert env.get("TWELVEDATA_API_KEY") == "${{ secrets.TWELVEDATA_API_KEY }}"
    assert env.get("ALPHAVANTAGE_API_KEY") == "${{ secrets.ALPHAVANTAGE_API_KEY }}"
