"""Category: a real, self-inflicted bug caught by an external independent
audit (2026-09-24, 13-stage review of this repository) --
`ingest_insider_transactions_full.yml`'s "Publish the combined catalog
to a durable Release" step (added earlier this same session) had a
stray `if-no-files-found: ignore` line INSIDE its `run: |` shell block,
left over from being copy-pasted near an `upload-artifact` step's
`with:` block. That step has no `with:` key at all -- nothing
consumes that line as YAML, so it becomes literal shell text executed
right after the real `gh release upload` succeeds.

Reproduced directly (`bash -c 'if-no-files-found: ignore'`) --
`bash: line 1: if-no-files-found:: command not found`, exit 127. Under
`set -euo pipefail` (every `run:` block in this repo's workflows starts
with it) that kills the step -- so the step, and therefore the job,
reports FAILURE every single time, even though the actual publish
(the line right before it) already succeeded. This is exactly the
"CI shows red on a run that actually worked" alert-fatigue failure
mode this project's own monitoring/operations discipline exists to
avoid.

One consolidated, generic scan across every workflow (matching
`test_workflow_actions_are_sha_pinned.py`'s own precedent) rather than
one test per workflow -- this bug class (a GitHub-Actions-step-level
YAML key, valid only inside a `with:`/step mapping, leaking into a
`run:` block's shell text) can recur in any future workflow edit, not
just this one file."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
ALL_WORKFLOW_FILES = sorted(WORKFLOWS_DIR.glob("*.yml"))

# Step-level (or with:-block) keys that are valid GitHub Actions YAML
# syntax but are never a real, standalone bash command a workflow's own
# run: block would legitimately contain -- a bare "<key>: <value>" line
# matching one of these, at a run: block's own top indentation level, is
# almost certainly a misplaced YAML key rather than intentional shell.
_LEAKED_STEP_KEY_RE = re.compile(
    r"^(if-no-files-found|retention-days|continue-on-error|working-directory)\s*:\s*\S"
)


def _load(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text())
    assert isinstance(doc, dict), f"{path.name} did not parse to a mapping"
    return doc


def _iter_run_blocks(doc: dict):
    for job_name, job in (doc.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            run = step.get("run")
            if run:
                yield job_name, step.get("name", "<unnamed step>"), run


def test_at_least_thirteen_workflows_are_covered() -> None:
    assert len(ALL_WORKFLOW_FILES) >= 13


def test_no_run_block_contains_a_leaked_step_level_yaml_key() -> None:
    for path in ALL_WORKFLOW_FILES:
        doc = _load(path)
        for job_name, step_name, run in _iter_run_blocks(doc):
            for line in run.splitlines():
                assert not _LEAKED_STEP_KEY_RE.match(line.strip()), (
                    f"{path.name}::{job_name}::{step_name!r} run: block contains "
                    f"{line.strip()!r} -- this looks like a GitHub Actions step-level "
                    f"YAML key (valid only inside a with:/step mapping) that leaked "
                    f"into shell text; it will execute as a bash command and fail "
                    f"with 'command not found' right after whatever ran before it, "
                    f"marking an otherwise-successful step as FAILED"
                )


def test_ingest_insider_transactions_full_publish_step_no_longer_has_the_leaked_key() -> None:
    """The exact, real bug the external audit caught -- pinned as its
    own explicit regression test, not just covered generically above."""
    doc = _load(WORKFLOWS_DIR / "ingest_insider_transactions_full.yml")
    publish_step = next(
        s for s in doc["jobs"]["merge"]["steps"]
        if "Publish the combined catalog" in s.get("name", "")
    )
    assert "if-no-files-found" not in publish_step["run"]


# Independent audit finding (2026-09-24): a `workflow_dispatch` input
# interpolated directly into a `run:` block via `${{ inputs.foo }}` is a
# real script-injection vector -- GitHub expands the `${{ }}` expression
# BEFORE the shell ever sees the script, so a crafted input string
# becomes literal shell code, not a quoted argument, with whatever
# secrets/permissions that job's `env:` carries in scope. Only a free
# `type: string` input is exploitable this way -- GitHub itself
# constrains a `type: choice`/`type: boolean` input to one of a fixed,
# non-attacker-controlled set of values before the workflow ever runs,
# so those are excluded here (`ingest_fama_french_factors.yml`'s
# `frequency`, `repair_ingestion_time_inversions.yml`'s `apply`).
_INPUT_INTERPOLATION_RE = re.compile(r"\$\{\{\s*inputs\.([A-Za-z0-9_-]+)\s*\}\}")


def _string_input_names(doc: dict) -> set[str]:
    dispatch = ((doc.get("on") or {}).get("workflow_dispatch") or {})
    inputs = dispatch.get("inputs") or {}
    return {
        name for name, spec in inputs.items()
        if (spec or {}).get("type", "string") == "string"
    }


def test_no_run_block_interpolates_a_free_string_workflow_dispatch_input_directly() -> None:
    for path in ALL_WORKFLOW_FILES:
        doc = _load(path)
        string_inputs = _string_input_names(doc)
        if not string_inputs:
            continue
        for job_name, step_name, run in _iter_run_blocks(doc):
            for match in _INPUT_INTERPOLATION_RE.finditer(run):
                input_name = match.group(1)
                assert input_name not in string_inputs, (
                    f"{path.name}::{job_name}::{step_name!r} run: block interpolates "
                    f"${{{{ inputs.{input_name} }}}} directly -- a free-text "
                    f"workflow_dispatch input must be passed via env: and referenced "
                    f"as a shell variable instead, never interpolated into the run: "
                    f"block's own text (script-injection risk: GitHub expands ${{{{ }}}} "
                    f"before the shell parses the script)"
                )
