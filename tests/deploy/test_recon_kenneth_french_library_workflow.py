"""Minimal static consistency checks for the one-shot Kenneth French
Data Library recon workflow (docs/PROJECT_STATUS.md backlog item #7)
-- see `scripts/recon_kenneth_french_library.py`'s own module
docstring for why this exists and what it deliberately does not do yet
(no parsing, no assumptions about the real response shape)."""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "recon_kenneth_french_library.yml"


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
    assert "recon_kenneth_french_library.py" in run_text


def test_also_runs_the_csv_format_follow_up_script():
    """2026-09-19 follow-up: the index page/zip download recon above
    already came back real HTTP 200s from a GitHub Actions runner --
    this second script looks INSIDE the zip so a real parser can be
    written from the real CSV layout instead of an assumption."""
    steps = _load()["jobs"]["recon"]["steps"]
    run_text = "\n".join(s.get("run", "") for s in steps)
    assert "recon_kenneth_french_csv_format.py" in run_text
