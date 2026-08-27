"""Category: Safety Test -- every one of `evaluate_safety_gate`'s eleven
conditions independently blocks submission; all conditions together
pass. This is the single most safety-critical test file in Phase 16."""

from __future__ import annotations

from live_helpers import make_broker_capabilities, make_live_config, make_passing_gate_context, utc

from broker.enums import BrokerCapability, CapabilityStatus, OrderValidationStatus
from broker.live.safety_gate import evaluate_safety_gate

from monitoring.enums import ComponentHealthStatus


class TestFullyPassingContext:
    def test_all_conditions_satisfied_passes(self) -> None:
        result = evaluate_safety_gate(make_passing_gate_context())
        assert result.passed is True
        assert result.failed_conditions == ()


class TestEachConditionIndependentlyBlocks:
    def test_environment_is_structurally_always_live(self) -> None:
        """`LiveTradingConfig` cannot represent a non-"live" environment
        at all (`test_live_config.py::TestEnvironmentGuard`) -- so
        `evaluate_safety_gate`'s `environment_not_live` branch can never
        actually fire through a real `LiveTradingConfig`. This test just
        confirms the gate context always carries `environment == "live"`
        by construction."""
        ctx = make_passing_gate_context()
        assert ctx.config.environment == "live"
        result = evaluate_safety_gate(ctx)
        assert "environment_not_live" not in result.failed_conditions

    def test_live_trading_not_enabled(self) -> None:
        ctx = make_passing_gate_context(config=make_live_config(live_trading_enabled=False))
        result = evaluate_safety_gate(ctx)
        assert result.passed is False
        assert "live_trading_not_enabled" in result.failed_conditions

    def test_missing_approval(self) -> None:
        ctx = make_passing_gate_context(approval=None)
        result = evaluate_safety_gate(ctx)
        assert result.passed is False
        assert "activation_approval_missing_or_invalid" in result.failed_conditions

    def test_broker_capability_unknown_source(self) -> None:
        ctx = make_passing_gate_context(broker_capabilities=None)
        result = evaluate_safety_gate(ctx)
        assert result.passed is False
        assert "broker_capability_unknown" in result.failed_conditions

    def test_required_capability_not_enabled(self) -> None:
        caps = make_broker_capabilities(overrides={BrokerCapability.ACCOUNT_BALANCE: CapabilityStatus.UNKNOWN})
        ctx = make_passing_gate_context(
            required_capabilities=(BrokerCapability.MARKET_ORDER, BrokerCapability.ACCOUNT_BALANCE),
            broker_capabilities=caps,
        )
        result = evaluate_safety_gate(ctx)
        assert result.passed is False
        assert "broker_capability_not_verified_account_balance" in result.failed_conditions

    def test_risk_engine_not_healthy(self) -> None:
        for status in (ComponentHealthStatus.DEGRADED, ComponentHealthStatus.UNAVAILABLE, ComponentHealthStatus.UNKNOWN, None):
            ctx = make_passing_gate_context(risk_health=status)
            result = evaluate_safety_gate(ctx)
            assert result.passed is False
            assert "risk_engine_not_healthy" in result.failed_conditions

    def test_order_validator_not_accepted(self) -> None:
        ctx = make_passing_gate_context(order_validation_status=OrderValidationStatus.VALIDATION_REJECTED)
        result = evaluate_safety_gate(ctx)
        assert result.passed is False
        assert "order_validator_not_accepted" in result.failed_conditions

    def test_kill_switch_engaged(self) -> None:
        ctx = make_passing_gate_context(kill_switch_engaged=True)
        result = evaluate_safety_gate(ctx)
        assert result.passed is False
        assert "kill_switch_engaged" in result.failed_conditions

    def test_account_state_unknown(self) -> None:
        ctx = make_passing_gate_context(account_state_known=False)
        result = evaluate_safety_gate(ctx)
        assert result.passed is False
        assert "account_state_unknown" in result.failed_conditions

    def test_position_state_unknown(self) -> None:
        ctx = make_passing_gate_context(position_state_known=False)
        result = evaluate_safety_gate(ctx)
        assert result.passed is False
        assert "position_state_unknown" in result.failed_conditions

    def test_model_state_not_valid(self) -> None:
        ctx = make_passing_gate_context(model_state_valid=False)
        result = evaluate_safety_gate(ctx)
        assert result.passed is False
        assert "model_state_not_valid_for_live" in result.failed_conditions

    def test_configuration_integrity_invalid(self) -> None:
        ctx = make_passing_gate_context(configuration_integrity_valid=False)
        result = evaluate_safety_gate(ctx)
        assert result.passed is False
        assert "configuration_integrity_invalid" in result.failed_conditions


