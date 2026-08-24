"""Category: Cash accounting test.
Category: Position accounting test.
Category: PnL test.

See docs/specifications/PHASE-2-backtesting.md section 8.
"""

from __future__ import annotations

import pytest
from backtest_helpers import utc

from backtest.enums import OrderSide
from backtest.fills import Fill
from backtest.portfolio import PortfolioAccounting


def _fill(security_id="AAA", side=OrderSide.BUY, quantity=10.0, price=100.0, commission=1.0,
          spread_cost=0.5, slippage_cost=0.5, decision_day=1, execution_day=2) -> Fill:
    return Fill(
        order_id=f"ORD-{security_id}-{decision_day}-{side.value}",
        security_id=security_id,
        side=side,
        quantity=quantity,
        reference_price=price,
        price=price,
        commission=commission,
        spread_cost=spread_cost,
        slippage_cost=slippage_cost,
        decision_time=utc(2024, 1, decision_day, 20),
        execution_time=utc(2024, 1, execution_day, 20),
        data_version=f"v-{execution_day}",
    )


class TestCashAccounting:
    def test_buy_decreases_cash_by_notional_plus_commission(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        fill = _fill(side=OrderSide.BUY, quantity=10, price=100.0, commission=2.0)
        portfolio.apply_fill(fill)
        assert portfolio.cash == pytest.approx(10_000.0 - (1000.0 + 2.0))

    def test_sell_increases_cash_by_notional_minus_commission(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill(side=OrderSide.BUY, quantity=10, price=100.0, commission=1.0))
        cash_after_buy = portfolio.cash
        portfolio.apply_fill(_fill(side=OrderSide.SELL, quantity=10, price=110.0, commission=1.5))
        assert portfolio.cash == pytest.approx(cash_after_buy + (1100.0 - 1.5))

    def test_dividend_credits_cash_proportional_to_holding(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill(side=OrderSide.BUY, quantity=20, price=50.0, commission=0.0))
        cash_before = portfolio.cash
        portfolio.apply_dividend("AAA", amount_per_share=0.5, as_of_time=utc(2024, 1, 5, 20))
        assert portfolio.cash == pytest.approx(cash_before + 20 * 0.5)
        assert len(portfolio.cash_flows) == 1
        assert portfolio.cash_flows[0].reason == "dividend"

    def test_dividend_on_unheld_security_is_a_no_op(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_dividend("ZZZ", amount_per_share=1.0, as_of_time=utc(2024, 1, 5, 20))
        assert portfolio.cash == 10_000.0
        assert portfolio.cash_flows == []


class TestPositionAccounting:
    def test_buy_creates_position_with_average_cost(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill(side=OrderSide.BUY, quantity=10, price=100.0))
        pos = portfolio.positions["AAA"]
        assert pos.quantity == 10.0
        assert pos.average_cost == pytest.approx(100.0)

    def test_second_buy_updates_weighted_average_cost(self) -> None:
        portfolio = PortfolioAccounting(100_000.0)
        portfolio.apply_fill(_fill(side=OrderSide.BUY, quantity=10, price=100.0, decision_day=1, execution_day=2))
        portfolio.apply_fill(_fill(side=OrderSide.BUY, quantity=10, price=120.0, decision_day=3, execution_day=4))
        pos = portfolio.positions["AAA"]
        assert pos.quantity == 20.0
        assert pos.average_cost == pytest.approx((10 * 100.0 + 10 * 120.0) / 20.0)

    def test_full_sell_removes_position(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill(side=OrderSide.BUY, quantity=10, price=100.0))
        portfolio.apply_fill(_fill(side=OrderSide.SELL, quantity=10, price=110.0, decision_day=3, execution_day=4))
        assert "AAA" not in portfolio.positions

    def test_partial_sell_reduces_quantity_keeps_average_cost(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill(side=OrderSide.BUY, quantity=10, price=100.0))
        portfolio.apply_fill(_fill(side=OrderSide.SELL, quantity=4, price=110.0, decision_day=3, execution_day=4))
        pos = portfolio.positions["AAA"]
        assert pos.quantity == 6.0
        assert pos.average_cost == pytest.approx(100.0)

    def test_split_adjusts_quantity_and_average_cost_without_recording_a_trade(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill(side=OrderSide.BUY, quantity=10, price=100.0))
        portfolio.apply_split("AAA", ratio_multiplier=2.0)  # 2:1 split
        pos = portfolio.positions["AAA"]
        assert pos.quantity == 20.0
        assert pos.average_cost == pytest.approx(50.0)
        assert portfolio.closed_trades == []  # not a trade
        # No mark_to_market call yet in this test, so no valuation history
        # exists; turnover() is defined as 0.0 in that case (portfolio.py).
        # The point being verified: apply_split must not itself add to
        # the trade-notional list turnover() is computed from.
        assert portfolio.turnover() == 0.0

    def test_split_on_unheld_security_is_a_no_op(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_split("ZZZ", ratio_multiplier=2.0)
        assert "ZZZ" not in portfolio.positions


class TestPnl:
    def test_realized_pnl_on_profitable_round_trip(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill(side=OrderSide.BUY, quantity=10, price=100.0, commission=1.0, spread_cost=0, slippage_cost=0))
        portfolio.apply_fill(
            _fill(side=OrderSide.SELL, quantity=10, price=120.0, commission=1.0, spread_cost=0, slippage_cost=0,
                  decision_day=3, execution_day=4)
        )
        # gross = (120-100)*10 = 200; net of the SELL fill's own total_cost (1.0)
        assert portfolio.realized_pnl == pytest.approx(200.0 - 1.0)

    def test_realized_pnl_on_losing_round_trip_is_negative(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill(side=OrderSide.BUY, quantity=10, price=100.0, commission=0, spread_cost=0, slippage_cost=0))
        portfolio.apply_fill(
            _fill(side=OrderSide.SELL, quantity=10, price=90.0, commission=0, spread_cost=0, slippage_cost=0,
                  decision_day=3, execution_day=4)
        )
        assert portfolio.realized_pnl == pytest.approx(-100.0)

    def test_unrealized_pnl_reflects_mark_to_market(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill(side=OrderSide.BUY, quantity=10, price=100.0))
        assert portfolio.unrealized_pnl({"AAA": 115.0}) == pytest.approx(150.0)

    def test_mark_to_market_falls_back_to_average_cost_when_price_missing(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill(side=OrderSide.BUY, quantity=10, price=100.0))
        point, missing = portfolio.mark_to_market({}, utc(2024, 1, 5, 20))
        assert missing == ["AAA"]
        assert point.market_value == pytest.approx(1000.0)  # 10 * average_cost fallback

    def test_closed_trade_record_created_on_sell(self) -> None:
        portfolio = PortfolioAccounting(10_000.0)
        portfolio.apply_fill(_fill(side=OrderSide.BUY, quantity=10, price=100.0))
        portfolio.apply_fill(
            _fill(side=OrderSide.SELL, quantity=10, price=105.0, decision_day=3, execution_day=4)
        )
        assert len(portfolio.closed_trades) == 1
        assert portfolio.closed_trades[0].security_id == "AAA"
