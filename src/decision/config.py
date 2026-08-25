"""DecisionConfig: every threshold `BaselineRuleDecisionAgent` uses, kept
out of code -- the same discipline `regime.config.RegimeConfig` (Phase 5)
and `predict.config.PredictionConfig` (Phase 6) already established.

See docs/specifications/PHASE-7-decision-agent.md section 4.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from data_infra.versioning import compute_data_version


@dataclass(frozen=True)
class DecisionConfig:
    version: str = "decision_config_v1"

    # -- fail-closed gates, checked before any directional action --
    min_confidence: float = 0.75
    min_signal_to_uncertainty_ratio: float = 1.0  # |expected_return| must exceed uncertainty by this multiple

    # -- directional thresholds (symmetric around zero) --
    min_expected_return: float = 0.005  # BUY requires expected_return >= this
    exit_return_threshold: float = -0.005  # SELL (while holding) requires expected_return <= this

    # -- target_weight_hint bound (a hint only -- Position Sizing, Phase 8,
    # decides the real value) --
    max_target_weight_hint: float = 0.10

    def configuration_version(self) -> str:
        return compute_data_version(asdict(self))


DEFAULT_DECISION_CONFIG = DecisionConfig()
