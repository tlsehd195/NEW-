# ADR-0072: Real computations for `model_state_valid`/`configuration_integrity_valid`

**Status:** Accepted
**Session:** 36 (continued)

## Context

ADR-0071 narrowed `live_runner.run_cycle`'s caller-supplied
`SafetyGateContext` fields to six, saying real computations for
`risk_health`/`model_state_valid`/`configuration_integrity_valid` did
not exist anywhere. Re-reading `docs/specifications/
PHASE-16-live-trading.md` section 5 found this was only half true: the
spec already precisely defines both `model_state_valid` and
`configuration_integrity_valid` -- the definitions were simply never
implemented as code.

| Condition | Source (spec, already written) |
|---|---|
| `model_state_valid == True` | latest `ModelStatusTransition.to_status in {APPROVED, DEPLOYED}` and `passed == True` |
| `configuration_integrity_valid == True` | caller-supplied hash comparison against a pinned `configuration_version` |

## Decision

`src/orchestration/live_safety_gate_inputs.py` (new) implements both as
pure functions, exactly per spec:

- `compute_model_state_valid(transition: Optional[ModelStatusTransition]) -> bool`
  -- `False` on `None` (fail-closed) or `passed=False`; `True` only when
  the latest transition both passed and reached APPROVED/DEPLOYED.
- `compute_configuration_integrity_valid(config, pinned_configuration_version) -> bool`
  -- a plain string-equality check against the config's own
  `configuration_version()`.

**Reading an already-recorded human decision is not automating one.**
`learning.enums.CandidateModelStatus.APPROVED`/`DEPLOYED` structurally
cannot be assigned by any `learning.*`/`evolution.*` code path --
`compute_model_state_valid` only ever reads a caller-supplied
`ModelStatusTransition`; it never constructs one and never imports
`evolution.criteria` (the module that decides transitions), the same
restriction `broker.live.*` enforces on itself
(`tests/broker/live/test_live_boundary.py`), applied here by choice even
though `orchestration` sits outside that boundary.

**Discovered mid-implementation**: `tests/evolution/
test_production_safety_candidate_boundary.py`'s repo-wide scan bans ANY
`ast.Attribute` node named `.APPROVED`/`.DEPLOYED` anywhere in `src/`,
deliberately not distinguishing "compares against" from "constructs" --
this is the first legitimate need in this codebase's history to compare
against either status outside the enum's own definition (nothing in
`src/` previously needed to). Rather than loosen that existing,
deliberately blunt rule, `compute_model_state_valid` compares against
the enum's raw `.value` strings (`"APPROVED"`/`"DEPLOYED"`) instead of
`CandidateModelStatus.APPROVED`/`.DEPLOYED` directly -- same behavior,
zero `ast.Attribute` references, full compliance with the existing test
as written.

## What this does NOT close

`live_runner.run_cycle` still cannot call either function itself:

- `model_state_valid` needs a real `candidate_id` to fetch a transition
  for. Nothing in this codebase ties `run_cycle`'s deterministic
  `predictor`/`decision_agent` (`DriftPredictor`/`BaselineRuleDecisionAgent`)
  to any specific `CandidateModelArtifact` -- "which candidate, if any,
  governs a given live run" is a real, separate, still-open architecture
  question this ADR does not answer.
- `configuration_integrity_valid` needs a pinned reference hash only an
  operator can supply.
- `risk_health` remains fully open: `monitoring.health.
  evaluate_health_from_failure_rate` is the right generic evaluator, but
  nothing tracks a real running failure-rate for `risk_engine.assess()`
  calls, and `DeterministicPortfolioRiskEngine.assess` structurally
  returns REJECT rather than raising, so "failure" would need a more
  specific definition than "REJECTs a lot" -- not designed this session.

The caller still computes these three and supplies them on the base
`gate_context`; `live_runner.py`'s module docstring is updated to
reference the two new functions and describe precisely why `run_cycle`
still can't call them itself.

## Tests

`tests/orchestration/test_live_safety_gate_inputs.py` (8 tests): every
`(transition, passed)` combination against the spec's table.
`tests/orchestration/test_live_safety_gate_inputs_boundary.py` (3
tests, AST-level): never imports `evolution.criteria`, never constructs
a `ModelStatusTransition`. Full suite: 2344 passed (up from 2333).
