# ADR-0189: Batch L -- colibri's Brio entropy-gate pattern

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Claude Code (session continued), account owner (asked to
work through `EXTERNAL_REPO_APPLICABILITY_REPORT.md`'s remaining
quick items in order of size after Batch K; this is priority 7,
colibri's Brio mode)

## Context

`EXTERNAL_REPO_APPLICABILITY_REPORT.md` names colibri's "Brio" mode --
given a closed set of options, read each option's probability via
softmax and report the normalized Shannon entropy as a 0..1 uncertainty
score -- as a design pattern worth documenting even though colibri's
actual inference engine cannot run in this project's environment (its
smallest usable model needs >=20GB disk and >=24GB RAM; see the
separate discussion in this session on why an Oracle Cloud Always Free
ARM VM is a plausible but unverified future path, not something this
session can provision).

`decision.agent.BaselineRuleDecisionAgent` already has three fail-closed
gates that turn model uncertainty into `NO_TRADE` (`prediction.
confidence < config.min_confidence`, the signal-to-uncertainty ratio
gate, and the regime-UNKNOWN gates) -- see `src/decision/agent.py`
lines ~124-145. What Brio's pattern adds is not a new decision policy,
but a reusable way to turn a *closed-option probability distribution*
(something none of today's providers produce) into the kind of single
confidence number those existing gates already know how to consume.

## Decision

Add `src/decision/entropy.py` (`normalized_entropy()`): an independent
reimplementation of colibri's own formula
(`softmax -> -Σp·ln(max(p,1e-12))/ln(max(n,2))`, per the report's own
direct re-verification against `c/openai_server.py:4073-4081`), not a
copy of any colibri source -- a plain Python function with zero
dependencies, on either colibri or this project's own `ai_gateway`/
`decision` packages.

**Not wired into `BaselineRuleDecisionAgent` or `ai_gateway` in this
batch.** Today's only provider (`ai_gateway.provider.
MockProviderAdapter`) returns one structured JSON response per request,
never a probability distribution over a closed set of outcomes -- there
is nothing real for `normalized_entropy()` to be called on yet. Adding
the tested primitive now, without inventing a caller for it, follows
this project's own ADR-0151 "adopt now, wire in later" precedent
(already used once this session for `ai_gateway.admission.
RpmAdmissionGate`, Batch K): a future `Predictor` or provider that DOES
expose logprobs/probabilities over discrete options -- colibri's own
Brio mode, or any OpenAI-compatible provider that returns logprobs --
has a ready, independently tested formula to plug into a new gate
without re-deriving it from the paper.

## Consequences

### Positive
- A real, independently verifiable formula (matches a hand-computed
  reference value in its own test) is available the moment any future
  provider actually exposes option probabilities -- no design work
  needed at that point, only wiring.
- Zero new dependencies, zero new production exposure: `normalized_
  entropy()` has no caller today, matching `RpmAdmissionGate`'s own
  disclosed trade-off.

### Negative / Trade-offs
- No decision-quality improvement ships in this batch -- the actual
  benefit (a measured uncertainty number feeding
  `BaselineRuleDecisionAgent`'s existing gates) only materializes once
  a real provider exposing option probabilities exists, which is not
  scheduled work today.
- colibri's own inference engine remains entirely out of reach for this
  project's current environment; this ADR adopts only the mathematical
  pattern, never colibri's code or a live provider connection to it.

## Tests

`tests/decision/test_entropy.py`: boundary values (fully certain ->
0.0, uniform over N outcomes -> 1.0, single outcome -> 0.0 without a
division-by-zero), a hand-computed reference value for a known 3-option
distribution, unnormalized-input equivalence, and input validation
(empty/negative/all-zero probabilities each raise `ValueError`).
Verified as meaningful by temporarily removing the `max(n, 2)` guard and
confirming the single-outcome test then fails with a real
`ZeroDivisionError`, then restoring it.

Full suite run before merge as the merge gate (see PR).

## Status of Implementation at Time of This ADR

Code and tests complete. This is Batch L, following Batch K's own
priority-ordered work through `EXTERNAL_REPO_APPLICABILITY_REPORT.md`'s
remaining recommendations, smallest first.
