"""Category: Order Validation Test -- instruction section 5: an invalid
or unapproved order never reaches a `BrokerAdapter`, and always ends in
an explicit `VALIDATION_REJECTED` verdict rather than an exception."""

from __future__ import annotations

import dataclasses

from broker_helpers import make_risk_checked_position, utc

from broker.enums import OrderValidationStatus
from broker.validation import build_validated_order, compute_client_order_id

from backtest.enums import OrderSide, OrderType

from risk.enums import RiskCheckStatus


class TestAcceptedOrders:
    def test_buy_when_target_exceeds_current(self) -> None:
        rcp = make_risk_checked_position(final_target_quantity=50.0)
        result = build_validated_order(rcp, current_quantity=10.0, configuration_version="cfg-v1")
        assert result.status == OrderValidationStatus.ACCEPTED
        assert result.validated_order.side == OrderSide.BUY
        assert result.validated_order.quantity == 40.0

    def test_sell_when_target_below_current(self) -> None:
        rcp = make_risk_checked_position(final_target_quantity=10.0)
        result = build_validated_order(rcp, current_quantity=50.0, configuration_version="cfg-v1")
        assert result.status == OrderValidationStatus.ACCEPTED
        assert result.validated_order.side == OrderSide.SELL
        assert result.validated_order.quantity == 40.0

    def test_reduce_status_is_still_accepted(self) -> None:
        rcp = make_risk_checked_position(status=RiskCheckStatus.REDUCE, final_target_quantity=20.0)
        result = build_validated_order(rcp, current_quantity=10.0, configuration_version="cfg-v1")
        assert result.status == OrderValidationStatus.ACCEPTED

    def test_validated_order_carries_full_lineage(self) -> None:
        rcp = make_risk_checked_position(
            risk_id="RISK-000042", decision_id="DEC-OUT-000042", sizing_id="SIZE-000042", final_target_quantity=30.0,
        )
        result = build_validated_order(rcp, current_quantity=0.0, configuration_version="cfg-v1")
        order = result.validated_order
        assert order.decision_id == "DEC-OUT-000042"
        assert order.sizing_id == "SIZE-000042"
        assert order.risk_assessment_id == "RISK-000042"
        assert order.configuration_version == "cfg-v1"


class TestRejectedOrders:
    def test_reject_status_is_validation_rejected(self) -> None:
        rcp = make_risk_checked_position(status=RiskCheckStatus.REJECT, final_target_quantity=0.0)
        result = build_validated_order(rcp, current_quantity=0.0, configuration_version="cfg-v1")
        assert result.status == OrderValidationStatus.VALIDATION_REJECTED
        assert result.validated_order is None
        assert result.reason == "risk_status_is_pass_or_reduce"

    def test_unknown_status_is_validation_rejected(self) -> None:
        rcp = make_risk_checked_position(status=RiskCheckStatus.UNKNOWN, final_target_quantity=None)
        result = build_validated_order(rcp, current_quantity=0.0, configuration_version="cfg-v1")
        assert result.status == OrderValidationStatus.VALIDATION_REJECTED
        assert result.reason == "risk_status_is_pass_or_reduce"

    def test_missing_decision_id_is_validation_rejected(self) -> None:
        rcp = make_risk_checked_position(decision_id=None)
        result = build_validated_order(rcp, current_quantity=0.0, configuration_version="cfg-v1")
        assert result.status == OrderValidationStatus.VALIDATION_REJECTED
        assert result.reason == "missing_lineage"

    def test_missing_sizing_id_is_validation_rejected(self) -> None:
        rcp = make_risk_checked_position(sizing_id=None)
        result = build_validated_order(rcp, current_quantity=0.0, configuration_version="cfg-v1")
        assert result.status == OrderValidationStatus.VALIDATION_REJECTED
        assert result.reason == "missing_lineage"

    def test_missing_final_target_quantity_is_validation_rejected(self) -> None:
        rcp = make_risk_checked_position(final_target_quantity=None)
        result = build_validated_order(rcp, current_quantity=0.0, configuration_version="cfg-v1")
        assert result.status == OrderValidationStatus.VALIDATION_REJECTED
        assert result.reason == "final_target_quantity_present"

    def test_no_trade_needed_is_validation_rejected(self) -> None:
        rcp = make_risk_checked_position(final_target_quantity=25.0)
        result = build_validated_order(rcp, current_quantity=25.0, configuration_version="cfg-v1")
        assert result.status == OrderValidationStatus.VALIDATION_REJECTED
        assert result.reason == "no_trade_needed"

    def test_non_finite_current_quantity_is_validation_rejected(self) -> None:
        rcp = make_risk_checked_position(final_target_quantity=25.0)
        result = build_validated_order(rcp, current_quantity=float("nan"), configuration_version="cfg-v1")
        assert result.status == OrderValidationStatus.VALIDATION_REJECTED
        assert result.reason == "current_quantity_finite"

    def test_rejection_result_carries_audit_checks(self) -> None:
        rcp = make_risk_checked_position(status=RiskCheckStatus.REJECT)
        result = build_validated_order(rcp, current_quantity=0.0, configuration_version="cfg-v1")
        assert result.checks["risk_status_is_pass_or_reduce"] is False


