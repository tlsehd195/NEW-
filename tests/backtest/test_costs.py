"""Category: Transaction cost test.
Category: Slippage test.

See docs/specifications/PHASE-2-backtesting.md section 7 and ADR-0007.
"""

from __future__ import annotations

import pytest

from backtest.costs import FixedBpsSlippageModel, TransactionCostModel, VolumeScaledSlippageModel
from backtest.enums import OrderSide


class TestTransactionCostModel:
    def test_commission_is_fixed_plus_per_share(self) -> None:
        model = TransactionCostModel(fixed_per_trade=1.5, per_share=0.01, spread_bps=0.0)
        assert model.commission(100) == pytest.approx(1.5 + 0.01 * 100)

    def test_commission_zero_for_zero_quantity(self) -> None:
        model = TransactionCostModel(fixed_per_trade=1.5, per_share=0.01)
        assert model.commission(0) == 0.0

    def test_spread_moves_buy_price_up(self) -> None:
        model = TransactionCostModel(spread_bps=10.0)  # 10 bps full spread -> 5 bps half-spread
        adjusted = model.apply_spread(100.0, OrderSide.BUY)
        expected = 100.0 * (1 + 0.0005)
        assert adjusted == pytest.approx(expected)
        assert adjusted > 100.0

    def test_spread_moves_sell_price_down(self) -> None:
        model = TransactionCostModel(spread_bps=10.0)
        adjusted = model.apply_spread(100.0, OrderSide.SELL)
        expected = 100.0 * (1 - 0.0005)
        assert adjusted == pytest.approx(expected)
        assert adjusted < 100.0

    def test_zero_spread_leaves_price_unchanged(self) -> None:
        model = TransactionCostModel(spread_bps=0.0)
        assert model.apply_spread(100.0, OrderSide.BUY) == 100.0
        assert model.apply_spread(100.0, OrderSide.SELL) == 100.0


class TestSlippageModels:
    def test_fixed_bps_slippage_moves_buy_price_up(self) -> None:
        model = FixedBpsSlippageModel(bps=20.0)
        adjusted = model.adjust(100.0, quantity=10, side=OrderSide.BUY, bar_volume=100_000)
        assert adjusted == pytest.approx(100.0 * 1.002)

    def test_fixed_bps_slippage_moves_sell_price_down(self) -> None:
        model = FixedBpsSlippageModel(bps=20.0)
        adjusted = model.adjust(100.0, quantity=10, side=OrderSide.SELL, bar_volume=100_000)
        assert adjusted == pytest.approx(100.0 * 0.998)

    def test_volume_scaled_slippage_grows_with_participation(self) -> None:
        model = VolumeScaledSlippageModel(base_bps=5.0, impact_coefficient_bps=1000.0)
        small_order = model.adjust(100.0, quantity=100, side=OrderSide.BUY, bar_volume=100_000)  # 0.1% participation
        large_order = model.adjust(100.0, quantity=10_000, side=OrderSide.BUY, bar_volume=100_000)  # 10% participation
        assert large_order > small_order > 100.0

    def test_volume_scaled_slippage_matches_hand_computation(self) -> None:
        model = VolumeScaledSlippageModel(base_bps=5.0, impact_coefficient_bps=1000.0)
        # participation = 1000/100000 = 1% -> total_bps = 5 + 1000*0.01 = 15 bps
        adjusted = model.adjust(100.0, quantity=1_000, side=OrderSide.BUY, bar_volume=100_000)
        assert adjusted == pytest.approx(100.0 * (1 + 15.0 / 10_000))

    def test_zero_bar_volume_does_not_crash_and_uses_base_only(self) -> None:
        model = VolumeScaledSlippageModel(base_bps=5.0, impact_coefficient_bps=1000.0)
        adjusted = model.adjust(100.0, quantity=100, side=OrderSide.BUY, bar_volume=0)
        assert adjusted == pytest.approx(100.0 * (1 + 5.0 / 10_000))

    def test_slippage_never_favors_the_trader(self) -> None:
        for side in (OrderSide.BUY, OrderSide.SELL):
            fixed = FixedBpsSlippageModel(bps=5.0).adjust(100.0, 10, side, 100_000)
            scaled = VolumeScaledSlippageModel(base_bps=5.0, impact_coefficient_bps=50.0).adjust(
                100.0, 10, side, 100_000
            )
            if side == OrderSide.BUY:
                assert fixed >= 100.0 and scaled >= 100.0
            else:
                assert fixed <= 100.0 and scaled <= 100.0