class TestRiskLimitNoneSemanticsOptionB:
    """Phase 22: LIVE-RISK-POLICY.md's long-open "None means not
    enforced vs. structurally blocks Live" DECISION REQUIRED is now
    resolved as Option B for the two risk limits the gate has direct
    visibility into. An unset max_daily_loss/max_order_frequency_per_hour
    is itself a fail-closed condition -- not merely "no automatic
    circuit breaker," as it was through Phase 21."""

    def test_max_daily_loss_none_blocks(self) -> None:
        ctx = make_passing_gate_context(config=make_live_config(live_trading_enabled=True, max_daily_loss=None, max_order_frequency_per_hour=6))
        result = evaluate_safety_gate(ctx)
        assert result.passed is False
        assert "risk_limit_not_configured_max_daily_loss" in result.failed_conditions

    def test_max_order_frequency_per_hour_none_blocks(self) -> None:
        ctx = make_passing_gate_context(config=make_live_config(live_trading_enabled=True, max_daily_loss=2000.0, max_order_frequency_per_hour=None))
        result = evaluate_safety_gate(ctx)
        assert result.passed is False
        assert "risk_limit_not_configured_max_order_frequency_per_hour" in result.failed_conditions

    def test_both_none_reports_both_reasons(self) -> None:
        ctx = make_passing_gate_context(config=make_live_config(live_trading_enabled=True, max_daily_loss=None, max_order_frequency_per_hour=None))
        result = evaluate_safety_gate(ctx)
        assert result.passed is False
        assert "risk_limit_not_configured_max_daily_loss" in result.failed_conditions
        assert "risk_limit_not_configured_max_order_frequency_per_hour" in result.failed_conditions

    def test_both_set_does_not_block_on_this_condition(self) -> None:
        ctx = make_passing_gate_context(config=make_live_config(live_trading_enabled=True, max_daily_loss=2000.0, max_order_frequency_per_hour=6))
        result = evaluate_safety_gate(ctx)
        assert "risk_limit_not_configured_max_daily_loss" not in result.failed_conditions
        assert "risk_limit_not_configured_max_order_frequency_per_hour" not in result.failed_conditions
        assert result.passed is True

    def test_default_live_trading_config_is_none_by_default_and_therefore_blocks(self) -> None:
        """LiveTradingConfig's own class-level default for both fields
        stays None (Phase 22 does not invent a capital-dependent
        absolute daily-loss figure -- see LIVE-RISK-POLICY.md), so a
        caller that forgets to configure these explicitly is correctly
        blocked, not silently permitted."""
        ctx = make_passing_gate_context(config=make_live_config(live_trading_enabled=True))
        result = evaluate_safety_gate(ctx)
        assert result.passed is False
        assert "risk_limit_not_configured_max_daily_loss" in result.failed_conditions
        assert "risk_limit_not_configured_max_order_frequency_per_hour" in result.failed_conditions


class TestMultipleFailuresAllReported:
    def test_all_conditions_failing_reports_all_reasons(self) -> None:
        ctx = make_passing_gate_context(
            config=make_live_config(live_trading_enabled=False), approval=None, broker_capabilities=None,
            risk_health=None, order_validation_status=None, kill_switch_engaged=True,
            account_state_known=False, position_state_known=False, model_state_valid=False,
            configuration_integrity_valid=False,
        )
        result = evaluate_safety_gate(ctx)
        assert result.passed is False
        assert len(result.failed_conditions) >= 10


class TestRealTossCapabilitiesStructurallyBlockLiveTrading:
    def test_toss_unconfirmed_capabilities_block_the_gate(self) -> None:
        """Direct proof of ADR-0022 decision 2: even with every other
        condition satisfied, `TossBrokerAdapter`'s real, honestly-
        reported capability set (Phase 13) blocks the gate."""
        from broker.capabilities import build_capabilities

        toss_capabilities = build_capabilities(
            "toss",
            {
                BrokerCapability.MARKET_ORDER: CapabilityStatus.ENABLED,
                BrokerCapability.LIMIT_ORDER: CapabilityStatus.ENABLED,
                BrokerCapability.IDEMPOTENT_CLIENT_ORDER_ID: CapabilityStatus.ENABLED,
                BrokerCapability.CANCEL_ORDER: CapabilityStatus.UNKNOWN,
                BrokerCapability.ORDER_STATUS: CapabilityStatus.UNKNOWN,
                BrokerCapability.ACCOUNT_BALANCE: CapabilityStatus.UNKNOWN,
                BrokerCapability.POSITIONS: CapabilityStatus.UNKNOWN,
                BrokerCapability.QUOTE: CapabilityStatus.UNKNOWN,
            },
            recorded_at=utc(2024, 1, 2),
        )
        ctx = make_passing_gate_context(
            broker_capabilities=toss_capabilities,
            required_capabilities=(BrokerCapability.MARKET_ORDER, BrokerCapability.ACCOUNT_BALANCE, BrokerCapability.POSITIONS),
        )
        result = evaluate_safety_gate(ctx)
        assert result.passed is False
        assert "broker_capability_not_verified_account_balance" in result.failed_conditions
        assert "broker_capability_not_verified_positions" in result.failed_conditions


class TestResultShape:
    def test_passed_result_has_no_failed_conditions(self) -> None:
        result = evaluate_safety_gate(make_passing_gate_context())
        assert result.passed is True and result.failed_conditions == ()

    def test_failed_result_requires_at_least_one_reason(self) -> None:
        import pytest

        from broker.live.safety_gate import SafetyGateResult

        with pytest.raises(ValueError):
            SafetyGateResult(passed=False, failed_conditions=(), evaluated_at=utc(2024, 1, 2), configuration_version="cfg-1")

    def test_passed_result_cannot_carry_failed_conditions(self) -> None:
        import pytest

        from broker.live.safety_gate import SafetyGateResult

        with pytest.raises(ValueError):
            SafetyGateResult(passed=True, failed_conditions=("x",), evaluated_at=utc(2024, 1, 2), configuration_version="cfg-1")
