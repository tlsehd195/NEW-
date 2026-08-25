"""Point-in-time / leakage protection tests.

See docs/specifications/PHASE-10-counterfactual-attribution.md section 5.
"""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest
from counterfactual_helpers import make_bars_repo, make_experiment_record, make_performance_report, utc
from journal_helpers import make_fill

from backtest.enums import OrderSide

from trade_journal.enums import DecisionAction, TradeProvenance
from trade_journal.models import TradeRecord

from counterfactual.attribution import build_attribution_result
from counterfactual.counterfactual import build_counterfactual_record, compute_cash_counterfactual

_SRC = Path(__file__).resolve().parents[2] / "src" / "counterfactual"


def _trade() -> TradeRecord:
    return TradeRecord(
        trade_id="TRD-000001", decision_id="DEC-000001", order_id="ORD-000001", security_id="AAA",
        timestamp=utc(2024, 1, 9), side=OrderSide.BUY, quantity=10.0, execution_price=110.0,
        reference_price=109.9, slippage=0.1, transaction_cost=1.0, position_after=10.0,
        fill=make_fill(), realized_pnl=100.0, realized_return=0.10,
        provenance=TradeProvenance.HISTORICAL_SIMULATION,
    )


class TestCashCounterfactualHasNoDataDependency:
    def test_never_imports_data_infra(self) -> None:
        tree = ast.parse((_SRC / "counterfactual.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                assert not node.module.startswith("data_infra") or node.module == "data_infra.repository", (
                    f"unexpected data_infra import: {node.module}"
                )


class TestHoldCounterfactualDoesNotSeeFutureBars:
    def test_recompute_after_future_bars_are_ingested_is_byte_identical(self) -> None:
        repo = make_bars_repo({date(2024, 1, 2): 100.0, date(2024, 1, 9): 110.0})
        trade = _trade()

        before = build_counterfactual_record(
            repo, trade, DecisionAction.BUY, decision_time=utc(2024, 1, 2), evaluation_time=utc(2024, 1, 9),
        )

        # Ingest bars *after* 2024-01-09 into the same repository -- future
        # data relative to the fixed evaluation_time above.
        repo_with_future = make_bars_repo(
            {date(2024, 1, 2): 100.0, date(2024, 1, 9): 110.0, date(2024, 2, 1): 500.0}
        )

        after = build_counterfactual_record(
            repo_with_future, trade, DecisionAction.BUY,
            decision_time=utc(2024, 1, 2), evaluation_time=utc(2024, 1, 9),
        )

        assert before == after


class TestAttributionMakesNoDataRepositoryCall:
    def test_build_attribution_result_signature_has_no_repository_parameter(self) -> None:
        import inspect

        params = inspect.signature(build_attribution_result).parameters
        assert "repository" not in params
        assert "data_repository" not in params

    def test_is_a_pure_function_of_its_experiment_input(self) -> None:
        metrics = make_performance_report(cumulative_return=0.10, benchmark_cumulative_return=0.06)
        experiment = make_experiment_record(metrics=metrics)
        first = build_attribution_result(experiment)
        second = build_attribution_result(experiment)
        assert first == second


class TestEvaluationTimeOrdering:
    def test_cash_counterfactual_rejects_evaluation_before_decision(self) -> None:
        with pytest.raises(ValueError):
            compute_cash_counterfactual(utc(2024, 1, 9), utc(2024, 1, 2))
