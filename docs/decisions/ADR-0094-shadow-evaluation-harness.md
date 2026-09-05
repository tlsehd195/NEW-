# ADR-0094: Shadow evaluation harness for risk-policy changes

**Status:** Accepted
**Session:** 36 (continued)

## Context

Fifth and last of the 5 items identified from comparing this project
against `dragon1086/prism-insight` (see ADR-0090's Context for the full
background), per the account owner's "전부 적용" instruction:
`prism-insight`'s own architecture runs candidate signals/rules
alongside live decisions without letting them act, to accumulate
evidence before trusting them.

The natural first real user of this pattern already exists in this
project: ADR-0093's reentry-cooldown proposal (`RiskConfig.
reentry_cooldown_days=5`, PROPOSED, not ratified). This project's own
constitutional principle -- risk limits are not self-modified by AI --
means that number cannot simply be turned on to see what happens; a
shadow harness is exactly the mechanism that lets a proposed limit
accumulate real "what would this have changed" evidence without ever
letting it bind, mirroring the governance SPIRIT of `strategy_research.
evidence.LiveActivationApproval` (a policy needs a human-reviewed
record before it takes effect) without reusing that class, which is
strategy-promotion-specific and, per its own AST-scan test, structurally
constructible only inside its own test file.

A repo-wide grep confirmed no existing shadow/dry-run mechanism of any
kind exists in this codebase before this ADR.

## Decision

New module, `src/risk/shadow.py`:

- **`ShadowEvaluationRecord`** (frozen dataclass): one side-by-side
  comparison -- `real_status`/`real_reason` (what actually governed the
  decision) vs. `shadow_status`/`shadow_reason` (what the candidate
  policy would have produced for the identical inputs), plus a
  precomputed `diverged` field and a caller-supplied, factual
  `policy_name` (e.g. `"reentry_cooldown_days=5"` -- never a fabricated
  narrative).
- **`ShadowEvaluationRepository`** Protocol + **`InMemoryShadowEvaluationRepository`**
  reference implementation -- mirrors every earlier phase's own
  InMemory-first, Protocol-typed repository pattern
  (`regime.repository.InMemoryRegimeRepository` et al.). A persistent
  DuckDB-backed implementation is a documented future step, not built
  now -- no real shadow-evaluation volume exists yet to justify one.
- **`evaluate_in_shadow(real_engine, shadow_engine, ...)`**: runs the
  IDENTICAL inputs through two independently supplied
  `PortfolioRiskEngine` instances and returns `(real_result,
  evaluation)`. `real_result` is exactly what calling
  `real_engine.assess(...)` alone would have produced -- nothing in
  this function has a code path that lets `shadow_engine`'s result
  reach it. `evaluation` is optionally persisted via a supplied
  `repository` before being returned.
- **`ShadowIdAllocator`**: a plain monotonic counter for `shadow_id`,
  mirroring the existing "an ID is a constructor argument, allocated by
  the caller before construction" convention every other ID-bearing
  model in this project already follows (`RegimeObservation.regime_id`,
  `RiskCheckedPosition.risk_id`) -- not generated as a side effect
  inside the record's own construction or the repository's `record()`.

**Deliberately narrow, not "any policy change" in the abstract**: built
and tested against `PortfolioRiskEngine.assess` comparisons
specifically (comparing two `RiskConfig`s), since that is the concrete
need this session has. A future use against a different comparison
shape (e.g. two `PositionSizer`s, or a Decision/Prediction layer
change) would need its own record shape and function, not a forced
generalization of this one -- this project's own "don't design for
hypothetical future requirements" discipline, applied here rather than
building a maximally-generic "shadow anything" framework nobody yet
needs.

**Demonstrated against the reentry-cooldown proposal**, the concrete,
already-real candidate this session produced: a `real_engine`
configured with `reentry_cooldown_days=None` (today's actual, unratified
default) alongside a `shadow_engine` configured with `reentry_cooldown_
days=5` (ADR-0093's proposal) shows the real decision unaffected while
correctly recording when the two diverge -- exactly the evidence a
future ratification decision would want to review, without ever having
let the unratified number touch a real order.

## What this does NOT do

Does not wire `evaluate_in_shadow` into any real orchestration code path
(`orchestration.paper_runner`/`orchestration.live_runner`) -- no caller
in this codebase invokes it outside its own test file yet. That
integration (running every real risk assessment through both the real
and a shadow-configured engine, accumulating records over a real
trading history) is separate, future work, and depends on the same
`last_exit_time_by_security`-from-real-history wiring ADR-0093 already
flagged as not yet built. Does not build a DuckDB-persisted
`ShadowEvaluationRepository` -- `InMemoryShadowEvaluationRepository` is
the only implementation, sufficient for the volume of shadow evidence
that exists today (none, until this integration is wired up). Does not
claim any evidence exists yet for or against the 5-trading-day
proposal -- this ADR builds the mechanism that would accumulate it, it
does not run it against real data.

## Tests

`tests/risk/test_shadow.py` (9 tests): the real result is provably
unaffected by the shadow engine's configuration (compared byte-for-byte
against calling the real engine alone); `diverged=True` when the shadow
policy would have rejected a BUY the real policy passed; `diverged=False`
when both agree; the evaluation persists when a repository is supplied,
and is still returned when one is not; `InMemoryShadowEvaluationRepository.
list_evaluations` filters by `policy_name`/`security_id`/`diverged_only`;
`ShadowEvaluationRecord` rejects empty `shadow_id`/`policy_name` and a
timezone-naive `as_of_time`; `ShadowIdAllocator` is monotonic. Full
suite re-run, all tests pass.
