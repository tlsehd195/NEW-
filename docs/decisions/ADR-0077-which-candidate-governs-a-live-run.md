# ADR-0077: "Which candidate governs a live run" -- analysis, no new code

**Status:** Accepted (analysis; no code change)
**Session:** 36 (continued)

## Context

ADR-0072/ADR-0074 left `model_state_valid`'s real computation gated
behind a `candidate_id` `run_cycle` has no way to supply on its own --
"which candidate, if any, governs a given live run" was flagged as a
real, separate, still-open architecture question each time. This ADR
is that question, actually thought through, per the user's instruction
to work through the remaining items.

## The actual situation

`orchestration.live_runner.run_cycle`'s `predictor`/`decision_agent`
(`DriftPredictor`/`BaselineRuleDecisionAgent` in every real usage this
project has) are deterministic, hand-written baselines -- not learned
models drawn from the `evolution`/`learning` Candidate registry at
all. Nothing in this codebase has ever connected the two: the Candidate
pipeline (Phase 9-11) evaluates and gates *trained* models
(`CandidateModelArtifact`, `ModelStatusTransition`); the actual
Live/Paper trading pipeline runs fixed rule-based logic that never
passes through that pipeline.

Separately, and more decisively: **this project's own real research
this session found zero of 30 literature-factor candidates reaching
`EvidenceLevel.VALIDATED`** (`STRATEGY-VALIDATION-REPORT.md`'s Phase 33
Addendum) -- the highest bar any real strategy reached was `CANDIDATE`,
and even those showed strongly negative held-out TEST results. RULE 0.8
and this project's own discipline throughout have treated that as a
reason to hold, not promote.

## Analysis: three ways this could go

1. **Loosen `model_state_valid`'s definition for deterministic
   baselines** -- treat `LiveActivationApproval.strategy_evidence_reviewed`
   (already required, already attests the strategy reached CANDIDATE-
   or-better with a human reviewing the TEST result specifically) as
   sufficient on its own, without also requiring a real
   `ModelStatusTransition` lookup. *Rejected*: this would make
   `model_state_valid` redundant with `approval` rather than an
   independent check, and would mean the field could never fail for a
   pipeline that never touches the Candidate registry at all -- not a
   design, a way to make the check vacuous.

2. **Formally register the deterministic baseline as a Candidate** --
   run it through `evolution`'s evaluation pipeline once, get it
   manually promoted to `APPROVED` by a human, and use that
   `candidate_id` going forward. *Rejected for now*: real, non-trivial
   work (the criteria pipeline evaluates trained models against
   walk-forward/PBO/DSR results, which the deterministic baselines were
   never run through in that framing) undertaken for a strategy that
   has not reached `VALIDATED` -- i.e., manufacturing a "candidate" to
   satisfy a gate check rather than because a real evaluated strategy
   earned one. This is precisely the kind of after-the-fact
   justification RULE 0.8 exists to prevent.

3. **Leave `model_state_valid` fail-closed by not supplying
   `candidate_id`/`model_status_repository` at all** -- exactly
   today's default behavior (ADR-0074). *This is correct, and is not a
   gap to close.* No candidate_id exists to supply BECAUSE nothing has
   reached the evidence bar this project itself set. A `SafetyGateContext`
   whose `model_state_valid` stays whatever the caller's base context
   says (and a caller with no real candidate has no honest way to set
   it `True`) is the system correctly reflecting "no strategy is
   currently approved for Live" -- not a bug, not an oversight.

## Decision

No code change. Option 3 -- today's existing behavior -- is affirmed
as correct, not merely left unresolved. The real, still-open question
this reduces to is not architectural but substantive: **does any
strategy in this project's pipeline ever reach `VALIDATED` evidence
level with a genuinely positive held-out TEST result?** That is a
research question this project's existing infrastructure
(`scripts/run_long_horizon_validation.py`, `strategy_research.pbo_dsr`)
is already built to answer honestly -- not something ADR-0077 or any
future architecture document can shortcut.

## Tests

None -- analysis only, no code touched.
