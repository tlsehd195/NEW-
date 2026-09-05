"""Static consistency checks for the GitHub Actions scheduler workflow
(ADR-0082). The workflow's real execution (against a real network and
a real Tiingo API key) cannot happen inside this test suite -- same
long-standing caveat as `ingest_real_market_data.py` itself. What IS
checkable without running it: the YAML is well-formed, it invokes the
same scripts with the ratified flags, and no secret value is ever
hardcoded into the file.
"""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "paper_trading_cycle.yml"


def _load() -> dict:
    assert WORKFLOW_PATH.exists(), f"workflow file not found: {WORKFLOW_PATH}"
    text = WORKFLOW_PATH.read_text()
    doc = yaml.safe_load(text)
    assert isinstance(doc, dict)
    return doc


def _steps(doc: dict) -> list[dict]:
    jobs = doc["jobs"]
    assert "run-cycle" in jobs
    return jobs["run-cycle"]["steps"]


def _run_text(steps: list[dict]) -> str:
    return "\n".join(step.get("run", "") for step in steps)


def test_workflow_is_valid_yaml_with_a_schedule_trigger():
    doc = _load()
    # PyYAML parses the bare `on:` key as the boolean True.
    triggers = doc.get(True, doc.get("on"))
    assert triggers is not None
    assert "schedule" in triggers
    assert triggers["schedule"][0]["cron"] == "0 22 * * 1-5"
    assert "workflow_dispatch" in triggers


def test_workflow_grants_only_read_permissions():
    doc = _load()
    perms = doc["permissions"]
    assert perms.get("contents") == "read"
    assert perms.get("actions") == "read"


def test_no_secret_value_is_hardcoded():
    steps = _steps(_load())
    ingest_step = next(s for s in steps if "ingest_real_market_data.py" in s.get("run", ""))
    env = ingest_step.get("env", {})
    assert env.get("MARKET_DATA_API_KEY") == "${{ secrets.MARKET_DATA_API_KEY }}", (
        "the API key must be referenced via the secrets context, never a "
        "literal value in the workflow file"
    )


def test_ingestion_step_uses_ratified_universe_and_key_reference():
    steps = _steps(_load())
    text = _run_text(steps)
    assert "ingest_real_market_data.py" in text
    assert '--universe "$UNIVERSE"' in text
    assert "$MARKET_DATA_DIR" in text


def test_cycle_step_uses_resume_and_ratified_risk_limits():
    steps = _steps(_load())
    text = _run_text(steps)
    assert "run_paper_trading_cycle.py" in text
    assert "--resume" in text
    # ADR-0080 ratified values (#5/#10).
    assert "--max-sector-weight 0.25" in text
    assert "--max-order-notional 1000" in text


def test_both_state_directories_are_restored_and_reuploaded():
    doc = _load()
    steps = _steps(doc)
    run_text = _run_text(steps)
    assert "market-data-catalog" in run_text
    assert "paper-trading-store" in run_text

    upload_steps = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact")]
    uploaded_names = {s["with"]["name"] for s in upload_steps}
    assert "market-data-catalog" in uploaded_names
    assert "paper-trading-store" in uploaded_names
    for step in upload_steps:
        assert step.get("if") == "always()", (
            f"{step.get('name')} must upload with if: always() so a failed "
            "run does not silently lose already-written state"
        )
