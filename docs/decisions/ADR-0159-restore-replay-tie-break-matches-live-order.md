# ADR-0159: `PaperTradingSession.restore()`'s exact-timestamp tie-break must match the live order

**Status:** Accepted
**Date:** 2026-09-18
**Deciders:** Claude Code (session continued)
**Related documents:** `docs/decisions/ADR-0158-corporate-actions-before-t-plus-one-fill.md`
(the ADR whose own "timing-agnostic" claim this one retracts and
fixes), `docs/decisions/ADR-0155-paper-trading-corporate-actions.md`
(the original replay-ordering design this refines)

---

## Context

A fifth independent verification report, reviewing PR #46-#47
(ADR-0157/ADR-0158), found a real MEDIUM-severity gap: ADR-0158 fixed
the LIVE ordering of corporate actions relative to a same-cycle T+1
fill (actions first, then the fill — see that ADR), and stated in its
own Decision section that `PaperTradingSession.restore()`'s replay
merge was unaffected: "both are timing-agnostic within a single call
to `run_cycle`; only the ORDER of two calls within one cycle changed."

That claim is false. Verified directly against the code before acting
on the report: `restore()` builds one list of `("fill", timestamp,
record)` and `("action", timestamp, record)` tuples — fills first,
actions second, by construction — then calls `sorted(..., key=lambda
item: item[1])`, i.e. by timestamp ALONE. Python's `sorted` is stable,
so on an EXACT timestamp tie the fill (which appears first in the
input list) replays before the action — the OPPOSITE of ADR-0158's new
live order.

This tie is not a theoretical edge case. `orchestration.paper_runner.
run_cycle` (ADR-0158) passes the SAME `as_of_time` to both
`session.apply_corporate_actions(...)` and `session.advance(as_of_time)`
whenever a corporate action becomes available the same cycle a T+1
fill lands — precisely the overlap case ADR-0158 exists to fix on the
live path. Every real occurrence of that overlap therefore produces a
literal tied timestamp (`fill.execution_time == action.applied_at`) in
the persisted store, and every subsequent restart replays that tie in
the wrong order — reintroducing, on the restart-replay path only, the
exact double-adjustment/wrong-dividend/missed-dividend corruption
ADR-0158 closed on the live path.

## Decision

`PaperTradingSession.restore()`'s sort key now breaks an exact
timestamp tie explicitly, in favor of the action: `key=lambda item:
(item[1], 0 if item[0] == "action" else 1)`. This makes replay order
match live order exactly, including on a tie — no reliance on list
construction order or sort stability as an implicit, undocumented tie
rule.

`ADR-0158`'s Decision and Consequences sections are corrected in place
(retracting the "timing-agnostic"/"None identified" claims) rather
than only noted here, since a future session reading ADR-0158 alone
must not inherit the false claim.

## Consequences

### Positive

- The restart-replay path now produces the identical account state the
  live path would have, on every overlap case, not just the ones where
  timestamps happen to differ.
- No new persisted state, no schema change, no change to
  `apply_corporate_actions`'s own idempotency contract — purely a
  1-line sort-key fix.

### Negative / Trade-offs

- None identified. This narrows an implicit, undocumented ordering
  (whatever `sorted`'s stability happened to produce) into an explicit,
  tested one — strictly a correctness improvement with no new
  behavior to trade off.

## Tests

New `test_a_fill_and_an_action_sharing_the_exact_same_timestamp_replay_in_live_order`
in `tests/storage/test_paper_repository.py::TestCorporateActionReplayOrdering`:
a fresh BUY's fill and a 2:1 split sharing the exact same timestamp,
replayed via `restore()` from a persisted store, end at the real
(undoubled) quantity. Confirmed to actually fail against the pre-fix
tie-break (20.0 instead of 10.0) by temporarily reverting the fix and
re-running it, before being accepted as real regression coverage.
Full suite re-run: 3222 passed (up from 3221).

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed.
