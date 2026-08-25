"""Category: Boundary Test -- Model Evolution never creates an order,
calls a broker, mutates a risk/position limit, or reaches
APPROVED/DEPLOYED (instruction section 19, 23; PROJECT_MASTER_PLAN.md
section 11.5)."""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import evolution

from evolution.comparison import compare_candidates
from evolution.criteria import evaluate_transition, next_status
from evolution.models import CandidateComparison, ModelLineageRecord, ModelStatusTransition
from evolution.trainer import TrailingWindowMeanTrainer

from learning.enums import CandidateModelStatus

_FORBIDDEN_FIELDS = {
    "order_id", "broker_order", "execution_price", "risk_limit", "position_limit",
    "kill_switch", "broker", "side", "quantity",
}
_FORBIDDEN_METHOD_NAMES = {
    "submit_order", "place_order", "execute", "send_order", "cancel_order", "create_order",
    "call_broker", "call_toss_api", "set_risk_limit", "set_position_limit", "release_kill_switch",
    "activate_live_trading", "approve", "deploy",
}


class TestNoOrderOrBrokerShapedFields:
    def test_no_forbidden_field_on_any_evolution_model(self) -> None:
        for cls in (ModelStatusTransition, ModelLineageRecord, CandidateComparison):
            field_names = {f.name for f in dataclasses.fields(cls)}
            assert field_names.isdisjoint(_FORBIDDEN_FIELDS), f"{cls.__name__} has a forbidden field"


class TestNoOrderOrBrokerOrRiskMutationMethod:
    def test_trainer_has_no_forbidden_method(self) -> None:
        public_attrs = {name for name in dir(TrailingWindowMeanTrainer) if not name.startswith("_")}
        assert public_attrs.isdisjoint(_FORBIDDEN_METHOD_NAMES)


class TestPipelineSignaturesTakeNoBrokerOrRiskInput:
    def test_evaluate_transition_signature_has_no_broker_or_risk_parameter(self) -> None:
        params = set(inspect.signature(evaluate_transition).parameters)
        assert params.isdisjoint({"broker", "risk_limit", "position_limit", "kill_switch"})

    def test_compare_candidates_signature_has_no_broker_or_risk_parameter(self) -> None:
        params = set(inspect.signature(compare_candidates).parameters)
        assert params.isdisjoint({"broker", "risk_limit", "position_limit", "kill_switch"})


class TestNeverReachesApprovedOrDeployed:
    def test_next_status_never_returns_approved_or_deployed(self) -> None:
        for status in CandidateModelStatus:
            try:
                result = next_status(status)
            except ValueError:
                continue
            assert result not in (CandidateModelStatus.APPROVED, CandidateModelStatus.DEPLOYED)

    def test_no_code_path_in_evolution_module_references_approved_or_deployed(self) -> None:
        package_dir = Path(evolution.__file__).parent
        forbidden = {"APPROVED", "DEPLOYED"}
        for py_file in package_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in forbidden:
                    raise AssertionError(f"{py_file.name} references CandidateModelStatus.{node.attr}")

    def test_no_evolution_function_has_an_approve_or_deploy_parameter_or_name(self) -> None:
        import evolution.comparison
        import evolution.criteria
        import evolution.lineage
        import evolution.pipeline
        import evolution.trainer

        forbidden_names = {"approve", "deploy", "approved", "deployed"}
        for module in (evolution.comparison, evolution.criteria, evolution.lineage, evolution.pipeline, evolution.trainer):
            for name, obj in vars(module).items():
                if inspect.isfunction(obj) or inspect.isclass(obj):
                    assert name.lower() not in forbidden_names, f"{module.__name__}.{name} looks like an approval/deploy entry point"
