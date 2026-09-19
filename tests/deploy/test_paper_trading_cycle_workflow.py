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


def _backup_job_steps(doc: dict) -> list[dict]:
    jobs = doc["jobs"]
    assert "commit-backup" in jobs
    return jobs["commit-backup"]["steps"]


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


def test_run_cycle_job_no_longer_has_contents_write():
    """ADR-0162: `run-cycle` never pushes to this repo -- only the
    "commit-backup" job below does -- so the workflow-level default
    every job inherits (unless it overrides it, GitHub Actions'
    documented `permissions:` semantics) must not grant `write` here.
    `actions: read` stays, since `run-cycle`'s own artifact-restore
    steps call `gh api .../actions/artifacts`."""
    doc = _load()
    perms = doc["permissions"]
    assert perms.get("contents") == "read"
    assert perms.get("actions") == "read"
    assert "permissions" not in doc["jobs"]["run-cycle"], (
        "run-cycle must not override the workflow-level default with its own write grant"
    )


def test_commit_backup_job_has_contents_write_and_the_real_push():
    """ADR-0162: `contents: write` is narrowed to exactly the job whose
    steps actually push -- confirmed here that the elevation is real
    (the "commit-backup" job's own `permissions:`) and that the step
    actually using it exists, not a permission granted and then
    unused. Also depends on "run-cycle" and runs even on its failure
    (`if: always()`), matching the single-job version's own "back up
    whatever exists even after a failed cycle" guarantee."""
    doc = _load()
    backup_job = doc["jobs"]["commit-backup"]
    perms = backup_job["permissions"]
    assert perms.get("contents") == "write"
    assert perms.get("actions") == "read"
    assert backup_job.get("needs") == "run-cycle"
    assert backup_job.get("if") == "always()"

    steps = _backup_job_steps(doc)
    backup_step = next(s for s in steps if "export_paper_store_backup.py" in s.get("run", ""))
    assert "git push" in backup_step["run"]

    download_steps = [s for s in steps if s.get("uses", "").startswith("actions/download-artifact")]
    assert any(s["with"]["name"] == "paper-trading-store" for s in download_steps), (
        "commit-backup must download the paper-trading-store artifact run-cycle uploaded -- "
        "jobs never share a filesystem, so this is its only path to the updated DuckDB store"
    )


def test_no_secret_value_is_hardcoded():
    steps = _steps(_load())
    ingest_step = next(s for s in steps if "ingest_real_market_data.py" in s.get("run", ""))
    env = ingest_step.get("env", {})
    assert env.get("MARKET_DATA_API_KEY") == "${{ secrets.MARKET_DATA_API_KEY }}", (
        "the API key must be referenced via the secrets context, never a "
        "literal value in the workflow file"
    )


def test_second_and_third_tier_provider_keys_are_wired_via_secrets_context():
    """ADR-0164: Twelve Data/Alpha Vantage extend the Tiingo fallback
    chain (Stooq, the original secondary, is a confirmed permanent
    dead end -- ADR-0160 -- and needs no API key/secret at all)."""
    steps = _steps(_load())
    ingest_step = next(s for s in steps if "ingest_real_market_data.py" in s.get("run", ""))
    env = ingest_step.get("env", {})
    assert env.get("TWELVEDATA_API_KEY") == "${{ secrets.TWELVEDATA_API_KEY }}"
    assert env.get("ALPHAVANTAGE_API_KEY") == "${{ secrets.ALPHAVANTAGE_API_KEY }}"


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
    # ADR-0177 continuation (independent audit P1-3, account owner's own
    # explicit choice, 2026-09-19): drawdown/volatility limits were
    # previously left disabled (None) in production even though the
    # script has supported them since Session 36 and --resume already
    # reconstructs real value_history for them. 0.20/0.30 are
    # risk.config.RiskConfig's own existing dataclass defaults, not new
    # numbers invented for this workflow.
    assert "--max-drawdown 0.20" in text
    assert "--max-portfolio-volatility 0.30" in text


def test_performance_tearsheet_is_generated_and_never_fails_the_job():
    """Account owner's own request (2026-09-18): automate the optional
    quantstats tearsheet (ADR-0138) so nobody needs a local `pip
    install -e '.[reporting]'` -- must never fail the job (a fresh
    --paper-store with fewer than 2 checkpoints is expected on this
    cycle's very first few runs, not a real failure)."""
    steps = _steps(_load())
    text = _run_text(steps)
    assert "pip install -e '.[reporting]'" in text
    assert "generate_paper_performance_tearsheet.py" in text
    assert '--paper-store "$PAPER_STORE_DIR"' in text

    tearsheet_steps = [
        s for s in steps
        if "reporting" in s.get("run", "") or "tearsheet" in s.get("run", "")
    ]
    assert tearsheet_steps
    for step in tearsheet_steps:
        assert step.get("continue-on-error") is True, (
            f"{step.get('name')} must set continue-on-error so a tearsheet "
            "failure never blocks the real trading cycle"
        )

    upload_steps = [s for s in _steps(_load()) if s.get("uses", "").startswith("actions/upload-artifact")]
    tearsheet_upload = next(s for s in upload_steps if "tearsheet" in s["with"]["name"])
    assert tearsheet_upload.get("if") == "always()"
    assert tearsheet_upload["with"].get("if-no-files-found") == "ignore"


def test_signal_ic_alphalens_script_is_deliberately_not_automated():
    """TEST-1 (src/strategy_research/locked_windows.py) spans
    2023-04-28 to 2026-08-27, which covers this project's entire real
    ingested history (START_DATE 2024-01-02) until very recently --
    wiring scripts/verify_signal_ic_with_alphalens.py (ADR-0139) into
    this daily schedule would either violate the locked-window guard
    every single run or run over too little post-lock data to mean
    anything. Deliberately left as a manual/occasional research
    script, unlike the tearsheet above."""
    text = _run_text(_steps(_load()))
    assert "verify_signal_ic_with_alphalens.py" not in text


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
