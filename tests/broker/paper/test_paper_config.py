"""Category: Unit Test -- `PaperTradingConfig` validation."""

from __future__ import annotations

import pytest

from broker.paper.config import PaperTradingConfig


class TestEnvironmentGuard:
    def test_environment_must_be_paper(self) -> None:
        with pytest.raises(ValueError):
            PaperTradingConfig(environment="live")

    def test_default_environment_is_paper(self) -> None:
        assert PaperTradingConfig().environment == "paper"


class TestValidation:
    def test_negative_initial_cash_rejected(self) -> None:
        with pytest.raises(ValueError):
            PaperTradingConfig(initial_cash=-1.0)

    def test_negative_commission_rejected(self) -> None:
        with pytest.raises(ValueError):
            PaperTradingConfig(commission_fixed_per_trade=-1.0)
        with pytest.raises(ValueError):
            PaperTradingConfig(commission_per_share=-1.0)

    def test_negative_spread_or_slippage_bps_rejected(self) -> None:
        with pytest.raises(ValueError):
            PaperTradingConfig(spread_bps=-1.0)
        with pytest.raises(ValueError):
            PaperTradingConfig(slippage_bps=-1.0)

    def test_max_participation_must_be_in_zero_one_range(self) -> None:
        with pytest.raises(ValueError):
            PaperTradingConfig(max_participation=0.0)
        with pytest.raises(ValueError):
            PaperTradingConfig(max_participation=1.5)

    def test_maximum_order_quantity_must_be_positive_if_set(self) -> None:
        with pytest.raises(ValueError):
            PaperTradingConfig(maximum_order_quantity=0.0)
        with pytest.raises(ValueError):
            PaperTradingConfig(maximum_order_quantity=-5.0)

    def test_maximum_notional_must_be_positive_if_set(self) -> None:
        with pytest.raises(ValueError):
            PaperTradingConfig(maximum_notional=0.0)

    def test_unknown_failure_mode_rejected(self) -> None:
        with pytest.raises(ValueError):
            PaperTradingConfig(failure_mode="not_a_real_mode")

    def test_zero_slippage_and_zero_commission_are_explicit_overrides(self) -> None:
        """A zero-cost config must be reachable, but only explicitly --
        never the silent fallback (mirrors ADR-0007's Phase 2
        precedent)."""
        config = PaperTradingConfig(
            commission_fixed_per_trade=0.0, commission_per_share=0.0, spread_bps=0.0, slippage_bps=0.0,
        )
        assert config.transaction_cost_model().commission(10.0) == 0.0


class TestConfigurationVersion:
    def test_same_fields_produce_same_version(self) -> None:
        c1 = PaperTradingConfig(initial_cash=500_000.0)
        c2 = PaperTradingConfig(initial_cash=500_000.0)
        assert c1.configuration_version() == c2.configuration_version()

    def test_different_fields_produce_different_version(self) -> None:
        c1 = PaperTradingConfig(initial_cash=500_000.0)
        c2 = PaperTradingConfig(initial_cash=600_000.0)
        assert c1.configuration_version() != c2.configuration_version()
