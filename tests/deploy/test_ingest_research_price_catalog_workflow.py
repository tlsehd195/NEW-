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
    assert "permissions" not in doc["jobs"]["first-half"]
    assert doc["jobs"]["second-half"]["permissions"]["contents"] == "write"


def test_defaults_target_stage5_from_2000_and_end_is_required():
    inputs = _inputs()
    assert inputs["universe"]["default"] == "RESEARCH_UNIVERSE_STAGE5"
    assert inputs["start"]["default"] == "2000-01-01"
    assert inputs["end"]["required"] is True


def test_every_shard_fits_one_tiingo_hour_and_both_halves_cover_every_shard():
    doc = _load()
    shard_count = int(doc["env"]["SHARD_COUNT"])
    assert int(doc["env"]["SHARD_SLEEP_SECONDS"]) > 3600
    largest_shard = -(-len(RESEARCH_UNIVERSE_STAGE5.symbols) // shard_count) + 1  # + SPY on shard 0
    assert largest_shard * 2 <= _TIINGO_EFFECTIVE_HOURLY_CAP
    runs = [
        s["run"] for job in ("first-half", "second-half")
        for s in doc["jobs"][job]["steps"] if "ingest_price_catalog_shards.sh" in s.get("run", "")
    ]
    assert runs == [
        "bash scripts/ingest_price_catalog_shards.sh 0 4 no-initial-sleep",
        "bash scripts/ingest_price_catalog_shards.sh 5 9 initial-sleep",
    ]
    assert shard_count == 10


def test_each_half_fits_the_hosted_job_limit():
    doc = _load()
    sleep_minutes = int(doc["env"]["SHARD_SLEEP_SECONDS"]) / 60
    # 5 shards per half, the second half also sleeps before its first.
    assert 5 * sleep_minutes < doc["jobs"]["second-half"]["timeout-minutes"] <= _GITHUB_HOSTED_JOB_LIMIT_MINUTES
    assert doc["jobs"]["first-half"]["timeout-minutes"] <= _GITHUB_HOSTED_JOB_LIMIT_MINUTES
    assert doc["jobs"]["second-half"]["needs"] == "first-half"


def test_shard_script_is_tiingo_only():
    text = SHARD_SCRIPT.read_text()
    assert "--tiingo-only" in text
    assert "--shard-index" in text and "--shard-count" in text


def test_inputs_never_interpolated_into_run_blocks_and_only_tiingo_key_is_passed():
    doc = _load()
    for job in doc["jobs"].values():
        for step in job["steps"]:
            assert "${{ inputs." not in step.get("run", "")
            env = step.get("env", {})
            assert "TWELVEDATA_API_KEY" not in env
            assert "ALPHAVANTAGE_API_KEY" not in env


def test_coverage_report_gates_publishing():
    steps = _load()["jobs"]["second-half"]["steps"]
    names = [s.get("name", "") for s in steps]
    coverage = next(i for i, n in enumerate(names) if n.startswith("Coverage report"))
    publish = next(i for i, n in enumerate(names) if n.startswith("Publish"))
    assert coverage < publish
    assert "if" not in steps[publish]
    assert "report_price_catalog_coverage.py" in steps[coverage]["run"]
