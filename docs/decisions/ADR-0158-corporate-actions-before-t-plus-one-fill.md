# ADR-0158: Apply corporate actions BEFORE this cycle's T+1 fill, not after

**Status:** Accepted
**Date:** 2026-09-18
**Deciders:** Claude Code (session continued)
**Related documents:** `docs/decisions/ADR-0154-paper-trading-t-plus-one-fill.md`,
`docs/decisions/ADR-0155-paper-trading-corporate-actions.md` (the two
ADRs whose boundary this one fixes), `docs/decisions/ADR-0115` (the
identical fix `backtest.engine.BacktestEngine.run()` already applied,
cited directly by an independent verification report)

---

## Context

A fourth independent verification report (reviewing PR #42-#45,
covering ADR-0154's T+1 fill fix and ADR-0155's corporate-action
handling, both merged the same day) found a real HIGH-severity
regression at the boundary between the two: `orchestration.paper_
runner.run_cycle` applied every cycle's corporate actions AFTER
`session.advance(as_of_time)` (the call that produces this cycle's own
T+1 fills), not before.

Verified directly against the code before acting on the report (this
project's own standing discipline): `PaperBrokerAdapter._attempt_fill`
(called from `advance_simulation`) fills against `get_reference_bar(
security_id, as_of=as_of)` — the SAME `as_of_time` a corporate action
effective as of that same time also uses. `backtest.portfolio.
PortfolioAccounting.apply_split`/`apply_dividend` mutate whatever
position is CURRENTLY held with no notion of how or when it got there.
Combined with the old after-the-fill ordering, this reproduced the
exact same-time-boundary corruption `backtest.engine.BacktestEngine.
run()` already had to fix once (ADR-0115, quoted directly by the
verification report): applying a checkpoint's own corporate actions
strictly BEFORE any fill lands on that same checkpoint.

Concretely, with the OLD ordering:

1. **A same-cycle BUY fill got double-split-adjusted.** A fill landing
   at `as_of_time` (this cycle's T+1 fill) already trades at the real
   market's own price for that moment — nothing about it needs
   retroactive split adjustment. But once that fill landed in
   `accounting.positions`, the SAME cycle's own corporate-action block
   (running after) would blindly multiply the now-larger position by
   the split ratio too, corrupting the newly-bought shares.
2. **A same-cycle BUY wrongly received a dividend** declared for
   holders as of the prior close, since the new shares were already in
   `accounting.positions` by the time `apply_dividend` ran.
3. **A same-cycle closing SELL silently lost its rightful dividend.**
   `apply_dividend` no-ops against a flat/closed position (`if pos is
   None or pos.quantity == 0: return`) — if the SELL fill emptied the
   position before the dividend block ran, the seller never received
   the dividend they were entitled to (held through the prior close).

None of these were disclosed in ADR-0154 or ADR-0155's own
Consequences sections — both were written and merged the same day,
and the boundary between them was not re-examined once both were in
place.

## Decision

Swap the order in `run_cycle`: corporate actions effective as of
`as_of_time` (`view.get_corporate_actions` over `_tracked_security_ids`
and the 400-day lookback, applied via `session.apply_corporate_
actions`) are now applied FIRST, before `pre_advance_account` is
captured and before `session.advance(as_of_time)` runs. This exactly
mirrors `backtest.engine.BacktestEngine.run()`'s own fix: existing
holdings are adjusted/paid before any new fill lands, so a new fill is
never double-adjusted or wrongly paid, and a same-cycle closing SELL
still receives the dividend it earned before its own fill removes the
position.

A side effect, also correct and desired: `pre_advance_account` (the
pre-fill baseline `_record_delayed_advance_fills` uses for realized-PnL
math) is now captured AFTER the corporate-action block, so it reflects
the already-adjusted state on a cycle where an action and a delayed
fill land at the same `as_of_time` — previously it would have used the
stale pre-split average_cost in that overlap case.

No change to `PaperTradingSession.apply_corporate_actions`'s own
persisted-ledger idempotency (ADR-0155). No change to
`PaperTradingSession.restore()`'s chronological replay merge either —
**correction (2026-09-18, ADR-0159, a fifth independent verification
report): the claim that follows was WRONG and is retracted.** This ADR
originally stated here that `restore()`'s merge was "timing-agnostic,"
i.e. unaffected by this reorder. It is not: `restore()` sorted fills
and corporate actions by timestamp alone, and on an EXACT tie (which
this ADR's own live-path fix produces whenever a fill and an action
share the identical `as_of_time` — precisely the overlap case this ADR
exists to fix) Python's stable sort replayed the fill first, the
OPPOSITE of this ADR's new live order. See ADR-0159 for the fix (an
explicit tie-break) — retracted here rather than silently left wrong
for a future session to inherit.

## Consequences

### Positive

- Paper Trading's corporate-action handling is now correct at the
  exact boundary case ADR-0115 already proved matters — a real fill
  and a real corporate action becoming available on the same day,
  which will happen in a real long-running daily deployment sooner or
  later, not a hypothetical edge case.
- `_record_delayed_advance_fills`'s realized-PnL math is also more
  accurate on an overlap day, as a direct side effect of the reorder.

### Negative / Trade-offs

- **Retracted (ADR-0159): this section originally said "None
  identified."** That was wrong — see the Decision section's
  correction above. The restart-replay path (`PaperTradingSession.
  restore()`) needed its own fix, separate from this ADR's live-path
  reorder, because the two paths determine same-timestamp order
  differently (a live `run_cycle` call vs. a stored-timestamp sort).

## Tests

New `TestCorporateActionOrderingRelativeToFill` in `tests/orchestration/
test_paper_runner.py` (2 tests): a fresh BUY's delayed fill landing the
same cycle a 2:1 split becomes available ends at the real (undoubled)
quantity; a closing SELL's delayed fill landing the same cycle a
dividend becomes available still credits that dividend. Both tests
were confirmed to actually fail against the pre-fix code (verified
directly by temporarily reverting the reorder and re-running them)
before being accepted as real regression coverage, not vacuous
assertions. Full suite re-run: 3221 passed (up from 3219).

## Status of Implementation at Time of This ADR

Code, tests, and documentation complete and committed. Also fixed in
the same change, per the same verification report's two LOW-severity
findings: `ADR-0151`'s Provenance note asserted "the original 19
unmerged commits (listed above)" with no such list actually present
anywhere in that file (now includes the real list); both
`--pending-order-ttl-days` CLI help texts now disclose that ADR-0154's
T+1 change means a TTL of 1 day cancels every order before its first
real fill attempt.
