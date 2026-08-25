"""Category: Boundary Test -- Position Sizing/Risk Engine compute
target_weight/target_quantity (their authoritative responsibility per
PROJECT_MASTER_PLAN.md section 8.3/8.4), but never an order, a broker
call, or an execution price (Phase 8 spec section 5, 14). Also verifies
Phase 7's Decision Agent boundary is untouched by this phase.
"""

from __future__ import annotations

import dataclasses
import inspect

from decision.agent import BaselineRuleDecisionAgent
from decision.models import DecisionOutput

from risk.models import PortfolioRiskState, PositionSizingResult, RiskCheckedPosition
from risk.sizing import DeterministicPositionSizer
from risk.engine import DeterministicPortfolioRiskEngine

_FORBIDDEN_ORDER_FIELDS = {
    "order_id", "broker_order", "execution_price", "broker", "order_type",
    "side", "limit_price", "stop_price", "fill_price", "commission",
}
_FORBIDDEN_METHOD_NAMES = {
    "submit_order", "place_order", "execute", "send_order", "cancel_order", "create_order",
}


class TestPositionSizingResultHasNoOrderShapedField:
    def test_no_forbidden_field_on_position_sizing_result(self) -> None:
        field_names = {f.name for f in dataclasses.fields(PositionSizingResult)}
        assert field_names.isdisjoint(_FORBIDDEN_ORDER_FIELDS)

    def test_position_sizing_result_does_carry_target_weight_and_quantity(self) -> None:
        # unlike DecisionOutput, this IS this layer's authoritative output
        field_names = {f.name for f in dataclasses.fields(PositionSizingResult)}
        assert "proposed_target_weight" in field_names
        assert "proposed_target_quantity" in field_names


class TestRiskCheckedPositionHasNoOrderShapedField:
    def test_no_forbidden_field_on_risk_checked_position(self) -> None:
        field_names = {f.name for f in dataclasses.fields(RiskCheckedPosition)}
        assert field_names.isdisjoint(_FORBIDDEN_ORDER_FIELDS)

    def test_risk_checked_position_does_carry_final_target_weight_and_quantity(self) -> None:
        field_names = {f.name for f in dataclasses.fields(RiskCheckedPosition)}
        assert "final_target_weight" in field_names
        assert "final_target_quantity" in field_names


class TestPortfolioRiskStateHasNoOrderShapedField:
    def test_no_forbidden_field_on_portfolio_risk_state(self) -> None:
        field_names = {f.name for f in dataclasses.fields(PortfolioRiskState)}
        assert field_names.isdisjoint(_FORBIDDEN_ORDER_FIELDS)


class TestNoMethodCanSubmitAnOrder:
    def test_position_sizer_has_no_order_submission_method(self) -> None:
        public_attrs = {name for name in dir(DeterministicPositionSizer) if not name.startswith("_")}
        assert public_attrs.isdisjoint(_FORBIDDEN_METHOD_NAMES)

    def test_risk_engine_has_no_order_submission_method(self) -> None:
        public_attrs = {name for name in dir(DeterministicPortfolioRiskEngine) if not name.startswith("_")}
        assert public_attrs.isdisjoint(_FORBIDDEN_METHOD_NAMES)


class TestSizeAndAssessSignaturesTakeNoBrokerOrExecutionInput:
    def test_size_signature_has_no_broker_or_execution_parameter(self) -> None:
        params = set(inspect.signature(DeterministicPositionSizer.size).parameters)
        assert params.isdisjoint({"broker", "order", "execution_price", "broker_order"})

    def test_assess_signature_has_no_broker_or_execution_parameter(self) -> None:
        params = set(inspect.signature(DeterministicPortfolioRiskEngine.assess).parameters)
        assert params.isdisjoint({"broker", "order", "execution_price", "broker_order"})


class TestPhase7DecisionAgentBoundaryIsUntouched:
    """Phase 8 must not weaken or bypass Phase 7's own boundary --
    DecisionOutput still has no quantity/order-shaped field, and
    BaselineRuleDecisionAgent still exposes no way to submit an order."""

    def test_decision_output_still_has_no_quantity_field(self) -> None:
        field_names = {f.name for f in dataclasses.fields(DecisionOutput)}
        assert "quantity" not in field_names
        assert field_names.isdisjoint(_FORBIDDEN_ORDER_FIELDS)

    def test_decision_agent_still_has_no_order_submission_method(self) -> None:
        public_attrs = {name for name in dir(BaselineRuleDecisionAgent) if not name.startswith("_")}
        assert public_attrs.isdisjoint(_FORBIDDEN_METHOD_NAMES)
