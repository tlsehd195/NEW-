# ADR-0226: Paper cycle: read bars as of the last checkpoint, skip checkpoints with no bar yet

**Status:** Accepted
**Date:** 2026-09-29
**Deciders:** account owner (asked for the fix, 2026-09-29), Claude Code session

## Context

The 2026-09-29 scheduled Paper Trading run (`paper_trading_cycle.yml`,
cron `0 22 * * 1-5`) started late, at 01:39 UTC. The workflow passes
`--end "$(date -u +%F)"`, so it asked for 2026-09-29, a US session that
had not opened yet. `build_daily_checkpoints` still produced a
2026-09-29 20:00 UTC checkpoint, `run_cycle` processed it on the
2026-09-28 bar, and `--resume` (which skips every checkpoint up to the
latest recorded prediction) will never revisit that day.
`backups/paper_trading_store/trades.json` holds four trades stamped
2026-09-29T20:00.

Looking at why those fills had a price at all found a second, older bug
in `scripts/run_paper_trading_cycle.py`: the bars handed to
`InMemoryPaperMarketDataSource` (the fill-price source) were read with
`as_of_time=args.end`, which is midnight of the `--end` day. Every bar
is available at 20:00 UTC of its own day (`bar_available_time`), so the
`--end` day's bar was always missing. A T+1 fill on a run's last
checkpoint then fell back to the previous bar, the same bar the order
was decided on. ADR-0154 exists to stop exactly that. Production runs
process one new checkpoint per invocation, so this hit every
production fill; a multi-day run only hit its last day. A daily
`--resume` test run reproduces it: a fill executed 2024-06-17 carried
`data_version` `v-2024-06-14`, the decision day's bar.

## Decision

In `scripts/run_paper_trading_cycle.py` and
`scripts/run_multi_strategy_paper_trading_cycle.py`:

1. Read bars with `as_of_time` set to the last checkpoint (20:00 UTC on
   the last trading day up to `--end`), not `--end`'s midnight. Each
   fill still only sees bars with `available_time <= execution time`
   (`InMemoryPaperMarketDataSource.get_reference_bar`), so this adds no
   look-ahead.
2. Drop every checkpoint later than the newest bar's `available_time`
   before `--resume` filtering. A session that has not closed or not
   been ingested waits for the next run instead of being decided on
   stale bars and then marked done.

The workflow's `--end "$(date -u +%F)"` is unchanged; the script now
copes with a late start by itself.

`paper_trading_cycle.yml` gains a manual-only input,
`fresh_paper_store` (default false). When set, the paper-trading-store
restore step is skipped and the run rebuilds the ledger from
`START_DATE` with the fixed code. Scheduled runs have no inputs and
always restore.

## Consequences

- From the next run on, fills use the execution day's bar and no
  checkpoint runs ahead of the data.
- The existing ledger keeps the old effects: the 2026-09-29 checkpoint
  (decided on 2026-09-28 bars) stays recorded, so 2026-09-29 is never a
  decision day, and past daily-run fills are priced on their decision
  bar. Rebuilding with `fresh_paper_store` is the account owner's call;
  older artifacts and the git history of `backups/paper_trading_store/`
  keep the current ledger either way.
- Tests: `tests/orchestration/test_run_paper_trading_cycle_cli.py::
  TestCheckpointsWithoutBarsYet` (all three fail on the old code) and
  `tests/deploy/test_paper_trading_cycle_workflow.py::
  test_a_fresh_paper_store_is_an_opt_in_manual_input_only`.
