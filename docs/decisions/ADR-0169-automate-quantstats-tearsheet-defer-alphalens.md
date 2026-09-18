# ADR-0169: Automate the quantstats tearsheet into the daily cycle; deliberately do not automate the alphalens Signal IC cross-check

**Status:** Accepted
**Date:** 2026-09-18
**Deciders:** Claude Code (session continued), account owner (asked to
automate "the tearsheet/Signal IC scripts" into CI as part of working
through the backlog of items only the account owner could previously
execute, ADR-0167/ADR-0168's follow-up)
**Related documents:** `docs/decisions/ADR-0138-quantstats-tearsheet-for-paper-trading.md`,
`docs/decisions/ADR-0139-alphalens-signal-ic-cross-verification.md`,
`src/strategy_research/locked_windows.py` (`TEST_1`)

## Context

Session 38's own backlog (`docs/PROJECT_STATUS.md`, 2026-09-17 entry)
recorded two optional-dependency scripts as "the account owner's own
local `pip install` + manual run" items:
`scripts/generate_paper_performance_tearsheet.py` (ADR-0138) and
`scripts/verify_signal_ic_with_alphalens.py` (ADR-0139). The account
owner asked to automate both into the existing `paper_trading_cycle.yml`
schedule so neither needs a local install or manual run.

Checking each script's actual inputs before wiring either in (rather
than assuming both are equally safe to run daily) found a real
difference:

- **The tearsheet** reads only `orchestration.paper_runner.
  equity_history_from_risk_repository` against the run's own
  `--paper-store` -- a real, already-elapsed equity curve with no
  concept of a locked historical window. Running it once more after
  every daily cycle is exactly the same operation the account owner
  would otherwise run by hand, just automatic.
- **The Signal IC cross-check** refuses to run (by design, no override
  flag) if `[--start, --end)` overlaps `strategy_research.
  locked_windows.TEST_1` (2023-04-28 to 2026-08-27). This project's
  entire real ingested history starts at `START_DATE = 2024-01-02`
  (`paper_trading_cycle.yml`'s own env), meaning essentially all of it
  falls inside `TEST_1` until very recently (today, 2026-09-18, is
  only 3 weeks past `TEST_1`'s end). A recurring daily run using a
  fixed historical `--start` and a rolling `--end` would either
  overlap `TEST_1` and fail every single day, or would need to use
  only the ~3 weeks of post-lock data available so far -- far too
  little for a meaningful IC comparison. This is not a script bug;
  the script's own docstring already frames it as a deliberate,
  occasional diagnostic tool, not a recurring job.

## Decision

1. **Automate the tearsheet.** `paper_trading_cycle.yml`'s `run-cycle`
   job now installs the `reporting` extra and runs
   `generate_paper_performance_tearsheet.py --security-id AAPL` right
   after the paper trading cycle step, uploading the HTML as a
   `paper-performance-tearsheet-<run_id>` artifact
   (`if-no-files-found: ignore`, since a fresh `--paper-store` legitimately
   has nothing to upload yet). Both the install and run steps use
   `continue-on-error: true` -- the script's own designed failure mode
   (fewer than 2 real checkpoints -- never a fabricated point,
   ADR-0138's own "RULE 0.8" discipline) is expected on this cycle's
   first few runs, not a reason to fail the whole job.
2. **Do not automate the Signal IC cross-check.** Left exactly as
   ADR-0139 shipped it -- a manual, occasional research script, run by
   hand when there's an actual reason to compare this project's own
   `compute_ic_series` against `alphalens-reloaded` over a specific
   window deliberately chosen to sit outside `TEST_1`. Automating it
   now would either produce constant, meaningless failures or silently
   normalize touching data uncomfortably close to the locked window on
   a schedule nobody is deliberately choosing -- worse than not having
   the automation at all.

## Consequences

### Positive

- The account owner gets a real, up-to-date performance tearsheet
  after every scheduled cycle with zero local setup, closing that part
  of the "things only you can run" backlog for good.
- The Signal IC script's TEST-1 lock discipline (a load-bearing project
  rule protecting this project's own held-out validation window) is
  not accidentally weakened by wiring it into an unattended recurring
  job.

### Negative / Trade-offs

- `paper_trading_cycle.yml`'s `run-cycle` job is slightly longer/heavier
  (installs `quantstats` + `pandas` every run). Accepted: the account
  owner explicitly asked for this automation, and `continue-on-error`
  keeps it from ever blocking the real trading cycle.
- The tearsheet's `--security-id AAPL` is a fixed, arbitrary proxy for
  the whole portfolio's shared per-checkpoint value (same convention
  `generate_paper_performance_tearsheet.py`'s own docstring already
  establishes) -- not specific to AAPL's own performance.
- The Signal IC automation request is not fulfilled -- reported back to
  the account owner rather than building something that would fail
  daily or run on too little data to be meaningful.

## Tests

`tests/deploy/test_paper_trading_cycle_workflow.py`: 2 new tests --
`test_performance_tearsheet_is_generated_and_never_fails_the_job`
(install/run steps present, both `continue-on-error: true`, upload step
`if: always()` with `if-no-files-found: ignore`) and
`test_signal_ic_alphalens_script_is_deliberately_not_automated`
(confirms the script is never referenced in this workflow, so a future
session doesn't accidentally re-add it without re-deriving this same
TEST-1 conflict). Full suite re-run: see `docs/PROJECT_STATUS.md`'s
session log for the exact count.
