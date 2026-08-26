"""Category: Unit Test -- `LiveTradingConfig` validation."""

from __future__ import annotations

import pytest

from broker.live.config import DEFAULT_LIVE_TRADING_CONFIG, LiveTradingConfig


class TestEnvironmentGuard:
    def test_environment_must_be_live(self) -> None:
        with pytest.raises(ValueError):
            LiveTradingConfig(environment="paper")

    def test_default_environment_is_live(self) -> None:
        assert LiveTradingConfig().environment == "live"


class TestDefaultIsInert:
    def test_default_config_has_live_trading_disabled(self) -> None:
        assert LiveTradingConfig().live_trading_enabled is False

    def test_module_default_constant_is_disabled(self) -> None:
        assert DEFAULT_LIVE_TRADING_CONFIG.live_trading_enabled is False


class TestValidation:
    def test_negative_reconciliation_tolerance_rejected(self) -> None:
        with pytest.raises(ValueError):
            LiveTradingConfig(reconciliation_tolerance=-0.01)

    def test_empty_broker_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            LiveTradingConfig(broker_id="")

    def test_max_daily_loss_must_be_positive_if_set(self) -> None:
        with pytest.raises(ValueError):
            LiveTradingConfig(max_daily_loss=0.0)
        with pytest.raises(ValueError):
            LiveTradingConfig(max_daily_loss=-100.0)

    def test_max_order_frequency_must_be_positive_if_set(self) -> None:
        with pytest.raises(ValueError):
            LiveTradingConfig(max_order_frequency_per_hour=0)

    def test_daily_loss_and_frequency_limits_default_to_unset(self) -> None:
        """No capital/loss policy is invented by this phase -- instruction
        section 22, 53."""
        config = LiveTradingConfig()
        assert config.max_daily_loss is None
        assert config.max_order_frequency_per_hour is None


class TestConfigurationVersion:
    def test_same_fields_produce_same_version(self) -> None:
        c1 = LiveTradingConfig(broker_id="toss")
        c2 = LiveTradingConfig(broker_id="toss")
        assert c1.configuration_version() == c2.configuration_version()

    def test_different_fields_produce_different_version(self) -> None:
        c1 = LiveTradingConfig(live_trading_enabled=False)
        c2 = LiveTradingConfig(live_trading_enabled=True)
        assert c1.configuration_version() != c2.configuration_version()
