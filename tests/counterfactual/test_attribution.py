"""Unit tests for counterfactual.attribution.

See docs/specifications/PHASE-10-counterfactual-attribution.md section 4.
"""

from __future__ import annotations

import pytest
from counterfactual_helpers import make_experiment_record, make_performance_report

from counterfactual.attribution import (
    build_attribution_result,
    compute_market_attribution,
    compute_selection_attribution,
)


class TestMarketAttribution:
    def test_matches_benchmark_cumulative_return(self) -> None:
        metrics = make_performance_report(benchmark_cumulative_return=0.06)
        assert compute_market_attribution(metrics) == pytest.approx(0.06)

    def test_none_when_no_benchmark_was_configured(self) -> None:
        metrics = make_performance_report(benchmark_cumulative_return=None)
        assert compute_market_attribution(metrics) is None


class TestSelectionAttribution:
    def test_is_the_residual_after_market_and_execution(self) -> None:
        metrics = make_performance_report(cumulative_return=0.10, benchmark_cumulative_return=0.06)
        market = 0.06
        execution = -0.01
        selection = compute_selection_attribution(metrics, market, execution)
        assert selection == pytest.approx(0.10 - 0.06 - (-0.01))

    def test_none_when_market_is_none(self) -> None:
        metrics = make_performance_report(cumulative_return=0.10, benchmark_cumulative_return=None)
        assert compute_selection_attribution(metrics, None, -0.01) is None


class TestAttributionReconciles:
    """The one hard invariant this phase guarantees (ADR-0016 point 5):
    market + selection + execution == cumulative_return, exactly, whenever
    market is not None."""

    def test_components_sum_to_cumulative_return(self) -> None:
        metrics = make_performance_report(
            cumulative_return=0.137, total_transaction_cost=250.0, benchmark_cumulative_return=0.041,
        )
        experiment = make_experiment_record(initial_capital=25_000.0, metrics=metrics)
        result = build_attribution_result(experiment)
        assert result.market + result.selection + result.execution == pytest.approx(metrics.cumulative_return)

    def test_reconciles_even_with_a_loss(self) -> None:
        metrics = make_performance_report(
            cumulative_return=-0.05, total_transaction_cost=400.0, benchmark_cumulative_return=0.02,
        )
        experiment = make_experiment_record(initial_capital=10_000.0, metrics=metrics)
        result = build_attribution_result(experiment)
        assert result.market + result.selection + result.execution == pytest.approx(metrics.cumulative_return)


class TestBuildAttributionResult:
    def test_execution_matches_phase3_formula_unchanged(self) -> None:
        metrics = make_performance_report(total_transaction_cost=500.0)
        experiment = make_experiment_record(initial_capital=50_000.0, metrics=metrics)
        result = build_attribution_result(experiment)
        assert result.execution == pytest.approx(-0.01)

    def test_sector_factor_timing_stay_reserved(self) -> None:
        experiment = make_experiment_record()
        result = build_attribution_result(experiment)
        assert result.sector is None
        assert result.factor is None
        assert result.timing is None

    def test_experiment_id_is_carried_through(self) -> None:
        experiment = make_experiment_record(experiment_id="BT-000042")
        result = build_attribution_result(experiment)
        assert result.experiment_id == "BT-000042"

    def test_no_benchmark_leaves_market_and_selection_none_but_execution_still_computed(self) -> None:
        metrics = make_performance_report(benchmark_cumulative_return=None, total_transaction_cost=200.0)
        experiment = make_experiment_record(initial_capital=20_000.0, metrics=metrics)
        result = build_attribution_result(experiment)
        assert result.market is None
        assert result.selection is None
        assert result.execution == pytest.approx(-0.01)

    def test_computed_at_defaults_to_none_not_now(self) -> None:
        result = build_attribution_result(make_experiment_record())
        assert result.computed_at is None
