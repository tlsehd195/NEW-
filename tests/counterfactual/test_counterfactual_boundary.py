"""Structural boundary tests.

See docs/specifications/PHASE-10-counterfactual-attribution.md section 8.
Mirrors every prior phase's test_*_boundary.py reflection/AST-scan
technique (test_decision_boundary.py, test_risk_boundary.py,
test_learning_boundary.py).
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

from trade_journal.models import AttributionResult, CounterfactualRecord

from counterfactual import attribution, counterfactual, pipeline, repository

_SRC = Path(__file__).resolve().parents[2] / "src" / "counterfactual"

_FORBIDDEN_NAMES = {
    "Order",
    "OrderStatus",
    "RiskCheckedPosition",
    "PositionSizingResult",
    "PortfolioRiskState",
}
_FORBIDDEN_ATTRS = {"APPROVED", "DEPLOYED"}


class TestNoOrderBrokerRiskShapedFields:
    def test_counterfactual_record_has_no_order_or_risk_shaped_field(self) -> None:
        names = {f.name for f in dataclasses.fields(CounterfactualRecord)}
        forbidden = {"order_id", "broker_order", "execution_price", "quantity", "risk_id", "sizing_id"}
        assert names.isdisjoint(forbidden)

    def test_attribution_result_has_no_order_or_risk_shaped_field(self) -> None:
        names = {f.name for f in dataclasses.fields(AttributionResult)}
        forbidden = {"order_id", "broker_order", "execution_price", "quantity", "risk_id", "sizing_id"}
        assert names.isdisjoint(forbidden)


class TestNoOrderBrokerRiskConstruction:
    """AST scan: no file under src/counterfactual constructs an Order,
    a RiskCheckedPosition/PositionSizingResult, or references
    CandidateModelStatus.APPROVED/DEPLOYED."""

    def test_no_forbidden_construction_anywhere_in_the_package(self) -> None:
        offenders: dict[str, list[str]] = {}
        for path in _SRC.glob("*.py"):
            tree = ast.parse(path.read_text())
            found = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
                    found.append(node.id)
                if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_ATTRS:
                    found.append(node.attr)
            if found:
                offenders[path.name] = found
        assert offenders == {}


class TestNoOrderBrokerRiskParametersInPublicFunctions:
    def test_pipeline_functions_take_no_order_broker_or_risk_override_parameter(self) -> None:
        forbidden_params = {"order", "broker", "broker_order", "risk_override", "execution_price"}
        for module in (counterfactual, attribution, pipeline, repository):
            for name, obj in inspect.getmembers(module, inspect.isfunction):
                params = set(inspect.signature(obj).parameters)
                assert params.isdisjoint(forbidden_params), f"{module.__name__}.{name} has forbidden param"
