"""Category: Boundary Test -- Decision Agent does not create orders,
does not decide quantity, does not call a broker, does not bypass risk
limits (Phase 7 spec section 5, 12).

Verified by reflection, the same discipline Phase 5/6 used to verify
their own structural boundaries.
"""

from __future__ import annotations

import dataclasses
import inspect

from decision.agent import BaselineRuleDecisionAgent
from decision.models import DecisionOutput

_ORDER_SHAPED_NAMES = {
    "quantity", "order_id", "broker_order", "execution_price", "side", "order_type",
}
_RISK_BYPASS_NAMES = {"risk_limit_override", "force_execute", "bypass_risk", "kill_switch_override"}


class TestDecisionOutputHasNoOrderOrRiskBypassFields:
    def test_no_order_shaped_field_exists(self) -> None:
        field_names = {f.name for f in dataclasses.fields(DecisionOutput)}
        assert field_names.isdisjoint(_ORDER_SHAPED_NAMES)

    def test_target_weight_hint_is_named_as_a_hint_not_an_authoritative_weight(self) -> None:
        """`target_weight` (without "_hint") does not exist -- Position
        Sizing (Phase 8) owns the authoritative value."""
        field_names = {f.name for f in dataclasses.fields(DecisionOutput)}
        assert "target_weight" not in field_names
        assert "target_weight_hint" in field_names

    def test_no_risk_bypass_field_exists(self) -> None:
        field_names = {f.name for f in dataclasses.fields(DecisionOutput)}
        assert field_names.isdisjoint(_RISK_BYPASS_NAMES)


class TestDecisionAgentNeverProducesOrdersOrCallsABroker:
    def test_decide_signature_has_no_broker_or_execution_parameter(self) -> None:
        sig = inspect.signature(BaselineRuleDecisionAgent.decide)
        param_names = set(sig.parameters) - {"self"}
        assert "broker" not in param_names
        assert "quantity" not in param_names
        assert "order" not in param_names

    def test_decide_return_type_is_decision_output_not_an_order_type(self) -> None:
        from backtest.orders import Order
        from backtest.strategy import OrderIntent

        return_annotation = inspect.signature(BaselineRuleDecisionAgent.decide).return_annotation
        assert return_annotation in (DecisionOutput, "DecisionOutput")
        assert return_annotation is not Order
        assert return_annotation is not OrderIntent

    def test_decision_agent_does_not_implement_the_strategy_protocol(self) -> None:
        assert not hasattr(BaselineRuleDecisionAgent, "generate_orders")

    def test_no_method_on_decision_agent_can_submit_an_order(self) -> None:
        public_attrs = {name for name in dir(BaselineRuleDecisionAgent) if not name.startswith("_")}
        forbidden = {"submit_order", "place_order", "execute", "send_order", "cancel_order"}
        assert public_attrs.isdisjoint(forbidden)

    def test_decision_agent_has_no_risk_limit_configuration_it_could_bypass(self) -> None:
        """The agent has no notion of a hard risk limit at all -- it
        cannot "bypass" what it does not represent. Risk limit
        enforcement remains entirely Phase 8's responsibility; this
        agent's only self-referential gates (confidence/uncertainty/
        regime thresholds) are pre-trade signal-quality checks, not
        risk-limit checks, and none of them can be satisfied by any
        input this agent receives to force a BUY/SELL through."""
        import dataclasses as dc

        from decision.config import DecisionConfig

        field_names = {f.name for f in dc.fields(DecisionConfig)}
        risk_limit_names = {"position_limit", "sector_limit", "drawdown_limit", "max_leverage", "risk_budget"}
        assert field_names.isdisjoint(risk_limit_names)
