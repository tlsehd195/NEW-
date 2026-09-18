# ADR-0163: Apply corporate actions in the BUY_AND_HOLD paper-trading path too

**Status:** Accepted
**Date:** 2026-09-18
**Deciders:** Claude Code (session continued)
**Related documents:** `docs/decisions/ADR-0155-paper-trading-corporate-actions.md`
(the original corporate-action design; its own Negative/Trade-offs
section disclosed this exact gap), `docs/decisions/
ADR-0158-corporate-actions-before-t-plus-one-fill.md` (the ordering
rule this change must also respect)

---

## Context

ADR-0155 wired corporate-action handling into `orchestration.paper_
runner.run_cycle`, but disclosed a real, known scope gap in its own
Negative/Trade-offs section: `scripts/run_multi_strategy_paper_trading_
cycle.py`'s `PaperStrategyKind.BUY_AND_HOLD` path (`_run_buy_and_hold_
strategy`) never calls `run_cycle` at all -- it submits one equal-weight
buy on the first checkpoint via `broker.paper.us_longterm_runner.
run_buy_and_hold_paper_session`, then only loops `session.advance(checkpoint)`
(for the T+1 fill retry) and a read-only `compute_portfolio_snapshot`
per checkpoint. A real split or dividend on a Buy & Hold position held
for months would silently drift un-split-adjusted/un-paid forever, with
no error -- the exact corruption ADR-0155 already fixed for RUN_CYCLE-
kind strategies, just never closed for this one.

Verified directly before fixing (this project's own standing
discipline): the `session` object `_run_buy_and_hold_strategy` receives
is constructed identically for both strategy kinds (`scripts/run_multi_
strategy_paper_trading_cycle.py::main`, `PaperTradingSession.restore(...,
corporate_action_repository=corporate_action_repository, ...)`) -- so
this was already feasible with the exact same repository and view
already in hand, just never invoked.

## Decision

Extracted the corporate-action-fetch-and-apply block `run_cycle` already
had (`_tracked_security_ids` over the 400-day lookback, `view.get_
corporate_actions`, `session.apply_corporate_actions`) into a new shared
function, `orchestration.paper_runner.apply_due_corporate_actions(security_ids,
session, view, as_of_time, state=None)`. `run_cycle` now calls this
helper instead of inlining the same logic itself -- no behavior change
for the RUN_CYCLE path, purely a refactor to make the logic callable
from a second site.

`_run_buy_and_hold_strategy` now calls `apply_due_corporate_actions(...)`
once per checkpoint, BEFORE `session.advance(checkpoint)` -- the same
ADR-0158 ordering rule `run_cycle` follows (actions applied before any
same-checkpoint fill lands, so a fill is never double-adjusted and a
closing sell still receives a dividend it earned). A fresh `PaperRunnerState()`
local to this function collects `corporate_action_warnings`, surfaced in
this strategy's own return dict the same way `_run_run_cycle_strategy`
already surfaces it.

## Consequences

### Positive

- Closes the exact scope gap ADR-0155 disclosed: a Buy & Hold position's
  real corporate actions are now applied every checkpoint, restart-safe
  (via the same persisted ledger `apply_corporate_actions` already
  checks), matching RUN_CYCLE-kind strategies exactly.
- No duplicated logic: both call sites now share one implementation,
  so a future fix to the fetch/apply/warning-surfacing logic (e.g.
  another ADR-0159-style ordering correction) only needs to change one
  function.

### Negative / Trade-offs

- None identified. This is strictly additive to `_run_buy_and_hold_
  strategy` (an extra call per checkpoint, using data structures the
  session already carried) -- it does not change the initial buy logic,
  sizing, or `--resume` idempotency at all.

## Tests

New `test_buy_and_hold_applies_a_split_landing_after_the_initial_buy` in
`tests/orchestration/test_run_multi_strategy_paper_trading_cycle_cli.py::TestMultiStrategyIsolation`:
seeds a 2:1 split effective after the initial buy, confirms `final_positions`
reflects the doubled quantity. Confirmed to actually fail (48.0 instead
of 96.0) against the pre-fix code by temporarily reverting the new
`apply_due_corporate_actions` call and re-running it, before being
accepted as real regression coverage.

Full suite re-run: see `docs/PROJECT_STATUS.md`'s session log for the
exact before/after counts.

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed.
