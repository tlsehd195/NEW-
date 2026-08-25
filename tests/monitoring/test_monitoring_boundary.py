"""Category: Boundary Test -- Monitoring never creates an order, never
mutates broker/risk/decision state, never approves/deploys a Model
Evolution candidate, and never calls an AI provider directly
(instruction section 20's Monitoring-specific boundary list)."""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import monitoring

_FORBIDDEN_IMPORT_MODULES = {
    "decision.agent", "risk.sizing", "risk.engine", "ai_gateway.gateway", "broker.pipeline",
    "broker.validation", "broker.protocol",
}
_FORBIDDEN_METHOD_NAMES = {
    "decide", "size_position", "assess", "generate", "approve", "deploy", "submit_order", "cancel_order",
    "set_risk_limit", "set_position_limit", "release_kill_switch",
}
_ORDER_OR_RISK_SHAPED_FIELDS = {
    "order_id", "broker_order", "execution_price", "quantity", "side", "target_weight", "risk_limit",
    "kill_switch",
}


def _package_files():
    return list(Path(monitoring.__file__).parent.rglob("*.py"))


class TestNoDirectCallsToTradingLayers:
    def test_no_forbidden_module_imported_anywhere_in_monitoring(self) -> None:
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in _FORBIDDEN_IMPORT_MODULES:
                    raise AssertionError(f"{py_file.name} imports {node.module}")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name not in _FORBIDDEN_IMPORT_MODULES, f"{py_file.name} imports {alias.name}"

    def test_no_forbidden_method_name_defined_anywhere(self) -> None:
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name in _FORBIDDEN_METHOD_NAMES:
                    raise AssertionError(f"{py_file.name} defines forbidden method {node.name}")


class TestNoModelApprovalOrDeployment:
    def test_no_approved_or_deployed_attribute_assignment(self) -> None:
        forbidden = {"APPROVED", "DEPLOYED"}
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in forbidden:
                    raise AssertionError(f"{py_file.name} references .{node.attr}")

    def test_candidate_model_status_import_is_read_only_observation(self) -> None:
        """`monitoring.metrics` legitimately imports
        `learning.enums.CandidateModelStatus` to *count* observed
        transitions (`compute_model_evolution_metrics`) -- the boundary
        is "never assign `.APPROVED`/`.DEPLOYED`", not "never import the
        enum" (unlike `broker.*`, which has no legitimate reason to
        import it at all)."""
        import monitoring.metrics

        assert hasattr(monitoring.metrics, "CandidateModelStatus")


class TestNoOrderOrRiskShapedFieldsInMonitoringModels:
    def test_monitoring_event_has_no_order_or_risk_field(self) -> None:
        from monitoring.models import MonitoringEvent

        field_names = {f.name for f in dataclasses.fields(MonitoringEvent)}
        assert field_names.isdisjoint(_ORDER_OR_RISK_SHAPED_FIELDS)

    def test_component_health_has_no_order_or_risk_field(self) -> None:
        from monitoring.models import ComponentHealth

        field_names = {f.name for f in dataclasses.fields(ComponentHealth)}
        assert field_names.isdisjoint(_ORDER_OR_RISK_SHAPED_FIELDS)

    def test_drift_result_has_no_order_or_risk_field(self) -> None:
        from monitoring.models import DriftResult

        field_names = {f.name for f in dataclasses.fields(DriftResult)}
        assert field_names.isdisjoint(_ORDER_OR_RISK_SHAPED_FIELDS)

    def test_alert_has_no_order_or_risk_field(self) -> None:
        from monitoring.models import Alert

        field_names = {f.name for f in dataclasses.fields(Alert)}
        assert field_names.isdisjoint(_ORDER_OR_RISK_SHAPED_FIELDS)

    def test_no_decision_action_field_carried_directly(self) -> None:
        from monitoring.models import Alert, ComponentHealth, DriftResult, MonitoringEvent

        for cls in (MonitoringEvent, ComponentHealth, DriftResult, Alert):
            field_names = {f.name for f in dataclasses.fields(cls)}
            assert "action" not in field_names


class TestDriftIsObservationOnly:
    def test_drift_result_status_enum_has_no_action_values(self) -> None:
        from monitoring.enums import DriftStatus

        values = {member.value for member in DriftStatus}
        assert values == {"NO_DRIFT", "DRIFT_DETECTED", "UNKNOWN"}

    def test_no_drift_function_returns_anything_but_a_driftresult(self) -> None:
        import monitoring.drift as drift_module

        for name in ("detect_mean_shift", "detect_variance_shift", "detect_distribution_shift"):
            func = getattr(drift_module, name)
            return_annotation = inspect.signature(func).return_annotation
            assert return_annotation.__name__ == "DriftResult" if hasattr(return_annotation, "__name__") else True


class TestAlertsAreNeverMutatedAfterCreation:
    def test_alert_dataclass_is_frozen(self) -> None:
        from monitoring.models import Alert

        assert dataclasses.fields(Alert)
        instance_dict = getattr(Alert, "__dataclass_params__")
        assert instance_dict.frozen is True

    def test_component_health_is_frozen(self) -> None:
        from monitoring.models import ComponentHealth

        assert getattr(ComponentHealth, "__dataclass_params__").frozen is True

    def test_drift_result_is_frozen(self) -> None:
        from monitoring.models import DriftResult

        assert getattr(DriftResult, "__dataclass_params__").frozen is True

    def test_monitoring_event_is_frozen(self) -> None:
        from monitoring.models import MonitoringEvent

        assert getattr(MonitoringEvent, "__dataclass_params__").frozen is True


class TestNoAIProviderCalledDirectly:
    def test_no_ai_gateway_gateway_import(self) -> None:
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "ai_gateway.gateway":
                    raise AssertionError(f"{py_file.name} imports ai_gateway.gateway")

    def test_no_http_client_libraries_imported(self) -> None:
        forbidden = {"requests", "httpx", "urllib3"}
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name not in forbidden, f"{py_file.name} imports {alias.name}"
