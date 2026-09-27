"""`backtest.strategy.new_position_cash` (ADR-0219): new positions of an
equal-weight rebalance are sized with this rebalance's own sell proceeds
and capped at an equal share of the portfolio."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from backtest.portfolio import PortfolioView, PositionView
from backtest.strategy import new_position_cash

NOW = datetime(2019, 4, 12, 20, tzinfo=timezone.utc)


class _Data:
    def __init__(self, closes):
        self._closes = closes

    def get_bars(self, security_id, start, end):
        close = self._closes.get(security_id)
        return [SimpleNamespace(close=close)] if close is not None else []


def _portfolio(cash, positions, value):
    return PortfolioView(
        as_of_time=NOW, cash=cash,
        positions={sid: PositionView(sid, qty, 0.0) for sid, qty in positions.items()}, portfolio_value=value,
    )


def test_sell_proceeds_of_the_same_rebalance_fund_the_new_buys() -> None:
    """Old behavior: $1,000 cash / 2 buys = $490 each, leaving the
    $4,000 from selling A idle until the next rebalance."""
    portfolio = _portfolio(1_000.0, {"A": 40.0, "B": 50.0}, 10_000.0)  # A 40 x $100, B 50 x $100
    cash = new_position_cash(portfolio, _Data({"A": 100.0, "B": 100.0}), NOW, {"B", "C", "D"}, 2, 0.02)
    assert cash == min(5_000.0 * 0.98 / 2, 10_000.0 * 0.98 / 3)


def test_accumulated_cash_is_capped_at_an_equal_share_of_the_portfolio() -> None:
    """The real sloan_accruals case: idle cash from an earlier rebalance
    must not pour into one or two new names."""
    portfolio = _portfolio(6_900.0, {"B": 31.0}, 10_000.0)
    cash = new_position_cash(portfolio, _Data({"B": 100.0}), NOW, {"B", "C", "D", "E", "F", "G", "H", "I", "J", "K"}, 2, 0.02)
    assert cash == 10_000.0 * 0.98 / 10


def test_a_sold_name_without_a_price_contributes_nothing() -> None:
    portfolio = _portfolio(1_000.0, {"A": 40.0}, 5_000.0)
    assert new_position_cash(portfolio, _Data({}), NOW, {"C"}, 1, 0.0) == 1_000.0
