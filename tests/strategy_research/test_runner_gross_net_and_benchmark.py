"""Category: Cost integration + Benchmark comparison + Reproducibility
(instruction sections 22, 23, 34, 35-N/O/S). Uses the existing, unmodified
`backtest.costs.ZERO_*`/`DEFAULT_*` models and `backtest.benchmark`
engine -- this test file adds no new cost or benchmark computation of
its own."""

from __future__ import annotations

from datetime import date

from research_helpers import synthetic_multi_year_repository

from backtest.strategy import BuyAndHoldStrategy

from strategy_research.long_term_momentum import LongTermMomentumParameters, LongTermMomentumStrategy
from strategy_research.runner import run_gross_and_net


class TestGrossVsNet:
    def test_net_final_value_never_exceeds_gross_final_value(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2022, 6, 1), symbols=universe)

        result = run_gross_and_net(
            repo, lambda: LongTermMomentumStrategy(list(universe), LongTermMomentumParameters(lookback_months=6, top_n=1, rebalance_months=3)),
            universe, start_date=date(2020, 1, 2), end_date=date(2022, 6, 1), initial_capital=100_000.0,
            benchmark_id="SP500",
        )
        gross_final = result.gross.performance.cumulative_return
        net_final = result.net.performance.cumulative_return
        # Costs strictly reduce (or leave unchanged, if zero trades)
        # realized return -- never improve it.
        assert net_final <= gross_final
        assert result.net.performance.total_transaction_cost >= result.gross.performance.total_transaction_cost

    def test_buy_and_hold_gross_vs_net_also_reflects_cost_drag(self) -> None:
        """Reuses Phase 2's own BuyAndHoldStrategy unchanged, proving
        the runner is not specific to the three new candidates."""
        universe = ("TRENDUP", "TRENDDOWN")
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2021, 6, 1), symbols=universe)
        result = run_gross_and_net(
            repo, lambda: BuyAndHoldStrategy(list(universe)),
            universe, start_date=date(2020, 1, 2), end_date=date(2021, 6, 1), initial_capital=50_000.0,
        )
        assert result.net.performance.total_transaction_cost > 0.0
        assert result.gross.performance.total_transaction_cost == 0.0


class TestBenchmarkComparison:
    def test_benchmark_fields_present_when_benchmark_id_supplied(self) -> None:
        universe = ("TRENDUP", "CYCLICAL")
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2021, 6, 1), symbols=universe)
        result = run_gross_and_net(
            repo, lambda: LongTermMomentumStrategy(list(universe), LongTermMomentumParameters(lookback_months=6, top_n=1, rebalance_months=3)),
            universe, start_date=date(2020, 1, 2), end_date=date(2021, 6, 1), initial_capital=100_000.0,
            benchmark_id="SP500",
        )
        assert result.net.benchmark is not None
        assert result.net.performance.benchmark_cumulative_return is not None
        assert result.net.performance.excess_return is not None

    def test_no_benchmark_id_leaves_benchmark_fields_none_not_fabricated(self) -> None:
        universe = ("TRENDUP", "CYCLICAL")
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2021, 6, 1), symbols=universe)
        result = run_gross_and_net(
            repo, lambda: LongTermMomentumStrategy(list(universe), LongTermMomentumParameters(lookback_months=6, top_n=1, rebalance_months=3)),
            universe, start_date=date(2020, 1, 2), end_date=date(2021, 6, 1), initial_capital=100_000.0,
        )
        assert result.net.benchmark is None
        assert result.net.performance.excess_return is None


class TestReproducibility:
    def test_identical_run_twice_yields_identical_gross_and_net_performance(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2022, 1, 1), symbols=universe)

        def build():
            return run_gross_and_net(
                repo, lambda: LongTermMomentumStrategy(list(universe), LongTermMomentumParameters(lookback_months=6, top_n=1, rebalance_months=3)),
                universe, start_date=date(2020, 1, 2), end_date=date(2022, 1, 1), initial_capital=100_000.0,
                benchmark_id="SP500",
            )

        result1, result2 = build(), build()
        assert result1.gross.performance == result2.gross.performance
        assert result1.net.performance == result2.net.performance
