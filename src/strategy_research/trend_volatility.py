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

from strategy_research._dates import TRADING_DAYS_PER_MONTH, add_months, trim_to_lookback

TREND_LOOKBACK_MONTHS_RANGE = (6, 9, 12)
VOL_LOOKBACK_DAYS_RANGE = (60, 90, 126)
VOL_THRESHOLD_RANGE = (0.25, 0.35, 0.45)


@dataclass(frozen=True)
class FilterEvaluation:
    """Result of `TrendVolatilityStrategy._evaluate`: the boolean the
    filter always produces, plus whatever of `moving_average`,
    `current_price`, `realized_vol` was actually computed before that
    result was reached (ADR-0161) -- never all three when an earlier
    check already returned, so a rejection for a bad trend never claims
    a `realized_vol` that was never computed."""

    passed: bool
    features: Optional[dict] = None


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

    def _evaluate(self, security_id: str, as_of_time: datetime, data: AsOfDataView) -> FilterEvaluation:
        trend_days = self._params.trend_lookback_months * TRADING_DAYS_PER_MONTH
        # The *1.6 padding only guarantees enough calendar days are
        # fetched to contain `trend_days` trading days -- without
        # trim_to_lookback, the moving average below was silently
        # computed over the whole padded (roughly 1.6x too large)
        # window rather than the `trend_lookback_months` this
        # strategy's own parameters document (found comparing against
        # gs-quant's timeseries.moving_average, which operates on a
        # precisely-sized window).
        trend_bars = trim_to_lookback(
            data.get_bars(security_id, as_of_time - timedelta(days=int(trend_days * 1.6)), as_of_time),
            trend_days,
        )
        if len(trend_bars) < 2:
            return FilterEvaluation(False)
        closes = [b.adjusted_close or b.close for b in trend_bars]
        moving_average = sum(closes) / len(closes)
        current_price = closes[-1]
        if moving_average <= 0:
            return FilterEvaluation(False)
        features = {"moving_average": moving_average, "current_price": current_price}
        if current_price <= moving_average:
            return FilterEvaluation(False, features)

        vol_bars = trim_to_lookback(
            data.get_bars(
                security_id, as_of_time - timedelta(days=int(self._params.vol_lookback_days * 1.6)), as_of_time
            ),
            self._params.vol_lookback_days,
        )
        if len(vol_bars) < 2:
            return FilterEvaluation(False, features)
        vol_closes = [b.adjusted_close or b.close for b in vol_bars]
        returns = compute_returns(vol_closes)
        realized_vol = annualized_volatility(returns)
        features = {**features, "realized_vol": realized_vol}
        return FilterEvaluation(realized_vol <= self._params.vol_threshold, features)

    def _passes_filter(self, security_id: str, as_of_time: datetime, data: AsOfDataView) -> bool:
        # Kept as a plain bool predicate -- `signal_ic.bucket_return_analysis`
        # and its tests call this directly as a `FilterFn`, outside this
        # class, and use the return value as a truth value (ADR-0161).
        return self._evaluate(security_id, as_of_time, data).passed

    def generate_orders(
        self, as_of_time: datetime, data: AsOfDataView, portfolio: PortfolioView
    ) -> list[OrderIntent]:
        if self._next_rebalance_time is not None and as_of_time < self._next_rebalance_time:
            return []
        self._next_rebalance_time = add_months(as_of_time, self._params.rebalance_months)

        evaluations = {sid: self._evaluate(sid, as_of_time, data) for sid in self._security_ids}
        qualifying = [sid for sid in self._security_ids if evaluations[sid].passed]
        target = set(qualifying)

        intents: list[OrderIntent] = []
        for security_id, position in portfolio.positions.items():
            if security_id not in target and position.quantity > 0:
                # A held position not in `self._security_ids` was never
                # evaluated this call -- no real, actually-computed-this-call
                # value exists for it, so `features` stays `None` rather than
                # reusing a stale value from a prior cycle (ADR-0161).
                evaluation = evaluations.get(security_id)
                features = evaluation.features if evaluation is not None else None
                intents.append(OrderIntent(security_id, OrderSide.SELL, position.quantity, OrderType.MARKET, features=features))

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
                    intents.append(
                        OrderIntent(
                            security_id, OrderSide.BUY, quantity, OrderType.MARKET, features=evaluations[security_id].features
                        )
                    )
        return intents
