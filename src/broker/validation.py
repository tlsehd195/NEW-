"""build_validated_order: the Order Validation boundary instruction
section 5 requires -- turns an already risk-approved
`risk.models.RiskCheckedPosition` (plus the caller's freshly-known
current position size) into a `ValidatedOrder`, or a factual
`VALIDATION_REJECTED` verdict. This is the *only* place in this
codebase that computes a trade quantity/side from a target
position -- `risk.models.RiskCheckedPosition.final_target_quantity` is
an absolute target, not a delta (`risk.sizing`/`risk.engine`, Phase 8),
so nothing upstream of this module already knows what to actually buy
or sell.

See docs/specifications/PHASE-13-toss-securities-adapter.md section 7.

This module never queries a `DataRepository`/`AsOfDataView`, never calls
`decision.agent`/`risk.sizing`/`risk.engine`, and never re-derives a
target weight/quantity of its own -- `current_quantity` must be supplied
by the caller (in production, sourced from `BrokerAdapter.
get_positions()`; in a backtest/offline context, from the same
`PortfolioView` the rest of the pipeline already uses).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from broker.enums import OrderValidationStatus
from broker.models import OrderValidationResult, ValidatedOrder

from backtest.enums import OrderSide, OrderType

from data_infra.versioning import compute_data_version

from risk.enums import RiskCheckStatus
from risk.models import RiskCheckedPosition

CLIENT_ORDER_ID_VERSION = "client_order_id_v1"


def _finite(value: Optional[float]) -> bool:
    if value is None:
        return False
    return value == value and value not in (float("inf"), float("-inf"))


def compute_client_order_id(
    decision_id: str, sizing_id: str, risk_assessment_id: str,
    security_id: str, side: OrderSide, quantity: float, as_of_time: datetime,
) -> str:
    """Deterministic (instruction section 12): the same logical order
    (same decision/sizing/risk lineage, same symbol/side/quantity, same
    as_of_time) always produces the same `client_order_id`, so a caller
    retrying after an ambiguous transport failure resubmits the *same*
    idempotency key rather than minting a new one and risking a
    duplicate fill."""
    payload = {
        "version": CLIENT_ORDER_ID_VERSION,
        "decision_id": decision_id, "sizing_id": sizing_id, "risk_assessment_id": risk_assessment_id,
        "security_id": security_id, "side": side.value, "quantity": quantity,
        "as_of_time": as_of_time.isoformat(),
    }
    digest = compute_data_version(payload)
    return f"CID-{digest[:24]}"


def _rejected(reason: str, checks: dict) -> OrderValidationResult:
    return OrderValidationResult(
        status=OrderValidationStatus.VALIDATION_REJECTED, validated_order=None, reason=reason, checks=checks,
    )


def build_validated_order(
    risk_checked_position: RiskCheckedPosition,
    current_quantity: float,
    *,
    configuration_version: str,
) -> OrderValidationResult:
    rcp = risk_checked_position
    checks: dict = {}

    checks["risk_status_is_pass_or_reduce"] = rcp.status in (RiskCheckStatus.PASS, RiskCheckStatus.REDUCE)
    if not checks["risk_status_is_pass_or_reduce"]:
        return _rejected("risk_status_is_pass_or_reduce", checks)

    checks["has_decision_id"] = bool(rcp.decision_id)
    checks["has_sizing_id"] = bool(rcp.sizing_id)
    checks["has_risk_assessment_id"] = bool(rcp.risk_id)
    if not (checks["has_decision_id"] and checks["has_sizing_id"] and checks["has_risk_assessment_id"]):
        return _rejected("missing_lineage", checks)

    checks["final_target_quantity_present"] = rcp.final_target_quantity is not None
    if not checks["final_target_quantity_present"]:
        return _rejected("final_target_quantity_present", checks)

    checks["current_quantity_finite"] = _finite(current_quantity)
    if not checks["current_quantity_finite"]:
        return _rejected("current_quantity_finite", checks)

    trade_quantity = rcp.final_target_quantity - current_quantity

    checks["trade_quantity_finite"] = _finite(trade_quantity)
    if not checks["trade_quantity_finite"]:
        return _rejected("trade_quantity_finite", checks)

    checks["trade_quantity_nonzero"] = trade_quantity != 0
    if not checks["trade_quantity_nonzero"]:
        return _rejected("no_trade_needed", checks)

    side = OrderSide.BUY if trade_quantity > 0 else OrderSide.SELL
    quantity = abs(trade_quantity)

    client_order_id = compute_client_order_id(
        rcp.decision_id, rcp.sizing_id, rcp.risk_id, rcp.security_id, side, quantity, rcp.as_of_time,
    )

    order = ValidatedOrder(
        client_order_id=client_order_id, security_id=rcp.security_id, side=side, quantity=quantity,
        order_type=OrderType.MARKET, as_of_time=rcp.as_of_time,
        decision_id=rcp.decision_id, sizing_id=rcp.sizing_id, risk_assessment_id=rcp.risk_id,
        configuration_version=configuration_version, provenance=rcp.provenance, experiment_id=rcp.experiment_id,
    )
    return OrderValidationResult(status=OrderValidationStatus.ACCEPTED, validated_order=order, reason="ok", checks=checks)
