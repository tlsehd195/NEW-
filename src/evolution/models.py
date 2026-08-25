"""Model Evolution data models.

See docs/specifications/PHASE-11-model-evolution.md sections 4, 5, 6.

**Structural boundary enforcement**: no type in this module has an
`order_id`, `broker_order`, `execution_price`, `risk_limit`, or
`kill_switch`-shaped field, and nothing in this module (or the rest of
`evolution.*`) ever constructs `to_status=CandidateModelStatus.APPROVED`
or `.DEPLOYED` -- `evolution.criteria.next_status` structurally cannot
return either (verified by reflection/AST scan in
`tests/evolution/test_evolution_boundary.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from learning.enums import CandidateModelStatus

from trade_journal.enums import TradeProvenance


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


@dataclass(frozen=True)
class ModelStatusTransition:
    """One attempted transition of a candidate's status, passing or
    failing -- an append-only audit record, never mutated or
    overwritten (mirrors `trade_journal.models.PostTradeAnalysis`/
    `CounterfactualRecord`'s append-history discipline, Phase 3/10). The
    candidate's own `CandidateModelArtifact.status` field is never
    reassigned; a candidate's *current* status is always the `to_status`
    of its most recent transition (or `CandidateModelStatus.CANDIDATE`
    if it has none), read via
    `evolution.repository.ModelStatusTransitionRepository.get_latest`.
    """

    transition_id: str  # "TRANS-000001"
    candidate_id: str
    dataset_id: str
    dataset_version: str
    evaluation_id: Optional[str]
    from_status: CandidateModelStatus
    to_status: CandidateModelStatus
    passed: bool
    criteria_version: str
    criteria: dict  # {"check_name": bool | float | int | None, ...} -- every check's raw input/verdict, fully auditable
    reason: str  # factual: "all_criteria_met" or the specific failed check name(s)
    provenance: TradeProvenance
    evaluated_at: datetime
    recorded_at: Optional[datetime] = None  # set by the repository at record time

    def __post_init__(self) -> None:
        if not self.transition_id:
            raise ValueError("ModelStatusTransition.transition_id must not be empty")
        _require_aware("ModelStatusTransition.evaluated_at", self.evaluated_at)


@dataclass(frozen=True)
class ModelLineageRecord:
    """Model Evolution's version/lineage tree (PROJECT_MASTER_PLAN.md
    section 11.3/76): which candidate this one evolved from, and how
    many generations deep it is. `generation=0` with
    `parent_candidate_id=None` marks a root candidate (Phase 9's first
    trainer run over a dataset, or any independently-generated
    candidate); every other candidate's `generation` is its parent's
    `generation + 1`, enforced structurally by `evolution.lineage.
    derive_lineage` rather than left to the caller to compute
    correctly."""

    candidate_id: str
    parent_candidate_id: Optional[str]
    generation: int
    lineage_basis: str  # e.g. "initial", "hyperparameter_variation"
    dataset_id: str
    dataset_version: str
    provenance: TradeProvenance
    recorded_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("ModelLineageRecord.candidate_id must not be empty")
        if self.generation < 0:
            raise ValueError("ModelLineageRecord.generation must not be negative")
        if self.parent_candidate_id is None and self.generation != 0:
            raise ValueError("a root ModelLineageRecord (no parent) must have generation=0")
        if self.parent_candidate_id is not None and self.generation == 0:
            raise ValueError("a ModelLineageRecord with a parent must have generation >= 1")
        if self.parent_candidate_id is not None and self.parent_candidate_id == self.candidate_id:
            raise ValueError("ModelLineageRecord.candidate_id must not equal its own parent_candidate_id")


@dataclass(frozen=True)
class CandidateComparison:
    """A read-only ranking of candidates evaluated on the same dataset,
    by one explicitly named metric -- never a "winner"/"is_better"
    verdict (the same discipline `learning.models.EvaluationResult`
    already established by omitting a `candidate_is_better` field,
    Phase 9 spec section 13). This is a research/review aid; it confers
    no approval or deployment authority."""

    comparison_id: str  # "CMP-000001"
    dataset_id: str
    dataset_version: str
    candidate_ids: tuple[str, ...]
    ranking_metric: str  # e.g. "test_mean_absolute_error"
    ranked_candidate_ids: tuple[str, ...]  # ascending by ranking_metric (lower = better); ties broken by candidate_id
    compared_at: datetime

    def __post_init__(self) -> None:
        if not self.comparison_id:
            raise ValueError("CandidateComparison.comparison_id must not be empty")
        _require_aware("CandidateComparison.compared_at", self.compared_at)
        if set(self.ranked_candidate_ids) != set(self.candidate_ids):
            raise ValueError("ranked_candidate_ids must be a reordering of candidate_ids")
