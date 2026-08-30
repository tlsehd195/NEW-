"""`MLStrategy`: puts the first ML model (ADR-0043) through the SAME
walk-forward + PBO/DSR pipeline the 5 rule-based strategy candidates
already went through -- the identical validation step this project
applied to `leverage_score`'s own promising raw Signal IC before
trusting it (`LeverageStrategy`, ADR-0042 Decision 13/14). The real
`leverage` result there (a strong raw IC that did NOT clear the
CANDIDATE fold-consistency bar once actually tested as a strategy) is
exactly the outcome this module exists to check for here too -- the
first ML VALIDATION result (mean_ic=+0.1055, IR=0.41, 11 observations)
must not be trusted on its own, for the same reason and then some: 11
observations is far fewer than any prior IC result this project has
computed, and that VALIDATION window (2019-12-29..2021-08-28) is
dominated by the COVID crash and recovery, an unusually extreme
regime.

**Why this needs its OWN in-strategy fitting, unlike every rule-based
strategy in this codebase**: `run_walk_forward_evaluation` calls a
zero-argument `strategy_factory: Callable[[], Strategy]` once per fold
and never tells the returned instance what that fold's train/test
boundaries are (see that module's own docstring: each fold's
`train_window_months` is "a sanity/documentation parameter," not
something plumbed into the strategy). Every existing strategy tolerates
this because none of them fit anything -- `leverage_score` etc. are
closed-form formulas evaluated fresh at whatever `as_of_time` arrives.
An ML model cannot work that way: it must be FIT on a TRAIN set before
it can predict anything.

**The fix needs no new plumbing in `walk_forward_evaluation.py`, only a
different strategy-side pattern**: exactly like `LongTermMomentumStrategy`'s
own 12-month lookback "automatically sees genuine train-period history
the moment the test window's first checkpoint fires" (that module's own
docstring), `MLStrategy` fits itself, lazily, the first time
`generate_orders` is ever called -- at that moment `as_of_time` IS the
fold's own `test_start`, so walking backward from it by
`train_window_months` reconstructs exactly that fold's own TRAIN
region, entirely through the already-clocked `AsOfDataView` the
Strategy Protocol already provides. Zero fold-boundary information
needs to reach this class from the outside.

**Leakage safety of the in-strategy fit, precisely**: every training
sample's target must be FULLY REALIZED by the live `as_of_time` the
fit is running at -- i.e. `training_date + horizon_days <= as_of_time`
-- so every `data.get_bars(security_id, start, end)` call the fit
issues (for both feature AND target computation) always has
`end <= as_of_time`, `AsOfDataView`'s own enforced ceiling. This is
strictly a NARROWER constraint than what `AsOfDataView` itself already
guarantees, not a new or separate guard.

**Why target computation here duplicates, rather than calls,
`strategy_research.signal_ic.forward_return`**: that function takes a
raw `data_infra.repository.DataRepository` and an explicit
caller-supplied `as_of_time` -- built for after-the-fact diagnostic
scripts that deliberately bypass `AsOfDataView` (see that module's own
docstring on why that bypass is correct there). A live `Strategy` must
never hold a raw repository reference at all -- `AsOfDataView`'s own
docstring states this codebase's central invariant explicitly: "There
is no method, override, or parameter through which a well-behaved
Strategy implementation could request data beyond the clock's current
checkpoint." Reusing `forward_return` here would require exactly that
violation. `_realized_return_via_view` below is the same handful of
lines of math, re-expressed against `AsOfDataView`'s narrower
interface, not a parallel leakage-guard mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from backtest.asof import AsOfDataView
from backtest.enums import OrderSide, OrderType
from backtest.portfolio import PortfolioView
from backtest.strategy import OrderIntent

from ml.dataset import MLSample
from ml.features import FEATURE_IDS, FUNDAMENTALS_FEATURE_FNS, build_price_feature_fns, compute_feature_vector
from ml.linear_model import LinearRegressionModel
from ml.target import HORIZON_DAYS
from strategy_research._dates import add_months

REBALANCE_MONTHS_RANGE = (1, 3)


@dataclass(frozen=True)
class MLStrategyParameters:
    top_n: int = 5
    rebalance_months: int = 3
    # Own internal fit-lookback -- decoupled from run_walk_forward_
    # evaluation's own train_window_months (which stays a rule-based-
    # strategy-only "documentation parameter", see module docstring).
    # 3 years balances "enough fiscal-year fundamentals snapshots and
    # rebalance-date samples to fit 6 features meaningfully" against
    # "refitting from scratch at every one of a walk-forward
    # evaluation's 70-100+ folds must stay tractable" -- fixed before
    # any fold's result is seen, not tuned against one.
    train_window_months: int = 36

    def __post_init__(self) -> None:
        if self.rebalance_months not in REBALANCE_MONTHS_RANGE:
            raise ValueError(f"rebalance_months must be one of {REBALANCE_MONTHS_RANGE}")
        if self.top_n < 1:
            raise ValueError("top_n must be >= 1")
        if self.train_window_months < 1:
            raise ValueError("train_window_months must be >= 1")


def _realized_return_via_view(
    data: AsOfDataView, security_id: str, start: datetime, horizon_days: int
) -> Optional[float]:
    """See module docstring's "why target computation here duplicates,
    rather than calls, forward_return" -- same math, `AsOfDataView`
    interface. Caller is responsible for `start + horizon_days <=
    as_of_time` (the live checkpoint `data` is bound to); this function
    does not and cannot check that itself since `AsOfDataView` never
    exposes its own current_time-independent ceiling to the caller
    beyond what `get_bars` already silently applies."""
    end = start + timedelta(days=horizon_days)
    bars = data.get_bars(security_id, start, end)
    if len(bars) < 2:
        return None
    start_price = bars[0].adjusted_close or bars[0].close
    end_price = bars[-1].adjusted_close or bars[-1].close
    if start_price <= 0:
        return None
    return end_price / start_price - 1.0


class MLStrategy:
    """Long-only, cross-sectional ranking by a lazily-self-fit OLS
    model's predicted forward return, rebalanced by elapsed calendar
    months -- portfolio construction identical to `LeverageStrategy`'s
    (equal-weight among newly-entering top-N), for the same reason:
    isolating "does the model's ranking carry information" from "does a
    more elaborate sizing scheme help or hurt." See module docstring
    for the fitting mechanism and its leakage-safety argument."""

    version = "ml_ols_v1"
    COST_SAFETY_MARGIN = 0.02

    # Training-sample cadence used ONLY inside `_fit`, deliberately
    # decoupled from `params.rebalance_months` (the LIVE rebalance
    # cadence). Fundamentals features only change once per fiscal year
    # (FY-only, per factor_scores.py) -- sampling training dates every
    # 3 months (the default live cadence) recomputes the same
    # fundamentals values 4x over per training sample, buying no new
    # information for real cost: this lazily-fit-per-fold design
    # already refits from scratch at every fold's first checkpoint
    # (walk-forward evaluation routinely has 70-100+ folds), so this
    # constant is a real, measured performance requirement, not
    # speculative tuning -- profiled at ~2s/fit for 5 synthetic
    # symbols at 3-month cadence; a real 39-symbol run would not
    # complete in reasonable time otherwise.
    TRAIN_SAMPLE_STEP_MONTHS = 6

    def __init__(
        self,
        security_ids: Sequence[str],
        fundamentals_repository: object,
        params: MLStrategyParameters = MLStrategyParameters(),
    ) -> None:
        self._security_ids = list(security_ids)
        self._fundamentals_repository = fundamentals_repository
        self._params = params
        self._price_score_fns = build_price_feature_fns(self._security_ids)
        self._model: Optional[LinearRegressionModel] = None
        self._fit_attempted = False
        self._next_rebalance_time: Optional[datetime] = None

    def _fit(self, as_of_time: datetime, data: AsOfDataView) -> Optional[LinearRegressionModel]:
        horizon = timedelta(days=HORIZON_DAYS)
        latest_training_date = as_of_time - horizon
        training_dates = []
        cursor = add_months(as_of_time, -self._params.train_window_months)
        while cursor <= latest_training_date:
            training_dates.append(cursor)
            cursor = add_months(cursor, self.TRAIN_SAMPLE_STEP_MONTHS)
        if not training_dates:
            return None

        samples: list[MLSample] = []
        for training_date in training_dates:
            for security_id in self._security_ids:
                features = compute_feature_vector(
                    security_id, training_date, self._price_score_fns, data,
                    FUNDAMENTALS_FEATURE_FNS, self._fundamentals_repository,
                )
                if features is None:
                    continue
                target = _realized_return_via_view(data, security_id, training_date, HORIZON_DAYS)
                if target is None:
                    continue
                samples.append(
                    MLSample(
                        security_id=security_id, as_of_time=training_date, features=features, target=target,
                        feature_available_at=training_date, target_period_start=training_date,
                        target_period_end=training_date + horizon,
                    )
                )
        if not samples:
            return None

        model = LinearRegressionModel(feature_ids=list(FEATURE_IDS))
        try:
            model.fit(samples)
        except ValueError:
            # Singular normal-equations matrix (e.g. too few distinct
            # samples for this fold) -- no signal, never a fabricated
            # fallback fit (mirrors this project's non-finite-value/
            # missing-feature honesty elsewhere).
            return None
        return model

    def generate_orders(
        self, as_of_time: datetime, data: AsOfDataView, portfolio: PortfolioView
    ) -> list[OrderIntent]:
        if not self._fit_attempted:
            self._fit_attempted = True
            self._model = self._fit(as_of_time, data)
        if self._model is None:
            return []

        if self._next_rebalance_time is not None and as_of_time < self._next_rebalance_time:
            return []
        self._next_rebalance_time = add_months(as_of_time, self._params.rebalance_months)

        scores: dict[str, float] = {}
        for security_id in self._security_ids:
            features = compute_feature_vector(
                security_id, as_of_time, self._price_score_fns, data,
                FUNDAMENTALS_FEATURE_FNS, self._fundamentals_repository,
            )
            if features is not None:
                scores[security_id] = self._model.predict(features)

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
