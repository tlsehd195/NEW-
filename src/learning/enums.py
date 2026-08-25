"""Enumerations for the Learning Engine (Phase 9).

See docs/specifications/PHASE-9-learning-engine.md sections 6, 10.
"""

from __future__ import annotations

from enum import Enum


class SampleStatus(str, Enum):
    """Data Cleaning's outcome per sample (instruction section 7: "VALID
    / INVALID / EXCLUDED / UNKNOWN"). An invalid/excluded/unknown sample
    is never silently dropped -- it is recorded with this status plus a
    factual `reason`, mirroring the same fail-closed, no-silent-defaults
    discipline `RiskCheckStatus` (Phase 8) already established for a
    different pipeline stage.

    VALID: passed every check, usable for labeling/training.
    INVALID: a structural defect this pipeline can positively identify
      (NaN/infinite numeric value, duplicate trade_id, a provenance
      that does not match the dataset's declared provenance).
    EXCLUDED: structurally fine, but not usable for this particular
      label definition (e.g. no realized outcome yet -- a legitimate,
      honest state per trade_journal.experience's own documented
      convention, not a defect).
    UNKNOWN: this pipeline cannot determine validity at all (e.g. the
      experience's decision cannot be resolved, so no
      `sample_as_of_time` exists to check anything against).
    """

    VALID = "VALID"
    INVALID = "INVALID"
    EXCLUDED = "EXCLUDED"
    UNKNOWN = "UNKNOWN"


class SplitName(str, Enum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    TEST = "TEST"


class CandidateModelStatus(str, Enum):
    """Mirrors PROJECT_MASTER_PLAN.md section 11.2's full state machine.
    Phase 9 code only ever produces `CANDIDATE` -- the remaining states
    are reserved here (the same "reserve ahead of the first producer"
    pattern `trade_journal.enums.DecisionAction.HOLD/EXIT/NO_TRADE` and
    `backtest.enums.OrderStatus.CANCELLED` already established) so
    Phase 10/11's validation/evolution/registry work has a stable,
    already-tested type to extend rather than design from scratch.
    `APPROVED`/`DEPLOYED` in particular require a human approval step
    this phase never performs (master plan section 11.5) -- no code
    path in `learning.*` can assign either.
    """

    CANDIDATE = "CANDIDATE"
    BACKTESTED = "BACKTESTED"  # reserved -- Phase 10
    VALIDATED = "VALIDATED"  # reserved -- Phase 10
    OOS_TESTED = "OOS_TESTED"  # reserved -- Phase 10
    PAPER_TESTED = "PAPER_TESTED"  # reserved -- Phase 15
    APPROVED = "APPROVED"  # reserved -- Phase 11, requires human approval
    DEPLOYED = "DEPLOYED"  # reserved -- Phase 11+
