"""Category: Unit Test -- `broker.paper.execution.simulate_fill`'s pure
price/cost math, in isolation from the adapter."""

from __future__ import annotations

from paper_helpers import make_bar, utc

from broker.paper.execution import simulate_fill

from backtest.costs import FixedBpsSlippageModel, TransactionCostModel
from backtest.enums import OrderSide


def _models(**overrides):
    cost = TransactionCostModel(fixed_per_trade=1.0, per_share=0.005, spread_bps=2.0)
    slip = FixedBpsSlippageModel(bps=5.0)
    return cost, slip


class TestNoLiquidity:
    def test_zero_volume_bar_produces_no_fill(self) -> None:
        cost, slip = _models()
        bar = make_bar(volume=0.0)
        fill = simulate_fill(
            order_id="CID-1", security_id="AAA", side=OrderSide.BUY, remaining_quantity=10.0, bar=bar,
            cost_model=cost, slippage_model=slip, max_participation=0.10, partial_fill_enabled=True,
            decision_time=utc(2024, 1, 2), execution_time=utc(2024, 1, 2),
        )
        assert fill is None

    def test_zero_remaining_quantity_produces_no_fill(self) -> None:
        cost, slip = _models()
        bar = make_bar(volume=1_000.0)
        fill = simulate_fill(
            order_id="CID-1", security_id="AAA", side=OrderSide.BUY, remaining_quantity=0.0, bar=bar,
            cost_model=cost, slippage_model=slip, max_participation=0.10, partial_fill_enabled=True,
            decision_time=utc(2024, 1, 2), execution_time=utc(2024, 1, 2),
        )
        assert fill is None


class TestParticipationCap:
    def test_fill_capped_at_max_participation_of_bar_volume(self) -> None:
        cost, slip = _models()
        bar = make_bar(volume=1_000.0)
        fill = simulate_fill(
            order_id="CID-1", security_id="AAA", side=OrderSide.BUY, remaining_quantity=500.0, bar=bar,
            cost_model=cost, slippage_model=slip, max_participation=0.10, partial_fill_enabled=True,
            decision_time=utc(2024, 1, 2), execution_time=utc(2024, 1, 2),
        )
        assert fill is not None
        assert fill.quantity == 100.0

    def test_full_fill_when_remaining_below_cap(self) -> None:
        cost, slip = _models()
        bar = make_bar(volume=1_000.0)
        fill = simulate_fill(
            order_id="CID-1", security_id="AAA", side=OrderSide.BUY, remaining_quantity=50.0, bar=bar,
            cost_model=cost, slippage_model=slip, max_participation=0.10, partial_fill_enabled=True,
            decision_time=utc(2024, 1, 2), execution_time=utc(2024, 1, 2),
        )
        assert fill is not None
        assert fill.quantity == 50.0


class TestPartialFillDisabled:
    def test_all_or_nothing_never_fills_below_full_liquidity(self) -> None:
        cost, slip = _models()
        bar = make_bar(volume=1_000.0)
        fill = simulate_fill(
            order_id="CID-1", security_id="AAA", side=OrderSide.BUY, remaining_quantity=500.0, bar=bar,
            cost_model=cost, slippage_model=slip, max_participation=0.10, partial_fill_enabled=False,
            decision_time=utc(2024, 1, 2), execution_time=utc(2024, 1, 2),
        )
        assert fill is None

    def test_all_or_nothing_fills_when_liquidity_sufficient(self) -> None:
        cost, slip = _models()
        bar = make_bar(volume=1_000.0)
        fill = simulate_fill(
            order_id="CID-1", security_id="AAA", side=OrderSide.BUY, remaining_quantity=50.0, bar=bar,
            cost_model=cost, slippage_model=slip, max_participation=0.10, partial_fill_enabled=False,
            decision_time=utc(2024, 1, 2), execution_time=utc(2024, 1, 2),
        )
        assert fill is not None
        assert fill.quantity == 50.0


class TestCostBreakdown:
    def test_spread_and_slippage_costs_are_computed_against_reference_price(self) -> None:
        cost, slip = _models()
        bar = make_bar(volume=1_000.0, close=100.0)
        fill = simulate_fill(
            order_id="CID-1", security_id="AAA", side=OrderSide.BUY, remaining_quantity=10.0, bar=bar,
            cost_model=cost, slippage_model=slip, max_participation=1.0, partial_fill_enabled=True,
            decision_time=utc(2024, 1, 2), execution_time=utc(2024, 1, 2),
        )
        assert fill.reference_price == 100.0
        assert fill.commission == cost.commission(10.0)
        assert fill.spread_cost > 0
        assert fill.slippage_cost > 0
        assert fill.price > fill.reference_price  # BUY: spread + slippage both push price up

    def test_data_version_copied_from_bar_provenance(self) -> None:
        cost, slip = _models()
        bar = make_bar(volume=1_000.0)
        fill = simulate_fill(
            order_id="CID-1", security_id="AAA", side=OrderSide.BUY, remaining_quantity=10.0, bar=bar,
            cost_model=cost, slippage_model=slip, max_participation=1.0, partial_fill_enabled=True,
            decision_time=utc(2024, 1, 2), execution_time=utc(2024, 1, 2),
        )
        assert fill.data_version == bar.provenance.data_version
