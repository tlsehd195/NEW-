"""Category: Strategy determinism + hypothesis sanity (instruction
section 35-L). TrendVolatilityStrategy must hold the steadily
trending-up, low-volatility name and reject the steadily-declining name
(fails the trend filter) and the high-volatility flat name (fails the
volatility filter)."""

from __future__ import annotations

import pytest
from datetime import date, datetime, timezone

from research_helpers import synthetic_multi_year_repository

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock
from backtest.engine import BacktestConfig, BacktestEngine
from backtest.enums import OrderSide
from backtest.portfolio import PortfolioView, PositionView

from strategy_research.trend_volatility import TrendVolatilityParameters, TrendVolatilityStrategy


def _utc(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


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


def _params():
    return TrendVolatilityParameters(trend_lookback_months=6, vol_lookback_days=60, vol_threshold=0.35, rebalance_months=1)


def _empty_portfolio(as_of_time):
    return PortfolioView(as_of_time=as_of_time, cash=100_000.0, positions={}, portfolio_value=100_000.0)


def _portfolio_holding(as_of_time, security_id, quantity):
    return PortfolioView(
        as_of_time=as_of_time,
        cash=100_000.0,
        positions={security_id: PositionView(security_id=security_id, quantity=quantity, average_cost=100.0)},
        portfolio_value=100_000.0 + quantity * 100.0,
    )


class TestOrderIntentFeatures:
    """ADR-0161: `TrendVolatilityStrategy._passes_filter` already
    computes `moving_average`, `current_price`, and `realized_vol`
    internally (ADR-0153 disclosed this strategy as the one remaining
    residual gap) -- this class checks those real, already-computed
    values now reach `OrderIntent.features` for both BUY and SELL, and
    are correctly omitted (never fabricated) when unavailable."""

    def test_buy_order_carries_all_three_real_values(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "FLATHIGH")
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        strategy = TrendVolatilityStrategy(list(universe), _params())
        as_of_time = _utc(2021, 3, 1)
        data = AsOfDataView(repo, BacktestClock(checkpoints=(as_of_time,)))

        intents = strategy.generate_orders(as_of_time, data, _empty_portfolio(as_of_time))

        buy_intents = [i for i in intents if i.side == OrderSide.BUY]
        assert {i.security_id for i in buy_intents} == {"TRENDUP"}
        features = buy_intents[0].features
        assert features is not None
        assert features["moving_average"] > 0
        assert features["current_price"] > features["moving_average"]
        assert features["realized_vol"] >= 0
        assert features["realized_vol"] <= _params().vol_threshold

    def test_sell_order_carries_trend_features_when_only_the_trend_check_fails(self) -> None:
        # TRENDDOWN fails at `current_price <= moving_average`, before
        # `realized_vol` is ever computed -- the SELL features must
        # contain exactly the two values that were actually computed,
        # never a fabricated `realized_vol`.
        universe = ("TRENDDOWN",)
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        strategy = TrendVolatilityStrategy(list(universe), _params())
        as_of_time = _utc(2021, 3, 1)
        data = AsOfDataView(repo, BacktestClock(checkpoints=(as_of_time,)))

        intents = strategy.generate_orders(as_of_time, data, _portfolio_holding(as_of_time, "TRENDDOWN", 10.0))

        sell_intents = [i for i in intents if i.side == OrderSide.SELL and i.security_id == "TRENDDOWN"]
        assert len(sell_intents) == 1
        features = sell_intents[0].features
        assert features is not None
        assert set(features) == {"moving_average", "current_price"}
        assert features["current_price"] <= features["moving_average"]

    def test_sell_order_carries_all_three_real_values_when_only_the_vol_check_fails(self) -> None:
        # FLATHIGH is above its own moving average at this as_of_time
        # (passes the trend check) but its realized volatility exceeds
        # `vol_threshold` -- all three values were actually computed
        # this call, so all three belong in the SELL features even
        # though the security is being sold, not bought.
        universe = ("FLATHIGH",)
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        strategy = TrendVolatilityStrategy(list(universe), _params())
        as_of_time = _utc(2020, 7, 1)
        data = AsOfDataView(repo, BacktestClock(checkpoints=(as_of_time,)))
        assert strategy._passes_filter("FLATHIGH", as_of_time, data) is False

        intents = strategy.generate_orders(as_of_time, data, _portfolio_holding(as_of_time, "FLATHIGH", 10.0))

        sell_intents = [i for i in intents if i.side == OrderSide.SELL and i.security_id == "FLATHIGH"]
        assert len(sell_intents) == 1
        features = sell_intents[0].features
        assert features is not None
        assert set(features) == {"moving_average", "current_price", "realized_vol"}
        assert features["current_price"] > features["moving_average"]
        assert features["realized_vol"] > _params().vol_threshold

    def test_sell_order_omits_features_for_a_position_outside_this_call_s_universe(self) -> None:
        # A held position whose security_id isn't in `self._security_ids`
        # was never evaluated this call -- there is no real,
        # actually-computed-this-call value for it, so `features` must
        # be `None` rather than reusing a stale value from a prior cycle.
        universe = ("TRENDUP",)
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        strategy = TrendVolatilityStrategy(list(universe), _params())
        as_of_time = _utc(2021, 3, 1)
        data = AsOfDataView(repo, BacktestClock(checkpoints=(as_of_time,)))

        intents = strategy.generate_orders(as_of_time, data, _portfolio_holding(as_of_time, "UNTRACKED", 5.0))

        sell_intents = [i for i in intents if i.side == OrderSide.SELL and i.security_id == "UNTRACKED"]
        assert len(sell_intents) == 1
        assert sell_intents[0].features is None

    def test_sell_order_omits_features_when_there_is_not_enough_history_to_compute_anything(self) -> None:
        # Too early for even `trend_bars` to have 2 bars -- `_evaluate`
        # returns before computing anything, so features must be `None`,
        # not a partial or fabricated dict.
        universe = ("TRENDUP",)
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        strategy = TrendVolatilityStrategy(list(universe), _params())
        as_of_time = _utc(2020, 1, 3)
        data = AsOfDataView(repo, BacktestClock(checkpoints=(as_of_time,)))
        assert strategy._evaluate("TRENDUP", as_of_time, data).features is None

        intents = strategy.generate_orders(as_of_time, data, _portfolio_holding(as_of_time, "TRENDUP", 5.0))

        sell_intents = [i for i in intents if i.side == OrderSide.SELL and i.security_id == "TRENDUP"]
        assert len(sell_intents) == 1
        assert sell_intents[0].features is None
