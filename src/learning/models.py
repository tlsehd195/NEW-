"""Learning Engine data models.

See docs/specifications/PHASE-9-learning-engine.md sections 4, 5, 7, 8,
9, 11, 13, 16.

**Structural boundary enforcement**: no type in this module has an
`order_id`, `broker_order`, `execution_price`, `risk_limit`, or
`kill_switch`-shaped field, and `CandidateModelArtifact.status` is typed
`CandidateModelStatus` -- a value this module's own code never sets to
`APPROVED`/`DEPLOYED` (enforced by `learning.trainer` only ever
constructing `CandidateModelStatus.CANDIDATE`, verified by reflection in
`tests/learning/test_learning_boundary.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from learning.enums import CandidateModelStatus, SampleStatus, SplitName

from trade_journal.enums import TradeProvenance


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


@dataclass(frozen=True)
class CleaningResult:
    """Data Cleaning's verdict for one Experience sample (instruction
    section 7). Never silently drops a sample -- `status`/`reason`
    together are the audit trail for why a sample did or did not make
    it into a `TrainingDataset`."""

    trade_id: str
    experience_id: str
    status: SampleStatus
    reason: str  # factual rule name, e.g. "missing_decision", "invalid_reward_numeric", "no_realized_outcome", "ok"
    sample_as_of_time: Optional[datetime]  # the resolved decision_time -- None only when status is UNKNOWN
    provenance: TradeProvenance


@dataclass(frozen=True)
class LabeledSample:
    """One cleaned, labeled training sample. `feature_cutoff_time` and
    `label_start_time`/`label_end_time` are kept as distinct fields
    (instruction section 5) even though this phase's baseline label
    always sets `feature_cutoff_time == label_start_time == sample_as_of_time`
    -- the schema keeps them separate so a future label definition that
    *does* need a gap between feature cutoff and label start does not
    require a schema change (the same "keep distinct fields separate
    even when today's reference implementation always sets them equal"
    precedent `regime.models.RegimeObservation.timestamp`/`as_of_time`
    already established, Phase 5 spec)."""

    trade_id: str
    experience_id: str
    sample_as_of_time: datetime
    feature_cutoff_time: datetime
    label_start_time: datetime
    label_end_time: Optional[datetime]  # sample_as_of_time + holding_period, when known
    label_value: float
    label_version: str
    label_definition: str
    label_horizon: Optional[int]  # None -- this phase's label has a variable horizon (actual holding period), not a fixed one
    label_generated_at: datetime
    provenance: TradeProvenance
    feature_version: Optional[str]
    data_version: tuple[str, ...]
    # Session 36 (ADR-0048/0049): copied from ExperienceRecord.state
    # ["features"] by learning.labeling.Labeler -- None whenever the
    # originating DecisionSnapshot never had OrderIntent.features set
    # (every existing Strategy, today). A real Trainer (e.g.
    # learning.linear_trainer.LinearRegressionTrainer) reads this to
    # fit against; MeanRewardBaselineTrainer ignores it entirely, the
    # same as it always has.
    features: Optional[dict] = None

    def __post_init__(self) -> None:
        _require_aware("LabeledSample.sample_as_of_time", self.sample_as_of_time)
        _require_aware("LabeledSample.feature_cutoff_time", self.feature_cutoff_time)
        _require_aware("LabeledSample.label_start_time", self.label_start_time)
        if self.label_end_time is not None:
            _require_aware("LabeledSample.label_end_time", self.label_end_time)


@dataclass(frozen=True)
class TrainingDataset:
    dataset_id: str  # "TDS-000001"
    dataset_version: str  # content-hash of (source_experience_ids, configuration_version) -- reproducibility
    created_at: datetime
    source_experience_ids: tuple[str, ...]
    provenance: TradeProvenance  # never mixed -- one dataset is always exactly one provenance category
    feature_version: Optional[str]
    label_version: str
    data_version: tuple[str, ...]
    cleaning_config_version: str
    label_config_version: str
    split_config_version: str
    sampling_config_version: str
    configuration_version: str
    sample_count: int
    excluded_count: int
    quality_status: str  # "OK" | "INSUFFICIENT_SAMPLES"
    splits: dict[SplitName, tuple[str, ...]] = field(default_factory=dict)  # trade_id lists, chronological within each split
    as_of_cutoff: Optional[datetime] = None  # None -- built from every available experience at build time

    def __post_init__(self) -> None:
        if not self.dataset_id:
            raise ValueError("TrainingDataset.dataset_id must not be empty")
        _require_aware("TrainingDataset.created_at", self.created_at)
        if self.as_of_cutoff is not None:
            _require_aware("TrainingDataset.as_of_cutoff", self.as_of_cutoff)


@dataclass(frozen=True)
class CandidateModelArtifact:
    candidate_id: str  # "CAND-000001"
    status: CandidateModelStatus  # always CandidateModelStatus.CANDIDATE, produced by this phase
    trainer_version: str
    dataset_id: str
    dataset_version: str
    feature_version: Optional[str]
    label_version: str
    parameters: dict  # the "learned" parameters -- e.g. {"predicted_value": mean_train_label}
    seed: Optional[int]
    trained_at: datetime
    provenance: TradeProvenance
    experiment_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("CandidateModelArtifact.candidate_id must not be empty")
        _require_aware("CandidateModelArtifact.trained_at", self.trained_at)


@dataclass(frozen=True)
class EvaluationMetrics:
    sample_count: int
    mean_absolute_error: Optional[float]
    mean_squared_error: Optional[float]
    mean_label: Optional[float]


@dataclass(frozen=True)
class EvaluationResult:
    evaluation_id: str  # "EVAL-000001"
    candidate_id: str
    dataset_id: str
    dataset_version: str
    train_metrics: EvaluationMetrics
    validation_metrics: EvaluationMetrics
    test_metrics: EvaluationMetrics
    baseline_metrics: EvaluationMetrics  # a trivial "always predict 0.0" comparison point -- never claims the candidate is superior
    evaluator_version: str
    evaluated_at: datetime
    provenance: TradeProvenance

    def __post_init__(self) -> None:
        if not self.evaluation_id:
            raise ValueError("EvaluationResult.evaluation_id must not be empty")
        _require_aware("EvaluationResult.evaluated_at", self.evaluated_at)


@dataclass(frozen=True)
class LearningExperimentRecord:
    """A training/evaluation run's experiment record -- deliberately a
    new type, not a reuse of `backtest.experiment.ExperimentRecord`
    (see docs/decisions/ADR-0015 section 1 for why that reuse was
    rejected: its `metrics: PerformanceReport` and backtest-specific
    cost/slippage/benchmark fields do not fit a training run). Follows
    the identical persistence *pattern* `storage.experiment_repository`
    already established (one DuckDB catalog, natural-key idempotency),
    just for a differently-shaped record."""

    experiment_id: str  # "LRN-000001"
    dataset_id: str
    dataset_version: str
    trainer_version: str
    evaluator_version: str
    candidate_id: str
    evaluation_id: str
    configuration_version: str
    seed: Optional[int]
    provenance: TradeProvenance
    status: str  # "COMPLETED" | "FAILED" -- this phase never runs an async/long-lived job, so no PENDING/RUNNING state exists yet
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.experiment_id:
            raise ValueError("LearningExperimentRecord.experiment_id must not be empty")
        _require_aware("LearningExperimentRecord.created_at", self.created_at)
