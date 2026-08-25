"""DataCleaningConfig / LabelConfig / SplitConfig / SamplingConfig /
TrainingDatasetConfig: every threshold and configuration choice the
Learning Engine's pipeline uses, kept out of code -- the same discipline
`DecisionConfig` (Phase 7) / `PositionSizingConfig`/`RiskConfig`
(Phase 8) already established.

See docs/specifications/PHASE-9-learning-engine.md sections 7, 8, 9, 10.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from data_infra.versioning import compute_data_version


@dataclass(frozen=True)
class DataCleaningConfig:
    version: str = "data_cleaning_config_v1"
    require_sample_as_of_time: bool = True  # a sample whose decision cannot be resolved is UNKNOWN, not silently skipped
    require_realized_outcome: bool = True  # a sample with no realized_return is EXCLUDED, not fabricated as 0.0

    def configuration_version(self) -> str:
        return compute_data_version(asdict(self))


@dataclass(frozen=True)
class LabelConfig:
    version: str = "label_config_v1"
    # The minimum viable label this phase implements: the trade's own
    # already-realized return (trade_journal.models.TradeRecord.realized_return),
    # never a newly-computed multi-day forward return derived from price
    # data (instruction section 8: "실제 프로젝트 목표와 기존 데이터로
    # 검증 가능한 최소 label부터 구현한다"). No fixed label_horizon --
    # the horizon is each trade's own variable holding_period.
    label_definition: str = "actual_realized_return_v1"

    def configuration_version(self) -> str:
        return compute_data_version(asdict(self))


@dataclass(frozen=True)
class SplitConfig:
    version: str = "split_config_v1"
    train_fraction: float = 0.6
    validation_fraction: float = 0.2
    test_fraction: float = 0.2

    def __post_init__(self) -> None:
        total = self.train_fraction + self.validation_fraction + self.test_fraction
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"train/validation/test fractions must sum to 1.0, got {total}")
        for name, value in (
            ("train_fraction", self.train_fraction),
            ("validation_fraction", self.validation_fraction),
            ("test_fraction", self.test_fraction),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]: {value!r}")

    def configuration_version(self) -> str:
        return compute_data_version(asdict(self))


@dataclass(frozen=True)
class SamplingConfig:
    version: str = "sampling_config_v1"
    max_samples: Optional[int] = None  # None -- no cap, use every VALID sample

    def __post_init__(self) -> None:
        if self.max_samples is not None and self.max_samples <= 0:
            raise ValueError("max_samples must be positive when configured")

    def configuration_version(self) -> str:
        return compute_data_version(asdict(self))


@dataclass(frozen=True)
class TrainingDatasetConfig:
    version: str = "training_dataset_config_v1"
    cleaning: DataCleaningConfig = DataCleaningConfig()
    labeling: LabelConfig = LabelConfig()
    split: SplitConfig = SplitConfig()
    sampling: SamplingConfig = SamplingConfig()

    def configuration_version(self) -> str:
        return compute_data_version({
            "version": self.version,
            "cleaning": self.cleaning.configuration_version(),
            "labeling": self.labeling.configuration_version(),
            "split": self.split.configuration_version(),
            "sampling": self.sampling.configuration_version(),
        })


DEFAULT_TRAINING_DATASET_CONFIG = TrainingDatasetConfig()
