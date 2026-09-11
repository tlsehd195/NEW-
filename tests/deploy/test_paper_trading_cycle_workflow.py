"""Static consistency checks for the GitHub Actions scheduler workflow
(ADR-0082). The workflow's real execution (against a real network and
a real Tiingo API key) cannot happen inside this test suite -- same
long-standing caveat as `ingest_real_market_data.py` itself. What IS
checkable without running it: the YAML is well-formed, it invokes the
same scripts with the ratified flags, and no secret value is ever
hardcoded into the file.
"""
import subprocess
import tempfile
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


def test_ingestion_requests_the_incremental_start_not_the_full_fixed_range():
    # ADR-0085: a real run re-requesting the full $START_DATE..today
    # range every day exhausted the provider's rate limit partway
    # through (10 symbols, including SPY, got zero bars). The
    # ingestion step must use the computed incremental start, not
    # $START_DATE directly.
    steps = _steps(_load())
    start_step = next(s for s in steps if s.get("id") == "ingest_start")
    assert "compute_incremental_ingestion_start.py" in start_step.get("run", "")
    assert "--fallback-start \"$START_DATE\"" in start_step.get("run", "")

    ingest_step = next(s for s in steps if "ingest_real_market_data.py" in s.get("run", ""))
    ingest_run = ingest_step.get("run", "")
    assert "steps.ingest_start.outputs.start" in ingest_run
    assert '--start "$START_DATE"' not in ingest_run


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


def test_both_restore_steps_defend_against_a_wrapped_artifact_zip():
    """Session 37 (ADR-0115, external review N-14): `actions/upload-
    artifact@v4` may wrap a single-directory upload in a subfolder named
    after that directory instead of flattening its contents to the zip
    root -- undetected, a wrapped zip would look exactly like "no prior
    catalog" to every downstream step (the marker file `catalog.duckdb`
    would be one level too deep), forcing a full re-request every run
    and risking a repeat of ADR-0085's rate-limit incident. Both restore
    steps must check for and flatten a single wrapping subfolder."""
    steps = _steps(_load())
    restore_steps = [s for s in steps if s.get("name", "").startswith("Restore previous")]
    assert len(restore_steps) == 2
    for step in restore_steps:
        run_text = step.get("run", "")
        assert "catalog.duckdb" in run_text, f"{step['name']} has no marker-file check for a wrapped zip"
        assert "find" in run_text and "-maxdepth 1" in run_text, f"{step['name']} has no single-subfolder detection"


def test_the_flatten_logic_actually_promotes_a_wrapped_subfolders_contents():
    """Real, executable proof the flatten snippet works -- not just that
    matching text is present in the workflow file. Reproduces the exact
    shell logic used by both restore steps (kept byte-for-byte identical
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
        # YAML block-scalar indentation is not semantically meaningful
        # here -- compare line content only, ignoring leading whitespace.
        return "\n".join(line.strip() for line in text.strip().splitlines())

    run_text = _run_text(_steps(_load()))
    normalized_run_text = _normalized(run_text)
    # The real workflow substitutes $MARKET_DATA_DIR/$PAPER_STORE_DIR for
    # $DIR -- confirm the same logic, modulo that one variable name, is
    # really what's in the file (not just a similarly-worded comment).
    for var in ("MARKET_DATA_DIR", "PAPER_STORE_DIR"):
        assert _normalized(flatten_snippet.replace("$DIR", f"${var}")) in normalized_run_text, (
            f"the workflow's {var} restore step no longer matches the tested flatten snippet"
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wrapped = root / "real_market_data"
        wrapped.mkdir()
        (wrapped / "catalog.duckdb").write_text("real catalog content")
        (wrapped / "parquet").mkdir()
        (wrapped / "parquet" / "marker.parquet").write_text("x")

        script = f'DIR="{root}"\n{flatten_snippet}'
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

        assert (root / "catalog.duckdb").read_text() == "real catalog content"
        assert (root / "parquet" / "marker.parquet").exists()
        assert not wrapped.exists()

    with tempfile.TemporaryDirectory() as tmp:
        # Unwrapped case (today's actual, un-reproduced-locally behavior,
        # or a future upload-artifact version that doesn't wrap) must be
        # a complete no-op -- never touched, never mistaken for wrapped.
        root = Path(tmp)
        (root / "catalog.duckdb").write_text("already at top level")
        script = f'DIR="{root}"\n{flatten_snippet}'
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert (root / "catalog.duckdb").read_text() == "already at top level"
