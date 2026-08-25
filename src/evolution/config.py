"""PromotionConfig: every threshold the candidate status-transition gate
(`evolution.criteria`) uses, kept out of code -- the same discipline
`learning.config`/`decision.config`/`risk.config` already established.

See docs/specifications/PHASE-11-model-evolution.md section 5.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from data_infra.versioning import compute_data_version


@dataclass(frozen=True)
class PromotionConfig:
    version: str = "promotion_config_v1"
    # Minimum sample_count a split's EvaluationMetrics must have before a
    # transition into the status that split gates can be attempted at
    # all -- a metric computed over too few samples is not a basis for
    # any status transition, passing or failing (never silently accepted
    # as "0 samples, trivially passes").
    min_validation_sample_count: int = 5
    min_test_sample_count: int = 5
    # Optional, explicit comparative bar for OOS_TESTED: when set, the
    # candidate's TEST mean_absolute_error must not exceed
    # baseline_metrics.mean_absolute_error * this ratio. None (default)
    # means no comparative bar is enforced here -- only completeness/
    # validity of the metrics themselves is required. A caller who wants
    # a concrete "must beat baseline by X" bar sets this explicitly
    # rather than the module inventing one (PROJECT_MASTER_PLAN.md
    # section 13.6: "복잡한 AI가 정말 가치가 있는지 확인").
    max_test_mae_over_baseline_ratio: Optional[float] = None

    def __post_init__(self) -> None:
        if self.min_validation_sample_count <= 0:
            raise ValueError("min_validation_sample_count must be positive")
        if self.min_test_sample_count <= 0:
            raise ValueError("min_test_sample_count must be positive")
        if self.max_test_mae_over_baseline_ratio is not None and self.max_test_mae_over_baseline_ratio <= 0:
            raise ValueError("max_test_mae_over_baseline_ratio must be positive when configured")

    def configuration_version(self) -> str:
        return compute_data_version(asdict(self))


DEFAULT_PROMOTION_CONFIG = PromotionConfig()
