"""DecisionAgent Protocol + BaselineRuleDecisionAgent.

See docs/specifications/PHASE-7-decision-agent.md sections 4, 6, 8.

`DecisionAgent.decide()` takes already-computed `PredictionOutput`/
`CompositeRegimeObservation`/`PortfolioView` as plain data arguments --
it does not fetch data itself, call `AsOfDataView`, or do anything that
could introduce a new leakage path. Point-in-time correctness is
entirely inherited from whoever produced those inputs (Phase 5's
`RegimeDetector`, Phase 6's `Predictor`, both already `AsOfDataView`-safe)
-- Decision adds no new guard because it needs none (Phase 7 spec
section 3).

Every rule is evaluated in a fixed, fail-closed order: the first
condition that is not satisfied produces `NO_TRADE` with a factual
`decision_reason` naming exactly which condition failed. No rule ever
produces BUY/SELL by "falling through" an unhandled case -- the final
`else` branch is itself `NO_TRADE` (Phase 7 spec section 6).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol

from backtest.portfolio import PortfolioView

from decision.config import DecisionConfig
from decision.models import DecisionOutput

from predict.models import PredictionOutput

from regime.enums import RegimeAxis, StressState, TrendState
from regime.models import CompositeRegimeObservation

from trade_journal.enums import DecisionAction, TradeProvenance

FEATURE_VERSION = "phase7_decision_features_v1"


class DecisionAgent(Protocol):
    def decide(
        self,
        security_id: str,
        as_of_time: datetime,
        prediction: Optional[PredictionOutput],
        regime: Optional[CompositeRegimeObservation],
        portfolio_state: Optional[PortfolioView],
        risk_state: Optional[dict] = None,
        *,
        provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
        experiment_id: Optional[str] = None,
    ) -> DecisionOutput: ...


class _IdAllocator:
    def __init__(self, start: int = 1) -> None:
        self._next_id = start

    def allocate(self) -> str:
        did = f"DEC-OUT-{self._next_id:06d}"
        self._next_id += 1
        return did


class BaselineRuleDecisionAgent:
    """A deterministic, hand-verifiable rule set -- no AI/ML. Kept
    interchangeable with a future model-based agent via the same
    `DecisionAgent` Protocol (Phase 7 spec section 7): only the class
    implementing `decide()` would change, never the callers or the
    `DecisionOutput` shape."""

    version = "baseline_rule_decision_agent_v1"

    def __init__(self, config: DecisionConfig = DecisionConfig(), *, starting_id: int = 1) -> None:
        self._config = config
        self._ids = _IdAllocator(starting_id)

    def decide(
        self,
        security_id: str,
        as_of_time: datetime,
        prediction: Optional[PredictionOutput],
        regime: Optional[CompositeRegimeObservation],
        portfolio_state: Optional[PortfolioView],
        risk_state: Optional[dict] = None,
        *,
        provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
        experiment_id: Optional[str] = None,
    ) -> DecisionOutput:
        config = self._config
        regime_context = (
            {axis.value: obs.state for axis, obs in regime.axes.items()} if regime is not None else None
        )
        regime_version = None
        if regime is not None:
            trend_obs = regime.get(RegimeAxis.TREND)
            regime_version = trend_obs.configuration_version if trend_obs is not None else None

        def build(action: DecisionAction, reason: str, *, target_weight_hint: Optional[float] = None) -> DecisionOutput:
            return DecisionOutput(
                decision_id=self._ids.allocate(),
                security_id=security_id,
                as_of_time=as_of_time,
                action=action,
                decision_reason=reason,
                confidence=prediction.confidence if prediction is not None else None,
                time_horizon_days=prediction.horizon_days if prediction is not None else None,
                target_weight_hint=target_weight_hint,
                regime=regime_context,
                prediction_id=prediction.prediction_id if prediction is not None else None,
                prediction_version=prediction.method_version if prediction is not None else None,
                regime_version=regime_version,
                feature_version=FEATURE_VERSION,
                data_version=prediction.data_version if prediction is not None else (),
                model_version=None,
                decision_version=self.version,
                provenance=provenance,
                experiment_id=experiment_id,
                recorded_at=as_of_time,
            )

        # -- fail-closed gates, in order; the first violated gate wins --

        if prediction is None or prediction.expected_return is None or prediction.confidence is None:
            return build(DecisionAction.NO_TRADE, "prediction_unavailable")

        if prediction.confidence < config.min_confidence:
            return build(DecisionAction.NO_TRADE, "confidence_below_threshold")

        if (
            prediction.uncertainty is not None
            and abs(prediction.expected_return) <= prediction.uncertainty * config.min_signal_to_uncertainty_ratio
        ):
            return build(DecisionAction.NO_TRADE, "uncertainty_exceeds_signal")

        if regime is not None:
            trend_obs = regime.get(RegimeAxis.TREND)
            if trend_obs is not None and trend_obs.state == TrendState.UNKNOWN.value:
                return build(DecisionAction.NO_TRADE, "regime_trend_unknown")
            stress_obs = regime.get(RegimeAxis.STRESS)
            if stress_obs is not None and stress_obs.state == StressState.UNKNOWN.value:
                # Same fail-closed treatment as the trend-UNKNOWN gate
                # above -- an unknown stress state is not evidence of
                # low stress, so it must not fall through to a
                # directional decision (ADR-0115).
                return build(DecisionAction.NO_TRADE, "regime_stress_unknown")
            if stress_obs is not None and stress_obs.state == StressState.HIGH.value:
                return build(DecisionAction.NO_TRADE, "regime_stress_high")

        if portfolio_state is None:
            # PROJECT_MASTER_PLAN.md section 1.4 (Fail-Closed table):
            # "Position Unknown -> 신규 주문 차단" -- applied here as
            # "no directional decision without a known position."
            return build(DecisionAction.NO_TRADE, "portfolio_state_unavailable")

        current_quantity = portfolio_state.quantity_of(security_id)
        expected_return = prediction.expected_return

        if expected_return >= config.min_expected_return:
            if current_quantity > 0:
                return build(DecisionAction.HOLD, "already_positioned_positive_signal")
            hint = min(config.max_target_weight_hint, prediction.confidence * config.max_target_weight_hint)
            return build(DecisionAction.BUY, "positive_expected_return_above_threshold", target_weight_hint=hint)

        if expected_return <= config.exit_return_threshold:
            if current_quantity > 0:
                return build(DecisionAction.SELL, "negative_expected_return_below_threshold", target_weight_hint=0.0)
            return build(DecisionAction.NO_TRADE, "negative_signal_no_position_to_exit")

        return build(DecisionAction.NO_TRADE, "expected_return_below_threshold")
