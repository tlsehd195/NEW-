# ADR-0181: Fix paper-trading oversell (R1) and restart amnesia (R2) (audit Batch D)

**Status:** Accepted
**Date:** 2026-09-19
**Deciders:** Claude Code (session continued), account owner (asked to
process every remaining P2/P3 finding from the independent audit
report, in batches; this is Batch D -- paper trading correctness)

## Context

The independent audit's Step 8 (`src/broker/paper/`) reproduced two
real bugs directly (its own inline repro script,
`/home/z/audit_step8_repros.py`, run against this repository), both
confirmed real here independently before fixing:

**R1 -- delayed double-SELL oversell.** `PaperBrokerAdapter._attempt_
fill`'s BUY branch already re-checks solvency (cash) at FILL time, not
just submit time -- but the SELL side's `allow_short=False` guard was
only ever checked once, at SUBMIT time (`submit_order`, against the
position quantity known then). Two SELL orders for the same security,
each individually valid against that SAME starting quantity, can both
pass that submit-time check while still PENDING (T+1, ADR-0154 --
neither has reserved any inventory yet). If both later fill on the
same `advance_simulation` call, the real position can go negative even
with `allow_short=False` -- independently reproduced here: BUY 100,
two SELL 60 orders submitted before either fills, both attempt to fill
on the same `advance_simulation()` call, driving the position to -20
without this fix.

**R2 -- "restart amnesia."** An order rejected at FILL time (e.g.
`_attempt_fill`'s own `insufficient_cash` check) is recorded that way
by mutating the adapter's in-memory `PaperOrderRecord` and separately
persisting a `REJECTED` `OrderStatusObservation` to `status_repository`
-- but `PaperTradingSession.capture()` (the only call site that
persists `PaperOrderRecord.initial_status` itself, to `order_
repository`) is never invoked again after submission for an order that
only fails later, at fill time (`session.advance()` never calls
`capture()`). `order_repository` therefore keeps that order's
ORIGINAL, now-stale `PENDING` record forever. `PaperTradingSession.
restore()` replays `order_repository`'s own records verbatim
(`restore_order`) -- resurrecting a genuinely-rejected order as
`PENDING` in a fresh process, where `_attempt_fill`'s own retry guard
(`record.initial_status == BrokerOrderStatus.REJECTED: return`) never
triggers, and `advance_simulation` retries it forever.

## Decision

**R1**: `_attempt_fill` gained a SELL-side fill-time re-check,
symmetric to the BUY branch's own solvency re-check immediately above
it: when `allow_short=False`, the REAL position quantity as of THIS
fill attempt (`self._accounting.snapshot_view(as_of).quantity_of(...)`
-- reflecting every other order's fills that have already landed, not
the stale submit-time snapshot) must be at least the fill's own
quantity, or the fill is skipped (and the order marked `REJECTED` with
`"insufficient_position"` on its first fill attempt, mirroring the BUY
branch's own `already_filled <= 0` convention exactly).

**R2**: New `PaperBrokerAdapter.restore_rejection(client_order_id,
rejection_reason)`, mirroring the already-existing `restore_
cancellation`'s own pattern exactly. `PaperTradingSession.restore()`
now computes which orders were `REJECTED` the same way it already
computes `cancelled_ids` -- from the real, persisted `status_
repository` observations -- and calls `restore_rejection` for each.
The specific ORIGINAL rejection reason string (e.g.
`"insufficient_cash"`) is not itself persisted per-observation
anywhere and is honestly NOT reconstructed -- a generic, disclosed
placeholder (`"restored_as_rejected_from_status_history"`) is used
instead, since only `initial_status` (what actually gates
`_attempt_fill`'s own retry guard) needs to be correct to stop the
real "retries forever" bug.

## Consequences

### Positive
- Both fixes close real, independently-reproduced defects in the
  PAPER trading path specifically -- unlike Batch C's deferred items,
  this path DOES have real production callers (the daily
  `paper_trading_cycle.yml` cron), so these fixes have immediate real
  value.
- Both fixes mirror an already-established pattern in the same file
  (the BUY cash re-check for R1; `restore_cancellation` for R2) rather
  than inventing new policy -- minimizing design risk.
- R1's fix reuses the exact same `snapshot_view(as_of).quantity_of(...)`
  primitive `submit_order`'s own submit-time check already uses, just
  called again at fill time.

### Negative / Trade-offs
- R1 does not attempt to PARTIALLY fill the second SELL up to whatever
  quantity remains available (e.g. filling 40 of the 60 remaining) --
  it skips the whole fill attempt, exactly mirroring the BUY branch's
  own established "fail closed either way -- no fill this attempt"
  behavior for consistency. A future session could consider a
  reduced-quantity fill if this proves too coarse in practice.
- R2's restored `rejection_reason` is honestly a reconstructed
  placeholder, not the real original reason -- a caller reading it
  from a restored session cannot recover WHY the fill-time rejection
  originally happened (only THAT it did, which is what actually
  matters for correctness here). Persisting the real reason
  per-observation would need a schema change to `OrderStatusObservation`,
  out of scope for this fix.
- Neither fix addresses the eight other Step 8 findings the audit
  named at lower severity (P3): total_return computed against negative
  equity, no backup-restore tooling, unflagged mark-to-market cost-basis
  fallback, 8 real production orders with fills but no
  `order_status_events` row. These are tracked separately, not silently
  dropped -- Batch I picks up the trade-journal-adjacent ones.

## Tests

`tests/broker/paper/test_paper_accounting_invariants.py`: new
`test_two_pending_sells_each_individually_valid_at_submit_time_do_not_
together_oversell` -- BUY 100, two SELL 60 orders, confirms the final
position is exactly 40 (never negative) and exactly one of the two
orders ends up `FILLED`, the other `REJECTED`. Verified as a real
regression guard: reverting the fix reproduces the exact -20 position
the audit's own repro found.

`tests/broker/paper/test_paper_session.py`: new
`test_restore_does_not_resurrect_a_fill_time_rejection_as_pending` --
an insufficient-cash fill-time rejection, then `restore()`, confirms
the restored order's status is `REJECTED` (not `PENDING`) and a
subsequent `advance()` does not retry it. Verified as a real
regression guard the same way.

`tests/broker/paper/ tests/orchestration/`: 275 passed. Full suite:
3500 passed.

## Status of Implementation at Time of This ADR

Code and tests complete for both R1 and R2. This is Batch D of a
larger, explicitly-requested pass through every remaining P2/P3
finding in the independent audit report; Batch E (kill switch
production wiring) is next.
