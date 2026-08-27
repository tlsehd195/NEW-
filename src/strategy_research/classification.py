"""Candidate classification + criteria (instruction sections 28/38).

`CandidateClassification` deliberately has no `PROVEN_ALPHA`/`VERIFIED_ALPHA`
member -- instruction section 28/47 forbid this Phase from ever
producing that label automatically, and this enum makes it structurally
impossible to assign one by accident (there is no such value to assign).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CandidateClassification(str, Enum):
    REJECTED = "REJECTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    PROMISING_CANDIDATE = "PROMISING_CANDIDATE"


@dataclass(frozen=True)
class PromisingCriteria:
    """The instruction section 28 checklist. Every field is a boolean
    the caller must have actually evaluated (never defaulted to True) --
    `classify_candidate` requires ALL of them to be `True` before it will
    return `PROMISING_CANDIDATE`; any `False`, or any `None` (not yet
    evaluated), falls back to `INCONCLUSIVE`."""

    meaningful_vs_benchmark: Optional[bool] = None
    survives_costs: Optional[bool] = None
    has_out_of_sample_result: Optional[bool] = None
    consistent_across_periods: Optional[bool] = None
    not_single_symbol_dependent: Optional[bool] = None
    not_overly_parameter_sensitive: Optional[bool] = None
    reasonable_turnover: Optional[bool] = None
    acceptable_drawdown: Optional[bool] = None

    def all_evaluated(self) -> bool:
        return all(v is not None for v in self.__dict__.values())

    def all_true(self) -> bool:
        return self.all_evaluated() and all(self.__dict__.values())

    def failing_criteria(self) -> tuple[str, ...]:
        return tuple(name for name, value in self.__dict__.items() if value is not True)


@dataclass(frozen=True)
class CandidateEvaluation:
    """One full, honest record of one strategy-candidate evaluation --
    intended to be appended to a `ResearchLog`, never overwritten or
    discarded (instruction section 26/39: rejected candidates are kept,
    not deleted)."""

    strategy_name: str
    strategy_version: str
    hypothesis: str
    parameters: dict
    train_period: tuple
    validation_period: tuple
    test_period: Optional[tuple]
    criteria: PromisingCriteria
    classification: CandidateClassification
    rejection_reason: Optional[str] = None
    notes: tuple[str, ...] = field(default_factory=tuple)


def classify_candidate(
    criteria: PromisingCriteria, *, has_real_evaluation_data: bool, explicit_rejection_reason: Optional[str] = None
) -> CandidateClassification:
    """`has_real_evaluation_data=False` (e.g. this Phase's BLOCKED real
    market data status) forces `INCONCLUSIVE` regardless of what
    `criteria` says -- a classification computed only from synthetic
    pipeline-validation fixture data is never allowed to present itself
    as REJECTED or PROMISING_CANDIDATE, both of which are claims about
    real-world performance (instruction sections 35/38)."""
    if explicit_rejection_reason is not None:
        return CandidateClassification.REJECTED
    if not has_real_evaluation_data:
        return CandidateClassification.INCONCLUSIVE
    if criteria.all_true():
        return CandidateClassification.PROMISING_CANDIDATE
    return CandidateClassification.INCONCLUSIVE
