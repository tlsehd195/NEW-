"""Strategy candidate 4: Risk-Controlled Momentum.

HYPOTHESIS (instruction section 17): plain cross-sectional momentum
(`strategy_research.long_term_momentum`) tends to concentrate capital in
whichever names happened to trend the hardest, which are often also the
most volatile -- inversely volatility-weighting the momentum leaders
(and capping any single name's weight) is hypothesized to retain most of
the momentum signal's return while reducing concentration-driven
drawdown, at the cost of giving up some upside versus the unweighted
version.

**This strategy's internal `max_position_weight` is a research-design
parameter local to this module only.** It is NOT
`risk.config.RiskConfig.max_position_weight` and does not read from or
write to Phase 8's production Risk Engine in any way (instruction
section 17: "연구 전략 내부의 position allocation과 production risk
limit을 혼동하지 않는다") -- the two happen to share a similar name
because they solve a similar allocation problem, not because either
reuses the other's configuration or code path.

PARAMETER RANGE (documented, not brute-forced):
    lookback_months in {6, 9, 12, 18}   (shared with long_term_momentum)
    vol_lookback_days in {60, 90, 126}  (shared with trend_volatility)
    max_position_weight in {0.15, 0.20, 0.30}
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
from strategy_research.long_term_momentum import LOOKBACK_MONTHS_RANGE

VOL_LOOKBACK_DAYS_RANGE = (60, 90, 126)
MAX_POSITION_WEIGHT_RANGE = (0.15, 0.20, 0.30)


@dataclass(frozen=True)
class RiskControlledMomentumParameters:
    lookback_months: int = 12
    top_n: int = 5
    rebalance_months: int = 3
    vol_lookback_days: int = 90
    max_position_weight: float = 0.20

    def __post_init__(self) -> None:
        if self.lookback_months not in LOOKBACK_MONTHS_RANGE:
            raise ValueError(f"lookback_months must be one of {LOOKBACK_MONTHS_RANGE}")
        if self.vol_lookback_days not in VOL_LOOKBACK_DAYS_RANGE:
            raise ValueError(f"vol_lookback_days must be one of {VOL_LOOKBACK_DAYS_RANGE}")
        if self.max_position_weight not in MAX_POSITION_WEIGHT_RANGE:
            raise ValueError(f"max_position_weight must be one of {MAX_POSITION_WEIGHT_RANGE}")
        if self.top_n < 1:
            raise ValueError("top_n must be >= 1")


class RiskControlledMomentumStrategy:
    """Ranks the universe by trailing momentum (same scoring as
    `LongTermMomentumStrategy`), selects the top N, then sizes each
    selected position inversely proportional to its own realized
    volatility (an inverse-volatility / naive risk-parity weighting)
    capped at `max_position_weight` of total portfolio value -- rather
    than `LongTermMomentumStrategy`'s plain equal split."""

    version = "risk_controlled_momentum_v1"

    COST_SAFETY_MARGIN = 0.02
    _MIN_VOL_FLOOR = 0.01  # avoids a division blow-up for a near-zero-volatility name

    def __init__(
        self, security_ids: Sequence[str], params: RiskControlledMomentumParameters = RiskControlledMomentumParameters()
    ) -> None:
        self._security_ids = list(security_ids)
        self._params = params
        self._next_rebalance_time: Optional[datetime] = None

    def _momentum_score(self, security_id: str, as_of_time: datetime, data: AsOfDataView) -> Optional[float]:
        lookback_days = self._params.lookback_months * TRADING_DAYS_PER_MONTH
        # See long_term_momentum.py's identical comment: the *2 padding
        # only guarantees enough calendar days are fetched -- trim back
        # to the intended trading-day window before using it as the
        # momentum lookback.
        bars = trim_to_lookback(
            data.get_bars(security_id, as_of_time - timedelta(days=lookback_days * 2), as_of_time),
            lookback_days,
        )
        if len(bars) < 2:
            return None
        start_price = bars[0].adjusted_close or bars[0].close
        end_price = bars[-1].adjusted_close or bars[-1].close
        if start_price <= 0:
            return None
        return end_price / start_price - 1.0

    def _realized_vol(self, security_id: str, as_of_time: datetime, data: AsOfDataView) -> Optional[float]:
        bars = trim_to_lookback(
            data.get_bars(
                security_id, as_of_time - timedelta(days=int(self._params.vol_lookback_days * 1.6)), as_of_time
            ),
            self._params.vol_lookback_days,
        )
        if len(bars) < 2:
            return None
        closes = [b.adjusted_close or b.close for b in bars]
        return annualized_volatility(compute_returns(closes))

    def _current_portfolio_value(self, as_of_time: datetime, data: AsOfDataView, portfolio: PortfolioView) -> float:
        value = portfolio.cash
        for security_id, position in portfolio.positions.items():
            if position.quantity <= 0:
                continue
            bars = data.get_bars(security_id, as_of_time - timedelta(days=14), as_of_time)
            if bars:
                value += position.quantity * bars[-1].close
            else:
                value += position.quantity * position.average_cost
        return value

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
        ranked = sorted(scores, key=lambda sid: scores[sid], reverse=True)[: self._params.top_n]

        intents: list[OrderIntent] = []
        target = set(ranked)
        for security_id, position in portfolio.positions.items():
            if security_id not in target and position.quantity > 0:
                intents.append(OrderIntent(security_id, OrderSide.SELL, position.quantity, OrderType.MARKET))

        if not ranked:
            return intents

        inv_vols: dict[str, float] = {}
        for security_id in ranked:
            vol = self._realized_vol(security_id, as_of_time, data)
            inv_vols[security_id] = 1.0 / max(vol, self._MIN_VOL_FLOOR) if vol is not None else 0.0
        total_inv_vol = sum(inv_vols.values())
        if total_inv_vol <= 0:
            return intents

        raw_weights = {sid: inv_vols[sid] / total_inv_vol for sid in ranked}
        capped_weights = {sid: min(w, self._params.max_position_weight) for sid, w in raw_weights.items()}
        # Capping can leave weight unallocated -- deliberately left as
        # uninvested cash rather than silently redistributed to other
        # names (a fixed weight cap that "spills over" would defeat the
        # point of having a cap at all).

        portfolio_value = self._current_portfolio_value(as_of_time, data, portfolio)
        to_buy = [sid for sid in ranked if portfolio.quantity_of(sid) == 0]
        available_cash = portfolio.cash * (1.0 - self.COST_SAFETY_MARGIN)
        for security_id in to_buy:
            target_notional = min(capped_weights[security_id] * portfolio_value, available_cash)
            if target_notional <= 0:
                continue
            bars = data.get_bars(security_id, as_of_time - timedelta(days=14), as_of_time)
            if not bars:
                continue
            price = bars[-1].close
            if price <= 0:
                continue
            quantity = float(int(target_notional / price))
            if quantity > 0:
                intents.append(OrderIntent(security_id, OrderSide.BUY, quantity, OrderType.MARKET))
                available_cash -= quantity * price
        return intents
