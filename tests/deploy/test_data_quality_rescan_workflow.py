"""Static consistency checks for the manual Retroactive Data Quality
Rescan workflow (Session 37, ADR-0128). Same category of checks
`test_paper_trading_cycle_workflow.py`/`test_learning_cycle_workflow.py`
already established: the workflow's real execution (against a real
restored market-data-catalog artifact) cannot happen inside this test
suite (see `tests/data_infra/test_rescan_data_quality_cli.py` for the
real, executable coverage of the underlying script itself).
"""
import subprocess
import tempfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "data_quality_rescan.yml"


def _load() -> dict:
    assert WORKFLOW_PATH.exists(), f"workflow file not found: {WORKFLOW_PATH}"
    text = WORKFLOW_PATH.read_text()
    doc = yaml.safe_load(text)
    assert isinstance(doc, dict)
    return doc


def _steps(doc: dict) -> list[dict]:
    jobs = doc["jobs"]
    assert "rescan" in jobs
    return jobs["rescan"]["steps"]


def _run_text(steps: list[dict]) -> str:
    return "\n".join(step.get("run", "") for step in steps)


def test_workflow_is_valid_yaml_with_a_weekly_schedule_and_manual_dispatch():
    """ADR-0129 revised ADR-0128's original manual-only decision: at this
    project's actual data scale, a full rescan is cheap enough to run
    weekly (defense-in-depth), timed before the Saturday Learning Cycle
    reads the same catalog. workflow_dispatch stays too, for an
    immediate on-demand run."""
    doc = _load()
    # PyYAML parses the bare `on:` key as the boolean True.
    triggers = doc.get(True, doc.get("on"))
    assert triggers is not None
    assert "workflow_dispatch" in triggers
    assert "schedule" in triggers
    assert triggers["schedule"][0]["cron"] == "0 5 * * 6"


def test_workflow_grants_only_read_permissions():
    doc = _load()
    perms = doc["permissions"]
    assert perms.get("contents") == "read"
    assert perms.get("actions") == "read"


def test_runs_the_real_rescan_script_against_the_market_data_catalog():
    steps = _steps(_load())
    text = _run_text(steps)
    assert "rescan_data_quality.py" in text
    assert '--db-path "$MARKET_DATA_DIR"' in text


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
    """This is a market-data-catalog-only operation -- the Trade
    Journal/decisions/candidate models in paper-trading-store are out of
    scope (see the workflow's own header comment)."""
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
    `paper_trading_cycle.yml`'s restore steps already carry."""
    steps = _steps(_load())
    restore_step = next(s for s in steps if s.get("name", "").startswith("Restore market-data-catalog"))
    run_text = restore_step.get("run", "")
    assert "catalog.duckdb" in run_text
    assert "find" in run_text and "-maxdepth 1" in run_text


def test_the_flatten_logic_actually_promotes_a_wrapped_subfolders_contents():
    """Real, executable proof the flatten snippet works -- not just that
    matching text is present in the workflow file."""
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
    assert _normalized(flatten_snippet.replace("$DIR", "$MARKET_DATA_DIR")) in normalized_run_text, (
        "the workflow's restore step no longer matches the tested flatten snippet"
    )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wrapped = root / "real_market_data"
        wrapped.mkdir()
        (wrapped / "catalog.duckdb").write_text("real catalog content")

        script = f'DIR="{root}"\n{flatten_snippet}'
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

        assert (root / "catalog.duckdb").read_text() == "real catalog content"
        assert not wrapped.exists()
