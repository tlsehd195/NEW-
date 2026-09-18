"""Minimal static consistency checks for the one-shot recon workflow
(docs/PROJECT_STATUS.md backlog item #1) -- see
`scripts/recon_stockanalysis_delisted.py`'s own module docstring for
why this exists and what it deliberately does not do yet (no parsing,
no assumptions about the real response shape)."""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "recon_stockanalysis_delisted.yml"


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


def test_runs_the_real_recon_script():
    steps = _load()["jobs"]["recon"]["steps"]
    run_text = "\n".join(s.get("run", "") for s in steps)
    assert "recon_stockanalysis_delisted.py" in run_text
