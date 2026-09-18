"""Static consistency checks for the on-demand Verify Alpaca Paper
Broker workflow (account owner's own request, 2026-09-18). Same
category of checks `test_repair_ingestion_time_inversions_workflow.py`
already established: the workflow's real execution (against a real
Alpaca paper account) cannot happen inside this test suite -- see
`tests/scripts/test_verify_alpaca_paper_broker.py` for the real,
executable coverage the underlying script's design allows.
"""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "verify_alpaca_paper_broker.yml"


def _load() -> dict:
    assert WORKFLOW_PATH.exists(), f"workflow file not found: {WORKFLOW_PATH}"
    text = WORKFLOW_PATH.read_text()
    doc = yaml.safe_load(text)
    assert isinstance(doc, dict)
    return doc


def _steps(doc: dict) -> list[dict]:
    jobs = doc["jobs"]
    assert "verify" in jobs
    return jobs["verify"]["steps"]


def _run_text(steps: list[dict]) -> str:
    return "\n".join(step.get("run", "") for step in steps)


def test_workflow_is_valid_yaml_manual_dispatch_only():
    """Real (paper) orders are placed every run -- must never be on a
    recurring schedule, unlike data_quality_rescan.yml's weekly one."""
    doc = _load()
    triggers = doc.get(True, doc.get("on"))
    assert triggers is not None
    assert "workflow_dispatch" in triggers
    assert "schedule" not in triggers


def test_workflow_grants_only_read_permissions():
    doc = _load()
    perms = doc["permissions"]
    assert perms.get("contents") == "read"


def test_credentials_come_from_secrets_never_hardcoded():
    steps = _steps(_load())
    verify_step = next(s for s in steps if "verify_alpaca_paper_broker.py" in s.get("run", ""))
    env = verify_step.get("env", {})
    assert env.get("ALPACA_API_KEY") == "${{ secrets.ALPACA_API_KEY }}"
    assert env.get("ALPACA_SECRET_KEY") == "${{ secrets.ALPACA_SECRET_KEY }}"
    assert env.get("ALPACA_BASE_URL") == "${{ secrets.ALPACA_BASE_URL }}"

    full_text = WORKFLOW_PATH.read_text()
    for line in full_text.splitlines():
        if "secrets." in line or line.strip().startswith("#"):
            continue
        assert "ALPACA_API_KEY=" not in line.replace(" ", "")
        assert "ALPACA_SECRET_KEY=" not in line.replace(" ", "")


def test_installs_the_broker_verification_extra():
    text = _run_text(_steps(_load()))
    assert "pip install -e '.[broker-verification]'" in text


def test_runs_the_real_verification_script_with_configurable_symbol_and_qty():
    steps = _steps(_load())
    doc = _load()
    triggers = doc.get(True, doc.get("on"))
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert inputs["symbol"]["default"] == "AAPL"
    assert inputs["qty"]["default"] == "1"

    text = _run_text(steps)
    assert "verify_alpaca_paper_broker.py" in text
    assert "${{ inputs.symbol }}" in text
    assert "${{ inputs.qty }}" in text
