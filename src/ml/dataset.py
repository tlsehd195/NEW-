"""ML dataset assembly -- one `MLSample` per `(security_id,
as_of_time)` that has BOTH a complete feature vector and a computable
target, built by walking rebalance dates exactly the way `strategy_
research.signal_ic.compute_ic_series`/`compute_fundamentals_ic_series`
already do (same `AsOfDataView`/`BacktestClock` construction, same
"skip, never fabricate" handling of missing data).

Leakage guard (ML-RESEARCH-PROTOCOL.md section 4): every sample records
`feature_available_at`, `target_period_start`, `target_period_end`.
`feature_available_at` is always exactly `as_of_time` here, because
every feature function this package uses already enforces its own
`<= as_of_time` availability guard at the source (`AsOfDataView` for
price features, `DuckDBFundamentalsRepository` for fundamentals ones)
-- there is no separate "raw" feature value this module could leak by
reading past that boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock
from data_infra.repository import DataRepository

from ml.features import compute_feature_vector
from ml.target import HORIZON_DAYS, compute_target
from strategy_research.signal_ic import FundamentalsScoreFn, ScoreFn


@dataclass(frozen=True)
class MLSample:
    security_id: str
    as_of_time: datetime
    features: dict
    target: float
    feature_available_at: datetime
    target_period_start: datetime
    target_period_end: datetime


def build_ml_dataset(
    security_ids: Sequence[str],
    rebalance_dates: Sequence[datetime],
    price_score_fns: dict[str, ScoreFn],
    fundamentals_score_fns: dict[str, FundamentalsScoreFn],
    price_repository: DataRepository,
    fundamentals_repository: object,
) -> list[MLSample]:
    samples: list[MLSample] = []
    for as_of_time in rebalance_dates:
        data_view = AsOfDataView(price_repository, BacktestClock(checkpoints=(as_of_time,)))
        for security_id in security_ids:
            features = compute_feature_vector(
                security_id, as_of_time, price_score_fns, data_view, fundamentals_score_fns, fundamentals_repository,
            )
            if features is None:
                continue
            target = compute_target(price_repository, security_id, as_of_time)
            if target is None:
                continue
            samples.append(
                MLSample(
                    security_id=security_id,
                    as_of_time=as_of_time,
                    features=features,
                    target=target,
                    feature_available_at=as_of_time,
                    target_period_start=as_of_time,
                    target_period_end=as_of_time + timedelta(days=HORIZON_DAYS),
                )
            )
    return samples
