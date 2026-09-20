"""Static consistency checks, across every workflow file at once, for
ADR-0184 (independent audit, workflow hygiene): every one of this
repository's 13 GitHub Actions workflows previously had neither a
`concurrency` group nor a `timeout-minutes` on any job.

**The real risk this closes**: several of these workflows restore a
prior run's artifact, mutate it, and re-upload it under the same name
(`market-data-catalog`, `paper-trading-store`, the various insider-
transaction catalogs). Two overlapping runs of the SAME workflow --
either a slow scheduled run still going when the next scheduled fire
lands, or a manual `workflow_dispatch` re-run while one is already in
flight -- would both restore the same artifact, both mutate it
independently, and whichever uploads last silently wins, discarding the
other's work with no error. A `concurrency` group per workflow (keyed
on `github.workflow`+`github.ref`, `cancel-in-progress: false`) makes a
second run wait for the first to finish rather than race it.

`cancel-in-progress: false` specifically (not `true`): these are real
data-mutating jobs (SEC EDGAR ingestion, DuckDB catalog merges) --
cancelling one mid-write risks leaving a half-written artifact, which
`cancel-in-progress: true` would happily do. Queuing is the safe choice
here, `timeout-minutes` (below) is what keeps that queue from
deadlocking behind a hung job.

A single consolidated test file, not one file per workflow: the
assertion is identical across every workflow (a real, deliberately
chosen `concurrency` group exists at the workflow level; every job with
`runs-on` has an explicit, positive `timeout-minutes`), so verifying it
generically here covers all 13 without 13 near-identical files.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

ALL_WORKFLOW_FILES = sorted(WORKFLOWS_DIR.glob("*.yml"))


def _load(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text())
    assert isinstance(doc, dict), f"{path.name} did not parse to a mapping"
    return doc


def test_at_least_thirteen_workflows_are_covered() -> None:
    # A floor, not an exact count -- a future new workflow file should
    # extend this coverage automatically (the loop below is generic),
    # not silently shrink the set this test protects.
    assert len(ALL_WORKFLOW_FILES) >= 13


def test_every_workflow_declares_a_real_concurrency_group() -> None:
    for path in ALL_WORKFLOW_FILES:
        doc = _load(path)
        concurrency = doc.get("concurrency")
        assert concurrency is not None, f"{path.name} has no top-level concurrency group"
        assert concurrency.get("group"), f"{path.name}'s concurrency group is empty"
        assert "github.workflow" in concurrency["group"], (
            f"{path.name}'s concurrency group must be scoped per-workflow "
            "(github.workflow), not shared across unrelated workflows"
        )
        assert concurrency.get("cancel-in-progress") is False, (
            f"{path.name} must queue overlapping runs (cancel-in-progress: false), "
            "never cancel one mid-write into a shared artifact"
        )


def test_every_job_declares_a_positive_timeout() -> None:
    for path in ALL_WORKFLOW_FILES:
        doc = _load(path)
        jobs = doc.get("jobs") or {}
        assert jobs, f"{path.name} has no jobs"
        for job_name, job in jobs.items():
            timeout = job.get("timeout-minutes")
            assert isinstance(timeout, int) and timeout > 0, (
                f"{path.name}::{job_name} has no positive timeout-minutes -- "
                "a hung step here would otherwise run for GitHub's own "
                "6-hour default, blocking every later run queued behind it "
                "by this same workflow's own concurrency group"
            )
