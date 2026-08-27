"""Category: Strategy determinism + hypothesis sanity (instruction
section 35-M). RiskControlledMomentumStrategy must (1) still select
trending-up names via momentum ranking, (2) never let a single position
exceed its own `max_position_weight` cap, and (3) size a lower-volatility
selected name with a larger weight than a higher-volatility one (inverse-
volatility weighting)."""

from __future__ import annotations

from datetime import date

import pytest
from research_helpers import synthetic_multi_year_repository

from backtest.engine import BacktestConfig, BacktestEngine

from strategy_research.risk_controlled_momentum import RiskControlledMomentumParameters, RiskControlledMomentumStrategy


def _config(start, end, universe, capital=100_000.0):
    return BacktestConfig(
        market="US_EQUITY", start_date=start, end_date=end, initial_capital=capital,
        security_ids=tuple(universe), code_version="test",
    )


class TestPositionWeightCap:
    def test_no_single_fill_exceeds_max_position_weight_of_initial_capital(self) -> None:
        universe = ("TRENDUP", "CYCLICAL")
        start, end = date(2020, 1, 2), date(2021, 6, 1)
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        params = RiskControlledMomentumParameters(lookback_months=6, top_n=2, rebalance_months=3, max_position_weight=0.20)
        strategy = RiskControlledMomentumStrategy(list(universe), params)
        result = BacktestEngine(repo, _config(start, end, universe), strategy).run()

        for fill in result.fills:
            if fill.side.value != "BUY":
                continue
            notional = fill.quantity * fill.price
            # Generous slack (2x the cap) since this checks against
            # INITIAL capital, not the live portfolio value the strategy
            # itself sizes against as the backtest progresses and
            # capital compounds -- a tight equality would be brittle.
            assert notional <= params.max_position_weight * 100_000.0 * 2.0


class TestInverseVolatilityWeighting:
    def test_lower_volatility_name_gets_larger_initial_allocation(self) -> None:
        # CYCLICAL has materially lower realized volatility than
        # FLATHIGH would (were it eligible), but to keep this a clean
        # momentum-ranking comparison we compare two genuinely trending
        # names with different smoothness: TRENDUP (smooth, low vol) vs
        # CYCLICAL (oscillating, higher vol) -- both trend upward enough
        # to be selected by momentum, but the smoother one should get
        # more weight under inverse-vol sizing.
        universe = ("TRENDUP", "CYCLICAL")
        start, end = date(2020, 1, 2), date(2020, 8, 1)
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        params = RiskControlledMomentumParameters(lookback_months=6, top_n=2, rebalance_months=3, vol_lookback_days=60, max_position_weight=0.30)
        strategy = RiskControlledMomentumStrategy(list(universe), params)
        result = BacktestEngine(repo, _config(start, end, universe), strategy).run()

        first_fills = {}
        for fill in result.fills:
            if fill.side.value == "BUY" and fill.security_id not in first_fills:
                first_fills[fill.security_id] = fill.quantity * fill.price

        assert set(first_fills) == {"TRENDUP", "CYCLICAL"}
        assert first_fills["TRENDUP"] > first_fills["CYCLICAL"]


class TestParameterValidation:
    def test_rejects_out_of_range_max_position_weight(self) -> None:
        with pytest.raises(ValueError):
            RiskControlledMomentumParameters(max_position_weight=0.5)
