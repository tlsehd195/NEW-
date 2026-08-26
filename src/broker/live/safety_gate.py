"""evaluate_safety_gate: the single function that decides whether a
Live order submission may proceed. Every condition is independently
sourced and independently required -- a pure function over an
already-assembled `SafetyGateContext`, performing no I/O, no broker
call, no database query itself (mirrors `monitoring.health.evaluate_*`/
`broker.validation.build_validated_order`'s own pure-evaluator design).

See docs/specifications/PHASE-16-live-trading.md section 5, 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from broker.enums import BrokerCapability, OrderValidationStatus
from broker.live.approval import LiveActivationApproval
from broker.live.config import LiveTradingConfig
from broker.models import BrokerCapabilities

from monitoring.enums import ComponentHealthStatus


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


@dataclass(frozen=True)
class SafetyGateContext:
    """Every input the gate needs. No field here is an order/quantity/
    price of its own -- this is a verdict-input bundle, not a trading
    object."""

    as_of_time: datetime
    config: LiveTradingConfig
    approval: Optional[LiveActivationApproval]
    required_capabilities: tuple[BrokerCapability, ...]
    broker_capabilities: Optional[BrokerCapabilities]
    risk_health: Optional[ComponentHealthStatus]
    order_validation_status: Optional[OrderValidationStatus]
    kill_switch_engaged: bool
    account_state_known: bool
    position_state_known: bool
    model_state_valid: bool
    configuration_integrity_valid: bool

    def __post_init__(self) -> None:
        _require_aware("SafetyGateContext.as_of_time", self.as_of_time)


@dataclass(frozen=True)
class SafetyGateResult:
    """Never carries an order-shaped field of its own -- a pass/fail
    verdict plus factual reasons, nothing else
    (`tests/broker/live/test_live_boundary.py`)."""

    passed: bool
    failed_conditions: tuple[str, ...]
    evaluated_at: datetime
    configuration_version: str

    def __post_init__(self) -> None:
        if self.passed and self.failed_conditions:
            raise ValueError("SafetyGateResult.passed=True must not carry any failed_conditions")
        if not self.passed and not self.failed_conditions:
            raise ValueError("SafetyGateResult.passed=False requires at least one failed_condition")
        _require_aware("SafetyGateResult.evaluated_at", self.evaluated_at)


def evaluate_safety_gate(context: SafetyGateContext) -> SafetyGateResult:
    failed: list[str] = []

    if context.config.environment != "live":
        failed.append("environment_not_live")
    if not context.config.live_trading_enabled:
        failed.append("live_trading_not_enabled")
    if context.approval is None or not context.approval.is_valid():
        failed.append("activation_approval_missing_or_invalid")

    if context.broker_capabilities is None:
        failed.append("broker_capability_unknown")
    else:
        for capability in context.required_capabilities:
            if not context.broker_capabilities.is_enabled(capability):
                failed.append(f"broker_capability_not_verified_{capability.value.lower()}")

    if context.risk_health != ComponentHealthStatus.HEALTHY:
        failed.append("risk_engine_not_healthy")
    if context.order_validation_status != OrderValidationStatus.ACCEPTED:
        failed.append("order_validator_not_accepted")
    if context.kill_switch_engaged:
        failed.append("kill_switch_engaged")
    if not context.account_state_known:
        failed.append("account_state_unknown")
    if not context.position_state_known:
        failed.append("position_state_unknown")
    if not context.model_state_valid:
        failed.append("model_state_not_valid_for_live")
    if not context.configuration_integrity_valid:
        failed.append("configuration_integrity_invalid")

    return SafetyGateResult(
        passed=not failed, failed_conditions=tuple(failed), evaluated_at=context.as_of_time,
        configuration_version=context.config.configuration_version(),
    )
