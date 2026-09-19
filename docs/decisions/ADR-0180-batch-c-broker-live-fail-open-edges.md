# ADR-0180: Fix 3 broker/live fail-open edges; review 3 more (audit Batch C)

**Status:** Accepted
**Date:** 2026-09-19
**Deciders:** Claude Code (session continued), account owner (asked to
process every remaining P2/P3 finding from the independent audit
report, in batches; this is Batch C -- broker/live fail-open edges)

## Context

The audit's Step 7 (`src/broker/`) and Step 9 (`src/broker/live/`)
named six related items, several counted twice across both steps (the
same code, reached from two audit angles). Each was investigated
directly before deciding whether to fix it now.

## Fixed in this batch

1. **String order quantity never coerced to float**
   (`src/broker/toss/mapping.py`'s `parse_order_response`). Confirmed
   real: `BrokerOrderResponse.filled_quantity`/`avg_fill_price` are
   declared `Optional[float]`, but this function passed the raw JSON
   value straight through -- a Toss response stringifying a quantity
   (a real, plausible JSON shape; the sibling function `parse_order_
   detail_response` a few lines below already defends against exactly
   this) would silently violate that type, and the existing test suite
   had PINNED the buggy string value as expected
   (`assert result.filled_quantity == "3"`). A string `filled_quantity`
   reaching `Fill.quantity` would crash the first time a SELL fill
   tries to negate it (`-fill.quantity` on a `str` raises `TypeError`)
   -- the exact real crash the audit named. Fixed by applying the same
   `_to_float_or_none` coercion `parse_order_detail_response` already
   uses; the previously-pinning test was corrected to assert the real
   float value instead.

2. **Non-raising UNKNOWN response treated as a successful submission**
   (`src/broker/live/session.py`'s `LiveTradingSession.submit`,
   flagged "최상위"/highest-priority by the audit's own Step 9
   framing). Confirmed real: a response that returns normally (no
   `BrokerError` raised) but with `status == BrokerOrderStatus.UNKNOWN`
   (a real, non-raising path in `broker.toss.mapping` for an
   unrecognized/malformed status) fell through to the exact same
   success handling as a genuine FILLED/PENDING response --
   `_operational_state` set to `ACTIVE`, the consecutive-failure
   counter reset to `0`, `submitted=True`. This is the identical class
   of ambiguity the `except BrokerError` branch immediately above
   already treats as a real failure (this module's own docstring:
   "API 응답을 받지 못했다는 주문이 실행되지 않았다는 뜻이 아니다") --
   fixed by mirroring that branch's own counting/escalation exactly for
   a non-raising `UNKNOWN` status too, rather than inventing new
   policy. `broker.mock.MockBrokerAdapter` gained a new
   `submit_status_unknown` failure mode specifically to make this
   previously-untestable path testable (there was no way to reach it
   before without a real, malformed network response).

3. **`max_turnover`, when configured, rejects every BUY as
   `"turnover_unknown"`** (Step 4/9, counted in both). Confirmed real:
   `risk.engine.DeterministicPortfolioRiskEngine.assess` fail-closed
   REJECTs when `RiskConfig.max_turnover` is configured but no real
   `turnover` value is passed -- and `orchestration.paper_runner.
   run_cycle`'s own `risk_engine.assess(...)` call never passed one at
   all. A real, already-existing computation
   (`session.adapter.accounting.turnover()`,
   `backtest.portfolio.PortfolioAccounting.turnover`, cumulative trade
   notional over average historical portfolio value) is now threaded
   through. `live_runner.py`'s own identical gap is NOT fixed here --
   see below.

## Reviewed, not fixed in this batch

4. **`live_runner.py` still never passes a real `turnover` value.**
   Unlike `paper_runner.py`, `LiveTradingSession` has no local
   `PortfolioAccounting` to read a `turnover()` from at all (live
   trading reconciles against the REAL broker's own account/position
   state, never a locally-simulated one) -- `live_runner.py`'s own
   module docstring already explicitly discloses this as one of "these
   three [that] remain genuinely, unconditionally the caller's
   responsibility." Computing a real live turnover figure would need a
   trade-history-based design (e.g. from `trade_journal_repository`,
   if configured) that does not exist yet -- a real design task, not a
   one-line fix, and (per this session's own independent P0
   verification, ADR-0177 and this session's earlier audit
   cross-check) `live_runner.py`/`LiveTradingSession` have ZERO
   production callers today, so this gap has no current real-world
   exposure. Left open, flagged for whichever future session first
   builds a real live driver.
5. **2xx cancel response always interpreted as terminal `CANCELED`,
   never an intermediate `PENDING_CANCEL`**
   (`src/broker/toss/mapping.py`). Investigated and found to be an
   already-justified, deliberate choice, documented in the code's own
   comment: Toss's cancel endpoint's 2xx response carries no status
   field of its own (only a new cancel-operation id) -- there is no
   real, confirmed API signal to interpret as "pending" rather than
   "done." Inventing a `PENDING_CANCEL` interpretation without a real,
   documented API shape to justify it would violate this project's own
   "never guess an unconfirmed endpoint shape" discipline (the same
   discipline `docs/operations/TOSS-API-GAP-ANALYSIS.md`'s own
   Tier 1/Tier 2/UNKOWN classification already enforces elsewhere). No
   change made; assessed as correct given real API constraints.
6. **Toss client-side duplicate-order guard absent; a process restart
   clears `_order_id_map`/`_internal_status`; reconciliation `MISMATCH`
   has no operator-facing resolution API beyond a full restart.** All
   three are real, and all three are genuine architecture gaps in the
   LIVE trading path specifically -- state persistence across restarts,
   a real duplicate-submission guard, and a documented resolution
   procedure for a stuck reconciliation are each their own design
   undertaking (what should be persisted, when, and how a human
   operator is meant to intervene are real product decisions, not bug
   fixes). Given `LiveTradingSession`/`TossBrokerAdapter` have zero
   production callers today (same finding as item 4), none of these
   currently expose this project to real risk. Left open, flagged for
   whichever future session first builds a real live driver and
   operational runbook for it -- attempting a narrow, unreviewed fix to
   any of the three now would risk a false sense of live-readiness more
   than it would close a real, currently-exploitable gap.

## Consequences

### Positive
- Three real, independently-verified defects are fixed with real
  regression tests, including a live-session ambiguity the audit
  itself called the highest-priority item in its own Step 9.
- A pre-existing test that had PINNED a real type-safety bug as
  expected behavior (`test_partial_filled_response`) is corrected,
  removing a false safety net.
- `MockBrokerAdapter`'s new `submit_status_unknown` failure mode is a
  reusable testing primitive for any future work on this exact class
  of ambiguous-response handling.

### Negative / Trade-offs
- Four of the six named items in this audit step are explicitly NOT
  fixed here (items 4-6, one item covering three sub-issues) -- all
  are real, but all are live-trading-specific architecture gaps with
  zero current production exposure (no live driver exists), and each
  would need a real design decision this session should not make
  unilaterally on the account owner's behalf. This is disclosed, not
  silently dropped.
- The `turnover()` value now threaded into `paper_runner.py` is
  CUMULATIVE since the session's own creation, not a rolling recent
  window -- a real, disclosed property of the existing `PortfolioAccounting.
  turnover()` method this fix reuses unchanged, not a new limitation
  introduced here.

## Tests

`tests/broker/toss/test_toss_production_safety_contract.py`: corrected
the pre-existing string-pinning test, added a dedicated `avg_fill_price`
string-coercion test and an explicit negation-does-not-crash test.

`tests/broker/live/test_live_session.py`: new
`TestNonRaisingUnknownResponseIsNeverTreatedAsSuccess` (4 tests) using
the new `submit_status_unknown` mock failure mode -- verified as real
regression guards by temporarily reverting the `session.py` fix and
confirming all 4 fail first.

`tests/orchestration/test_paper_runner.py`: new
`TestMaxTurnoverPropagatesThroughTheWholeChain` -- verified as a real
regression guard the same way.

`tests/orchestration/ tests/risk/ tests/broker/`: 823 passed. Full
suite: 3498 passed.

## Status of Implementation at Time of This ADR

Code and tests complete for the three fixed items. The three deferred
items (turnover for live, 2xx-cancel semantics reviewed and confirmed
correct, and the three live-trading-restart/dedup/reconciliation gaps)
are documented above, not silently dropped. This is Batch C of a
larger, explicitly-requested pass through every remaining P2/P3
finding in the independent audit report; Batch D (paper trading
correctness: oversell, restart amnesia) is next.
