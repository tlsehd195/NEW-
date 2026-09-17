"""Category: Unit Test -- `PaperTradingConfig` validation."""

from __future__ import annotations

import pytest

from broker.paper.config import PaperTradingConfig

from backtest.costs import VolumeScaledSlippageModel
from backtest.enums import OrderSide


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

    def test_negative_slippage_impact_coefficient_rejected(self) -> None:
        with pytest.raises(ValueError):
            PaperTradingConfig(slippage_impact_coefficient_bps=-1.0)

    def test_pending_order_ttl_days_must_be_positive_if_set(self) -> None:
        with pytest.raises(ValueError):
            PaperTradingConfig(pending_order_ttl_days=0)
        with pytest.raises(ValueError):
            PaperTradingConfig(pending_order_ttl_days=-5)

    def test_pending_order_ttl_days_defaults_to_disabled(self) -> None:
        assert PaperTradingConfig().pending_order_ttl_days is None

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


class TestSlippageModel:
    """External review (Session 38 continued): `slippage_model()`
    previously hardcoded `FixedBpsSlippageModel`, ignoring
    `backtest.costs.VolumeScaledSlippageModel` entirely -- every fill
    got the same flat slippage regardless of how large a bite it took
    out of that bar's own liquidity."""

    def test_slippage_model_is_volume_scaled_not_flat(self) -> None:
        model = PaperTradingConfig().slippage_model()
        assert isinstance(model, VolumeScaledSlippageModel)

    def test_larger_participation_produces_more_slippage(self) -> None:
        model = PaperTradingConfig().slippage_model()
        small = model.adjust(100.0, quantity=10.0, side=OrderSide.BUY, bar_volume=1_000.0)  # 1% participation
        large = model.adjust(100.0, quantity=500.0, side=OrderSide.BUY, bar_volume=1_000.0)  # 50% participation
        assert large > small > 100.0  # BUY: slippage only ever pushes price up

    def test_slippage_bps_still_sets_the_base_rate_at_zero_participation(self) -> None:
        config = PaperTradingConfig(slippage_bps=20.0, slippage_impact_coefficient_bps=0.0)
        model = config.slippage_model()
        # impact_coefficient_bps=0.0 isolates the base rate: any participation
        # level should now produce exactly the flat 20bps adjustment.
        adjusted = model.adjust(100.0, quantity=500.0, side=OrderSide.BUY, bar_volume=1_000.0)
        assert adjusted == pytest.approx(100.0 * 1.0020)


class TestConfigurationVersion:
    def test_same_fields_produce_same_version(self) -> None:
        c1 = PaperTradingConfig(initial_cash=500_000.0)
        c2 = PaperTradingConfig(initial_cash=500_000.0)
        assert c1.configuration_version() == c2.configuration_version()

    def test_different_fields_produce_different_version(self) -> None:
        c1 = PaperTradingConfig(initial_cash=500_000.0)
        c2 = PaperTradingConfig(initial_cash=600_000.0)
        assert c1.configuration_version() != c2.configuration_version()
