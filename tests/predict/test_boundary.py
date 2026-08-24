"""Category: structural boundary with Decision/Risk/Execution (Phase 6
spec section 2, master principle 4-6 -- "Prediction 결과만으로 주문 생성
금지", "Decision Agent와 경계 유지", "Risk Engine과 경계 유지").

Verified by reflection, the same discipline Phase 5 used to verify
`AsOfDataView.get_bars` structurally has no `as_of_time` parameter.
"""

from __future__ import annotations

import dataclasses
import inspect

from predict.models import PredictionOutput
from predict.predictor import DriftPredictor, RandomWalkPredictor, RegimeAwarePredictor


_ORDER_SHAPED_NAMES = {"side", "action", "quantity", "order_type", "order_id", "target_weight", "target_quantity"}
_RISK_SHAPED_NAMES = {"risk_state", "risk_limit", "position_limit", "portfolio_state", "cash", "exposure"}


class TestPredictionOutputHasNoOrderOrRiskFields:
    def test_no_order_shaped_field_exists(self) -> None:
        field_names = {f.name for f in dataclasses.fields(PredictionOutput)}
        assert field_names.isdisjoint(_ORDER_SHAPED_NAMES)

    def test_no_risk_or_portfolio_shaped_field_exists(self) -> None:
        field_names = {f.name for f in dataclasses.fields(PredictionOutput)}
        assert field_names.isdisjoint(_RISK_SHAPED_NAMES)


class TestPredictorsNeverProduceOrders:
    def test_predict_method_signature_has_no_portfolio_or_risk_parameter(self) -> None:
        """Predictor.predict cannot even receive a portfolio/risk state
        as input -- there is no parameter through which one could be
        threaded in, which is the structural form of "Prediction은
        Decision/Risk/Execution과 반드시 분리한다" (this phase's
        instruction), not merely a documented convention."""
        for predictor_cls in (RandomWalkPredictor, DriftPredictor, RegimeAwarePredictor):
            sig = inspect.signature(predictor_cls.predict)
            param_names = set(sig.parameters) - {"self"}
            assert "portfolio" not in param_names
            assert "risk_state" not in param_names
            assert "risk" not in param_names

    def test_no_method_on_any_predictor_returns_an_order_type(self) -> None:
        from backtest.orders import Order
        from backtest.strategy import OrderIntent

        for predictor_cls in (RandomWalkPredictor, DriftPredictor, RegimeAwarePredictor):
            return_annotation = inspect.signature(predictor_cls.predict).return_annotation
            assert return_annotation in (PredictionOutput, "PredictionOutput")
            assert return_annotation is not Order
            assert return_annotation is not OrderIntent

    def test_predictors_do_not_implement_the_strategy_protocol(self) -> None:
        """A Predictor is not a Strategy -- it has no generate_orders
        method, so it cannot be handed to BacktestEngine as one by
        accident."""
        for predictor_cls in (RandomWalkPredictor, DriftPredictor, RegimeAwarePredictor):
            assert not hasattr(predictor_cls, "generate_orders")
