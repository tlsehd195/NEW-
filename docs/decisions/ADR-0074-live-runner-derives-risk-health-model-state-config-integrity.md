# ADR-0074: `run_cycle` derives `risk_health`/`model_state_valid`/`configuration_integrity_valid` when the caller supplies real inputs

**Status:** Accepted
**Session:** 36 (continued)

## Context

ADR-0071/ADR-0072 left three `SafetyGateContext` fields on the "still
genuinely caller-supplied" list -- not because a real computation was
impossible, but because it needed either a design decision
(`risk_health`) or inputs `run_cycle` doesn't inherently have
(`model_state_valid`'s `candidate_id`, `configuration_integrity_valid`'s
pin). Continuing the sequence the user asked for ("순서대로... risk_health
설계... 나머지 연결"), this ADR closes all three, as OPT-IN derivations.

## Decision 1 -- `risk_health`

`MonitoringConfig`'s own existing comment names "Risk rejections" as
this component's intended failure signal -- the same rejection-rate
basis Broker/AI Gateway already use, not an operational exception rate
(`DeterministicPortfolioRiskEngine.assess` structurally returns REJECT
rather than raising, so exception-rate would almost always read 0%,
uninformative). A risk engine REJECTing nearly everything is exactly
the kind of anomaly worth surfacing as DEGRADED/UNAVAILABLE, whether
each individual REJECT was itself correct per policy or not.

`LiveRunnerState` gained `risk_assessment_total`/`risk_assessment_rejected`,
incremented on every `risk_engine.assess()` call when `state` is
supplied. `run_cycle` feeds these into the existing, unmodified
`monitoring.health.evaluate_health_from_failure_rate` (`MonitoringComponent.RISK`)
and overrides `risk_health` with the result -- only when `state` is
supplied (already required for `value_history`); an optional
`monitoring_config` parameter overrides the default thresholds.
`sample_count=0` (nothing assessed yet) correctly reads `UNKNOWN` via
that function's own `min_sample_count` gate, not vacuously `HEALTHY`.

## Decision 2 -- `model_state_valid`

Overridden only when the caller supplies BOTH `candidate_id` and
`model_status_repository`: `orchestration.live_safety_gate_inputs.
compute_model_state_valid` (ADR-0072) reads that candidate's latest
real transition. Omit either -- the honest default, since nothing in
this codebase yet ties `run_cycle`'s deterministic `predictor`/
`decision_agent` to any specific `CandidateModelArtifact` -- and this
field is untouched. This ADR does not answer "which candidate governs
a live run": that remains a real, separate, still-open architecture
question a caller must resolve before it can supply `candidate_id` at
all.

## Decision 3 -- `configuration_integrity_valid`

Overridden only when the caller supplies `pinned_configuration_version`:
`compute_configuration_integrity_valid` (ADR-0072) compares it against
`session.config.configuration_version()`. This ADR does not decide how
or when an operator pins that reference hash -- only the comparison,
once a pin exists, is real.

## What remains unconditionally the caller's responsibility

`max_turnover`, `approval`, `required_capabilities` -- no opt-in path
exists for any of the three, for the structural reasons ADR-0071
already documented (no public `RiskConfig` access via the Protocol; a
human-signed attestation that cannot be synthesized; a caller-level
fact about which order types are in use).

## Tests

8 new in `tests/orchestration/test_live_runner.py`: without the right
inputs, each field's caller-supplied placeholder (deliberately wrong in
several tests) passes through untouched and the gate correctly fails on
it; with the right inputs, each is computed for real and the gate
result reflects it -- including a real REJECT-heavy history (4 REJECTs
then 1 real PASS) producing a real `UNAVAILABLE` risk_health that
blocks the 5th submission, and a custom `monitoring_config` genuinely
changing the outcome. Full suite: 2356 passed (up from 2347).
