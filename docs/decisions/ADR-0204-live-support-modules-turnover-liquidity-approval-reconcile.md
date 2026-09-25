# ADR-0204: Live support modules -- turnover, liquidity_state, activation-approval CLI, reconcile driver

**Status:** Accepted
**Date:** 2026-09-25
**Deciders:** Claude Code session (continuing ADR-0195 through ADR-0205's
audit-response and priority-pass work), account owner

**Related documents:** `docs/decisions/ADR-0197-external-audit-p2-batch-de-2026-09-24.md`
(Live turnover / liquidity_state deferrals), `docs/decisions/ADR-0200-external-audit-p2-batch-i-2026-09-25.md`
(F3 MISMATCH fix, F4 reconciliation-driver deferral), ADR-0205 (this
session's own priority-ranking exercise that surfaced this batch)

## Context

ADR-0197/ADR-0200 each deferred a Live-trading-related gap, all four
sharing the same stated reason: "no Live production CLI entrypoint
exists in this repository yet" (`scripts/run_live_trading_cycle.py`
does not exist), so building real support for them was judged
premature. Asked for a fresh priority ranking across every open item
in the project (not just the external audit's own scope), this batch
ranked 2nd -- real code with zero current blast radius, but which
becomes the first thing needed the moment Live is actually pursued.

**Scope explicitly bounded by the account owner before starting:**
build and test the 4 support modules for real; do **not** build
`scripts/run_live_trading_cycle.py` or any other real execution
entrypoint. This project's own repeated characterization -- "Live
불가, 구조적으로 안전한 상태(진입점 부재가 안전을 만들고 있음)" -- stays
true after this batch: nothing here is called by anything that could
place a real order.

## Decision

### 1 & 2. Live `turnover`/`liquidity_state` -- re-scoped from "new module" to "threading fix"

Both ADR-0197 items were re-investigated before writing any code.
**Neither needed the new module ADR-0197 believed it did:**

- `liquidity_state`: `regime.features.compute_liquidity` and
  `RegimeAxis.LIQUIDITY` already existed, and `regime` (a
  `CompositeRegimeObservation`) was already computed every loop
  iteration in both `paper_runner.run_cycle` and `live_runner.run_cycle`
  -- `position_sizer.size()` already read `regime.get(RegimeAxis.
  LIQUIDITY)` internally for its own `liquidity_scale`. `risk_engine.
  assess` simply never received the same value. Because `risk.engine`'s
  own guard is `if config.enforce_liquidity_limit and liquidity_state
  is not None`, and `enforce_liquidity_limit` **defaults to `True`**,
  this check had been silently inert for every Paper run to date, not
  merely untested for Live -- a real, live (if low-severity) gap, not
  a hypothetical one. Fixed in both runners: `liquidity_obs =
  regime.get(RegimeAxis.LIQUIDITY)` then
  `liquidity_state=liquidity_obs.state if liquidity_obs is not None
  else None` passed into `risk_engine.assess`.
- Live `turnover`: the formula and per-cycle portfolio-value history
  already existed too -- `backtest.portfolio.PortfolioAccounting.
  turnover()`'s own "cumulative real trade notional / average
  historical portfolio value", and `LiveRunnerState.value_history`
  (already accumulated for `max_drawdown`/`max_portfolio_volatility`).
  The only missing piece was `trade_notionals` accumulation. Added
  `LiveRunnerState.trade_notionals: list[float]`, appended
  `fill.notional` once per real fill (the same point
  `trade_journal_repository.record_trade` already fires from), and a
  new `_live_turnover(state)` helper reproducing `PortfolioAccounting.
  turnover()`'s exact formula against this state instead -- `None`
  (never a fabricated `0.0`) whenever `state` is absent or has no
  history yet, so `RiskConfig.max_turnover` still fails closed exactly
  as before for a caller not tracking state.

Both fixes verified as real regression guards: reverted, confirmed the
new tests fail with the exact expected collision/loss, restored. One
test (`test_a_real_low_liquidity_period_now_actually_rejects_the_buy`,
both runners) constructs a genuinely low-liquidity price history (last
5 days' volume dropped to 1/20th of baseline) and confirms a real BUY
now gets REJECTed as `liquidity_limit_breached` -- something
structurally impossible before this fix, since `liquidity_state` was
always `None`.

### 3. `LiveActivationApproval` grant CLI

`scripts/grant_live_activation_approval.py`: a real, tested CLI that
constructs a `LiveActivationApproval` from operator-supplied flags
(`--approved-by`, `--confirmation-token`, `--checklist-completed`,
`--strategy-evidence-reviewed`), relying entirely on
`LiveActivationApproval.__post_init__`'s own existing validation to
refuse an invalid combination (never re-implementing that logic) --
refuses (exit 1, writes nothing) rather than silently granting.
`broker.live.approval` gained `approval_to_payload`/
`payload_to_approval` (plain-JSON round trip, kept local to that
module rather than `storage.serialization` since this object has no
repository -- module's own docstring: nothing in the deterministic
pipeline constructs one) so the CLI's output file is real, round-trip
-verified JSON, not merely JSON-shaped. `payload_to_approval` re-runs
full `__post_init__` validation, so a hand-edited file cannot bypass
any check just by round-tripping structurally.

Does not violate `tests/broker/live/test_live_boundary.py::
TestActivationApprovalIsHumanOnly`'s AST scan (verified before writing
this script) -- that scan covers `src/` only; `scripts/` is exactly
where a human-operated tool belongs, and the new constructor call
inside `payload_to_approval` lives in `broker/live/approval.py`
itself, which the scan already excludes.

### 4. Reconciliation driver -- the "what", not the "when"

ADR-0200 F4 deferred this as "a genuine new feature (what triggers it,
how often, what it does with a MISMATCH beyond the F3 fix)". F3 already
answered the third question (a MISMATCH always forces
`RECONCILIATION_REQUIRED`). This ADR answers the first
(**what** gets reconciled) and deliberately leaves the second
(**when**/how often) unanswered, since that is a real operational
policy decision with no Live entrypoint to attach it to yet.

