"""Strategy candidate 3: Long-Term Trend + Volatility Filter.

HYPOTHESIS (instruction section 16): a security whose current price is
above its own long-term moving average (an established uptrend) AND
whose recent realized volatility is at or below a fixed threshold is
more likely to continue trending favorably than one that is either in a
downtrend or unusually volatile -- combining trend-following with a
simple risk-avoidance filter, in the spirit of long-term trend-following
literature (e.g. Faber's "A Quantitative Approach to Tactical Asset
Allocation"), without claiming this specific combination is validated
for this project's universe/period.

PARAMETER RANGE (documented, not brute-forced):
    trend_lookback_months in {6, 9, 12}
    vol_lookback_days      in {60, 90, 126}
    vol_threshold (annualized) in {0.25, 0.35, 0.45}
A single default combination is used unless overridden; this module
does not itself search the grid.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from backtest.asof import AsOfDataView
from backtest.enums import OrderSide, OrderType
from backtest.metrics import annualized_volatility, compute_returns
from backtest.portfolio import PortfolioView
from backtest.strategy import OrderIntent

from strategy_research._dates import TRADING_DAYS_PER_MONTH, add_months

TREND_LOOKBACK_MONTHS_RANGE = (6, 9, 12)
VOL_LOOKBACK_DAYS_RANGE = (60, 90, 126)
VOL_THRESHOLD_RANGE = (0.25, 0.35, 0.45)


@dataclass(frozen=True)
class TrendVolatilityParameters:
    trend_lookback_months: int = 9
    vol_lookback_days: int = 90
    vol_threshold: float = 0.35
    rebalance_months: int = 1

    def __post_init__(self) -> None:
        if self.trend_lookback_months not in TREND_LOOKBACK_MONTHS_RANGE:
            raise ValueError(f"trend_lookback_months must be one of {TREND_LOOKBACK_MONTHS_RANGE}")
        if self.vol_lookback_days not in VOL_LOOKBACK_DAYS_RANGE:
            raise ValueError(f"vol_lookback_days must be one of {VOL_LOOKBACK_DAYS_RANGE}")
        if self.vol_threshold not in VOL_THRESHOLD_RANGE:
            raise ValueError(f"vol_threshold must be one of {VOL_THRESHOLD_RANGE}")


class TrendVolatilityStrategy:
    """Long-only, equal-weight across every symbol that currently passes
    BOTH the trend filter (price > trailing moving average) and the
    volatility filter (annualized realized volatility <=
    `vol_threshold`); holds cash for the remainder of the universe that
    does not qualify. Rebalanced monthly by default (`rebalance_months`,
    calendar-time based, same discipline as
    `strategy_research.long_term_momentum`)."""

    version = "trend_volatility_v1"

    COST_SAFETY_MARGIN = 0.02

    def __init__(self, security_ids: Sequence[str], params: TrendVolatilityParameters = TrendVolatilityParameters()) -> None:
        self._security_ids = list(security_ids)
        self._params = params
        self._next_rebalance_time: Optional[datetime] = None

    def _passes_filter(self, security_id: str, as_of_time: datetime, data: AsOfDataView) -> bool:
        trend_days = self._params.trend_lookback_months * TRADING_DAYS_PER_MONTH
        trend_bars = data.get_bars(security_id, as_of_time - timedelta(days=int(trend_days * 1.6)), as_of_time)
        if len(trend_bars) < 2:
            return False
        closes = [b.adjusted_close or b.close for b in trend_bars]
        moving_average = sum(closes) / len(closes)
        current_price = closes[-1]
        if moving_average <= 0 or current_price <= moving_average:
            return False

        vol_bars = data.get_bars(
            security_id, as_of_time - timedelta(days=int(self._params.vol_lookback_days * 1.6)), as_of_time
        )
        if len(vol_bars) < 2:
            return False
        vol_closes = [b.adjusted_close or b.close for b in vol_bars]
        returns = compute_returns(vol_closes)
        realized_vol = annualized_volatility(returns)
        return realized_vol <= self._params.vol_threshold

    def generate_orders(
        self, as_of_time: datetime, data: AsOfDataView, portfolio: PortfolioView
    ) -> list[OrderIntent]:
        if self._next_rebalance_time is not None and as_of_time < self._next_rebalance_time:
            return []
        self._next_rebalance_time = add_months(as_of_time, self._params.rebalance_months)

        qualifying = [sid for sid in self._security_ids if self._passes_filter(sid, as_of_time, data)]
        target = set(qualifying)

        intents: list[OrderIntent] = []
        for security_id, position in portfolio.positions.items():
            if security_id not in target and position.quantity > 0:
                intents.append(OrderIntent(security_id, OrderSide.SELL, position.quantity, OrderType.MARKET))

        to_buy = [sid for sid in target if portfolio.quantity_of(sid) == 0]
        if to_buy:
            per_symbol_cash = portfolio.cash * (1.0 - self.COST_SAFETY_MARGIN) / len(to_buy)
            for security_id in to_buy:
                bars = data.get_bars(security_id, as_of_time - timedelta(days=14), as_of_time)
                if not bars:
                    continue
                price = bars[-1].close
                if price <= 0:
                    continue
                quantity = float(int(per_symbol_cash / price))
                if quantity > 0:
                    intents.append(OrderIntent(security_id, OrderSide.BUY, quantity, OrderType.MARKET))
        return intents
