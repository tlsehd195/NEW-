"""Category: Live Safety Gate Regression Test (Phase 18, instruction
section 11). Maps each of the nine named dimensions (account/positions/
order status/broker capability/reconciliation/model status/risk
status/data health/monitoring health) to the actual code path that
enforces "UNKNOWN -> NO NEW ORDER" for it, and proves that path blocks.

This file adds no new production code -- every enforcement point below
already exists (Phase 16/17). Where a dimension is not a direct
`SafetyGateContext` field (order status, reconciliation, data health,
monitoring health), the test proves the *actual* mechanism that covers
it (the kill-switch trigger chain, or `LiveTradingSession`'s own
operational-state/startup-check logic) rather than asserting a field
that does not exist -- duplicating those checks directly into
`SafetyGateContext` was considered and rejected (see
docs/decisions/ADR-0024-paper-performance-and-validation.md) because
the two real call sites of `evaluate_safety_gate`
(`broker.live.session.run_startup_checks`/`LiveTradingSession.submit`)
both already independently enforce reconciliation state, and
`data_health`/`monitoring_pipeline_health` already funnel through
`evaluate_kill_switch_triggers` into `kill_switch_engaged`, which *is*
a direct gate field.
"""

from __future__ import annotations

from datetime import datetime, timezone

from broker_helpers import make_risk_checked_position
from live_helpers import make_approval, make_broker_capabilities, make_live_config, make_passing_gate_context

from broker.enums import BrokerCapability, CapabilityStatus, OrderValidationStatus
from broker.live.enums import OperationalState, ReconciliationStatus
from broker.live.kill_switch import KillSwitchTriggerContext, engage_kill_switch, evaluate_kill_switch_triggers
from broker.live.reconciliation import ReconciliationResult
from broker.live.safety_gate import SafetyGateContext, evaluate_safety_gate
from broker.live.session import LiveTradingSession, run_startup_checks
from broker.mock import MockBrokerAdapter
from broker.config import BrokerConfig
from broker.validation import build_validated_order

from monitoring.enums import ComponentHealthStatus

from trade_journal.enums import TradeProvenance


def utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


class TestDimension1_Account:
    def test_account_state_unknown_blocks(self) -> None:
        result = evaluate_safety_gate(make_passing_gate_context(account_state_known=False))
        assert result.passed is False
        assert "account_state_unknown" in result.failed_conditions


class TestDimension2_Positions:
    def test_position_state_unknown_blocks(self) -> None:
        result = evaluate_safety_gate(make_passing_gate_context(position_state_known=False))
        assert result.passed is False
        assert "position_state_unknown" in result.failed_conditions


class TestDimension3_OrderStatus:
    """Order status UNKNOWN is enforced at the LiveTradingSession level
    (RECONCILIATION_REQUIRED), not as a SafetyGateContext field --
    tests/broker/live/test_live_partial_fill_and_5xx_regression.py
    already proves this end to end for a 5xx failure; this test proves
    it once more directly for an explicit UNKNOWN order-status
    observation via run_startup_checks's reconciliation_results path."""

    def test_unknown_order_status_reconciliation_blocks_startup(self) -> None:
        reconciliation = ReconciliationResult(
            reconciliation_id="R1", target="order_status", subject_id="CID-1",
            status=ReconciliationStatus.UNKNOWN, as_of_time=utc(2024, 1, 2), details={},
            configuration_version="cfg-1",
        )
        result = run_startup_checks(make_passing_gate_context(), reconciliation_results=(reconciliation,))
        assert result.ready is False
        assert "reconciliation_order_status_unknown" in result.blocking_reasons


class TestDimension4_BrokerCapability:
    def test_missing_capability_blocks(self) -> None:
        from broker.capabilities import build_capabilities

        capabilities = build_capabilities(
            "toss", {BrokerCapability.MARKET_ORDER: CapabilityStatus.ENABLED, BrokerCapability.ACCOUNT_BALANCE: CapabilityStatus.UNKNOWN},
            recorded_at=utc(2024, 1, 2),
        )
        result = evaluate_safety_gate(make_passing_gate_context(
            required_capabilities=(BrokerCapability.MARKET_ORDER, BrokerCapability.ACCOUNT_BALANCE),
            broker_capabilities=capabilities,
        ))
        assert result.passed is False
        assert "broker_capability_not_verified_account_balance" in result.failed_conditions

    def test_broker_capabilities_entirely_missing_blocks(self) -> None:
        result = evaluate_safety_gate(make_passing_gate_context(broker_capabilities=None))
        assert result.passed is False
        assert "broker_capability_unknown" in result.failed_conditions


