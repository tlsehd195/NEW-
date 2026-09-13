"""Static consistency checks for the weekly Learning Cycle scheduler
workflow (Session 37 continued). Same rationale and same limitation as
`test_paper_trading_cycle_workflow.py`: the workflow's real execution
(against a real restored paper-trading-store artifact) cannot happen
inside this test suite. What IS checkable without running it: the YAML
is well-formed, it invokes the real script with the right catalog
path, it round-trips the same `paper-trading-store` artifact the daily
Paper Trading Cycle produces, and it defends against the same wrapped-
artifact-zip failure mode that workflow already had to handle.
"""
import subprocess
import tempfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "learning_cycle.yml"


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


def test_workflow_is_valid_yaml_with_a_weekly_schedule_trigger():
    doc = _load()
    # PyYAML parses the bare `on:` key as the boolean True.
    triggers = doc.get(True, doc.get("on"))
    assert triggers is not None
    assert "schedule" in triggers
    assert triggers["schedule"][0]["cron"] == "0 6 * * 6"
    assert "workflow_dispatch" in triggers


def test_workflow_grants_only_read_permissions():
    doc = _load()
    perms = doc["permissions"]
    assert perms.get("contents") == "read"
    assert perms.get("actions") == "read"


def test_runs_the_real_learning_cycle_script_against_the_shared_paper_store():
    steps = _steps(_load())
    text = _run_text(steps)
    assert "run_learning_cycle.py" in text
    assert '--paper-store "$PAPER_STORE_DIR"' in text


def test_restores_the_same_paper_trading_store_artifact_the_daily_cycle_produces():
    steps = _steps(_load())
    run_text = _run_text(steps)
    assert "paper-trading-store" in run_text

    upload_steps = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact")]
    uploaded_names = {s["with"]["name"] for s in upload_steps}
    assert "paper-trading-store" in uploaded_names
    for step in upload_steps:
        assert step.get("if") == "always()", (
            f"{step.get('name')} must upload with if: always() so a failed "
            "run does not silently lose already-written state"
        )


def test_fails_loudly_when_no_prior_paper_store_artifact_exists():
    # Retraining from a paper store that was never even restored would
    # silently train from nothing (or a stale local empty directory) --
    # the restore step must hard-fail instead, matching this project's
    # never-silently-succeed discipline.
    steps = _steps(_load())
    restore_step = next(s for s in steps if s.get("name", "").startswith("Restore previous"))
    run_text = restore_step.get("run", "")
    assert "FATAL" in run_text and "exit 1" in run_text


def test_restore_step_defends_against_a_wrapped_artifact_zip():
    """Same ADR-0115 (external review N-14) defense
    `paper_trading_cycle.yml`'s restore steps already carry."""
    steps = _steps(_load())
    restore_step = next(s for s in steps if s.get("name", "").startswith("Restore previous"))
    run_text = restore_step.get("run", "")
    assert "catalog.duckdb" in run_text
    assert "find" in run_text and "-maxdepth 1" in run_text


def test_the_flatten_logic_actually_promotes_a_wrapped_subfolders_contents():
    """Real, executable proof the flatten snippet works -- not just that
    matching text is present in the workflow file. Reproduces the exact
    shell logic used by the restore step (kept byte-for-byte identical
    to the workflow via the substring assertion below) against a real
    temp directory shaped the way a wrapped `actions/upload-artifact@v4`
    zip would extract."""
    flatten_snippet = (
        'if [ ! -f "$DIR/catalog.duckdb" ]; then\n'
        '  SUBDIRS=$(find "$DIR" -mindepth 1 -maxdepth 1 -type d)\n'
        '  SUBDIR_COUNT=$(printf \'%s\\n\' "$SUBDIRS" | grep -c . || true)\n'
        '  if [ "$SUBDIR_COUNT" = "1" ] && [ -f "$SUBDIRS/catalog.duckdb" ]; then\n'
        '    echo "Artifact was wrapped in a subfolder ($SUBDIRS) -- flattening"\n'
        '    cp -r "$SUBDIRS"/. "$DIR"/\n'
        '    rm -rf "$SUBDIRS"\n'
        "  fi\n"
        "fi\n"
    )

    def _normalized(text: str) -> str:
        return "\n".join(line.strip() for line in text.strip().splitlines())

    run_text = _run_text(_steps(_load()))
    normalized_run_text = _normalized(run_text)
    assert _normalized(flatten_snippet.replace("$DIR", "$PAPER_STORE_DIR")) in normalized_run_text, (
        "the workflow's restore step no longer matches the tested flatten snippet"
    )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wrapped = root / "paper_trading_store"
        wrapped.mkdir()
        (wrapped / "catalog.duckdb").write_text("real catalog content")

        script = f'DIR="{root}"\n{flatten_snippet}'
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

        assert (root / "catalog.duckdb").read_text() == "real catalog content"
        assert not wrapped.exists()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "catalog.duckdb").write_text("already at top level")
        script = f'DIR="{root}"\n{flatten_snippet}'
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert (root / "catalog.duckdb").read_text() == "already at top level"
