# ADR-0129: Schedule the data quality rescan (amends ADR-0128)

**Status:** Accepted
**Session:** 37 (continued)

## Context

Immediately after ADR-0128 shipped (`workflow_dispatch`-only, no
schedule, with the stated reasoning that a full rescan every run would
be wasteful and noisy), the account owner asked two direct questions:

1. "자동으로 실행되게끔은 안돼?" (Can't this just run automatically?)
2. "지금 실패했던 데이터들 처리 완료 한거야?" (Is the data from the
   already-failed run actually processed now?)

Question 2's honest answer is no -- see ADR-0128 itself: writing the
script and workflow does not, by itself, run them against the real
`market-data-catalog` artifact. Verified directly (not assumed) this
session: `mcp__github__actions_list` (`list_workflows`) shows GitHub
currently recognizes only the two workflows already on `main`
(`Keepalive`, `Paper Trading Daily Cycle`) -- `learning_cycle.yml` and
`data_quality_rescan.yml` exist only on this PR's branch and are not
yet workflows GitHub Actions knows about at all. A direct
`workflow_dispatch` attempt via `mcp__github__actions_run_trigger`
(`run_workflow`, `ref=claude/phase-11-model-evolution-7hpibr`)
confirmed this with a real `404 Not Found` from GitHub's own API, not a
guess. **There is currently no way to run this rescan at all, from
inside or outside this session, until PR #19 merges to `main`.** Once
merged, a human must either wait for the next Saturday 05:00 UTC
schedule (see Decision below) or manually dispatch "Retroactive Data
Quality Rescan" from the Actions tab.

Question 1 is what this ADR is about. Re-examining ADR-0128's own
"wasteful/noisy" reasoning: it was true in the abstract but overstated
for this project's actual data scale. This project's real Paper Trading
universe (`RESEARCH_UNIVERSE`/`PILOT_UNIVERSE`, see
`src/data_infra/universe.py`) is on the order of a few dozen symbols
with, at most, a couple of years of daily bars each -- tens of thousands
of `PriceBar` rows total, not millions. `DataQualityFramework.run()`
over that volume is computationally trivial (sub-second), and
`DuckDBDataRepository.record_quality_issues()` is idempotent (`ON
CONFLICT (security_id, timestamp, check_name) DO NOTHING`), so
re-recording the same finding every week costs almost nothing and
duplicates no rows. The "noisy" concern (the same historical WARNING
"found" again) is a cosmetic log-reading annoyance, not a real cost or
correctness problem -- and it is outweighed by a real, ongoing benefit a
one-time catch-up does not provide: continuous defense-in-depth against
any FUTURE gap in the incremental checker (`ingest_real_market_data.py`
only ever quality-checks its own incremental window, per ADR-0085) that
a periodic full rescan would still catch even after the pre-ADR-0127
backlog is cleared.

## Decision

`.github/workflows/data_quality_rescan.yml` now also runs on a weekly
schedule (`0 5 * * 6` -- Saturday 05:00 UTC), in addition to keeping
`workflow_dispatch` for an immediate, on-demand run. The timing is
deliberate: after the week's last weekday Paper Trading run (Friday
22:00 UTC) has finished and uploaded its own updated
`market-data-catalog`, and *before* the Learning Cycle's own Saturday
06:00 UTC run reads that same catalog to build Experience -- so a
CRITICAL bar this rescan finds is already excluded from `get_bars()`
before that week's retraining ever sees it, not after.

`tests/deploy/test_data_quality_rescan_workflow.py`'s
`test_workflow_is_valid_yaml_with_manual_dispatch_only_no_schedule` is
replaced by `test_workflow_is_valid_yaml_with_a_weekly_schedule_and_manual_dispatch`,
asserting both triggers are present with the correct cron.

## What this still does not do

- It does not change anything about `scripts/rescan_data_quality.py`
  itself (still no corporate-action checks, still no `symbol_mismatch`
  -- see that script's own docstring, unchanged by this ADR).
- It does not retroactively claim the pre-existing backlog (e.g. "Paper
  Trading Daily Cycle #7") is now processed -- this ADR only changes the
  workflow's trigger, and the fastest way to a real answer for that
  specific run is triggering the `workflow_dispatch` run directly, not
  waiting for the next Saturday.
- It does not make the rescan itself run on every daily Paper Trading
  cycle -- weekly remains the chosen cadence; a daily full rescan would
  still be needlessly frequent relative to how slowly this catalog's
  history actually needs re-checking once the initial backlog clears.

## Tests

`tests/deploy/test_data_quality_rescan_workflow.py` (8 tests, 1 renamed/
rewritten for the new schedule) -- full suite re-run: no regressions
(see PROJECT_STATUS.md).