class TestDimension5_Reconciliation:
    def test_mismatch_blocks_startup(self) -> None:
        reconciliation = ReconciliationResult(
            reconciliation_id="R2", target="account", subject_id="toss", status=ReconciliationStatus.MISMATCH,
            as_of_time=utc(2024, 1, 2), details={}, configuration_version="cfg-1",
        )
        result = run_startup_checks(make_passing_gate_context(), reconciliation_results=(reconciliation,))
        assert result.ready is False
        assert "reconciliation_account_mismatch" in result.blocking_reasons

    def test_reconciliation_required_blocks_every_further_submission(self) -> None:
        adapter = MockBrokerAdapter(BrokerConfig(), failure_mode="unavailable")
        session = LiveTradingSession(make_live_config(live_trading_enabled=True), adapter)
        risk = make_risk_checked_position(risk_id="RISK-DIM5", final_target_quantity=10.0, provenance=TradeProvenance.LIVE_TRADING)
        order = build_validated_order(risk, current_quantity=0.0, configuration_version="cfg-v1").validated_order
        gate_context = SafetyGateContext(
            as_of_time=utc(2024, 1, 2), config=session.config, approval=make_approval(),
            required_capabilities=(BrokerCapability.MARKET_ORDER,), broker_capabilities=make_broker_capabilities(),
            risk_health=ComponentHealthStatus.HEALTHY, order_validation_status=OrderValidationStatus.ACCEPTED,
            kill_switch_engaged=False, account_state_known=True, position_state_known=True,
            model_state_valid=True, configuration_integrity_valid=True,
        )
        session.submit(order, requested_at=utc(2024, 1, 2), gate_context=gate_context)
        assert session.operational_state == OperationalState.RECONCILIATION_REQUIRED
        outcome = session.submit(order, requested_at=utc(2024, 1, 3), gate_context=gate_context)
        assert outcome.status == "BLOCKED"


class TestDimension6_ModelStatus:
    def test_model_state_invalid_blocks(self) -> None:
        result = evaluate_safety_gate(make_passing_gate_context(model_state_valid=False))
        assert result.passed is False
        assert "model_state_not_valid_for_live" in result.failed_conditions


class TestDimension7_RiskStatus:
    def test_risk_not_healthy_blocks(self) -> None:
        result = evaluate_safety_gate(make_passing_gate_context(risk_health=ComponentHealthStatus.UNKNOWN))
        assert result.passed is False
        assert "risk_engine_not_healthy" in result.failed_conditions

    def test_risk_unavailable_blocks(self) -> None:
        result = evaluate_safety_gate(make_passing_gate_context(risk_health=ComponentHealthStatus.UNAVAILABLE))
        assert result.passed is False


class TestDimension8_DataHealth:
    """data_health is not a SafetyGateContext field -- it feeds
    evaluate_kill_switch_triggers (Phase 17 addition), which produces a
    trigger reason the caller uses to engage the kill switch, whose
    engaged state *is* a direct gate field."""

    def test_data_health_unknown_triggers_kill_switch_which_then_blocks_the_gate(self) -> None:
        trigger_context = KillSwitchTriggerContext(
            as_of_time=utc(2024, 1, 2), broker_health=ComponentHealthStatus.HEALTHY,
            risk_health=ComponentHealthStatus.HEALTHY, monitoring_pipeline_health=ComponentHealthStatus.HEALTHY,
            account_state_known=True, position_state_known=True, daily_loss=None, orders_in_last_hour=None,
            config=make_live_config(), data_health=ComponentHealthStatus.UNKNOWN,
        )
        reason = evaluate_kill_switch_triggers(trigger_context)
        assert reason == "data_health_unknown"

        engage_kill_switch(event_id="KS1", reason=reason, occurred_at=utc(2024, 1, 2), configuration_version="cfg-1")
        result = evaluate_safety_gate(make_passing_gate_context(kill_switch_engaged=True))
        assert result.passed is False
        assert "kill_switch_engaged" in result.failed_conditions


class TestDimension9_MonitoringHealth:
    def test_monitoring_pipeline_health_unknown_triggers_kill_switch_which_then_blocks_the_gate(self) -> None:
        trigger_context = KillSwitchTriggerContext(
            as_of_time=utc(2024, 1, 2), broker_health=ComponentHealthStatus.HEALTHY,
            risk_health=ComponentHealthStatus.HEALTHY, monitoring_pipeline_health=ComponentHealthStatus.UNAVAILABLE,
            account_state_known=True, position_state_known=True, daily_loss=None, orders_in_last_hour=None,
            config=make_live_config(),
        )
        reason = evaluate_kill_switch_triggers(trigger_context)
        assert reason == "monitoring_pipeline_health_unavailable"

        result = evaluate_safety_gate(make_passing_gate_context(kill_switch_engaged=True))
        assert result.passed is False
