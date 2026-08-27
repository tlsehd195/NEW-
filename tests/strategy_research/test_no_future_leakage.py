"""Category: No-future-leakage test (instruction sections 20, 35-I).

Proves each new strategy candidate's signal at a given `as_of_time` is
identical whether or not the underlying repository happens to also hold
bars dated AFTER `as_of_time` -- if a strategy were reading future data
(directly or through a bug in its own lookback math), adding future rows
to the repository would change its past decisions. It must not."""

from __future__ import annotations

from datetime import date

from research_helpers import days_to_utc, synthetic_multi_year_repository

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock
from backtest.portfolio import PortfolioAccounting

from strategy_research.long_term_momentum import LongTermMomentumStrategy
from strategy_research.risk_controlled_momentum import RiskControlledMomentumStrategy
from strategy_research.trend_volatility import TrendVolatilityStrategy


def _signal_at(repo, strategy_factory, as_of, universe):
    clock = BacktestClock((as_of,))
    clock.index = 0
    data_view = AsOfDataView(repo, clock)
    portfolio = PortfolioAccounting(100_000.0)
    strategy = strategy_factory()
    intents = strategy.generate_orders(as_of, data_view, portfolio.snapshot_view(as_of))
    return sorted((i.security_id, i.side.value, i.quantity) for i in intents)


class TestNoFutureLeakage:
    def test_long_term_momentum_signal_unchanged_by_future_data(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        as_of = date(2021, 6, 1)
        repo_short = synthetic_multi_year_repository(date(2020, 1, 2), as_of, symbols=universe)
        repo_long = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)

        signal_short = _signal_at(repo_short, lambda: LongTermMomentumStrategy(list(universe)), days_to_utc(as_of), universe)
        signal_long = _signal_at(repo_long, lambda: LongTermMomentumStrategy(list(universe)), days_to_utc(as_of), universe)
        assert signal_short == signal_long

    def test_trend_volatility_signal_unchanged_by_future_data(self) -> None:
        universe = ("TRENDUP", "FLATHIGH", "CYCLICAL")
        as_of = date(2021, 9, 1)
        repo_short = synthetic_multi_year_repository(date(2020, 1, 2), as_of, symbols=universe)
        repo_long = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)

        signal_short = _signal_at(repo_short, lambda: TrendVolatilityStrategy(list(universe)), days_to_utc(as_of), universe)
        signal_long = _signal_at(repo_long, lambda: TrendVolatilityStrategy(list(universe)), days_to_utc(as_of), universe)
        assert signal_short == signal_long

    def test_risk_controlled_momentum_signal_unchanged_by_future_data(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        as_of = date(2021, 3, 1)
        repo_short = synthetic_multi_year_repository(date(2020, 1, 2), as_of, symbols=universe)
        repo_long = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)

        signal_short = _signal_at(repo_short, lambda: RiskControlledMomentumStrategy(list(universe)), days_to_utc(as_of), universe)
        signal_long = _signal_at(repo_long, lambda: RiskControlledMomentumStrategy(list(universe)), days_to_utc(as_of), universe)
        assert signal_short == signal_long
