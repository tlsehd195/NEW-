# ADR-0071: `live_runner.run_cycle` derives the `SafetyGateContext` fields it can know for certain

**Status:** Accepted
**Session:** 36 (continued)

## Context

ADR-0070 built `orchestration.live_runner.run_cycle` requiring a
caller-supplied, base `SafetyGateContext`, deriving only
`order_validation_status` itself. On review, several of the remaining
"caller-supplied" fields turned out to be things `run_cycle` can
determine with total certainty from data it already has -- letting a
caller's placeholder value stand for them was not a genuine open
question, it was an unnecessary and dangerous source of staleness/error
(a caller could accidentally supply `account_state_known=True` when it
was not, or `kill_switch_engaged=False` when the switch really was
engaged, and the gate would trust the lie).

## Decision

`run_cycle` now overrides SEVEN fields via `dataclasses.replace`, per
submission, using real values it already has in hand:

- `order_validation_status` -- unchanged from ADR-0070 (per-security
  `build_validated_order(...).status`).
- `as_of_time` -- unchanged from ADR-0070.
- `config` -- `session.config` (the session's own real config; a
  caller-supplied copy could never honestly differ).
- `broker_capabilities` -- `session.adapter.get_capabilities(as_of=
  as_of_time)`, a real, already-available broker call.
- `kill_switch_engaged` -- `session.is_kill_switch_engaged()`, likewise
  already available.
- `account_state_known`/`position_state_known` -- reaching this point
  in `run_cycle` at all means `_live_portfolio_view` already obtained a
  real, available account snapshot AND a real positions read (it raises
  otherwise) -- both are genuinely `True` whenever this code runs.

## What remains genuinely the caller's responsibility, and why

Six fields still pass through unchanged, each for a distinct, real
reason -- not because this work stopped short:

- `max_turnover` -- `risk_engine` is typed as the `PortfolioRiskEngine`
  Protocol, which exposes no public config; reading a specific
  implementation's private `RiskConfig` would silently break for any
  other implementation of the Protocol.
- `approval` (`LiveActivationApproval`) -- a human-signed attestation by
  construction (`approved_by` structurally rejects "AI"/"SYSTEM"/
  "CLAUDE"); no code may ever synthesize one.
- `required_capabilities` -- depends on what order types the calling
  strategy actually issues, a caller-level fact this module cannot
  infer.
- `risk_health`/`model_state_valid`/`configuration_integrity_valid` --
  real, honest computations for these do not exist anywhere in `src/`
  yet; building them (wiring `monitoring.health`'s existing evaluators,
  deciding what "model_state_valid" means against the Candidate
  approval boundary this project deliberately keeps automation-free) is
  separate, safety-critical design work, still not attempted.

## Tests

2 new tests in `tests/orchestration/test_live_runner.py`
(`TestGateContextDerivedFieldsOverrideCallerPlaceholders`, renamed from
the ADR-0070 class covering only `order_validation_status`): a caller's
wrong `account_state_known=False`/`kill_switch_engaged=True` placeholder
is overridden and the gate still passes; a REALLY engaged kill switch
(via `session.engage_kill_switch`) still blocks submission even when the
caller's placeholder wrongly claims `kill_switch_engaged=False` -- the
more dangerous direction, proving the derivation is not merely
convenient but safety-relevant. Full suite: 2333 passed (up from 2331).
