"""Category: Strategy determinism + hypothesis sanity (instruction
section 35-K). LongTermMomentumStrategy must (1) rank a steadily
trending-up synthetic series above a steadily trending-down one, (2)
rebalance strictly by elapsed calendar months (not decision-step count),
and (3) produce byte-identical order sequences on repeated runs given
identical inputs."""

from __future__ import annotations

from datetime import date

from research_helpers import synthetic_multi_year_repository

from backtest.engine import BacktestConfig, BacktestEngine

from strategy_research.long_term_momentum import LongTermMomentumParameters, LongTermMomentumStrategy


def _config(start, end, universe):
    return BacktestConfig(
        market="US_EQUITY", start_date=start, end_date=end, initial_capital=100_000.0,
        security_ids=tuple(universe), code_version="test",
    )


class TestPicksTheTrendingUpName:
    def test_top_1_selects_trendup_over_trenddown(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        start, end = date(2020, 1, 2), date(2021, 6, 1)
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        strategy = LongTermMomentumStrategy(list(universe), LongTermMomentumParameters(lookback_months=6, top_n=1, rebalance_months=3))
        result = BacktestEngine(repo, _config(start, end, universe), strategy).run()

        bought = {f.security_id for f in result.fills if f.side.value == "BUY"}
        assert bought == {"TRENDUP"}


class TestRebalanceCadence:
    def test_does_not_rebalance_every_daily_checkpoint(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        start, end = date(2020, 1, 2), date(2020, 6, 1)
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        strategy = LongTermMomentumStrategy(list(universe), LongTermMomentumParameters(lookback_months=6, top_n=1, rebalance_months=3))
        result = BacktestEngine(repo, _config(start, end, universe), strategy).run()

        # ~100 trading days in this window; a genuinely low-frequency
        # strategy should generate far fewer fills than that, not one
        # per checkpoint.
        assert 0 < len(result.fills) < 10


class TestDeterministicReplay:
    def test_identical_fills_on_replay(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        start, end = date(2020, 1, 2), date(2021, 1, 4)
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        config = _config(start, end, universe)

        result1 = BacktestEngine(
            repo, config, LongTermMomentumStrategy(list(universe), LongTermMomentumParameters(lookback_months=6, top_n=1, rebalance_months=3))
        ).run()
        result2 = BacktestEngine(
            repo, config, LongTermMomentumStrategy(list(universe), LongTermMomentumParameters(lookback_months=6, top_n=1, rebalance_months=3))
        ).run()

        def sig(f):
            return (f.security_id, f.side, f.quantity, f.price, f.execution_time)

        assert [sig(f) for f in result1.fills] == [sig(f) for f in result2.fills]
        assert result1.performance == result2.performance


class TestParameterValidation:
    def test_rejects_out_of_range_lookback(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            LongTermMomentumParameters(lookback_months=3)

    def test_rejects_out_of_range_rebalance(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            LongTermMomentumParameters(rebalance_months=2)
