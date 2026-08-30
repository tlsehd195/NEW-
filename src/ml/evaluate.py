"""Out-of-sample evaluation for a fitted ML model: the same rank-IC
diagnostic `strategy_research.signal_ic` already applies to rule-based
scores, applied here to a fitted model's `predict()` output instead of
a hand-crafted formula -- this is the ONLY fair comparison against this
project's existing factor-IC results (mean_ic=+0.0782 for `leverage`,
etc.), since it is the same metric computed the same way.

The model here already trained on TRAIN before this function is ever
called; this module never fits anything, it only scores.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock
from data_infra.repository import DataRepository

from ml.features import compute_feature_vector
from ml.target import compute_target
from strategy_research.signal_ic import FundamentalsScoreFn, IcSummary, ScoreFn, spearman_ic, summarize_ic_observations
from strategy_research.signal_ic import IcObservation


def evaluate_model_ic(
    model,
    security_ids: Sequence[str],
    rebalance_dates: Sequence[datetime],
    price_score_fns: dict[str, ScoreFn],
    fundamentals_score_fns: dict[str, FundamentalsScoreFn],
    price_repository: DataRepository,
    fundamentals_repository: object,
) -> IcSummary:
    observations: list[IcObservation] = []
    for as_of_time in rebalance_dates:
        data_view = AsOfDataView(price_repository, BacktestClock(checkpoints=(as_of_time,)))
        predictions: dict[str, float] = {}
        for security_id in security_ids:
            features = compute_feature_vector(
                security_id, as_of_time, price_score_fns, data_view, fundamentals_score_fns, fundamentals_repository,
            )
            if features is None:
                continue
            predictions[security_id] = model.predict(features)

        forward_returns = {}
        for security_id in predictions:
            target = compute_target(price_repository, security_id, as_of_time)
            if target is not None:
                forward_returns[security_id] = target

        ic = spearman_ic(predictions, forward_returns)
        if ic is not None:
            observations.append(
                IcObservation(as_of_time=as_of_time, ic=ic, num_securities=len(forward_returns))
            )

    return summarize_ic_observations(observations)
