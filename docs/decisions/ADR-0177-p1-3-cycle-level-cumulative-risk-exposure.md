# ADR-0177: Enforce cumulative gross exposure within one paper-trading cycle (independent audit P1-3, part 1)

**Status:** Accepted
**Date:** 2026-09-19
**Deciders:** Claude Code (session continued), account owner ("순서대로
고쳐" -- fix the 3 independently-verified P1 findings in order; this is
the third and last)

## Context

Independent audit finding P1-3 (already independently verified real
during this same session, before this fix), part 1: `src/orchestration/
paper_runner.run_cycle` computed `portfolio = _portfolio_view(account,
view, as_of_time)` exactly ONCE per cycle, before the `for security_id
in security_ids:` loop, and never updated it for the rest of that
loop -- even though `session.submit(...)` runs mid-loop for every
security whose order clears validation. Every subsequent security's
`decision_agent.decide`/`position_sizer.size`/`risk_engine.assess`
calls therefore saw the exact same portfolio snapshot the FIRST
security in the loop was evaluated against. `risk.engine.
DeterministicPortfolioRiskEngine.assess()` is a stateless function of
whatever `PortfolioView` it is handed (that module's own docstring) --
it has no way to know, on its own, that a security earlier in the same
loop already consumed part of the portfolio's risk budget. Concretely:
two BUY decisions in one cycle could each individually pass the
`gross_exposure_limit` check against that one stale snapshot while
their real, combined effect breaches `RiskConfig.max_gross_exposure`.

**A first fix attempt was tried and found to be a no-op, before being
corrected**: re-reading `session.account_summary(as_of=as_of_time)`
immediately after `session.submit()` and rebuilding `portfolio` from
that. This does NOT work, because of `ADR-0154`'s own deliberate T+1
discipline: `PaperBrokerAdapter.submit_order()`'s own comment states
"submission never attempts a fill synchronously... The order stays
PENDING here; its first fill attempt happens only via
`advance_simulation`, called by the driving loop at the START of the
NEXT cycle." Re-querying `account_summary()` within the same cycle
therefore returns the EXACT SAME state as before the submission --
appearing to fix the bug while changing nothing. This was caught before
being shipped, by tracing `PaperBrokerAdapter.submit_order()`'s real
control flow and by a regression test
(`test_real_broker_account_state_is_untouched_by_the_in_memory_estimate`)
added specifically to keep this mistake from recurring.

## Decision

`run_cycle` now updates its own LOCAL `portfolio` variable, in memory
only, immediately after a real submission (`validation.validated_order
is not None`), to reflect that security's own order AS IF it had
already filled at `current_price` -- never touching `session`'s real
broker/accounting state, and never claiming a real fill happened:

- `signed_quantity = order.quantity if order.side == BUY else
  -order.quantity`; the position's new quantity is `existing_quantity +
  signed_quantity`, its new `market_value` is `new_quantity *
  current_price`.
- `cash_delta = -(order.quantity * current_price)` for a BUY (positive
  for a SELL) -- a plain notional trade, no slippage/cost modeled (this
  is a same-cycle RISK-CHECK ESTIMATE, not a claim about what the real
  fill will cost).
- `portfolio_value` is left unchanged (cash and position value simply
  trade places, by construction of this same estimate).
- Skipped entirely when `current_price is None` (no market-value-based
  estimate can be built without one -- consistent with `_portfolio_
  view`'s own existing "no price -> no market-value computation"
  discipline, never a fabricated price).

This closes the exact gap the audit found -- every LATER security in
the same cycle's own `risk_engine.assess` call now sees this cycle's
own already-submitted orders' cumulative effect -- while leaving
ADR-0154's real same-bar-fill-leak protection completely untouched:
`session.account_summary()`/`session.adapter.accounting` are never
read or written by this fix, and the real fill for each of this
cycle's orders still only lands on the NEXT cycle's own `advance()`
call, exactly as ADR-0154 requires.

**Deliberately excluded from this fix**: `value_history` (used for
`max_drawdown`/`max_portfolio_volatility`) is NOT updated mid-cycle --
it is computed once above from this cycle's own opening mark-to-market
value, before any of this cycle's own orders. Drawdown/volatility are
properties of end-of-cycle portfolio value observed over TIME (across
cycles), not of intra-cycle security-evaluation ORDER -- refreshing it
mid-loop would conflate the two and does not correspond to any real
gap the audit named.

`_position_average_cost`/`opened_at`/`decision_snapshot`'s own
`portfolio_state` (used for realized-P&L bookkeeping inside the
existing `trade_journal_repository is not None` block, a few lines
above this fix) continue to read the PRE-fill `account`/`portfolio` as
they always have -- this fix's own in-memory update runs strictly
AFTER that block, so it never touches those already-documented,
unrelated invariants.

## Consequences

### Positive
- Closes a real, independently-verified TOCTOU gap: cumulative,
  same-cycle gross exposure across multiple securities is now actually
  enforced, not just per-security in isolation.
- Zero change to `risk.engine`/`ADR-0154`'s own real broker-state
  discipline -- the fix is entirely local to `paper_runner.run_cycle`'s
  own in-memory loop state.
- The rejected first attempt (re-reading `account_summary()`) is
  explicitly documented in both this ADR and the shipped code's own
  comment, specifically so a future reader does not silently
  reintroduce it believing it to be a fix.

### Negative / Trade-offs
- This is a same-cycle ESTIMATE, not a real fill -- if the real T+1
  fill (next cycle) ends up at a materially different price than
  `current_price` (a real, expected possibility -- prices move), the
  in-cycle risk check this fix improves was still computed against an
  approximation, not the eventual real fill price. This is a smaller,
  bounded gap than the one this ADR closes (no exposure tracking at
  all, previously), not a new one this fix introduces.
- Does not address `--max-drawdown`/`--max-portfolio-volatility` being
  left disabled (`None`) in the production daily workflow
  (`paper_trading_cycle.yml` only passes `--max-sector-weight`/
  `--max-order-notional`) -- the second half of audit finding P1-3.
  `scripts/run_paper_trading_cycle.py` already supports both flags and
  already reconstructs real `value_history` from persisted risk records
  at every run's start specifically so they would be evaluable; turning
  them on in production requires the account owner to choose real
  threshold values (a risk-tolerance decision, not a code-correctness
  one) and is tracked as a separate, explicit follow-up rather than
  decided unilaterally here.
- No slippage/transaction-cost modeling in the in-memory estimate --
  consistent with every other same-cycle approximation this codebase
  already makes (e.g. `PositionSizer`'s own cost-safety-margin
  reasoning), not a new simplification invented for this fix.

## Tests

`tests/orchestration/test_paper_runner.py`'s new
`TestCumulativeGrossExposureEnforcedWithinOneCycle` class (3 tests),
using a new `_two_security_scenario()` fixture (AAA and BBB with
identical price/volatility inputs, so `PositionSizer` -- which has no
cross-security visibility -- proposes the identical raw target weight
for both; any difference in the RISK-CHECKED result can only come from
`risk_engine.assess` seeing AAA's already-submitted order):

1. A `max_gross_exposure` tight enough to allow one full-size BUY but
   not two: the second security's `risk_checked.breached_limits`
   includes `"gross_exposure"` and its `final_target_weight` is
   strictly less than the first's.
2. A generous `max_gross_exposure`: neither security breaches
   `gross_exposure`, both submit at the identical full size.
3. Regression guard for the rejected first fix attempt: real
   `session.account_summary()` cash/positions are byte-for-byte
   unchanged after the cycle -- proves the fix never touches real
   broker state, only its own in-memory estimate.

Full suite re-run (this session): 3483 -> 3486 passed.

## Status of Implementation at Time of This ADR

Code and tests complete for the cumulative-gross-exposure half of
P1-3. The production-workflow `--max-drawdown`/`--max-portfolio-
volatility` half is tracked separately (see "Negative / Trade-offs"
above) pending the account owner's own threshold-value decision. This
is the third and last of the three P1 findings from the independent
audit report, fixed in the order the account owner specified
("순서대로 고쳐"): P1-1 (ADR-0175), P1-2 (ADR-0176), P1-3 (this ADR).
