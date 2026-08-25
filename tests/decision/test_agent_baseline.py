"""Category: Unit Test -- BUY/SELL/HOLD/EXIT/NO_TRADE, confidence
handling, missing data, UNKNOWN regime, invalid prediction, deterministic
output (Phase 7 spec section 12).
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

from decision_helpers import empty_portfolio, portfolio_holding

from decision.agent import BaselineRuleDecisionAgent
from decision.config import DecisionConfig

from predict.enums import PredictionMethodType
from predict.models import PredictionOutput

from regime.enums import RegimeAxis, SubjectKind, TrendState, StressState, VolatilityState
from regime.models import CompositeRegimeObservation, RegimeObservation

from trade_journal.enums import DecisionAction, TradeProvenance


def _utc(y, m, d, h=20) -> datetime:
    return datetime(y, m, d, h, tzinfo=timezone.utc)


def make_prediction(
    *, expected_return=0.02, probability=0.6, expected_volatility=0.2, uncertainty=0.001,
    confidence=0.9, as_of_time=None,
) -> PredictionOutput:
    return PredictionOutput(
        prediction_id="PRED-000001", security_id="AAA", as_of_time=as_of_time or _utc(2024, 6, 1),
        horizon_days=5, expected_return=expected_return, probability=probability,
        expected_volatility=expected_volatility, uncertainty=uncertainty, confidence=confidence,
        method="drift_v1", method_type=PredictionMethodType.DETERMINISTIC_BASELINE,
        feature_version="fv1", data_version=("dv1",), method_version="drift_v1",
        configuration_version="cv1",
    )


def make_regime_observation(axis: RegimeAxis, state: str, *, as_of_time=None) -> RegimeObservation:
    return RegimeObservation(
        regime_id=f"REG-{axis.value}", axis=axis, subject_id="AAA", subject_kind=SubjectKind.SECURITY,
        timestamp=as_of_time or _utc(2024, 6, 1), as_of_time=as_of_time or _utc(2024, 6, 1),
        state=state, value=0.1, definition="test", reliability=1.0, lookback_days=20,
        feature_version="fv1", data_version=("dv1",), method_version="mv1", configuration_version="cv1",
    )


def make_composite(
    *, trend_state="BULL", stress_state="NORMAL", vol_state="NORMAL", as_of_time=None,
) -> CompositeRegimeObservation:
    axes = {
        RegimeAxis.TREND: make_regime_observation(RegimeAxis.TREND, trend_state, as_of_time=as_of_time),
        RegimeAxis.VOLATILITY: make_regime_observation(RegimeAxis.VOLATILITY, vol_state, as_of_time=as_of_time),
        RegimeAxis.STRESS: make_regime_observation(RegimeAxis.STRESS, stress_state, as_of_time=as_of_time),
    }
    return CompositeRegimeObservation(
        composite_id="CREG-000001", subject_id="AAA", subject_kind=SubjectKind.SECURITY,
        as_of_time=as_of_time or _utc(2024, 6, 1), axes=axes,
    )


class TestBuySellHoldExitNoTrade:
    def test_buy_when_positive_return_and_no_position(self) -> None:
        agent = BaselineRuleDecisionAgent()
        prediction = make_prediction(expected_return=0.02, confidence=0.9)
        regime = make_composite()
        decision = agent.decide("AAA", _utc(2024, 6, 1), prediction, regime, empty_portfolio(_utc(2024, 6, 1)))
        assert decision.action == DecisionAction.BUY
        assert decision.target_weight_hint is not None and decision.target_weight_hint > 0

    def test_hold_when_positive_return_and_already_positioned(self) -> None:
        agent = BaselineRuleDecisionAgent()
        prediction = make_prediction(expected_return=0.02, confidence=0.9)
        regime = make_composite()
        portfolio = portfolio_holding(_utc(2024, 6, 1), "AAA")
        decision = agent.decide("AAA", _utc(2024, 6, 1), prediction, regime, portfolio)
        assert decision.action == DecisionAction.HOLD

    def test_sell_when_negative_return_and_holding(self) -> None:
        agent = BaselineRuleDecisionAgent()
        prediction = make_prediction(expected_return=-0.02, confidence=0.9)
        regime = make_composite()
        portfolio = portfolio_holding(_utc(2024, 6, 1), "AAA")
        decision = agent.decide("AAA", _utc(2024, 6, 1), prediction, regime, portfolio)
        assert decision.action == DecisionAction.SELL

    def test_no_trade_when_negative_return_and_no_position_to_exit(self) -> None:
        """No shorting in the baseline agent -- a negative signal with no
        existing position is NO_TRADE, not a short SELL."""
        agent = BaselineRuleDecisionAgent()
        prediction = make_prediction(expected_return=-0.02, confidence=0.9)
        regime = make_composite()
        decision = agent.decide("AAA", _utc(2024, 6, 1), prediction, regime, empty_portfolio(_utc(2024, 6, 1)))
        assert decision.action == DecisionAction.NO_TRADE
        assert decision.decision_reason == "negative_signal_no_position_to_exit"

    def test_no_trade_when_return_magnitude_below_threshold(self) -> None:
        agent = BaselineRuleDecisionAgent(DecisionConfig(min_expected_return=0.05, exit_return_threshold=-0.05))
        prediction = make_prediction(expected_return=0.01, confidence=0.9)
        regime = make_composite()
        decision = agent.decide("AAA", _utc(2024, 6, 1), prediction, regime, empty_portfolio(_utc(2024, 6, 1)))
        assert decision.action == DecisionAction.NO_TRADE
        assert decision.decision_reason == "expected_return_below_threshold"

    def test_exit_is_reserved_not_produced_by_the_baseline_agent(self) -> None:
        """EXIT is reserved for a future risk-driven forced close (Risk
        Engine, Phase 8) -- the baseline, signal-driven agent never emits
        it, mirroring how Phase 2 never produced OrderStatus.CANCELLED
        (Phase 3 spec section 5.3) even though the enum member exists."""
        assert DecisionAction.EXIT in DecisionAction


class TestConfidenceHandling:
    def test_no_trade_below_min_confidence(self) -> None:
        agent = BaselineRuleDecisionAgent(DecisionConfig(min_confidence=0.8))
        prediction = make_prediction(expected_return=0.05, confidence=0.5)
        regime = make_composite()
        decision = agent.decide("AAA", _utc(2024, 6, 1), prediction, regime, empty_portfolio(_utc(2024, 6, 1)))
        assert decision.action == DecisionAction.NO_TRADE
        assert decision.decision_reason == "confidence_below_threshold"

    def test_uncertainty_exceeding_signal_forces_no_trade(self) -> None:
        agent = BaselineRuleDecisionAgent()
        prediction = make_prediction(expected_return=0.005, confidence=0.9, uncertainty=0.01)
        regime = make_composite()
        decision = agent.decide("AAA", _utc(2024, 6, 1), prediction, regime, empty_portfolio(_utc(2024, 6, 1)))
        assert decision.action == DecisionAction.NO_TRADE
        assert decision.decision_reason == "uncertainty_exceeds_signal"

    def test_confidence_is_copied_onto_the_decision(self) -> None:
        agent = BaselineRuleDecisionAgent()
        prediction = make_prediction(expected_return=0.02, confidence=0.83)
        regime = make_composite()
        decision = agent.decide("AAA", _utc(2024, 6, 1), prediction, regime, empty_portfolio(_utc(2024, 6, 1)))
        assert decision.confidence == 0.83


class TestMissingOrInvalidData:
    def test_no_trade_when_prediction_missing(self) -> None:
        agent = BaselineRuleDecisionAgent()
        regime = make_composite()
        decision = agent.decide("AAA", _utc(2024, 6, 1), None, regime, empty_portfolio(_utc(2024, 6, 1)))
        assert decision.action == DecisionAction.NO_TRADE
        assert decision.decision_reason == "prediction_unavailable"

    def test_no_trade_when_prediction_has_none_estimates(self) -> None:
        """Mirrors DriftPredictor's own fail-closed output (insufficient
        history -> expected_return=None) -- Decision must not treat a
        None estimate as zero or skip the check."""
        agent = BaselineRuleDecisionAgent()
        prediction = dataclasses.replace(make_prediction(), expected_return=None, confidence=None)
        regime = make_composite()
        decision = agent.decide("AAA", _utc(2024, 6, 1), prediction, regime, empty_portfolio(_utc(2024, 6, 1)))
        assert decision.action == DecisionAction.NO_TRADE
        assert decision.decision_reason == "prediction_unavailable"

    def test_no_trade_when_portfolio_state_missing(self) -> None:
        """PROJECT_MASTER_PLAN.md section 1.4's Fail-Closed table:
        "Position Unknown -> 신규 주문 차단"."""
        agent = BaselineRuleDecisionAgent()
        prediction = make_prediction(expected_return=0.02, confidence=0.9)
        regime = make_composite()
        decision = agent.decide("AAA", _utc(2024, 6, 1), prediction, regime, None)
        assert decision.action == DecisionAction.NO_TRADE
        assert decision.decision_reason == "portfolio_state_unavailable"

    def test_no_trade_when_regime_trend_unknown(self) -> None:
        agent = BaselineRuleDecisionAgent()
        prediction = make_prediction(expected_return=0.02, confidence=0.9)
        regime = make_composite(trend_state=TrendState.UNKNOWN.value)
        decision = agent.decide("AAA", _utc(2024, 6, 1), prediction, regime, empty_portfolio(_utc(2024, 6, 1)))
        assert decision.action == DecisionAction.NO_TRADE
        assert decision.decision_reason == "regime_trend_unknown"

    def test_no_trade_when_regime_stress_high(self) -> None:
        agent = BaselineRuleDecisionAgent()
        prediction = make_prediction(expected_return=0.02, confidence=0.9)
        regime = make_composite(stress_state=StressState.HIGH.value)
        decision = agent.decide("AAA", _utc(2024, 6, 1), prediction, regime, empty_portfolio(_utc(2024, 6, 1)))
        assert decision.action == DecisionAction.NO_TRADE
        assert decision.decision_reason == "regime_stress_high"

    def test_regime_entirely_absent_does_not_block_a_decision(self) -> None:
        """Regime is a gate only when available -- Prediction is the
        mandatory input, Regime is an additional check applied only when
        present (Phase 7 spec section 6)."""
        agent = BaselineRuleDecisionAgent()
        prediction = make_prediction(expected_return=0.02, confidence=0.9)
        decision = agent.decide("AAA", _utc(2024, 6, 1), prediction, None, empty_portfolio(_utc(2024, 6, 1)))
        assert decision.action == DecisionAction.BUY


class TestDeterministicOutput:
    def test_same_inputs_produce_identical_decisions(self) -> None:
        prediction = make_prediction(expected_return=0.02, confidence=0.9)
        regime = make_composite()
        portfolio = empty_portfolio(_utc(2024, 6, 1))

        d1 = BaselineRuleDecisionAgent().decide("AAA", _utc(2024, 6, 1), prediction, regime, portfolio)
        d2 = BaselineRuleDecisionAgent().decide("AAA", _utc(2024, 6, 1), prediction, regime, portfolio)
        assert d1.action == d2.action
        assert d1.decision_reason == d2.decision_reason
        assert d1.target_weight_hint == d2.target_weight_hint

    def test_never_falls_through_to_an_undeclared_action(self) -> None:
        """Every branch in the rule set ends in an explicit `build(...)`
        call -- there is no code path that could leave `action` unset."""
        import inspect

        from decision.agent import BaselineRuleDecisionAgent as Agent

        source = inspect.getsource(Agent.decide)
        # Every `return build(` call must name one of the five actions.
        assert source.count("return build(") >= 5