class TestOrderValidationResultInvariants:
    def test_accepted_requires_validated_order(self) -> None:
        import pytest

        from broker.models import OrderValidationResult

        with pytest.raises(ValueError):
            OrderValidationResult(status=OrderValidationStatus.ACCEPTED, validated_order=None, reason="ok", checks={})

    def test_rejected_must_not_carry_validated_order(self) -> None:
        import pytest

        from broker.models import OrderValidationResult, ValidatedOrder

        rcp = make_risk_checked_position(final_target_quantity=30.0)
        accepted = build_validated_order(rcp, current_quantity=0.0, configuration_version="cfg-v1")
        with pytest.raises(ValueError):
            OrderValidationResult(
                status=OrderValidationStatus.VALIDATION_REJECTED,
                validated_order=accepted.validated_order, reason="x", checks={},
            )


class TestClientOrderIdIdempotency:
    def test_same_inputs_produce_same_client_order_id(self) -> None:
        id1 = compute_client_order_id("DEC-1", "SIZE-1", "RISK-1", "AAA", OrderSide.BUY, 10.0, utc(2024, 1, 2))
        id2 = compute_client_order_id("DEC-1", "SIZE-1", "RISK-1", "AAA", OrderSide.BUY, 10.0, utc(2024, 1, 2))
        assert id1 == id2

    def test_different_lineage_produces_different_client_order_id(self) -> None:
        id1 = compute_client_order_id("DEC-1", "SIZE-1", "RISK-1", "AAA", OrderSide.BUY, 10.0, utc(2024, 1, 2))
        id2 = compute_client_order_id("DEC-2", "SIZE-1", "RISK-1", "AAA", OrderSide.BUY, 10.0, utc(2024, 1, 2))
        assert id1 != id2

    def test_rebuilding_the_same_validated_order_twice_is_identical(self) -> None:
        rcp = make_risk_checked_position(final_target_quantity=40.0)
        r1 = build_validated_order(rcp, current_quantity=10.0, configuration_version="cfg-v1")
        r2 = build_validated_order(rcp, current_quantity=10.0, configuration_version="cfg-v1")
        assert r1.validated_order.client_order_id == r2.validated_order.client_order_id


class TestValidatedOrderStructuralInvariants:
    def test_frozen(self) -> None:
        import pytest

        rcp = make_risk_checked_position(final_target_quantity=30.0)
        order = build_validated_order(rcp, current_quantity=0.0, configuration_version="cfg-v1").validated_order
        with pytest.raises(dataclasses.FrozenInstanceError):
            order.quantity = 999.0

    def test_zero_quantity_rejected_at_construction(self) -> None:
        import pytest

        from broker.models import ValidatedOrder

        with pytest.raises(ValueError):
            ValidatedOrder(
                client_order_id="CID-x", security_id="AAA", side=OrderSide.BUY, quantity=0.0,
                order_type=OrderType.MARKET,
                as_of_time=utc(2024, 1, 2), decision_id="D", sizing_id="S", risk_assessment_id="R",
                configuration_version="cfg-v1",
            )
