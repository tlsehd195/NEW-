"""Static consistency checks for the sharded, full-universe SEC Form 4
insider-transaction collection workflow. Same category of checks the
other `workflow_dispatch`-only verification/collection workflows in
this repository already established -- the real execution (against
real SEC EDGAR endpoints, potentially hours long) cannot happen inside
this test suite; see `tests/scripts/test_select_universe_shard.py` and
`tests/scripts/test_merge_insider_transaction_catalogs.py` for the
real, executable coverage of the underlying scripts.
"""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ingest_insider_transactions_full.yml"


def _load() -> dict:
    assert WORKFLOW_PATH.exists(), f"workflow file not found: {WORKFLOW_PATH}"
    doc = yaml.safe_load(WORKFLOW_PATH.read_text())
    assert isinstance(doc, dict)
    return doc


def _ingest_steps(doc: dict) -> list[dict]:
    return doc["jobs"]["ingest"]["steps"]


def _merge_steps(doc: dict) -> list[dict]:
    return doc["jobs"]["merge"]["steps"]


def test_workflow_is_valid_yaml_manual_dispatch_only():
    doc = _load()
    triggers = doc.get(True, doc.get("on"))
    assert triggers is not None
    assert "workflow_dispatch" in triggers
    assert "schedule" not in triggers
    # write, not read: the merge job publishes the combined catalog to
    # a GitHub Release (see test_merge_job_publishes_the_combined_catalog_
    # to_a_durable_release below) -- this needs contents:write.
    assert doc["permissions"]["contents"] == "write"


def test_matrix_has_ten_shards_matching_the_env_shard_count():
    doc = _load()
    matrix_shards = doc["jobs"]["ingest"]["strategy"]["matrix"]["shard"]
    assert matrix_shards == list(range(10))
    assert doc["env"]["SHARD_COUNT"] == "10"


def test_matrix_uses_fail_fast_false_so_one_shard_failing_does_not_cancel_the_rest():
    doc = _load()
    assert doc["jobs"]["ingest"]["strategy"]["fail-fast"] is False


def test_each_shard_writes_to_its_own_isolated_db_path():
    """Real risk (docs/PROJECT_STATUS.md Session 37 concern): DuckDB
    allows only one read/write connection to a given file at a time --
    concurrent matrix jobs must never share a --db-path."""
    steps = _ingest_steps(_load())
    run_text = "\n".join(s.get("run", "") for s in steps)
    assert "insider_shard_${{ matrix.shard }}" in run_text


def test_each_shard_selects_its_own_symbols_via_the_shard_selector_script():
    steps = _ingest_steps(_load())
    run_text = "\n".join(s.get("run", "") for s in steps)
    assert "select_universe_shard.py" in run_text
    assert "--shard-index ${{ matrix.shard }}" in run_text
    assert "ingest_insider_transactions.py" in run_text


def test_shard_catalogs_and_manifests_are_uploaded_with_always_and_ignore_missing():
    steps = _ingest_steps(_load())
    upload_steps = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact")]
    assert len(upload_steps) == 2
    for step in upload_steps:
        assert step.get("if") == "always()"
        assert step["with"].get("if-no-files-found") == "ignore"


def test_merge_job_depends_on_ingest_and_always_runs():
    doc = _load()
    merge_job = doc["jobs"]["merge"]
    assert merge_job["needs"] == "ingest"
    assert merge_job.get("if") == "always()"


def test_merge_job_downloads_all_shards_and_runs_the_real_merge_script():
    steps = _merge_steps(_load())
    download_step = next(s for s in steps if s.get("uses", "").startswith("actions/download-artifact"))
    assert download_step["with"]["pattern"] == "insider-transactions-shard-*"

    run_text = "\n".join(s.get("run", "") for s in steps)
    assert "merge_insider_transaction_catalogs.py" in run_text
    assert "--target-db-path" in run_text


def test_merge_job_uploads_the_combined_catalog():
    steps = _merge_steps(_load())
    upload_steps = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact")]
    assert len(upload_steps) == 1
    assert upload_steps[0]["with"]["name"] == "insider-transactions-catalog"
    assert upload_steps[0].get("if") == "always()"


def test_merge_job_publishes_the_combined_catalog_to_a_durable_release():
    """A workflow artifact (above) expires after its retention window
    regardless of whether anyone comes back for it -- this step
    publishes the same catalog to a fixed, well-known Release tag
    automatically, every successful merge, so run_full_validation.yml's
    own fallback download always has a current copy without any human
    or Claude-session upload step in between."""
    steps = _merge_steps(_load())
    publish_step = next(s for s in steps if "gh release upload" in s.get("run", ""))
    assert publish_step.get("if") == "always()"
    run_text = publish_step["run"]
    assert "insider-transactions-catalog" in run_text
    assert "gh release view" in run_text  # creates the release only if it doesn't already exist
    assert "gh release create" in run_text
    assert "--clobber" in run_text  # replaces the asset in place on every run, not accumulating duplicates
    # Guards against publishing a stale/missing catalog from a run where
    # every shard failed.
    assert "if [ ! -f ./data/insider_combined/catalog.duckdb ]" in run_text
