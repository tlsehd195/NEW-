# ADR-0063: `max_order_notional` enforcement + consecutive-failure observability

**Status:** Accepted
**Session:** 36

## Context

Continuing the same 3-part risk-infrastructure request as ADR-0062,
this covers `LIVE-RISK-POLICY.md` items #10 (max order notional) and
#11 (max consecutive failures), both previously classified
**BLOCKING** ("no field exists at all").

## Decision 1 -- `RiskConfig.max_order_notional`

Added `max_order_notional: Optional[float] = None` to `RiskConfig`
(validated positive-when-set, same pattern as every other Optional
limit) and a new check in `PortfolioRiskEngine.assess`
(`src/risk/engine.py`), placed after `concentration_limit` (the last
of the simple weight-based clamps) and before the data-availability-
dependent checks: if configured, recomputes the order's notional value
from whatever weight the checks above it already produced, and clamps
further if that notional exceeds the cap. This is an absolute
dollar/currency-unit ceiling, independent of portfolio size --
distinct from every existing *weight*-based limit (#3/#4) and from
`broker.validation`'s *quantity* checks.

`None` still means "not enforced" -- same discipline as every other
Optional limit in `RiskConfig`. No number is set by this ADR; that
remains a separate financial-policy decision.

## Decision 2 -- `LiveTradingSession.consecutive_failure_count`: observability, not a new policy lever

Item #11's own prior analysis (recorded in `LIVE-RISK-POLICY.md`
before this ADR) already identified the real complication: `submit`'s
existing behavior -- halting to `RECONCILIATION_REQUIRED` on the
FIRST `BrokerError` -- is **already stricter** than any "tolerate N
consecutive failures" policy could be. Adding a configurable
`max_consecutive_failures` threshold would mean LOOSENING that
existing safety behavior (allowing some number of failures before
halting, where today even one halts everything) -- a real capital-risk
trade-off, not a number this session is positioned to invent
unilaterally (the same reasoning `LIVE-RISK-POLICY.md`'s other
DECISION REQUIRED blocks already apply to #1/#6/#7).

**What was built instead**: `LiveTradingSession.consecutive_failure_count`
(`src/broker/live/session.py`), a read-only property incremented on
every `BrokerError` inside `submit` and reset to 0 on every successful
submission. This closes the "no field exists" gap with a real,
observable count -- useful for monitoring/audit (e.g. distinguishing
"this is the 5th failure across separate submission attempts" from
"the first ever") -- **without changing `submit`'s halt behavior at
all**. The count only advances while a new submission is actually
attempted; it does not advance while blocked in
`RECONCILIATION_REQUIRED`, since no submission is attempted then.

**This is a deliberate scope boundary, not an oversight**: item #11
remains classified BLOCKING for the configurable-threshold sense the
policy item originally meant. Building that threshold is explicitly
left to a future, explicit human decision about whether to loosen the
existing single-failure halt -- this ADR does not make that call.

## What this deliberately does NOT do

- Does not set `RiskConfig.max_order_notional` to any value.
- Does not add a `max_consecutive_failures` config field, and does not
  change `LiveTradingSession.submit`'s existing halt-on-first-failure
  behavior in any way (regression-tested explicitly, see Tests below).
- Does not wire `max_order_notional` into any Live/Paper caller (same
  "no code anywhere calls `.assess(...)` yet" state ADR-0062 already
  documented -- unchanged by this ADR).

## Consequences

- `LIVE-RISK-POLICY.md` item #10 reclassified BLOCKING -> UNDEFINED.
- Item #11 stays BLOCKING, but its Notes now describe the real,
  tested observability counter that exists, and explicitly state why
  the configurable-threshold half of the original item was not built.
- `tests/broker/live/test_live_risk_policy_completeness.py`'s
  `TestBlockingPolicyItemsHaveNoField` class narrowed from #5/#10/#11
  to #11 only (matching ADR-0062's #5 reclassification too);
  `TestUndefinedPolicyItemsDefaultToNotEnforced` gained #5/#10.

## Tests

3 new (`tests/risk/test_engine.py::TestMaxOrderNotional`): a
notional-beyond-cap clamp, a within-cap no-op, and `None` skipping the
check. 5 new
(`tests/broker/live/test_live_session.py::TestConsecutiveFailureCount`):
starts at zero, a single failure increments to one, a success resets
to zero, repeated failures across reconciliation cycles accumulate,
and -- the regression guard for Decision 2's own core claim -- the
session still halts on exactly the first failure, unchanged. 2 tests
in `test_live_risk_policy_completeness.py` updated (not weakened) to
reflect #5/#10's real reclassification. Full suite: 2293 passed (up
from 2285).
