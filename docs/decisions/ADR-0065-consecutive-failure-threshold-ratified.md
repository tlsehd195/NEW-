# ADR-0065: `max_consecutive_failures=5` ratified -- the halt-on-first-failure default is now configurable

**Status:** Accepted
**Session:** 36

## Context

ADR-0063 built `LiveTradingSession.consecutive_failure_count` as an
observability-only counter, explicitly declining to make it a
configurable halt threshold: doing so would LOOSEN the session's
existing behavior (halting to `RECONCILIATION_REQUIRED` on the very
FIRST `BrokerError`), which is a real capital-risk trade-off, not
something to decide unilaterally.

The user was then asked directly, alongside the rest of this session's
open items, whether to keep that original strict default or loosen it
-- and explicitly chose: **halt after 5 consecutive failures** (i.e.
tolerate up to 4).

## Decision

`LiveTradingConfig.max_consecutive_failures: Optional[int] = None`
(validated `>= 1` when set) is a new field. `LiveTradingSession.submit`'s
`except BrokerError` branch now compares `consecutive_failure_count`
against `config.max_consecutive_failures or 1` and only transitions to
`OperationalState.RECONCILIATION_REQUIRED` once that threshold is
reached -- **`None` still means "halt on the first failure"**, the
exact original behavior, so any existing caller that never sets this
field sees no change whatsoever (regression-tested explicitly).

The user's ratified value, **5**, is recorded in
`LIVE-RISK-POLICY.md` item #11 using the same "RATIFIED, not yet
code-applied" pattern ADR-0060 established for #1/#6/#7: not baked
into `DEFAULT_LIVE_TRADING_CONFIG` (which stays fully inert,
`live_trading_enabled=False`, every threshold `None`), to be passed
explicitly whenever a real Live config is constructed.

## What this deliberately does NOT do

- Does not change `DEFAULT_LIVE_TRADING_CONFIG`'s default -- it
  remains `max_consecutive_failures=None` (halt on first failure).
- Does not change what happens to the FAILED ORDER itself -- every
  `BrokerError` still marks that order's internal status `UNKNOWN`
  regardless of the threshold; only the SESSION-level halt is now
  configurable. A human still needs `reconcile_order` to resolve each
  `UNKNOWN` order eventually, whether the session halted immediately
  or after 4 more attempts.
- Does not touch the kill switch, safety gate, or any other Live
  safety mechanism.

## Consequences

- `LIVE-RISK-POLICY.md` item #11 reclassified BLOCKING -> UNDEFINED,
  RATIFIED (matching #1/#6/#7/#10's own status).
- `TestBlockingPolicyItemsHaveNoField`
  (`tests/broker/live/test_live_risk_policy_completeness.py`) is now
  empty -- no BLOCKING risk-policy items remain from the original
  Phase 17 review except #14 (withdrawal policy, ADR-0064, a
  deliberately unresolved human financial-planning decision).

## Tests

4 new (`tests/broker/live/test_live_session.py::
TestConfigurableFailureThreshold`): failures below the threshold do
not halt; the Nth failure halts exactly at the threshold; a reset
count is compared correctly (not cumulative); the `None` default still
halts on the first failure. 2 existing tests updated (not weakened) in
`test_live_risk_policy_completeness.py` to reflect the field's real
existence. Full suite: 2297 passed (up from 2293).
