# ADR-0162: Narrow `paper_trading_cycle.yml`'s `contents: write` to the one job that needs it

**Status:** Accepted
**Date:** 2026-09-18
**Deciders:** Claude Code (session continued)
**Related documents:** `docs/decisions/ADR-0150-paper-trading-store-git-backup.md`
(introduced the backup-commit step this permission was originally
granted for), `.github/workflows/paper_trading_cycle.yml`

---

## Context

`paper_trading_cycle.yml` granted `permissions: contents: write` at the
WORKFLOW level, applying to every step of its single `run-cycle` job --
including installing dependencies, calling the real Tiingo/Stooq
ingestion API, and running the paper trading cycle itself, none of
which ever write to this repository. Only one step, "Export and commit
Paper Trading store backup" (ADR-0150), actually needs `contents: write`
(to `git push` a JSON snapshot to this branch).

GitHub Actions' `permissions:` block only narrows access at the JOB
level, not the step level -- a workflow-level `permissions:` block sets
the default every job inherits unless a job overrides it. With a single
job, there was no narrower scope to grant; every step ran with the same
over-broad token regardless of what it actually needed.

## Decision

Split the single `run-cycle` job into two:

- `run-cycle`: everything through "Send Discord notification" --
  install, restore artifacts, ingest, run the cycle, upload artifacts,
  notify. No longer needs to write to this repo at all.
- `commit-backup`: `needs: run-cycle`, `if: always()` (an existing
  `if: always()` on the backup step's OWN job now moves to the job
  level, since a failed `run-cycle` still leaves state worth backing
  up, unchanged from before). Downloads the `paper-trading-store`
  artifact `run-cycle` uploads (jobs do not share a filesystem, so this
  artifact IS this job's only path to the updated DuckDB store), then
  runs the same `scripts/export_paper_store_backup.py` + `git commit`/`push`
  sequence as before, unchanged.

The workflow-level `permissions:` block is narrowed to `contents: read`
(the GitHub Actions default token scope, made explicit rather than
implicit) + `actions: read` (needed by `run-cycle`'s artifact-restore
steps, which call `gh api .../actions/artifacts`). `commit-backup`
declares its own job-level `permissions: contents: write` + `actions: read`
(the latter to download `run-cycle`'s artifact) -- the ONLY place in
this workflow that still has write access to the repository.

## Consequences

### Positive

- The GITHUB_TOKEN used by every ingestion/paper-trading-cycle step
  (the largest, most complex, most likely-to-be-compromised-by-a-bug
  part of this workflow) can no longer push to this repository even if
  something in that code path were tricked into trying to.
- No behavior change to the backup itself: same export script, same
  overwrite-not-accumulate semantics, same `if: always()`-equivalent
  "back up whatever exists even after a failure" guarantee.

### Negative / Trade-offs

- `commit-backup` re-downloads the `paper-trading-store` artifact that
  `run-cycle` already had in its own filesystem, an unavoidable cost of
  jobs not sharing a filesystem -- a small amount of extra I/O per run,
  not a correctness concern.
- If `run-cycle` fails before its "Upload updated paper-trading store"
  step runs (e.g. `actions/checkout` itself fails), `commit-backup`'s
  artifact download has nothing to fetch and that job's own steps fail
  in turn -- this is not a regression: the single-job version's backup
  step would have faced the equivalent problem (an empty/missing
  `$PAPER_STORE_DIR`) in that same edge case.

## Tests

No unit-testable logic changed (a workflow YAML restructuring, not
application code) -- validated by parsing the YAML with `yaml.safe_load`
and confirming both jobs, their step lists, and their `permissions`
blocks are exactly as intended. Full local test suite re-run
unaffected (no Python source changed by this ADR).

## Status of Implementation at Time of This ADR

Code (workflow YAML) and documentation complete and committed. Not
independently verified against a real `workflow_dispatch` run within
this session -- unlike ADR-0156/ADR-0157's changes, this is a pure
job/permission restructuring, and the account owner did not request an
extra live-run verification cycle for it. The next scheduled or
manually-dispatched run of this workflow is the first real confirmation
that `commit-backup` correctly receives and applies the artifact.
