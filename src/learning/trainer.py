"""CandidateTrainer Protocol + MeanRewardBaselineTrainer.

See docs/specifications/PHASE-9-learning-engine.md sections 11, 14, 21.

Per instruction section 11: "특정 복잡한 ML 모델을 임의로 채택하지
않는다... 최소한 deterministic/mock candidate trainer 또는
baseline-compatible trainer로 pipeline을 검증할 수 있다." This mirrors
Phase 6's `RandomWalkPredictor` (a null-hypothesis baseline, not a
"real" model) exactly one layer further: `MeanRewardBaselineTrainer`
"trains" a single constant -- the mean `label_value` over the TRAIN
split only -- and predicts that constant for anything. It never touches
VALIDATION/TEST samples during training (leakage across splits, not
just across time, is exactly what a chronological split exists to
prevent). This is deliberately not claimed to be a good model; it
exists to prove the pipeline (dataset -> train -> evaluate ->
persistence) works end to end, the same "baseline first" discipline
every prior phase's own deterministic reference implementation follows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol, Sequence

from learning.enums import CandidateModelStatus, SplitName
from learning.models import CandidateModelArtifact, LabeledSample, TrainingDataset

from trade_journal.enums import TradeProvenance


class CandidateTrainer(Protocol):
    def train(
        self,
        dataset: TrainingDataset,
        labeled_samples: Sequence[LabeledSample],
        *,
        trained_at: datetime,
        seed: Optional[int] = None,
        experiment_id: Optional[str] = None,
    ) -> CandidateModelArtifact: ...


class _IdAllocator:
    def __init__(self) -> None:
        self._next_id = 1

    def allocate(self) -> str:
        cid = f"CAND-{self._next_id:06d}"
        self._next_id += 1
        return cid


class MeanRewardBaselineTrainer:
    """A deterministic, hand-verifiable "trainer" -- no AI/ML. Kept
    interchangeable with a future real trainer via the same
    `CandidateTrainer` Protocol: only the class implementing `train()`
    would change, never the callers or `CandidateModelArtifact`'s shape.
    `seed` is accepted (interface completeness for a future stochastic
    trainer) but unused -- this trainer has no randomness, which is
    documented rather than silently ignored."""

    version = "mean_reward_baseline_trainer_v1"

    def __init__(self) -> None:
        self._ids = _IdAllocator()

    def train(
        self,
        dataset: TrainingDataset,
        labeled_samples: Sequence[LabeledSample],
        *,
        trained_at: datetime,
        seed: Optional[int] = None,
        experiment_id: Optional[str] = None,
    ) -> CandidateModelArtifact:
        train_ids = set(dataset.splits.get(SplitName.TRAIN, ()))
        train_values = [s.label_value for s in labeled_samples if s.trade_id in train_ids]
        mean_value = sum(train_values) / len(train_values) if train_values else 0.0

        return CandidateModelArtifact(
            candidate_id=self._ids.allocate(),
            status=CandidateModelStatus.CANDIDATE,
            trainer_version=self.version,
            dataset_id=dataset.dataset_id,
            dataset_version=dataset.dataset_version,
            feature_version=dataset.feature_version,
            label_version=dataset.label_version,
            parameters={"predicted_value": mean_value, "train_sample_count": len(train_values)},
            seed=seed,
            trained_at=trained_at,
            provenance=dataset.provenance,
            experiment_id=experiment_id,
        )
