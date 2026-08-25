"""Category: Boundary Test -- the Broker Adapter never calls
Decision/PositionSizer/RiskEngine/AI Gateway directly, never bypasses
Order Validation, never reads a real secret outside `broker.toss.auth`,
and never auto-approves/deploys a Model Evolution candidate (instruction
section 20)."""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import broker
import broker.toss

_FORBIDDEN_IMPORT_MODULES = {
    "decision.agent", "risk.sizing", "risk.engine", "predict.predictor",
    "ai_gateway.gateway", "learning.enums",
}
_FORBIDDEN_METHOD_NAMES = {
    "decide", "size_position", "assess", "generate", "approve", "deploy",
    "set_risk_limit", "set_position_limit", "release_kill_switch",
}


def _package_files(package):
    return list(Path(package.__file__).parent.rglob("*.py"))


class TestNoDirectCallsToUpstreamDecisionLayers:
    def test_no_forbidden_module_imported_anywhere_in_broker(self) -> None:
        for py_file in _package_files(broker):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in _FORBIDDEN_IMPORT_MODULES:
                    raise AssertionError(f"{py_file.relative_to(Path(broker.__file__).parent)} imports {node.module}")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name not in _FORBIDDEN_IMPORT_MODULES, f"{py_file.name} imports {alias.name}"

    def test_broker_adapter_protocol_has_no_forbidden_method(self) -> None:
        from broker.protocol import BrokerAdapter

        public_attrs = {name for name in dir(BrokerAdapter) if not name.startswith("_")}
        assert public_attrs.isdisjoint(_FORBIDDEN_METHOD_NAMES)

    def test_mock_broker_adapter_has_no_forbidden_method(self) -> None:
        from broker.mock import MockBrokerAdapter

        public_attrs = {name for name in dir(MockBrokerAdapter) if not name.startswith("_")}
        assert public_attrs.isdisjoint(_FORBIDDEN_METHOD_NAMES)


class TestNoLearningOrModelEvolutionReference:
    def test_no_candidate_model_status_or_decision_action_import(self) -> None:
        for py_file in _package_files(broker):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module == "learning.enums":
                        raise AssertionError(f"{py_file.name} imports from learning.enums")
                    if node.module == "trade_journal.enums":
                        names = {alias.name for alias in node.names}
                        assert "DecisionAction" not in names, f"{py_file.name} imports DecisionAction"

    def test_no_approved_or_deployed_attribute_reference(self) -> None:
        forbidden = {"APPROVED", "DEPLOYED"}
        for py_file in _package_files(broker):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in forbidden:
                    raise AssertionError(f"{py_file.name} references .{node.attr}")


class TestNoOrderIsBuiltOutsideValidation:
    def test_validated_order_is_only_constructed_in_validation_module(self) -> None:
        """Every construction of `broker.models.ValidatedOrder(` outside
        `broker/validation.py`, `broker/models.py` itself, and test
        files is a structural violation of instruction section 4/5's
        "Broker Adapter가 BUY/SELL 판단을 스스로 내리지 않는다.\""""
        allowed_files = {"validation.py", "models.py"}
        for py_file in _package_files(broker):
            if py_file.name in allowed_files:
                continue
            source = py_file.read_text()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ValidatedOrder":
                    raise AssertionError(f"{py_file.name} constructs ValidatedOrder directly, bypassing broker.validation")


class TestNoOrderOrRiskShapedFieldMissing:
    def test_validated_order_has_no_prediction_or_risk_recomputation_field(self) -> None:
        from broker.models import ValidatedOrder

        field_names = {f.name for f in dataclasses.fields(ValidatedOrder)}
        assert field_names.isdisjoint({"expected_return", "target_weight", "risk_budget", "confidence"})


class TestExecutionModeGuard:
    def test_broker_config_default_execution_mode_is_offline(self) -> None:
        from broker.config import BrokerConfig
        from broker.enums import BrokerExecutionMode

        assert BrokerConfig().execution_mode == BrokerExecutionMode.OFFLINE

    def test_live_execution_mode_requires_explicit_opt_in(self) -> None:
        import pytest

        from broker.config import BrokerConfig
        from broker.enums import BrokerExecutionMode

        with pytest.raises(ValueError):
            BrokerConfig(execution_mode=BrokerExecutionMode.LIVE)  # live_opt_in defaults False

    def test_no_code_path_sets_live_opt_in_true_based_on_credential_presence_alone(self) -> None:
        """AST-level structural check: nowhere in `broker.*` does an
        `if credential ...:` / `if os.environ.get(...):`-shaped
        condition immediately gate a `live_opt_in=True`/`execution_mode=
        LIVE` construction -- the exact anti-pattern instruction section
        10 names explicitly."""
        for py_file in _package_files(broker):
            source = py_file.read_text()
            assert "if credential_exists" not in source
            # live_opt_in is only ever a literal keyword argument passed
            # by a caller, never computed from a conditional in this
            # package's own source.
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.keyword) and node.arg == "live_opt_in":
                    assert isinstance(node.value, (ast.Constant,)), (
                        f"{py_file.name} computes live_opt_in dynamically rather than a literal"
                    )


class TestSecretsOnlyResolvedInTossAuth:
    def test_os_environ_or_getenv_appears_only_in_toss_auth(self) -> None:
        allowed_file = "auth.py"
        allowed_dir = "toss"
        for py_file in _package_files(broker):
            relative = py_file.relative_to(Path(broker.__file__).parent)
            is_allowed = relative.parts == (allowed_dir, allowed_file)
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                hits_environ = isinstance(node, ast.Attribute) and node.attr == "environ"
                hits_getenv = isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "getenv"
                if hits_environ or hits_getenv:
                    assert is_allowed, f"{relative} touches os.environ/os.getenv outside broker/toss/auth.py"


class TestGenerateSignatureHasNoAiGatewayParameter:
    def test_submit_order_signature_has_no_ai_gateway_parameter(self) -> None:
        from broker.protocol import BrokerAdapter

        params = set(inspect.signature(BrokerAdapter.submit_order).parameters)
        assert params.isdisjoint({"ai_gateway", "gateway", "provider"})
