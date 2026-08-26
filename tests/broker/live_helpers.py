"""Shared test helpers for the Phase 16 Live Trading test suite."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from broker.enums import BrokerCapability, CapabilityStatus, OrderValidationStatus
from broker.live.approval import REQUIRED_CONFIRMATION_TOKEN, LiveActivationApproval
from broker.live.config import LiveTradingConfig
from broker.live.safety_gate import SafetyGateContext
from broker.models import BrokerCapabilities

from monitoring.enums import ComponentHealthStatus


def utc(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def make_live_config(**overrides) -> LiveTradingConfig:
    return LiveTradingConfig(**overrides)


def make_approval(
    *, approved_by: str = "jane.doe", approved_at: datetime = utc(2024, 1, 2),
    confirmation_token: str = REQUIRED_CONFIRMATION_TOKEN, checklist_completed: bool = True,
) -> LiveActivationApproval:
    return LiveActivationApproval(
        approved_by=approved_by, approved_at=approved_at, confirmation_token=confirmation_token,
        checklist_completed=checklist_completed,
    )


def make_broker_capabilities(
    *, broker_id: str = "mock-broker", recorded_at: datetime = utc(2024, 1, 2),
    overrides: Optional[dict] = None,
) -> BrokerCapabilities:
    capabilities = {
        BrokerCapability.MARKET_ORDER: CapabilityStatus.ENABLED,
        BrokerCapability.CANCEL_ORDER: CapabilityStatus.ENABLED,
        BrokerCapability.ORDER_STATUS: CapabilityStatus.ENABLED,
        BrokerCapability.ACCOUNT_BALANCE: CapabilityStatus.ENABLED,
        BrokerCapability.POSITIONS: CapabilityStatus.ENABLED,
        BrokerCapability.IDEMPOTENT_CLIENT_ORDER_ID: CapabilityStatus.ENABLED,
    }
    capabilities.update(overrides or {})
    return BrokerCapabilities(broker_id=broker_id, capabilities=capabilities, recorded_at=recorded_at)


def make_passing_gate_context(**overrides) -> SafetyGateContext:
    defaults = dict(
        as_of_time=utc(2024, 1, 2),
        config=make_live_config(live_trading_enabled=True),
        approval=make_approval(),
        required_capabilities=(BrokerCapability.MARKET_ORDER,),
        broker_capabilities=make_broker_capabilities(),
        risk_health=ComponentHealthStatus.HEALTHY,
        order_validation_status=OrderValidationStatus.ACCEPTED,
        kill_switch_engaged=False,
        account_state_known=True,
        position_state_known=True,
        model_state_valid=True,
        configuration_integrity_valid=True,
    )
    defaults.update(overrides)
    return SafetyGateContext(**defaults)


__all__ = ["utc", "make_live_config", "make_approval", "make_broker_capabilities", "make_passing_gate_context"]
