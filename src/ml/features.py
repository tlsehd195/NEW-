"""Feature registry (schema, per ML-RESEARCH-PROTOCOL.md section 8)
and feature-vector computation for the first ML model.

Every feature reuses an existing, already-point-in-time-safe score
function from `strategy_research.factor_scores`/`strategy_research.
long_term_momentum` -- this module adds no new signal logic, only
combines already-tested factors into a single feature vector per
`(security_id, as_of_time)`. This is deliberate: the ML question this
package asks is "does COMBINING these signals carry information the
individual signals didn't show," not "can we find a new hand-crafted
factor" (that remains `strategy_research`'s job).

**No imputation, ever.** If any one feature is unavailable for a given
`(security_id, as_of_time)` (missing fundamentals, insufficient price
history), `compute_feature_vector` returns `None` and the caller must
exclude that sample entirely -- never substitute a mean, a zero, or a
forward/backward fill. A model trained partly on fabricated feature
values would not be measuring the real predictive power of the actual
underlying data (the same "exclude, never fabricate" principle
`data_infra.quality`'s non-finite-value check and `DataRepository`'s
`available_time` guard already apply elsewhere in this codebase).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from backtest.asof import AsOfDataView

from strategy_research.factor_scores import (
    leverage_score,
    low_volatility_score,
    net_margin_score,
    roa_score,
    roe_score,
)
from strategy_research.long_term_momentum import LongTermMomentumParameters, LongTermMomentumStrategy
from strategy_research.signal_ic import FundamentalsScoreFn, ScoreFn


@dataclass(frozen=True)
class FeatureSpec:
    feature_id: str
    description: str
    source: str
    formula: str
    availability_time_rule: str
    lookback: str
    data_dependency: str
    known_leakage_risk: str
    version: str


def _momentum_score_fn(security_ids: Sequence[str]) -> ScoreFn:
    """Bound `_momentum_score` of a fresh `LongTermMomentumStrategy`
    instance with default parameters -- the exact same score
    `compute_signal_ic_from_catalog.py --strategy long_term_momentum`
    already evaluated (mean_ic=-0.0078, null on its own). Included as
    an ML feature anyway: a feature with no linear IC on its own can
    still carry information in combination with others, which is
    precisely the question this package exists to ask -- excluding it
    a priori would beg that question rather than answer it."""
    return LongTermMomentumStrategy(list(security_ids), LongTermMomentumParameters())._momentum_score


def build_price_feature_fns(security_ids: Sequence[str]) -> dict[str, ScoreFn]:
    """Price-derived feature functions bound to this specific universe
    (momentum's score function needs the full symbol list up front,
    matching `LongTermMomentumStrategy`'s own constructor requirement)."""
    return {
        "momentum": _momentum_score_fn(security_ids),
        "low_volatility": low_volatility_score,
    }


FUNDAMENTALS_FEATURE_FNS: dict[str, FundamentalsScoreFn] = {
    "roe": roe_score,
    "roa": roa_score,
    "net_margin": net_margin_score,
    "leverage": leverage_score,
}

FEATURE_SET_ID = "factor_scores_v1"

FEATURE_SPECS: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        feature_id="momentum", description="12-month trailing price momentum",
        source="strategy_research.long_term_momentum.LongTermMomentumStrategy._momentum_score",
        formula="(latest_close / close_12_months_ago) - 1",
        availability_time_rule="as_of_time (AsOfDataView-bound, price bars only)",
        lookback="12 months", data_dependency="price bars", known_leakage_risk="none (AsOfDataView-enforced)",
        version="v1",
    ),
    FeatureSpec(
        feature_id="low_volatility", description="negative trailing realized volatility",
        source="strategy_research.factor_scores.low_volatility_score",
        formula="-annualized_volatility(returns over trailing 126 trading days)",
        availability_time_rule="as_of_time (AsOfDataView-bound, price bars only)",
        lookback="126 trading days", data_dependency="price bars", known_leakage_risk="none (AsOfDataView-enforced)",
        version="v1",
    ),
    FeatureSpec(
        feature_id="roe", description="return on equity (FY-only)",
        source="strategy_research.factor_scores.roe_score",
        formula="NetIncomeLoss / StockholdersEquity, both fiscal_period=='FY'",
        availability_time_rule="available_time <= as_of_time (DuckDBFundamentalsRepository-enforced)",
        lookback="latest known fiscal year", data_dependency="SEC EDGAR fundamentals",
        known_leakage_risk="none (available_time is the actual SEC filing date)",
        version="v1",
    ),
    FeatureSpec(
        feature_id="roa", description="return on assets (FY-only)",
        source="strategy_research.factor_scores.roa_score",
        formula="NetIncomeLoss / Assets, both fiscal_period=='FY'",
        availability_time_rule="available_time <= as_of_time (DuckDBFundamentalsRepository-enforced)",
        lookback="latest known fiscal year", data_dependency="SEC EDGAR fundamentals",
        known_leakage_risk="none (available_time is the actual SEC filing date)",
        version="v1",
    ),
    FeatureSpec(
        feature_id="net_margin", description="net profit margin (FY-only)",
        source="strategy_research.factor_scores.net_margin_score",
        formula="NetIncomeLoss / Revenues, both fiscal_period=='FY'",
        availability_time_rule="available_time <= as_of_time (DuckDBFundamentalsRepository-enforced)",
        lookback="latest known fiscal year", data_dependency="SEC EDGAR fundamentals",
        known_leakage_risk="none (available_time is the actual SEC filing date)",
        version="v1",
    ),
    FeatureSpec(
        feature_id="leverage", description="negative of Liabilities/StockholdersEquity (FY-only)",
        source="strategy_research.factor_scores.leverage_score",
        formula="-(Liabilities / StockholdersEquity), both fiscal_period=='FY'",
        availability_time_rule="available_time <= as_of_time (DuckDBFundamentalsRepository-enforced)",
        lookback="latest known fiscal year", data_dependency="SEC EDGAR fundamentals",
        known_leakage_risk="none (available_time is the actual SEC filing date)",
        version="v1",
    ),
)

FEATURE_IDS: tuple[str, ...] = tuple(spec.feature_id for spec in FEATURE_SPECS)


def compute_feature_vector(
    security_id: str,
    as_of_time: datetime,
    price_score_fns: dict[str, ScoreFn],
    price_data_view: AsOfDataView,
    fundamentals_score_fns: dict[str, FundamentalsScoreFn],
    fundamentals_repository: object,
) -> Optional[dict[str, float]]:
    """All price-derived scores, then all fundamentals-derived scores,
    for one `(security_id, as_of_time)`. Returns `None` (never a
    partial dict) the moment any single feature comes back `None` --
    see module docstring on why imputation is never acceptable here."""
    values: dict[str, float] = {}
    for feature_id, fn in price_score_fns.items():
        value = fn(security_id, as_of_time, price_data_view)
        if value is None:
            return None
        values[feature_id] = value
    for feature_id, fn in fundamentals_score_fns.items():
        value = fn(security_id, as_of_time, fundamentals_repository)
        if value is None:
            return None
        values[feature_id] = value
    return values
