"""Category: CI supply-chain hardening (Batch K's adoption of
EXTERNAL_REPO_APPLICABILITY_REPORT.md's priority-3 recommendation -- pin
every GitHub Action to an immutable commit SHA, matching the practice
already applied to this repo's own third-party CSV fetch, ADR-0187
Batch J, and the CI hygiene colibri/Vibe-Trading/DeerFlow's own
workflows all independently converged on).

A floating major-version tag like `@v4` can be repointed by the action's
maintainer -- or, in a supply-chain compromise, by an attacker who has
taken over that maintainer's account -- to point at a different commit
at any time, with nothing in THIS repository's own history changing to
reflect it. Every `uses:` reference must be a real 40-character commit
SHA, with a human-readable `# vX.Y.Z` comment alongside it so the pin
stays understandable and bumpable without first having to resolve the
SHA back to a version.

One consolidated file across every workflow, matching
test_workflow_concurrency_and_timeouts.py's own precedent: the
assertion is identical for all of them, so verifying it generically here
covers every workflow without one near-identical file per workflow."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
ALL_WORKFLOW_FILES = sorted(WORKFLOWS_DIR.glob("*.yml"))

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA_REF_LINE_RE = re.compile(r"uses:\s*\S+@[0-9a-f]{40}")
_VERSION_COMMENT_RE = re.compile(r"@[0-9a-f]{40}\s*#\s*v\d")


def _load(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text())
    assert isinstance(doc, dict), f"{path.name} did not parse to a mapping"
    return doc


def _iter_uses_refs(doc: dict):
    for job_name, job in (doc.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            uses = step.get("uses")
            if uses:
                yield job_name, uses


def test_at_least_thirteen_workflows_are_covered() -> None:
    # A floor, not an exact count (a future workflow extends this
    # generic loop's coverage automatically).
    assert len(ALL_WORKFLOW_FILES) >= 13


def test_every_action_reference_is_pinned_to_a_commit_sha() -> None:
    for path in ALL_WORKFLOW_FILES:
        doc = _load(path)
        for job_name, uses in _iter_uses_refs(doc):
            assert "@" in uses, f"{path.name}::{job_name} uses {uses!r} with no version pin at all"
            _action, ref = uses.rsplit("@", 1)
            assert _SHA_RE.match(ref), (
                f"{path.name}::{job_name} uses {uses!r} pinned to a floating ref "
                f"({ref!r}), not an immutable 40-character commit SHA"
            )


def test_every_sha_pinned_action_documents_its_version_in_a_trailing_comment() -> None:
    for path in ALL_WORKFLOW_FILES:
        for line_num, line in enumerate(path.read_text().splitlines(), start=1):
            if not _SHA_REF_LINE_RE.search(line):
                continue
            assert _VERSION_COMMENT_RE.search(line), (
                f"{path.name}:{line_num} pins an action to a commit SHA with no "
                f"'# vX.Y.Z' comment documenting which version that is: {line!r}"
            )
