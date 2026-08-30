"""Strategy candidate: rank-average ensemble of `leverage_score` and
`net_margin_score` -- the only two factors in this project's history
with a positive raw Signal IC (mean_ic=+0.0782 and +0.0238
respectively; see `docs/research/STRATEGY-VALIDATION-REPORT.md`
Section G's "Third update"). Deliberately excludes every null factor
(`roe`, `roa`, `low_volatility`, `momentum`) rather than combining
everything indiscriminately -- combining a null factor into an average
can only dilute a real signal, never strengthen it.

**Why rank-averaging, and why this is a genuinely different question
from `MLStrategy`'s OLS/ridge combination**: `MLStrategy` (ADR-0043)
already asks "does a FITTED LINEAR combination of all 6 factors carry
information neither factor showed alone" -- and its answer so far
(`ml_ols` has the second-worst walk-forward fold-consistency of 6
candidates) suggests fitting a regression on this little data may
itself be adding noise. Rank-averaging is a genuinely different,
nonparametric combination technique: no fitting, no coefficients to
estimate, no leakage-safety machinery needed at all (every score is
computed fresh at the live `as_of_time`, exactly like `LeverageStrategy`
alone already does) -- it only ever combines the RELATIVE ORDER two
already-tested signals agree or disagree on. If two weak, independently
-motivated signals are both genuinely (if weakly) informative, their
rank average can be more stable than either alone, without paying
OLS's overfitting-on-few-samples risk.

Portfolio construction is deliberately the same simplest, already-
proven one every other fundamentals-based candidate here uses
(equal-weight among newly-entering top-N, rebalance-by-elapsed-
calendar-months) -- for the same reason: isolating "does the combined
ranking carry information" from "does a more elaborate sizing scheme
help or hurt."
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
from strategy_research.factor_scores import leverage_score, net_margin_score
from strategy_research.signal_ic import rank_average

REBALANCE_MONTHS_RANGE = (1, 3)


@dataclass(frozen=True)
class RankAverageEnsembleParameters:
    top_n: int = 5
    rebalance_months: int = 3

    def __post_init__(self) -> None:
        if self.rebalance_months not in REBALANCE_MONTHS_RANGE:
            raise ValueError(f"rebalance_months must be one of {REBALANCE_MONTHS_RANGE}")
        if self.top_n < 1:
            raise ValueError("top_n must be >= 1")


class RankAverageEnsembleStrategy:
    """Long-only, cross-sectional ranking by the average of
    `leverage_score`'s and `net_margin_score`'s ranks, rebalanced by
    elapsed calendar months. See module docstring for why rank-
    averaging, and why these two factors specifically."""

    version = "rank_average_ensemble_v1"
    COST_SAFETY_MARGIN = 0.02

    def __init__(
        self,
        security_ids: Sequence[str],
        fundamentals_repository: object,
        params: RankAverageEnsembleParameters = RankAverageEnsembleParameters(),
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

        leverage_scores: dict[str, float] = {}
        net_margin_scores: dict[str, float] = {}
        for security_id in self._security_ids:
            lv = leverage_score(security_id, as_of_time, self._fundamentals_repository)
            nm = net_margin_score(security_id, as_of_time, self._fundamentals_repository)
            # Only rank a security that has BOTH scores -- never
            # average a real score against a fabricated stand-in for a
            # missing one.
            if lv is not None and nm is not None:
                leverage_scores[security_id] = lv
                net_margin_scores[security_id] = nm

        intents: list[OrderIntent] = []
        if not leverage_scores:
            target: set[str] = set()
        else:
            common = sorted(leverage_scores)
            leverage_ranks = dict(zip(common, rank_average([leverage_scores[sid] for sid in common])))
            net_margin_ranks = dict(zip(common, rank_average([net_margin_scores[sid] for sid in common])))
            combined = {sid: (leverage_ranks[sid] + net_margin_ranks[sid]) / 2.0 for sid in common}
            ranked = sorted(combined, key=lambda sid: combined[sid], reverse=True)
            target = set(ranked[: self._params.top_n])

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
