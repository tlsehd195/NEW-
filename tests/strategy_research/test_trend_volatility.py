"""Category: Strategy determinism + hypothesis sanity (instruction
section 35-L). TrendVolatilityStrategy must hold the steadily
trending-up, low-volatility name and reject the steadily-declining name
(fails the trend filter) and the high-volatility flat name (fails the
volatility filter)."""

from __future__ import annotations

import pytest
from datetime import date

from research_helpers import synthetic_multi_year_repository

from backtest.engine import BacktestConfig, BacktestEngine

from strategy_research.trend_volatility import TrendVolatilityParameters, TrendVolatilityStrategy


def _config(start, end, universe):
    return BacktestConfig(
        market="US_EQUITY", start_date=start, end_date=end, initial_capital=100_000.0,
        security_ids=tuple(universe), code_version="test",
    )


class TestTrendAndVolatilityFilters:
    def test_holds_trendup_rejects_trenddown_and_flathigh(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "FLATHIGH")
        start, end = date(2020, 1, 2), date(2021, 1, 4)
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        strategy = TrendVolatilityStrategy(list(universe), TrendVolatilityParameters(trend_lookback_months=6, vol_lookback_days=60, vol_threshold=0.35, rebalance_months=1))
        result = BacktestEngine(repo, _config(start, end, universe), strategy).run()

        bought = {f.security_id for f in result.fills if f.side.value == "BUY"}
        assert "TRENDUP" in bought
        assert "TRENDDOWN" not in bought
        assert "FLATHIGH" not in bought

    def test_all_symbols_disqualified_produces_no_fills_not_an_error(self) -> None:
        """A universe where nothing passes both filters must simply
        produce zero fills -- never a fabricated fallback holding."""
        universe = ("TRENDDOWN", "FLATHIGH")
        start, end = date(2020, 1, 2), date(2021, 1, 4)
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        strategy = TrendVolatilityStrategy(list(universe), TrendVolatilityParameters(trend_lookback_months=6, vol_lookback_days=60, vol_threshold=0.35, rebalance_months=1))
        result = BacktestEngine(repo, _config(start, end, universe), strategy).run()
        assert len(result.fills) == 0


class TestParameterValidation:
    def test_rejects_out_of_range_vol_threshold(self) -> None:
        with pytest.raises(ValueError):
            TrendVolatilityParameters(vol_threshold=0.99)
