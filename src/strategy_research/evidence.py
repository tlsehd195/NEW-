"""Evidence-level classification for walk-forward results (Phase 25,
instruction section 19). Additive to, not a replacement for, Phase 23's
`strategy_research.classification.CandidateClassification` (a
single-run REJECTED/INCONCLUSIVE/PROMISING_CANDIDATE label) --
`EvidenceLevel` instead grades the STRENGTH of multi-fold walk-forward
evidence itself, a structurally different question ("how much do we
actually know yet" vs. "what does this one run suggest").

See docs/decisions/ADR-0031-long-horizon-walk-forward-validation.md for
the full rationale behind the thresholds chosen below.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from strategy_research.research_log import ResearchLog
from strategy_research.walk_forward_evaluation import WalkForwardAggregate

# Named, documented minimums -- not tuned against any result this
# module has ever seen (instruction section 0.8: parameters are fixed
# before evaluation, never adjusted afterward).
MIN_FOLDS_FOR_PRELIMINARY = 3
MIN_FOLDS_FOR_ROBUSTNESS = 6
MIN_DISTINCT_KNOWN_REGIMES_FOR_CANDIDATE = 2  # e.g. BULL and BEAR/NEUTRAL both observed
MIN_POSITIVE_FOLD_RATIO_FOR_CANDIDATE = 0.6


class EvidenceLevel(str, Enum):
    """No `VALIDATED_ALPHA`/`PROVEN_ALPHA` member is needed here because
    `classify_evidence_level` below structurally never returns
    `VALIDATED` -- see that function's docstring. `VALIDATED` exists in
    this enum only as a documented target state a human can assign
    after a review this module cannot itself perform."""

    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    PRELIMINARY = "PRELIMINARY"
    ROBUSTNESS_PENDING = "ROBUSTNESS_PENDING"
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"


@dataclass(frozen=True)
class EvidenceAssessment:
    level: EvidenceLevel
    reason: str
    fold_count: int
    positive_fold_ratio: Optional[float]
    distinct_known_regimes: int
    is_real_data: bool
    pbo_dsr_applied: bool


def classify_evidence_level(
    aggregate: WalkForwardAggregate, *, is_real_data: bool, pbo_dsr_applied: bool
) -> EvidenceAssessment:
    """Grades walk-forward evidence strength against fixed, named
    thresholds. **Never returns `EvidenceLevel.VALIDATED`** -- reaching
    `VALIDATED` requires an explicit human decision beyond what any
    automated fold-counting function should be trusted to award on its
    own (instruction section 20's "AI가 알파를 찾았다" prohibition,
    applied structurally rather than left to good intentions). The
    highest level this function can itself return is `CANDIDATE`.

    `is_real_data=False` (synthetic fixture) forces
    `INSUFFICIENT_EVIDENCE` regardless of how many folds ran or how
    good they look -- a synthetic result is a pipeline-correctness
    check, never evidence about real-world strategy performance
    (instruction rule 0.4)."""
    if not is_real_data:
        return EvidenceAssessment(
            level=EvidenceLevel.INSUFFICIENT_EVIDENCE,
            reason="synthetic/fixture data only -- no real-market evidence gathered yet",
            fold_count=aggregate.fold_count, positive_fold_ratio=None,
            distinct_known_regimes=0, is_real_data=False, pbo_dsr_applied=pbo_dsr_applied,
        )

    if aggregate.fold_count < MIN_FOLDS_FOR_PRELIMINARY:
        return EvidenceAssessment(
            level=EvidenceLevel.INSUFFICIENT_EVIDENCE,
            reason=f"only {aggregate.fold_count} real walk-forward fold(s), below the {MIN_FOLDS_FOR_PRELIMINARY}-fold minimum for any evidence claim",
            fold_count=aggregate.fold_count, positive_fold_ratio=None,
            distinct_known_regimes=0, is_real_data=True, pbo_dsr_applied=pbo_dsr_applied,
        )

    positive_ratio = aggregate.positive_net_return_folds / aggregate.fold_count
    known_regimes = {r for r in aggregate.regime_breakdown if r != "UNKNOWN"}

    if aggregate.fold_count < MIN_FOLDS_FOR_ROBUSTNESS:
        return EvidenceAssessment(
            level=EvidenceLevel.PRELIMINARY,
            reason=f"{aggregate.fold_count} real fold(s) clears the preliminary bar but is below the {MIN_FOLDS_FOR_ROBUSTNESS}-fold minimum this project requires before assessing robustness",
            fold_count=aggregate.fold_count, positive_fold_ratio=positive_ratio,
            distinct_known_regimes=len(known_regimes), is_real_data=True, pbo_dsr_applied=pbo_dsr_applied,
        )

    if not pbo_dsr_applied:
        return EvidenceAssessment(
            level=EvidenceLevel.ROBUSTNESS_PENDING,
            reason=f"{aggregate.fold_count} real folds is enough to assess robustness, but PBO/Deflated Sharpe has not been applied yet (see assess_pbo_dsr_applicability)",
            fold_count=aggregate.fold_count, positive_fold_ratio=positive_ratio,
            distinct_known_regimes=len(known_regimes), is_real_data=True, pbo_dsr_applied=False,
        )

    if positive_ratio >= MIN_POSITIVE_FOLD_RATIO_FOR_CANDIDATE and len(known_regimes) >= MIN_DISTINCT_KNOWN_REGIMES_FOR_CANDIDATE:
        return EvidenceAssessment(
            level=EvidenceLevel.CANDIDATE,
            reason=(
                f"{positive_ratio:.0%} of {aggregate.fold_count} real folds had a positive net "
                f"return (>= {MIN_POSITIVE_FOLD_RATIO_FOR_CANDIDATE:.0%} threshold), across "
                f"{len(known_regimes)} distinct known market regimes (>= {MIN_DISTINCT_KNOWN_REGIMES_FOR_CANDIDATE} "
                "required) -- meets this project's CANDIDATE bar. Still not VALIDATED: that requires "
                "explicit human review this function does not perform."
            ),
            fold_count=aggregate.fold_count, positive_fold_ratio=positive_ratio,
            distinct_known_regimes=len(known_regimes), is_real_data=True, pbo_dsr_applied=True,
        )

    return EvidenceAssessment(
        level=EvidenceLevel.ROBUSTNESS_PENDING,
        reason=(
            f"{aggregate.fold_count} real folds and PBO/DSR applied, but the CANDIDATE bar "
            f"(positive fold ratio >= {MIN_POSITIVE_FOLD_RATIO_FOR_CANDIDATE:.0%}, >= "
            f"{MIN_DISTINCT_KNOWN_REGIMES_FOR_CANDIDATE} distinct regimes) was not met -- "
            f"actual: {positive_ratio:.0%} positive folds, {len(known_regimes)} distinct regime(s)"
        ),
        fold_count=aggregate.fold_count, positive_fold_ratio=positive_ratio,
        distinct_known_regimes=len(known_regimes), is_real_data=True, pbo_dsr_applied=True,
    )


@dataclass(frozen=True)
class PboDsrApplicability:
    applicable: bool
    reason: str
    candidate_count: int
    parameter_combination_count: int
    min_real_out_of_sample_folds_across_candidates: int


def assess_pbo_dsr_applicability(
    research_log: ResearchLog, *, real_fold_counts_by_candidate: dict, min_candidates: int = 2, min_folds_per_candidate: int = 6
) -> PboDsrApplicability:
    """Checks the two conditions
    `docs/research/walk-forward-pbo-deflated-sharpe.md` section 9.1
    already names as PBO/DSR's adoption triggers ("multiple candidate
    variations are being compared for the same promotion decision")
    against what this session's `ResearchLog` and real walk-forward
    fold counts actually show -- never assumes the trigger fired just
    because multiple strategies exist in the codebase; PBO needs real
    out-of-sample RESULTS to rank, not just candidate code.

    `real_fold_counts_by_candidate` -- `{strategy_name: number of REAL
    (not synthetic) walk-forward folds actually run for that
    candidate}` -- is supplied by the caller rather than inferred, so
    this function never itself has to guess what counts as "real."""
    candidate_count = research_log.candidate_count
    combo_count = research_log.parameter_combination_count()

    if candidate_count < min_candidates:
        return PboDsrApplicability(
            applicable=False,
            reason=f"only {candidate_count} candidate(s) logged -- PBO's premise (selection among trials) needs at least {min_candidates}",
            candidate_count=candidate_count, parameter_combination_count=combo_count,
            min_real_out_of_sample_folds_across_candidates=0,
        )

    fold_counts = list(real_fold_counts_by_candidate.values())
    min_folds = min(fold_counts) if fold_counts else 0
    if min_folds < min_folds_per_candidate:
        return PboDsrApplicability(
            applicable=False,
            reason=(
                f"{candidate_count} candidates logged, but the least-evaluated one has only "
                f"{min_folds} real out-of-sample fold(s) (need >= {min_folds_per_candidate} each) -- "
                "PBO/DSR would be computed on too little real evidence to mean anything"
            ),
            candidate_count=candidate_count, parameter_combination_count=combo_count,
            min_real_out_of_sample_folds_across_candidates=min_folds,
        )

    return PboDsrApplicability(
        applicable=True,
        reason=(
            f"{candidate_count} candidates each with >= {min_folds_per_candidate} real "
            "out-of-sample folds -- PBO/Deflated Sharpe adoption trigger conditions are met; "
            "a future phase should implement the actual computation (deferred here, not "
            "computed speculatively without a human decision to adopt it, per this project's "
            "existing DECISION REQUIRED framing)."
        ),
        candidate_count=candidate_count, parameter_combination_count=combo_count,
        min_real_out_of_sample_folds_across_candidates=min_folds,
    )
