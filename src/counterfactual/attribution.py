"""Performance Attribution.

See docs/specifications/PHASE-10-counterfactual-attribution.md section 4.
Phase 3's execution attribution (`trade_journal.analysis.
compute_execution_attribution`) is imported and reused unchanged. This
module adds the `market` and `selection` components, both computed
without any new DataRepository call -- they only read fields already
present on an already-computed backtest.experiment.ExperimentRecord.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from backtest.experiment import ExperimentRecord
from backtest.metrics import PerformanceReport

from trade_journal.analysis import compute_execution_attribution
from trade_journal.models import AttributionResult


def compute_market_attribution(metrics: PerformanceReport) -> Optional[float]:
    """The benchmark's own cumulative return over the identical
    experiment window -- already computed by Phase 2's BenchmarkEngine
    and carried on PerformanceReport. None exactly when no benchmark was
    configured for the experiment (honest absence, not a computed zero).
    Inherits Phase 2 spec section 9.3's still-open PRICE_RETURN vs
    TOTAL_RETURN DECISION REQUIRED unchanged (ADR-0016 point 4)."""
    return metrics.benchmark_cumulative_return


def compute_selection_attribution(
    metrics: PerformanceReport, market: Optional[float], execution: float
) -> Optional[float]:
    """Exact residual: cumulative_return - market - execution. None when
    market is None (nothing to subtract a market component from). This
    is a COMBINED selection-and-timing residual, not a claim of pure
    stock-picking skill -- see ADR-0016 point 5 and Phase 10 spec section
    4.3. By construction, market + selection + execution ==
    metrics.cumulative_return whenever market is not None."""
    if market is None:
        return None
    return metrics.cumulative_return - market - execution


def build_attribution_result(
    experiment: ExperimentRecord, computed_at: Optional[datetime] = None
) -> AttributionResult:
    """Reads experiment.metrics/initial_capital (both already persisted
    by Phase 4's ExperimentRepository) and returns the exact Phase 3
    AttributionResult type. sector/factor/timing stay None -- reserved,
    see Phase 10 spec section 2.2 / ADR-0016 points 6-7."""
    metrics = experiment.metrics
    market = compute_market_attribution(metrics)
    execution = compute_execution_attribution(metrics.total_transaction_cost, experiment.initial_capital)
    selection = compute_selection_attribution(metrics, market, execution)
    return AttributionResult(
        experiment_id=experiment.experiment_id,
        market=market,
        sector=None,
        factor=None,
        selection=selection,
        timing=None,
        execution=execution,
        computed_at=computed_at,
    )
