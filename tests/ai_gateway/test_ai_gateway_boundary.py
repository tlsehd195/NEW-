"""Category: Boundary Test -- the AI Gateway never creates an order,
calls a broker, mutates a risk/position limit, produces a
`DecisionAction`, auto-approves/deploys a Model Evolution candidate, or
reads a real secret/environment variable (instruction sections 4, 5, 9,
11; PROJECT_MASTER_PLAN.md sections 1.5, 3, 5)."""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import ai_gateway

from ai_gateway.config import GatewayConfig, ProviderConfig
from ai_gateway.gateway import AIGateway
from ai_gateway.models import AIRequest, AIResponse, ProviderQuotaState
from ai_gateway.provider import MockProviderAdapter
from ai_gateway.provider_selector import ProviderSelector
from ai_gateway.quota_manager import QuotaManager
from ai_gateway.task_router import TaskRouter

_FORBIDDEN_FIELDS = {
    "order_id", "broker_order", "execution_price", "risk_limit", "position_limit",
    "kill_switch", "broker", "side", "quantity", "target_weight",
}
_FORBIDDEN_METHOD_NAMES = {
    "submit_order", "place_order", "execute", "send_order", "cancel_order", "create_order",
    "call_broker", "call_toss_api", "set_risk_limit", "set_position_limit", "release_kill_switch",
    "activate_live_trading", "approve", "deploy", "decide", "size_position",
}


def _package_files():
    return list(Path(ai_gateway.__file__).parent.glob("*.py"))


class TestNoOrderOrBrokerOrRiskShapedFields:
    def test_no_forbidden_field_on_any_ai_gateway_model(self) -> None:
        for cls in (AIRequest, AIResponse, ProviderQuotaState, ProviderConfig, GatewayConfig):
            field_names = {f.name for f in dataclasses.fields(cls)}
            assert field_names.isdisjoint(_FORBIDDEN_FIELDS), f"{cls.__name__} has a forbidden field"


class TestNoOrderBrokerRiskOrDecisionMutationMethod:
    def test_gateway_has_no_forbidden_method(self) -> None:
        public_attrs = {name for name in dir(AIGateway) if not name.startswith("_")}
        assert public_attrs.isdisjoint(_FORBIDDEN_METHOD_NAMES)

    def test_quota_manager_has_no_forbidden_method(self) -> None:
        public_attrs = {name for name in dir(QuotaManager) if not name.startswith("_")}
        assert public_attrs.isdisjoint(_FORBIDDEN_METHOD_NAMES)

    def test_provider_selector_has_no_forbidden_method(self) -> None:
        public_attrs = {name for name in dir(ProviderSelector) if not name.startswith("_")}
        assert public_attrs.isdisjoint(_FORBIDDEN_METHOD_NAMES)

    def test_task_router_has_no_forbidden_method(self) -> None:
        public_attrs = {name for name in dir(TaskRouter) if not name.startswith("_")}
        assert public_attrs.isdisjoint(_FORBIDDEN_METHOD_NAMES)


class TestGenerateSignatureHasNoBrokerRiskOrDataAccessParameter:
    def test_gateway_generate_signature(self) -> None:
        params = set(inspect.signature(AIGateway.generate).parameters)
        assert params.isdisjoint({"broker", "risk_limit", "position_limit", "kill_switch", "repository", "data_repository"})


class TestNoDecisionActionOrCandidateModelStatusReference:
    """Nothing in ai_gateway.* imports or references
    trade_journal.enums.DecisionAction or
    learning.enums.CandidateModelStatus -- the Gateway cannot express a
    trading decision or a Model Evolution approval/deployment even by
    accident, because the vocabulary to do so is never imported."""

    def test_no_decision_action_import(self) -> None:
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "trade_journal.enums":
                    names = {alias.name for alias in node.names}
                    assert "DecisionAction" not in names, f"{py_file.name} imports DecisionAction"

    def test_no_candidate_model_status_import(self) -> None:
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "learning.enums":
                    raise AssertionError(f"{py_file.name} imports from learning.enums")

    def test_no_approved_or_deployed_attribute_reference(self) -> None:
        forbidden = {"APPROVED", "DEPLOYED"}
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in forbidden:
                    raise AssertionError(f"{py_file.name} references .{node.attr}")


class TestNoRealSecretAccess:
    """PROJECT_MASTER_PLAN.md section 5/instruction section 5: no real
    provider is called this phase, so nothing here ever needs to resolve
    `ProviderConfig.api_key_reference` to an actual secret value."""

    def test_no_os_environ_or_getenv_call_anywhere(self) -> None:
        for py_file in _package_files():
            source = py_file.read_text()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "environ":
                    raise AssertionError(f"{py_file.name} references os.environ")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "getenv":
                    raise AssertionError(f"{py_file.name} calls os.getenv")

    def test_no_field_literally_named_api_key(self) -> None:
        field_names = {f.name for f in dataclasses.fields(ProviderConfig)}
        assert "api_key" not in field_names
        assert "secret" not in field_names
        assert "credential" not in field_names
        assert "api_key_reference" in field_names


class TestNoNewDataRepositoryOrAsOfDataViewAccess:
    """PROJECT_MASTER_PLAN.md's point-in-time principle, applied here:
    the Gateway does not go looking for its own market/decision data --
    every input is a plain, already-built `AIRequest` the caller
    assembled."""

    def test_no_data_repository_or_asof_dataview_import(self) -> None:
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module in ("data_infra.repository", "backtest.asof"):
                        raise AssertionError(f"{py_file.name} imports from {node.module}")


class TestMockAdapterProvesTheInterfaceOffline:
    def test_mock_provider_adapter_makes_no_network_call(self) -> None:
        # a structural proxy for "offline": no `socket`/`http`/`urllib`/
        # `requests` import anywhere in the package (this project's own
        # pyproject.toml declares no such dependency either).
        forbidden_modules = {"socket", "http", "http.client", "urllib", "urllib.request", "requests", "httpx"}
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name not in forbidden_modules, f"{py_file.name} imports {alias.name}"
                if isinstance(node, ast.ImportFrom) and node.module in forbidden_modules:
                    raise AssertionError(f"{py_file.name} imports from {node.module}")

    def test_mock_adapter_is_the_only_shipped_adapter_class(self) -> None:
        import ai_gateway.provider as provider_module

        adapter_like = [
            name for name, obj in vars(provider_module).items()
            if inspect.isclass(obj) and hasattr(obj, "generate") and not name.startswith("_")
            and name != "AIProviderAdapter"
        ]
        assert adapter_like == ["MockProviderAdapter"]
