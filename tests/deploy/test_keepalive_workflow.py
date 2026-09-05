"""Static consistency checks for the keepalive workflow (ADR-0083).

Cannot verify the actual push against a real GitHub repo from this
test suite. What IS checkable: the schedule interval is safely under
GitHub's 60-day scheduled-workflow auto-disable window, the workflow
has the permission it needs to push, and it never touches anything
other than its own heartbeat file (never data/, never a DuckDB path).
"""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "keepalive.yml"

# A monthly cron fires at most ~31 days apart; even one missed run
# leaves a wide margin under GitHub's 60-day auto-disable threshold.
MAX_SAFE_INTERVAL_DAYS = 45


def _load() -> dict:
    assert WORKFLOW_PATH.exists(), f"workflow file not found: {WORKFLOW_PATH}"
    doc = yaml.safe_load(WORKFLOW_PATH.read_text())
    assert isinstance(doc, dict)
    return doc


def test_schedule_is_well_under_the_60_day_auto_disable_window():
    doc = _load()
    triggers = doc.get(True, doc.get("on"))
    cron = triggers["schedule"][0]["cron"]
    minute, hour, day, month, weekday = cron.split()
    # A specific day-of-month (not "*") with "*" month means: fires
    # once per calendar month, i.e. at most ~31 days apart.
    assert day != "*", f"cron {cron!r} must fire at least monthly, not less often"
    assert month == "*", f"cron {cron!r} must fire every month"


def test_has_contents_write_permission_to_push():
    doc = _load()
    assert doc["permissions"]["contents"] == "write"


def test_only_touches_its_own_heartbeat_file():
    doc = _load()
    steps = doc["jobs"]["heartbeat"]["steps"]
    run_text = "\n".join(step.get("run", "") for step in steps)
    assert ".github/keepalive-heartbeat.txt" in run_text
    # Never touch the paths the paper trading scheduler owns.
    assert "data/" not in run_text
    assert ".duckdb" not in run_text
    assert ".parquet" not in run_text


def test_commit_is_conditional_on_an_actual_change():
    doc = _load()
    steps = doc["jobs"]["heartbeat"]["steps"]
    run_text = "\n".join(step.get("run", "") for step in steps)
    # `git diff --cached --quiet ||` skips the commit when nothing
    # changed, avoiding an empty commit on every run.
    assert "git diff --cached --quiet" in run_text
