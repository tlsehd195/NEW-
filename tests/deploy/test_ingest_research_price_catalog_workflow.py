"""Static checks for ingest_research_price_catalog.yml (ADR-0213). The
real run (Tiingo, ~10 hours) cannot happen inside this test suite; see
tests/scripts/test_ingest_real_market_data_sharding.py for the
executable coverage of the --tiingo-only/--shard-* flags it drives."""
from pathlib import Path

import yaml

from data_infra.universe import RESEARCH_UNIVERSE_STAGE5

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ingest_research_price_catalog.yml"
SHARD_SCRIPT = REPO_ROOT / "scripts" / "ingest_price_catalog_shards.sh"

# Confirmed Tiingo free tier (ADR-0160): 50/hour, of which
# TiingoRequestBudget treats 48 as usable.
_TIINGO_EFFECTIVE_HOURLY_CAP = 48
_GITHUB_HOSTED_JOB_LIMIT_MINUTES = 360


def _load() -> dict:
    doc = yaml.safe_load(WORKFLOW_PATH.read_text())
    assert isinstance(doc, dict)
    return doc


def _inputs() -> dict:
    doc = _load()
    return doc.get(True, doc.get("on"))["workflow_dispatch"]["inputs"]


def test_manual_dispatch_only_with_read_default_and_write_only_on_the_publishing_job():
    doc = _load()
    triggers = doc.get(True, doc.get("on"))
    assert set(triggers) == {"workflow_dispatch"}
    assert doc["permissions"]["contents"] == "read"
    assert "permissions" not in doc["jobs"]["part-1"]
    assert "permissions" not in doc["jobs"]["part-2"]
    assert doc["jobs"]["part-3"]["permissions"]["contents"] == "write"


def test_defaults_target_stage5_from_2000_and_end_is_required():
    inputs = _inputs()
    assert inputs["universe"]["default"] == "RESEARCH_UNIVERSE_STAGE5"
    assert inputs["start"]["default"] == "2000-01-01"
    assert inputs["end"]["required"] is True
    assert inputs["resume_from_run_id"]["default"] == ""


def _shard_runs(doc: dict) -> list[str]:
    return [
        s["run"] for job in ("part-1", "part-2", "part-3")
        for s in doc["jobs"][job]["steps"] if "ingest_price_catalog_shards.sh" in s.get("run", "")
    ]


def test_every_shard_fits_one_tiingo_hour_and_the_jobs_cover_every_shard_then_sweep():
    doc = _load()
    shard_count = int(doc["env"]["SHARD_COUNT"])
    assert int(doc["env"]["SHARD_SLEEP_SECONDS"]) > 3600
    largest_shard = -(-len(RESEARCH_UNIVERSE_STAGE5.symbols) // shard_count) + 1  # + SPY on shard 0
    assert largest_shard * 2 <= _TIINGO_EFFECTIVE_HOURLY_CAP
    assert int(doc["env"]["SWEEP_MAX_SYMBOLS"]) * 2 <= _TIINGO_EFFECTIVE_HOURLY_CAP
    assert _shard_runs(doc) == [
        "bash scripts/ingest_price_catalog_shards.sh 0 3 no-initial-sleep",
        "bash scripts/ingest_price_catalog_shards.sh 4 6 initial-sleep",
        "bash scripts/ingest_price_catalog_shards.sh 7 9 initial-sleep sweep",
    ]
    assert shard_count == 10


def test_each_job_fits_the_hosted_job_limit():
    doc = _load()
    sleep_minutes = int(doc["env"]["SHARD_SLEEP_SECONDS"]) / 60
    # part-3 sleeps before shard 7, 8, 9 and the sweep.
    assert 4 * sleep_minutes < doc["jobs"]["part-3"]["timeout-minutes"] <= _GITHUB_HOSTED_JOB_LIMIT_MINUTES
    for job in ("part-1", "part-2"):
        assert 3 * sleep_minutes < doc["jobs"][job]["timeout-minutes"] <= _GITHUB_HOSTED_JOB_LIMIT_MINUTES
    assert doc["jobs"]["part-2"]["needs"] == "part-1"
    assert doc["jobs"]["part-3"]["needs"] == "part-2"


def test_every_job_uploads_the_catalog_even_on_failure_so_a_run_can_be_resumed():
    doc = _load()
    for job in ("part-1", "part-2", "part-3"):
        uploads = [s for s in doc["jobs"][job]["steps"] if s.get("uses", "").startswith("actions/upload-artifact")]
        assert len(uploads) == 1
        assert uploads[0]["if"] == "always()"
        assert uploads[0]["with"]["overwrite"] is True
        assert uploads[0]["with"]["name"] == "${{ env.ARTIFACT_NAME }}"
    resume = next(s for s in doc["jobs"]["part-1"]["steps"] if s.get("name", "").startswith("Resume"))
    assert resume["with"]["run-id"] == "${{ inputs.resume_from_run_id }}"
    assert doc["permissions"]["actions"] == "read"


def test_shard_script_is_tiingo_only_skips_covered_symbols_and_uses_a_long_timeout():
    text = SHARD_SCRIPT.read_text()
    assert "--tiingo-only" in text
    assert "--skip-symbols-with-bars" in text
    assert '--tiingo-timeout-seconds "$TIINGO_TIMEOUT_SECONDS"' in text
    assert "--shard-index" in text and "--shard-count" in text
    assert '--max-symbols "$SWEEP_MAX_SYMBOLS"' in text
    assert float(_load()["env"]["TIINGO_TIMEOUT_SECONDS"]) > 10


def test_inputs_never_interpolated_into_run_blocks_and_only_tiingo_key_is_passed():
    doc = _load()
    for job in doc["jobs"].values():
        for step in job["steps"]:
            assert "${{ inputs." not in step.get("run", "")
            env = step.get("env", {})
            assert "TWELVEDATA_API_KEY" not in env
            assert "ALPHAVANTAGE_API_KEY" not in env


def test_coverage_report_gates_publishing():
    steps = _load()["jobs"]["part-3"]["steps"]
    names = [s.get("name", "") for s in steps]
    coverage = next(i for i, n in enumerate(names) if n.startswith("Coverage report"))
    publish = next(i for i, n in enumerate(names) if n.startswith("Publish"))
    assert coverage < publish
    assert "if" not in steps[publish]
    assert "report_price_catalog_coverage.py" in steps[coverage]["run"]


def test_shard_script_skip_marker_matches_the_ingest_scripts_own_message():
    """The script skips the hourly wait after a shard that fetched
    nothing, detected by this exact line in the ingest script's output."""
    ingest_text = (REPO_ROOT / "scripts" / "ingest_real_market_data.py").read_text()
    assert 'NOTHING_TO_DO="No symbols left to fetch"' in SHARD_SCRIPT.read_text()
    assert 'print("No symbols left to fetch -- nothing to do.")' in ingest_text
