"""Strategy candidate 2: Long-Term Cross-Sectional Momentum.

HYPOTHESIS (instruction section 15): among the pilot universe, symbols
with a relatively strong trailing total return over a long lookback
window (6-18 months) tend to continue outperforming the rest of the
universe over the following, low-frequency rebalance period -- the
classical cross-sectional momentum effect (Jegadeesh & Titman 1993),
applied here at a lower frequency than the typical academic 3-12 month
setup specifically to match this project's stated long-term/low-turnover
mandate (instruction section 2), not to chase a shorter-horizon signal.

This module makes NO claim that the hypothesis holds for this specific
universe/period -- that is exactly the empirical question
`strategy_research.runner`/`STRATEGY-RESEARCH-REPORT.md` exist to
evaluate, honestly, against whatever real or fixture data is available.

PARAMETER RANGE (documented, not brute-forced -- instruction section 15):
    lookback_months  in {6, 9, 12, 18}
    rebalance_months in {1, 3}   (monthly, quarterly)
A single default combination is used unless the caller overrides it;
this module does not itself search the grid (see
`strategy_research.classification`'s multiple-testing note on why an
automated grid search is deliberately not performed here).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from backtest.asof import AsOfDataView
from backtest.enums import OrderSide, OrderType
from backtest.portfolio import PortfolioView
from backtest.strategy import OrderIntent

from strategy_research._dates import TRADING_DAYS_PER_MONTH, add_months

LOOKBACK_MONTHS_RANGE = (6, 9, 12, 18)
REBALANCE_MONTHS_RANGE = (1, 3)


@dataclass(frozen=True)
class LongTermMomentumParameters:
    lookback_months: int = 12
    top_n: int = 5
    rebalance_months: int = 3

    def __post_init__(self) -> None:
        if self.lookback_months not in LOOKBACK_MONTHS_RANGE:
            raise ValueError(f"lookback_months must be one of {LOOKBACK_MONTHS_RANGE}")
        if self.rebalance_months not in REBALANCE_MONTHS_RANGE:
            raise ValueError(f"rebalance_months must be one of {REBALANCE_MONTHS_RANGE}")
        if self.top_n < 1:
            raise ValueError("top_n must be >= 1")


class LongTermMomentumStrategy:
    """Long-only, cross-sectional momentum, rebalanced by elapsed
    calendar months (not decision-step count -- `SimpleMomentumStrategy`
    (Phase 2)'s `rebalance_every` counts checkpoints, appropriate for its
    short lookback; a long-term strategy rebalances by real elapsed
    calendar time instead, so a change in checkpoint frequency does not
    silently change how often this strategy trades)."""

    version = "long_term_momentum_v1"

    # See BuyAndHoldStrategy.COST_SAFETY_MARGIN (Phase 2) -- same reasoning.
    COST_SAFETY_MARGIN = 0.02

    def __init__(self, security_ids: Sequence[str], params: LongTermMomentumParameters = LongTermMomentumParameters()) -> None:
        self._security_ids = list(security_ids)
        self._params = params
        self._next_rebalance_time: Optional[datetime] = None

    def _momentum_score(self, security_id: str, as_of_time: datetime, data: AsOfDataView) -> Optional[float]:
        lookback_days = self._params.lookback_months * TRADING_DAYS_PER_MONTH
        bars = data.get_bars(security_id, as_of_time - timedelta(days=lookback_days * 2), as_of_time)
        if len(bars) < 2:
            return None
        start_price = bars[0].adjusted_close or bars[0].close
        end_price = bars[-1].adjusted_close or bars[-1].close
        if start_price <= 0:
            return None
        return end_price / start_price - 1.0

    def generate_orders(
        self, as_of_time: datetime, data: AsOfDataView, portfolio: PortfolioView
    ) -> list[OrderIntent]:
        if self._next_rebalance_time is not None and as_of_time < self._next_rebalance_time:
            return []
        self._next_rebalance_time = add_months(as_of_time, self._params.rebalance_months)

        scores: dict[str, float] = {}
        for security_id in self._security_ids:
            score = self._momentum_score(security_id, as_of_time, data)
            if score is not None:
                scores[security_id] = score

        ranked = sorted(scores, key=lambda sid: scores[sid], reverse=True)
        target = set(ranked[: self._params.top_n])

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
