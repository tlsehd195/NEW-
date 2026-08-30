"""Strategy candidate 5: Low-Leverage (fundamentals-based).

HYPOTHESIS: among the universe, symbols with LOWER `Liabilities /
StockholdersEquity` tend to have relatively better forward returns --
the "low-leverage" quality/safety anomaly (e.g. one pillar of Asness,
Frazzini & Pedersen 2013's quality-minus-junk construction). This is
the first strategy this project builds around a fundamentals-derived
score rather than a price/volume-derived one.

**Why this strategy exists now, specifically**: `strategy_research.
factor_scores.leverage_score`'s real Signal IC (mean_ic=+0.0782,
ic_information_ratio=+0.2559, positive_ic_ratio=61.25%, computed
against the real 39-symbol catalog over 2010-2023-04-28) is the
strongest of 7 independently-motivated hypotheses this project has
tested (see `docs/research/STRATEGY-VALIDATION-REPORT.md` Section G's
"Third update" and `docs/decisions/ADR-0042-fundamentals-data-source-
selection.md` Decision 12). That IC result is explicitly flagged there
as a LEAD, not a validated edge -- with 7 hypotheses tested, one
result this size is not a low-probability outcome even if none of the
7 carried real signal, the same multiple-comparisons caution this
project's own PBO/DSR discipline applies to full strategies. This
module exists to put `leverage_score` through that exact discipline
(walk-forward + PBO/DSR via `run_long_horizon_validation.py`, the same
pipeline the original 4 candidates went through) rather than treating
the raw IC number as sufficient on its own.

**Portfolio construction is deliberately the simplest one already
proven correct in this codebase**: equal-weight among newly-entering
top-N positions, identical to `LongTermMomentumStrategy`'s own
construction (rebalance-by-elapsed-calendar-months, sell everything
that drops out of the target set, buy only symbols not already held).
Chosen specifically to isolate "does the ranking signal itself carry
information" from "does a more elaborate position-sizing scheme help
or hurt" -- `risk_controlled_momentum`'s own real bug (ADR-0038-era
finding) showed exactly how a more complex construction can obscure
(or fabricate the appearance of) a signal's own real quality. If this
simple version clears the CANDIDATE bar, a more elaborate construction
is a legitimate later question; if it does not, added complexity would
not have saved it.

**Data source note**: unlike every other strategy in this package,
`generate_orders` needs TWO repositories -- a price `DataRepository`
(via the `data: AsOfDataView` parameter the `Strategy` Protocol
already provides) for order sizing, and a fundamentals repository
(injected via the constructor, NOT threaded through the `Strategy`
Protocol's fixed `generate_orders` signature) for `leverage_score`
itself. This mirrors `strategy_research.signal_ic.
compute_fundamentals_ic_series`'s identical two-repository design --
fundamentals live in their own catalog, entirely separate from price
data's, so there is no way to fetch both through a single
`AsOfDataView`. `DuckDBFundamentalsRepository`'s own methods already
enforce `available_time <= as_of_time` directly (no `AsOfDataView`/
`BacktestClock` wrapper needed for that side), the same point-in-time
guarantee `AsOfDataView` provides for prices.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from backtest.asof import AsOfDataView
from backtest.enums import OrderSide, OrderType
from backtest.portfolio import PortfolioView
from backtest.strategy import OrderIntent

from strategy_research._dates import add_months
from strategy_research.factor_scores import leverage_score

REBALANCE_MONTHS_RANGE = (1, 3)


@dataclass(frozen=True)
class LeverageParameters:
    top_n: int = 5
    rebalance_months: int = 3

    def __post_init__(self) -> None:
        if self.rebalance_months not in REBALANCE_MONTHS_RANGE:
            raise ValueError(f"rebalance_months must be one of {REBALANCE_MONTHS_RANGE}")
        if self.top_n < 1:
            raise ValueError("top_n must be >= 1")


class LeverageStrategy:
    """Long-only, cross-sectional low-leverage ranking, rebalanced by
    elapsed calendar months -- see module docstring for the full
    rationale and the two-repository data-source note."""

    version = "leverage_v1"

    # See LongTermMomentumStrategy.COST_SAFETY_MARGIN -- same reasoning.
    COST_SAFETY_MARGIN = 0.02

    def __init__(
        self,
        security_ids: Sequence[str],
        fundamentals_repository: object,
        params: LeverageParameters = LeverageParameters(),
    ) -> None:
        self._security_ids = list(security_ids)
        self._fundamentals_repository = fundamentals_repository
        self._params = params
        self._next_rebalance_time: Optional[datetime] = None

    def generate_orders(
        self, as_of_time: datetime, data: AsOfDataView, portfolio: PortfolioView
    ) -> list[OrderIntent]:
        if self._next_rebalance_time is not None and as_of_time < self._next_rebalance_time:
            return []
        self._next_rebalance_time = add_months(as_of_time, self._params.rebalance_months)

        scores: dict[str, float] = {}
        for security_id in self._security_ids:
            score = leverage_score(security_id, as_of_time, self._fundamentals_repository)
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
