"""Generic, reusable `Strategy` wrappers around a single
`factor_scores.py` score function -- long-only, cross-sectional top-N
ranking, rebalanced by elapsed calendar months. Exactly
`leverage_strategy.LeverageStrategy`'s construction (ADR-0043 Decision
12), generalized so the 20 candidates ADR-0051 screens via raw IC do
not each need their own near-duplicate file -- `LeverageStrategy` and
`ensemble_strategy.RankAverageEnsembleStrategy` already show what that
duplication looks like at just 2 copies; scaling that pattern to 20
would be pure copy-paste with no informational benefit, exactly what
this project's own reuse discipline (see e.g. `ml_strategy.py` reusing
`ml.linear_model`) argues against. `LeverageStrategy`/
`RankAverageEnsembleStrategy` themselves are left untouched -- already
tested and running in production reports, not worth the regression risk
of a purely stylistic refactor.

Four variants, matching `factor_scores.py`'s three score_fn call shapes
plus the cross-sectional one `signal_ic.py` already defines:

- `PriceFactorStrategy` wraps a `ScoreFn`:
  `score_fn(security_id, as_of_time, data: AsOfDataView) -> Optional[float]`
  -- price/volume-only factors. No injected repository: `data` is the
  SAME `AsOfDataView` `generate_orders` already receives, used both for
  scoring and (as every strategy here does) for order-sizing bars.

- `FundamentalsFactorStrategy` wraps a `FundamentalsScoreFn`:
  `score_fn(security_id, as_of_time, fundamentals_repository) -> Optional[float]`
  -- identical shape to what `LeverageStrategy` already hardcodes to
  `leverage_score`, generalized to take any such score_fn.

- `HybridFactorStrategy` wraps a `HybridScoreFn`:
  `score_fn(security_id, as_of_time, fundamentals_repository, price_repository) -> Optional[float]`
  -- needs the RAW, point-in-time-safe price repository (its own
  `get_bars(..., as_of_time=...)`), NOT the `AsOfDataView` `generate_orders`
  receives (`AsOfDataView.get_bars` takes no `as_of_time` kwarg -- it IS
  the point-in-time guard, applied once at construction). This mirrors
  `signal_ic.compute_hybrid_ic_series`'s identical reasoning for why
  `score_fn` is called directly against both repositories with no
  extra wrapper. A strategy using this class therefore needs THREE data
  handles at once: `data` (AsOfDataView, order sizing only),
  `fundamentals_repository`, and `price_repository` (raw, for scoring)
  -- the same repository `run_long_horizon_validation.py` already holds
  as `repository`, just also injected into the strategy's constructor
  the way `fundamentals_repository` already is for `LeverageStrategy`.

- `UniverseFactorStrategy` wraps a `UniverseScoreFn`
  (`signal_ic.UniverseScoreFn`):
  `score_fn(security_ids, as_of_time, fundamentals_repository, price_repository) -> dict`
  -- for a cross-sectionally-ranked composite like
  `quality_minus_junk_score`/`value_composite_score`, called once per
  rebalance with the whole universe rather than once per security.

All four share one order-construction helper (`_orders_from_target`),
byte-for-byte the same logic `LeverageStrategy.generate_orders`/
`RankAverageEnsembleStrategy.generate_orders` already established:
sell anything not in the new top-N target, equal-weight-buy anything in
target not already held, `COST_SAFETY_MARGIN` reserved cash headroom,
`None`-scored securities excluded from ranking rather than fabricated
with a stand-in value.

**Session 36 addition**: all four also share `_select_target`, an
optional sector-neutralization cap on top of the plain top-N slice --
see that function's own docstring for the concentration artifact
(`size_score`'s SLB-dominated TEST PnL) it exists to prevent
structurally. Opt-in only (`FactorStrategyParameters.sector_by_security`
+ `max_per_sector`, both `None` by default) -- no existing candidate's
behavior changes unless a caller supplies real, provider-sourced sector
data (e.g. `SecEdgarFundamentalsProvider.normalize_submissions`) and
explicitly asks for a cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional, Sequence

from backtest.asof import AsOfDataView
from backtest.enums import OrderSide, OrderType
from backtest.portfolio import PortfolioView
from backtest.strategy import OrderIntent

from strategy_research._dates import add_months

REBALANCE_MONTHS_RANGE = (1, 3)
_COST_SAFETY_MARGIN = 0.02

PriceScoreFn = Callable[[str, datetime, AsOfDataView], Optional[float]]
FundamentalsScoreFn = Callable[[str, datetime, object], Optional[float]]
HybridScoreFn = Callable[[str, datetime, object, object], Optional[float]]
UniverseScoreFn = Callable[[Sequence[str], datetime, object, object], dict]


@dataclass(frozen=True)
class FactorStrategyParameters:
    top_n: int = 5
    rebalance_months: int = 3
    # Session 36 sector-neutralization addition (see _select_target's own
    # docstring for the full reasoning). Both default to None, meaning
    # "no cap" -- byte-for-byte the same selection every existing
    # candidate already uses. A caller opts in by supplying BOTH: a
    # security -> sector map (real, provider-sourced values only, e.g.
    # from SecEdgarFundamentalsProvider.normalize_submissions -- never
    # fabricated, per universe.py's own honesty discipline) and a
    # max_per_sector integer.
    sector_by_security: Optional[dict[str, str]] = None
    max_per_sector: Optional[int] = None

    def __post_init__(self) -> None:
        if self.rebalance_months not in REBALANCE_MONTHS_RANGE:
            raise ValueError(f"rebalance_months must be one of {REBALANCE_MONTHS_RANGE}")
        if self.top_n < 1:
            raise ValueError("top_n must be >= 1")
        if self.max_per_sector is not None and self.max_per_sector < 1:
            raise ValueError("max_per_sector must be >= 1")


def _select_target(ranked: Sequence[str], params: FactorStrategyParameters) -> set[str]:
    """Picks the top `params.top_n` securities from `ranked` (already
    sorted best score first), optionally capping how many of them may
    share one sector -- Session 36's sector-neutralization capability,
    built after `size_score` reaching walk-forward `CANDIDATE` at
    top_n=5 turned out to be a concentration artifact (SLB, the sole
    liquid Energy name at the time, supplying 76.3% of its positive
    TEST PnL -- `docs/research/STRATEGY-VALIDATION-REPORT.md`'s "Phase
    33 Addendum" section E) rather than a genuine cross-sectional size
    effect. This exists to prevent that structurally at construction
    time, not merely detect it after the fact the way the
    concentration report already does.

    Behaves BYTE-FOR-BYTE identically to plain `ranked[:top_n]` (every
    existing candidate's unchanged behavior) whenever
    `params.sector_by_security` or `params.max_per_sector` is `None` --
    a caller must opt in with BOTH to change anything. A security with
    no entry in `sector_by_security` (unknown/unconfirmed sector) is
    NEVER capped and always eligible -- absence of sector data is not
    evidence of concentration, and treating it as if it were would
    itself fabricate a fact this project's own honesty discipline
    (`data_infra.universe`'s module docstring) forbids. Securities are
    still considered in `ranked`'s own score order -- a lower-ranked
    security is only skipped, never promoted ahead of a higher-ranked
    one, so this changes WHICH `top_n` securities are picked, never how
    many or in what priority order."""
    if params.sector_by_security is None or params.max_per_sector is None:
        return set(ranked[: params.top_n])
    target: list[str] = []
    sector_counts: dict[str, int] = {}
    for security_id in ranked:
        if len(target) >= params.top_n:
            break
        sector = params.sector_by_security.get(security_id)
        if sector is not None:
            count = sector_counts.get(sector, 0)
            if count >= params.max_per_sector:
                continue
            sector_counts[sector] = count + 1
        target.append(security_id)
    return set(target)


def _orders_from_target(
    target: set[str], portfolio: PortfolioView, data: AsOfDataView, as_of_time: datetime,
) -> list[OrderIntent]:
    intents: list[OrderIntent] = []
    for security_id, position in portfolio.positions.items():
        if security_id not in target and position.quantity > 0:
            intents.append(OrderIntent(security_id, OrderSide.SELL, position.quantity, OrderType.MARKET))

    to_buy = [sid for sid in target if portfolio.quantity_of(sid) == 0]
    if to_buy:
        per_symbol_cash = portfolio.cash * (1.0 - _COST_SAFETY_MARGIN) / len(to_buy)
        for security_id in to_buy:
            bars = data.get_bars(security_id, as_of_time - timedelta(days=14), as_of_time)
            if not bars:
                continue
            price = bars[-1].close
            if price is None or price <= 0:
                continue
            quantity = float(int(per_symbol_cash / price))
            if quantity > 0:
                intents.append(OrderIntent(security_id, OrderSide.BUY, quantity, OrderType.MARKET))
    return intents


class PriceFactorStrategy:
    """Long-only, cross-sectional ranking by a price/volume-only
    `PriceScoreFn`, rebalanced by elapsed calendar months. See module
    docstring."""

    def __init__(
        self,
        security_ids: Sequence[str],
        score_fn: PriceScoreFn,
        *,
        version: str,
        params: FactorStrategyParameters = FactorStrategyParameters(),
    ) -> None:
        self._security_ids = list(security_ids)
        self._score_fn = score_fn
        self.version = version
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
            score = self._score_fn(security_id, as_of_time, data)
            if score is not None:
                scores[security_id] = score

        ranked = sorted(scores, key=lambda sid: scores[sid], reverse=True)
        target = _select_target(ranked, self._params)
        return _orders_from_target(target, portfolio, data, as_of_time)


class FundamentalsFactorStrategy:
    """Long-only, cross-sectional ranking by a fundamentals-only
    `FundamentalsScoreFn`, rebalanced by elapsed calendar months. Same
    shape `LeverageStrategy` hardcodes to `leverage_score` -- see module
    docstring."""

    def __init__(
        self,
        security_ids: Sequence[str],
        fundamentals_repository: object,
        score_fn: FundamentalsScoreFn,
        *,
        version: str,
        params: FactorStrategyParameters = FactorStrategyParameters(),
    ) -> None:
        self._security_ids = list(security_ids)
        self._fundamentals_repository = fundamentals_repository
        self._score_fn = score_fn
        self.version = version
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
            score = self._score_fn(security_id, as_of_time, self._fundamentals_repository)
            if score is not None:
                scores[security_id] = score

        ranked = sorted(scores, key=lambda sid: scores[sid], reverse=True)
        target = _select_target(ranked, self._params)
        return _orders_from_target(target, portfolio, data, as_of_time)


class HybridFactorStrategy:
    """Long-only, cross-sectional ranking by a `HybridScoreFn` needing
    BOTH the fundamentals repository and the RAW (not `AsOfDataView`)
    price repository -- see module docstring for why a third,
    separately-injected data handle is required here."""

    def __init__(
        self,
        security_ids: Sequence[str],
        fundamentals_repository: object,
        price_repository: object,
        score_fn: HybridScoreFn,
        *,
        version: str,
        params: FactorStrategyParameters = FactorStrategyParameters(),
    ) -> None:
        self._security_ids = list(security_ids)
        self._fundamentals_repository = fundamentals_repository
        self._price_repository = price_repository
        self._score_fn = score_fn
        self.version = version
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
            score = self._score_fn(
                security_id, as_of_time, self._fundamentals_repository, self._price_repository,
            )
            if score is not None:
                scores[security_id] = score

        ranked = sorted(scores, key=lambda sid: scores[sid], reverse=True)
        target = _select_target(ranked, self._params)
        return _orders_from_target(target, portfolio, data, as_of_time)


class UniverseFactorStrategy:
    """Long-only, cross-sectional ranking by a `UniverseScoreFn`
    (`signal_ic.UniverseScoreFn`) that computes the whole universe's
    scores in one call -- for `quality_minus_junk_score`/
    `value_composite_score`. See module docstring."""

    def __init__(
        self,
        security_ids: Sequence[str],
        fundamentals_repository: object,
        price_repository: object,
        score_fn: UniverseScoreFn,
        *,
        version: str,
        params: FactorStrategyParameters = FactorStrategyParameters(),
    ) -> None:
        self._security_ids = list(security_ids)
        self._fundamentals_repository = fundamentals_repository
        self._price_repository = price_repository
        self._score_fn = score_fn
        self.version = version
        self._params = params
        self._next_rebalance_time: Optional[datetime] = None

    def generate_orders(
        self, as_of_time: datetime, data: AsOfDataView, portfolio: PortfolioView
    ) -> list[OrderIntent]:
        if self._next_rebalance_time is not None and as_of_time < self._next_rebalance_time:
            return []
        self._next_rebalance_time = add_months(as_of_time, self._params.rebalance_months)

        scores = self._score_fn(
            self._security_ids, as_of_time, self._fundamentals_repository, self._price_repository,
        )
        ranked = sorted(scores, key=lambda sid: scores[sid], reverse=True)
        target = _select_target(ranked, self._params)
        return _orders_from_target(target, portfolio, data, as_of_time)
