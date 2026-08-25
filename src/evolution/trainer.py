"""TrailingWindowMeanTrainer: a second, genuinely different
`learning.trainer.CandidateTrainer` implementation, so Model Evolution
has more than one candidate to generate, compare, and validate from the
same `TrainingDataset` (PROJECT_MASTER_PLAN.md Phase 11 "후보 모델 생성").

See docs/specifications/PHASE-11-model-evolution.md section 3.

Like Phase 9's `MeanRewardBaselineTrainer`, this is deliberately not an
ML model -- the project has no ML dependency declared
(`pyproject.toml` lists only `duckdb`/`pyarrow`), and
PROJECT_MASTER_PLAN.md section 1.1 forbids adopting "임의의 AI 모델
하나"를 앞서 구현하는 것. It "trains" a single constant -- the mean
`label_value` over only the most recent `window` TRAIN-split samples,
in chronological order -- rather than the whole TRAIN split. Varying
`window` deterministically produces different, comparable candidates,
which is exactly what this phase's candidate-generation step needs to
exercise comparison/validation on more than one candidate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from learning.enums import CandidateModelStatus, SplitName
from learning.models import CandidateModelArtifact, LabeledSample, TrainingDataset


class _IdAllocator:
    def __init__(self) -> None:
        self._next_id = 1

    def allocate(self) -> str:
        cid = f"CAND-{self._next_id:06d}"
        self._next_id += 1
        return cid


class TrailingWindowMeanTrainer:
    """Implements `learning.trainer.CandidateTrainer` structurally (no
    import needed -- Protocol conformance is duck-typed) so it is a drop-in
    alternative to `MeanRewardBaselineTrainer` wherever a `CandidateTrainer`
    is accepted, including `learning.pipeline.run_learning_pipeline`'s
    `trainer` parameter."""

    def __init__(self, window: int) -> None:
        if window <= 0:
            raise ValueError("window must be positive")
        self.window = window
        self.version = f"trailing_window_mean_trainer_v1_w{window}"
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
        train_ids_in_order = dataset.splits.get(SplitName.TRAIN, ())
        by_trade_id = {s.trade_id: s for s in labeled_samples}
        train_values_in_order = [by_trade_id[tid].label_value for tid in train_ids_in_order if tid in by_trade_id]
        window_values = train_values_in_order[-self.window :]
        mean_value = sum(window_values) / len(window_values) if window_values else 0.0

        return CandidateModelArtifact(
            candidate_id=self._ids.allocate(),
            status=CandidateModelStatus.CANDIDATE,
            trainer_version=self.version,
            dataset_id=dataset.dataset_id,
            dataset_version=dataset.dataset_version,
            feature_version=dataset.feature_version,
            label_version=dataset.label_version,
            parameters={
                "predicted_value": mean_value,
                "window": self.window,
                "window_sample_count": len(window_values),
            },
            seed=seed,
            trained_at=trained_at,
            provenance=dataset.provenance,
            experiment_id=experiment_id,
        )
