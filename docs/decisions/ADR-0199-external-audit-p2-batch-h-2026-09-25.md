# ADR-0199: External Audit P2 Findings — Batch H (Stage 8 Paper Trading)

**Status:** Accepted
**Date:** 2026-09-25
**Deciders:** Claude Code session (continuing ADR-0195/ADR-0196/ADR-0197/ADR-0198's audit pass), account owner
**Related documents:** `docs/decisions/ADR-0195-external-audit-p1-fixes-2026-09-24.md`,
`docs/decisions/ADR-0196-external-audit-p2-batch-abc-2026-09-24.md`,
`docs/decisions/ADR-0197-external-audit-p2-batch-de-2026-09-24.md`,
`docs/decisions/ADR-0198-external-audit-p2-batch-g-2026-09-25.md`,
`docs/decisions/ADR-0154` (Paper Trading T+1 discipline),
independent 13-stage audit report of commit `76ab684`

---

## Context

Continues the batch-by-batch processing of the audit's remaining scope.
This ADR covers Stage 8 (Paper Trading), under the same discipline:
every finding independently reproduced against real code/tests before
being called a bug.

## Decision

- **F1 — BUY_AND_HOLD's initial buy could fill on the SAME bar it was
  decided on, violating ADR-0154 (real bug, fixed):**
  `scripts/run_multi_strategy_paper_trading_cycle.py`'s
  `_run_buy_and_hold_strategy` submits the initial buy with
  `requested_at=checkpoints[0]`, then its own driving loop's very first
  iteration (`i == 0`) unconditionally called
  `session.advance(checkpoints[0])` — the IDENTICAL `as_of` the order
  was just decided at. `PaperBrokerAdapter._attempt_fill`'s own
  docstring states "a decision and its fill can never share the same
  reference bar," but nothing enforced it here:
  `PaperMarketDataSource.get_reference_bar` resolves the exact same bar
  for both calls when `as_of` is identical, so this was a genuine
  same-bar decide-and-fill leak, reproduced directly (a fill's own
  `execution_time == decision_time` before the fix). Fixed by skipping
  that one `advance()` call only for a FRESH run's own first iteration
  (`i == 0 and not already_bought`) — never on a RESUMED run, where
  `checkpoints[0]` of the current run is a genuinely later, real
  checkpoint than whatever one the order was originally submitted
  under. The first real fill attempt now correctly lands one real
  checkpoint later, matching `run_cycle`'s own T+1 discipline exactly.
- **F2 — `_bar_participation_consumed` (max_participation's own running
  tally) was never rebuilt by `PaperTradingSession.restore()` (real
  bug, "restart amnesia" family, fixed):** every other piece of
  `PaperBrokerAdapter`'s in-process state that `restore()` needs
  (`_orders`, `_fills`, `_cancelled`, rejected-order status,
  `_fill_ids`/`_observation_ids` watermarks) already has an explicit
  `restore_*` method — `_bar_participation_consumed` did not. A restart
  mid-bar silently reset the tally to empty, letting a later order
  against the SAME bar in the restored process claim up to the FULL
  `max_participation` cap all over again on top of what a pre-restart
  process already consumed — reproduced directly (a second order that
  should have been capped at the bar's remaining 40-share allowance
  instead filled its full 100-share request). Fixed by having
  `restore_fill` also re-derive the same `bar_key` `_attempt_fill`
  itself computes (via `get_reference_bar` at the fill's own real
  `execution_time`) and accumulate into the tally, mirroring every
  sibling `restore_*` method's "reproduce what already happened, never
  guess" discipline.
- **F4 — a duplicate `security_id` in `run_buy_and_hold_paper_session`'s
  input distorted the equal-weight allocation and bypassed the
  concentration limit (real bug, fixed):**
  `positions_so_far[security_id] = PositionView(...)` silently
  OVERWRITES rather than accumulates on a repeat key, so
  `portfolio_value`'s own summation undercounted every symbol's
  contribution but the LAST one sharing that key — corrupting the
  risk-exposure picture every LATER symbol's own `risk_check` call
  sees. Separately, the repeat occurrence's own
  `build_validated_order(risk_checked, current_quantity=0.0, ...)` call
  always hardcodes `0.0` (correct for this strategy's genuine
  first-ever allocation, its own documented assumption) — for a
  duplicate, this silently lets the risk engine treat the second buy as
  opening a brand-new position rather than adding to the one just
  placed a few lines above, a real single-name concentration-limit
  bypass, not merely a bookkeeping inaccuracy. Fixed by deduplicating
  `security_ids` (first occurrence kept, order otherwise preserved) at
  the top of the function, matching the function's own already-stated
  "one MARKET BUY order per symbol" semantics.

## Consequences

- A fresh Paper Trading `buy_and_hold` run's initial position no longer
  risks a look-ahead-biased fill price (the same reference bar it was
  decided from) — its first real fill now correctly reflects the NEXT
  checkpoint's own market data, matching every other strategy's T+1
  discipline.
- A restarted Paper Trading process can no longer let a bar's real
  `max_participation` volume cap be silently doubled across the restart
  boundary.
- A malformed or accidentally-duplicated universe/security list can no
  longer cause `run_buy_and_hold_paper_session` to silently bypass its
  own concentration limit for the repeated symbol.
- Regression tests added: 1 (F1, verifies `Fill.execution_time >
  Fill.decision_time` for every real fill, confirmed to fail against
  the pre-fix code by direct reversion), 1 (F2, verifies a post-restart
  order against the same bar only gets the correctly-reduced remaining
  cap, confirmed to fail against the pre-fix code by direct reversion),
  1 (F4, verifies a duplicated symbol produces exactly one order, not
  two) — full suite (3737 tests) passes.
