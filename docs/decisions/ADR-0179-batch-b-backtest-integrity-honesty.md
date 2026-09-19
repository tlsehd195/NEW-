# ADR-0179: Delisted-position ERROR gate + honest pbo_dsr_applied reporting (audit Batch B)

**Status:** Accepted
**Date:** 2026-09-19
**Deciders:** Claude Code (session continued), account owner (asked to
process every remaining P2/P3 finding from the independent audit
report, in batches; this is Batch B -- backtest/strategy_research
integrity)

## Context

The independent audit's Step 2 (`src/backtest/`, `src/strategy_
research/`) named two related, real integrity gaps:

1. **Delisted positions valued at cost, still `PASSED_WITH_WARNINGS`.**
   `PortfolioAccounting.mark_to_market` (`src/backtest/portfolio.py`)
   falls back to a position's own `average_cost` when its security is
   missing a price -- an honest, reasonable choice for an ORDINARY
   temporary data gap, but never a plausible estimate for a REAL
   delisting (a security that is confirmed gone and, in the common
   case of bankruptcy, worth far less than its cost basis). This
   fallback was only ever flagged via `check_missing_data`, a
   WARNING-severity check (`src/backtest/integrity.py`) -- and
   `IntegrityReport.is_valid_performance` treats `PASSED_WITH_WARNINGS`
   as a legitimate result. A strategy that holds a position through a
   real delisting therefore has its (potentially badly inflated)
   performance reported as valid, with nothing distinguishing that case
   from an ordinary, harmless data gap.
2. **`pbo_dsr_applied=True` trusted without checking the actual PBO/DSR
   numbers were supplied.** `classify_evidence_level`
   (`src/strategy_research/evidence.py`) reaches `EvidenceLevel.
   CANDIDATE` and reports `pbo_dsr_applied=True` on its returned
   `EvidenceAssessment` whenever the caller passes `pbo_dsr_
   applied=True` -- REGARDLESS of whether `pbo_probability`/
   `deflated_sharpe_ratio` were ever actually supplied. The function's
   own docstring already disclosed this ("a caller asserting
   `pbo_dsr_applied=True` without supplying the actual numbers is
   trusted at face value"), but the resulting structured field is
   genuinely misleading to any future consumer who reads only
   `assessment.pbo_dsr_applied` (not the full prose `reason` string,
   which DOES correctly omit the "confirmed by PBO=...` clause in this
   case) -- a real verification-passed-masquerade risk, exactly as the
   audit described.

## Decision

**Item 1**: New `BacktestIntegrityChecker.check_delisted_position_
marked_at_cost`, ERROR severity (vs. the existing `check_missing_data`'s
WARNING). `BacktestEngine.run()` now partitions each checkpoint's
`missing` (no-price) security list by real `SecurityMaster.status ==
SecurityStatus.DELISTED` (queried via the existing `self._repository.
get_security(security_id, checkpoint)`, never guessed) before routing
each security_id to the correct check. An `IntegrityReport` containing
this new ERROR-severity issue makes `is_valid_performance` `False`,
exactly like any other ERROR/CRITICAL issue already does -- this project's
own gating rule (this module's own docstring: "a result with any
ERROR/CRITICAL issue must not be treated as a legitimate performance
outcome").

Deliberately does NOT attempt to estimate a real recovery value (mark
the position to $0, or to some other computed figure) -- a merger/
acquisition often pays real, non-zero consideration this project has
no real data source for, and `CorporateActionApplier` already
documents (Phase 2 spec section 8.4) that MERGER/ACQUISITION/
SPIN_OFF/TICKER_CHANGE/DELISTING are out of this project's current
scope to model. This fix only makes the resulting performance number
honestly untrustworthy instead of silently valid -- it does not (and
cannot, without real data this project lacks) correct the number
itself.

**Item 2**: `classify_evidence_level`'s CANDIDATE-reaching return now
reports `pbo_dsr_applied=pbo_dsr_values_supplied` (whether
`pbo_probability`/`deflated_sharpe_ratio` were ACTUALLY supplied)
instead of unconditionally `True`. The CANDIDATE classification logic
itself is completely unchanged -- a caller can still reach CANDIDATE
via `pbo_dsr_applied=True` alone with no real numbers (that broader
policy question -- whether it SHOULD be reachable that way -- is
separate from this field's own honesty and is not decided here). Only
the reported field's truthfulness is fixed: it now means exactly what
it says, "real PBO/DSR numbers were supplied and checked," never "the
caller merely claimed this stage was reached."

## Consequences

### Positive
- A real, previously-silent overstatement risk (holding a delisted
  position at cost basis) now correctly invalidates the affected
  backtest's performance result, matching this project's own existing
  ERROR/CRITICAL gating discipline.
- `EvidenceAssessment.pbo_dsr_applied` is now a trustworthy field for
  any current or future consumer that reads it directly, without
  requiring them to also parse the prose `reason` string to know
  whether real numbers backed it.
- Both fixes are narrowly scoped and confirmed (via grep) to have zero
  current downstream consumers relying on the old, incorrect values --
  no other code path changes behavior.

### Negative / Trade-offs
- Item 1 only fires when `SecurityMaster.status` has actually been set
  to `DELISTED` for the affected security -- a security that stops
  reporting prices without ever getting a real, provider-confirmed
  `DELISTED` status update (a possible real-world data gap on its own)
  still falls through to the ordinary WARNING-severity `missing_data`
  path, unchanged. This fix closes the gap for CONFIRMED delistings
  only; it does not (and structurally cannot, without real point-in-time
  delisting data for every security) catch every real-world case.
- Item 1 does not distinguish "just delisted, position should probably
  be closed soon" from "delisted 3 years ago, position never closed" --
  any duration produces the identical ERROR-severity issue. A future
  session could add a duration- or magnitude-aware severity if this
  proves too coarse in practice.
- Item 2 leaves the underlying policy question (should `pbo_dsr_
  applied=True` alone, without real numbers, ever be sufficient to
  reach CANDIDATE?) explicitly unresolved -- this ADR only fixes the
  reported field's honesty, not that broader design choice.

## Tests

`tests/backtest/test_integrity.py`: new unit test
(`test_a_confirmed_delisted_position_marked_at_cost_invalidates_the_
result`) proving the new checker method in isolation, and a new
engine-level end-to-end test
(`test_engine_level_confirmed_delisted_held_position_invalidates_the_
result`, real `BacktestEngine.run()`, a strategy that buys once and
holds through a real price-history stop + a `SecurityMaster` confirmed
`DELISTED`) proving the full wiring. Verified the engine-level test is
a real regression guard by temporarily reverting the `engine.py` wiring
and confirming it fails (`delisted_issues` was empty) before restoring
the fix.

`tests/strategy_research/test_evidence.py`: two new tests
(`test_omitting_pbo_dsr_values_reports_pbo_dsr_applied_as_false`,
`test_supplying_real_pbo_dsr_values_reports_pbo_dsr_applied_as_true`)
covering both the negative (claim without numbers) and positive
(numbers supplied and passing) cases; the pre-existing `test_omitting_
pbo_dsr_values_preserves_old_trust_the_flag_behavior` was renamed to
`..._preserves_old_candidate_classification` and kept unchanged in
substance, confirming the CANDIDATE classification logic itself did
not change.

`tests/strategy_research/ tests/backtest/`: 690 passed. Full suite:
3491 passed.

## Status of Implementation at Time of This ADR

Code and tests complete for both items in this audit step. This is
Batch B of a larger, explicitly-requested pass through every remaining
P2/P3 finding in the independent audit report; Batch C (broker/live
fail-open edges) is next.
