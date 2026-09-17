# ADR-0137: Wire `advance_simulation` Into `run_cycle` So Stuck Orders Actually Retry

**Status:** Accepted
**Date:** 2026-09-17
**Deciders:** Claude Code (session continued), pending project owner review
**Related documents:** `docs/decisions/ADR-0136-wire-paper-performance-report-into-daily-cycle.md`
(the immediately preceding fix to the same function)

---

## Context

Continuing the account owner's "쉬운거부터 순서대로" (easiest-first) pass
through their uploaded evaluation reports' findings: one report flagged
that `broker.paper.adapter.PaperBrokerAdapter.advance_simulation` (and
`PaperTradingSession.advance`, its own persistence-aware wrapper) --
"lets still-open orders attempt further fills as simulated time moves
forward," per that method's own docstring -- was never called anywhere
in this repository's real pipeline. Confirmed directly, not assumed: a
repo-wide search for `.advance(` / `advance_simulation` under `src/`
found zero callers before this ADR.

This is a real, reachable bug, not a hypothetical one:
`PaperTradingConfig.max_participation` defaults to `0.10` (10% of that
day's own bar volume, `partial_fill_enabled=True` by default) --
`broker.paper.execution.simulate_fill`'s own `max_fillable = floor(bar.
volume * max_participation)` caps any single fill attempt at that
day's own bar. Any order sized above that cap partial-fills on
submission day and, with no caller ever retrying it, stays
`PARTIAL_FILLED` forever -- a real "zombie order," reachable by any
real order whose target size exceeds 10% of that day's traded volume.

## Decision -- `run_cycle` calls `session.advance(as_of_time)` first, before anything else, unconditionally

Added one line at the very top of `orchestration.paper_runner.run_cycle`,
before `account = session.account_summary(...)` -- so any fill this
produces is reflected in the SAME cycle's own account/portfolio view,
not one cycle stale. Unconditional (not opt-in) for the same reason
ADR-0136's `mark_to_market` wiring was: it only lets already-submitted
orders continue filling against fresh market data, using logic
(`_attempt_fill`) this codebase already trusts, and changes no existing
return value of `run_cycle` -- every existing caller (`run_paper_
trading_cycle.py`, `run_multi_strategy_paper_trading_cycle.py`, every
test in `tests/orchestration/test_paper_runner.py`) is unaffected on any
scenario that never produces a partial fill in the first place (every
existing test's own `_session()` helper passes `max_participation=1.0`
specifically to avoid partial fills, confirmed by reading it -- so this
change was invisible to the entire existing suite until a new test
exercised it directly).

## Known, disclosed limitation -- NOT fixed here: a delayed fill from `advance()` is not yet mirrored into the Trade Journal

A same-cycle fill from `session.submit()` is journaled a few lines
below in `run_cycle`, linked to a real `DecisionSnapshot` recorded that
same cycle. A delayed fill `advance()` produces belongs to an OLDER
order, submitted (and its `DecisionSnapshot` recorded) on a past
checkpoint this call has no natural-key-safe way to re-locate without a
new persistent index (order id -> decision-snapshot id) that does not
exist today. Concretely: `--reentry-cooldown-days`'s own real-exit-history
check will not see a delayed SELL fill as a real exit until that gap is
separately closed. Disclosed here rather than silently worked around or
fabricated -- a real design change (the new index, plus threading it
through `advance()`'s own return value) judged out of scope for a
"wire the existing method up" fix, and left for a future session.

## Tests

`tests/orchestration/test_paper_runner.py::TestStuckOrderRetryViaAdvance`
(1 new test): submits a real 10,000-share order directly against a
1%-participation-capped session (bar volume 200,000 -> 2,000-share cap
per attempt), confirms it partial-fills at exactly 2,000 shares, then
calls `run_cycle` on the next checkpoint with an EMPTY `security_ids`
list (isolating the assertion to only this fix -- no new decision is
made that cycle) and confirms the SAME order's position grows to 4,000
shares, never a new order. Full suite re-run clean after this change.

## Update (external review, MEDIUM-2, ADR-0147's fix batch): the participation cap this ADR relies on was per-order, not per-bar

This ADR's own wiring made it reachable for the first time: retrying a
still-`PENDING`/`PARTIAL_FILLED` order via `advance()` alongside a
freshly-submitted order for the SAME security could hit the SAME bar
twice, and `broker.paper.execution.simulate_fill` recomputed
`max_fillable = floor(bar.volume * max_participation)` fresh on every
call -- with no memory of what another order already consumed from
that same bar. Two orders could each independently claim the full 10%
share, doubling the real per-bar participation cap this ADR's own
"Context" section above describes as a hard limit.

Fixed by having `PaperBrokerAdapter` track cumulative filled quantity
per `(security_id, bar.available_time, bar.timestamp)`
(`_bar_participation_consumed`) and subtracting it from `max_fillable`
on every subsequent attempt against that same bar -- see
`broker.paper.execution.simulate_fill`'s new `already_consumed_this_bar`
parameter. Keyed on the SAME tuple `PaperMarketDataSource.
get_reference_bar` itself uses to pick "the" bar (`bar.timestamp` alone
is not a safe proxy: real production data couples `timestamp` and
`available_time` 1:1, but several existing test fixtures deliberately
vary only `available_time` across otherwise-distinct bars). Deliberately
**process-local**, matching `PortfolioAccounting._valuation_history`'s
own disclosed scope: `PaperBrokerAdapter.restore_fill` (restart
rehydration) does not repopulate it, since a `Fill` alone does not
carry the bar's own `timestamp`/`available_time` distinctly from
`execution_time`. A process restart mid-bar therefore still resets this
specific tracking -- a narrower, disclosed residual of the same class
of gap, not a new one introduced by this fix.

Tests: `tests/broker/paper/test_paper_adapter.py::
TestParticipationCapSharedAcrossOrdersInTheSameBar` (3 new tests: a
second order against an already-fully-consumed bar gets nothing, a
second order gets only the remaining share of the cap, and a later bar
gets its own fresh cap). Full suite re-run clean.

## Status of Implementation at Time of This ADR

Code, test, and documentation complete and committed.