`LiveTradingSession.reconcile_open_orders(*, as_of)`: reconciles every
`client_order_id` this session tracks whose status
`not is_closed_status` -- the identical candidate set
`engage_kill_switch`'s own auto-cancel loop already uses, iterated
through the real, already-fail-closed `reconcile_order` per order
(never a parallel, unaudited reconciliation path). Not a
scheduler/cron/periodic trigger -- a caller (a future Live entrypoint,
or an operator invoking it by hand) decides *when* to call it; this
method only decides what happens once called. Matches this project's
own "adopt now, wire in later" precedent (ADR-0151).

## Consequences

### Positive
- Two of the four items turned out to be real, live (if low-severity)
  correctness gaps rather than the "needs a new module" ADR-0197
  originally believed -- `enforce_liquidity_limit`'s default-`True`
  check had been silently inert since Phase 8, now real for both Paper
  and Live.
- Every item is real, tested code reachable only through existing
  tested modules (`paper_runner`/`live_runner`/`LiveTradingSession`) or
  a standalone CLI -- no new execution entrypoint, no new network call,
  no new capability to place a real order. Live's own "no entrypoint =
  safe" structural property is unchanged.
- `grant_live_activation_approval.py` and `reconcile_open_orders` are
  both real, usable tools the moment a future Live entrypoint session
  needs them, rather than design notes to re-derive from scratch.

### Negative / Trade-offs
- `reconcile_open_orders` still has zero automatic callers -- the
  "how often" policy question ADR-0200 F4 raised remains genuinely
  open, deliberately, until a real Live entrypoint exists to answer it.
- The approval CLI's output JSON is not consumed by anything in this
  repository yet -- `payload_to_approval` exists so a future caller
  does not have to invent the read side, but nothing currently reads
  the file it writes.

## Tests

`tests/orchestration/test_paper_runner.py`
(`TestLiquidityStatePropagatesThroughTheWholeChain`, 2 new tests),
`tests/orchestration/test_live_runner.py`
(`TestLiquidityStatePropagatesThroughTheWholeChain` +
`TestLiveTurnoverPropagatesThroughTheWholeChain`, 5 new tests),
`tests/broker/live/test_live_approval.py` (`TestPayloadRoundTrip`, 3
new tests), `tests/scripts/test_grant_live_activation_approval_cli.py`
(new file, 6 tests), `tests/broker/live/test_live_session.py`
(`TestReconcileOpenOrders`, 3 new tests).

Every fix verified as a real regression guard before this commit: each
was temporarily reverted, the corresponding new test(s) confirmed to
fail with the exact expected behavior loss, then restored.

Full suite run before merge as the merge gate (see PR).
