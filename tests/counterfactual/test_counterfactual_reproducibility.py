"""Reproducibility tests.

See docs/specifications/PHASE-10-counterfactual-attribution.md section 7.
Mirrors Phase 9's tests/learning/test_reproducibility.py pattern exactly.
"""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

from counterfactual_helpers import make_bars_repo, make_experiment_record, make_performance_report, utc
from journal_helpers import make_fill

from backtest.enums import OrderSide

from trade_journal.enums import DecisionAction, TradeProvenance
from trade_journal.models import TradeRecord

from counterfactual.attribution import build_attribution_result
from counterfactual.counterfactual import build_counterfactual_record, compute_cash_counterfactual

_SRC = Path(__file__).resolve().parents[2] / "src" / "counterfactual"


def _forbidden_calls(tree: ast.AST) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "random":
                    found.append("import random")
        if isinstance(node, ast.ImportFrom) and node.module == "random":
            found.append("from random import ...")
        if isinstance(node, ast.Call):
            func = node.func
            attr_chain = []
            cur = func
            while isinstance(cur, ast.Attribute):
                attr_chain.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                attr_chain.append(cur.id)
            dotted = ".".join(reversed(attr_chain))
            if dotted in ("datetime.now", "datetime.utcnow", "random.random"):
                found.append(dotted)
    return found


class TestNoNondeterminism:
    def test_no_file_under_src_counterfactual_uses_random_or_wall_clock(self) -> None:
        offenders = {}
        for path in _SRC.glob("*.py"):
            tree = ast.parse(path.read_text())
            found = _forbidden_calls(tree)
            if found:
                offenders[path.name] = found
        assert offenders == {}


class TestDeterminism:
    def test_cash_counterfactual_is_deterministic(self) -> None:
        first = compute_cash_counterfactual(utc(2024, 1, 2), utc(2024, 1, 9), risk_free_rate=0.03)
        second = compute_cash_counterfactual(utc(2024, 1, 2), utc(2024, 1, 9), risk_free_rate=0.03)
        assert first == second

    def test_counterfactual_record_is_deterministic_given_the_same_inputs(self) -> None:
        repo = make_bars_repo({date(2024, 1, 2): 100.0, date(2024, 1, 9): 110.0})
        trade = TradeRecord(
            trade_id="TRD-000001", decision_id="DEC-000001", order_id="ORD-000001", security_id="AAA",
            timestamp=utc(2024, 1, 9), side=OrderSide.BUY, quantity=10.0, execution_price=110.0,
            reference_price=109.9, slippage=0.1, transaction_cost=1.0, position_after=10.0,
            fill=make_fill(), realized_pnl=100.0, realized_return=0.10,
            provenance=TradeProvenance.HISTORICAL_SIMULATION,
        )
        first = build_counterfactual_record(
            repo, trade, DecisionAction.BUY, decision_time=utc(2024, 1, 2), evaluation_time=utc(2024, 1, 9),
        )
        second = build_counterfactual_record(
            repo, trade, DecisionAction.BUY, decision_time=utc(2024, 1, 2), evaluation_time=utc(2024, 1, 9),
        )
        assert first == second

    def test_attribution_result_is_deterministic_given_the_same_experiment(self) -> None:
        metrics = make_performance_report(cumulative_return=0.10, benchmark_cumulative_return=0.06)
        experiment = make_experiment_record(metrics=metrics)
        first = build_attribution_result(experiment)
        second = build_attribution_result(experiment)
        assert first == second
