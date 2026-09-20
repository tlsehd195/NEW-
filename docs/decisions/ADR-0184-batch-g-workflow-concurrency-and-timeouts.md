# ADR-0184: Concurrency groups + timeouts on all 13 GitHub Actions workflows (audit Batch G)

**Status:** Accepted
**Date:** 2026-09-20
**Deciders:** Claude Code (session continued), account owner (asked to
process every remaining P2/P3 finding from the independent audit
report, in batches; this is Batch G -- workflow hygiene)

## Context

The independent audit's workflow-hygiene finding: none of this
repository's GitHub Actions workflows declared a `concurrency` group or
a `timeout-minutes` on any job. Confirmed real, directly: a repo-wide
grep of `.github/workflows/*.yml` found zero occurrences of either key
across all 13 files.

**The real risk**: several of these workflows restore a prior run's
artifact, mutate it, and re-upload it under the same name
(`market-data-catalog`, `paper-trading-store`, the various insider-
transaction catalogs). Two overlapping runs of the SAME workflow --
either a slow scheduled run still executing when the next scheduled
fire lands, or a manual `workflow_dispatch` re-run started while one is
already in flight -- would both restore the same artifact, both mutate
it independently, and whichever uploads last silently wins, discarding
the other's work with no error and no warning. This is the same class
of risk `paper_trading_cycle.yml`'s own wrapped-artifact-zip defense
(ADR-0115) was built to catch, but for a different failure mode:
correct artifact shape, wrong number of writers.

Separately: with no `timeout-minutes`, every job defaults to GitHub's
own 6-hour job timeout. A hung step (a network call that never times
out internally, a stuck subprocess) would occupy a runner for up to 6
hours before GitHub itself kills it -- and once a `concurrency` group is
added (this ADR), a hung run also blocks every later run of that same
workflow queued behind it for that entire window, turning a single
transient hang into a multi-hour outage of the whole workflow.

## Decision

All 13 workflow files gained, at the workflow level (immediately before
their existing `permissions:` block):

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: false
```

`cancel-in-progress: false`, not `true`: these are real data-mutating
jobs (SEC EDGAR ingestion, DuckDB catalog merges, paper trading
cycles) -- cancelling one mid-write risks leaving a half-written
artifact or a partially-applied commit, which `cancel-in-progress:
true` would happily do. Queuing the second run behind the first is the
safe choice; it is also the only one of the two that actually prevents
the "both mutate independently" race above.

Every job (`runs-on: ubuntu-latest`) across all 13 workflows gained an
explicit `timeout-minutes`, sized to that job's own real nature rather
than one blanket number:
- Quick verification/reconciliation jobs (`verify_alpaca_paper_broker`,
  `verify_insider_transactions_ingestion`, `recon_kenneth_french_
  library`): 20 minutes.
- Moderate single-purpose jobs (`ingest_fama_french_factors`, `recon_
  stockanalysis_delisted`, `repair_ingestion_time_inversions`, the
  insider-transaction catalog merge job): 30 minutes.
- Real network-bound ingestion jobs (`append_symbols_to_insider_
  catalog`, `ingest_stockanalysis_wayback_delisted_prices`, the daily
  `paper_trading_cycle` run-cycle job): 60 minutes.
- The insider-transaction full-universe matrix shards
  (`ingest_insider_transactions_full`'s `ingest` job): 240 minutes --
  this workflow's own comment already documents a real ~2-hour run for
  one unusually prolific symbol (JPM), so 60 would be a false-positive
  timeout risk on this job specifically.
- Weekly/scheduled cycle jobs with more historical work per run
  (`data_quality_rescan`, `learning_cycle`): 90 minutes.
- `paper_trading_cycle`'s `commit-backup` job: 15 minutes (a git
  add/commit/push of an already-produced artifact, not new compute).
- `keepalive`'s `heartbeat` job: 5 minutes (a trivial file write and
  commit).

## Consequences

### Positive
- Closes a real, previously undefended race: two overlapping runs of
  the same workflow can no longer both mutate and re-upload the same
  named artifact; the second now queues behind the first instead.
- A hung step now fails fast (per its own job's real expected duration)
  rather than silently occupying a runner, and a future workflow's own
  concurrency-queued run, for up to 6 hours.
- Purely additive YAML keys -- no step, script invocation, or existing
  behavior changed. Every existing workflow-level test in
  `tests/deploy/` passed unmodified.

### Negative / Trade-offs
- A job that occasionally runs longer than its assigned timeout under
  real conditions (e.g., an unusually slow SEC EDGAR response spread
  across many symbols) will now be killed rather than eventually
  finishing -- the timeouts above are deliberately generous relative to
  documented real run times, but are still a new failure mode that
  didn't exist before this ADR. A workflow that starts failing only on
  timeout, never on its own step logic, is the signal to raise that one
  job's number, not to remove the timeout.
- `cancel-in-progress: false` means a queued second run waits for the
  first to finish before starting, which can delay a manually
  triggered re-run (e.g., someone re-running `workflow_dispatch` right
  after kicking off the same workflow) rather than running it
  immediately -- an accepted cost given the alternative is a silent
  data race.

## Tests

`tests/deploy/test_workflow_concurrency_and_timeouts.py` (new, 3
tests): confirms at least 13 workflow files exist; every workflow
declares a real, per-workflow-scoped `concurrency` group with
`cancel-in-progress: false`; every job across every workflow declares a
positive `timeout-minutes`. A single consolidated file, not one per
workflow, since the assertion is identical across all 13.

Verified both assertions are real regression guards: temporarily
removed `keepalive.yml`'s `timeout-minutes` and confirmed
`test_every_job_declares_a_positive_timeout` fails; separately removed
its `concurrency` block and confirmed `test_every_workflow_declares_a_
real_concurrency_group` fails; restored the file (confirmed
byte-identical to the original) before finishing.

All 13 workflow YAML files parse successfully
(`yaml.safe_load`). Every pre-existing `tests/deploy/` test (98 total)
passed unmodified -- these are purely additive keys with no effect on
any existing static assertion.

## Status of Implementation at Time of This ADR

Code and tests complete. This is Batch G of a larger, explicitly-
requested pass through every remaining P2/P3 finding in the independent
audit report; Batch H (18 documentation-vs-code mismatches) is next.
