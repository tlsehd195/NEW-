"""Category: Boundary Test -- instruction sections 2, 11, 20, 35, 47.
Structurally verifies, by AST scan across the whole `broker.live`
package, that: no AI Gateway/Decision/Risk/Learning import exists, no
secret access exists outside `broker/toss/auth.py` (still the *only*
file in the whole repository allowed to touch `os.environ`), no
risk-limit mutation exists, no model-approval path exists,
`LiveActivationApproval` is constructed nowhere outside its own module
and this test's siblings, and `release_kill_switch` has exactly one
reachable call site in `src/`."""

from __future__ import annotations

import ast
from pathlib import Path

import broker.live


_FORBIDDEN_MODULES = {
    "ai_gateway.gateway", "decision.agent", "risk.sizing", "risk.engine", "learning.trainer",
    "evolution.criteria", "data_infra.repository", "backtest.asof",
}
_FORBIDDEN_NETWORK_MODULES = {"socket", "http", "http.client", "urllib", "urllib.request", "requests", "httpx"}
_ALLOWED_TOSS_REFERENCE_FILES = {"guard.py"}


def _package_files():
    return list(Path(broker.live.__file__).parent.rglob("*.py"))


class TestNoForbiddenModuleImport:
    def test_no_ai_decision_risk_learning_import_anywhere(self) -> None:
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in _FORBIDDEN_MODULES:
                    raise AssertionError(f"{py_file.name} imports {node.module}")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name not in _FORBIDDEN_MODULES, f"{py_file.name} imports {alias.name}"

    def test_no_toss_transport_or_toss_auth_import_except_guard(self) -> None:
        for py_file in _package_files():
            if py_file.name in _ALLOWED_TOSS_REFERENCE_FILES:
                continue
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in ("broker.toss.adapter", "broker.toss.transport", "broker.toss.auth"):
                    raise AssertionError(f"{py_file.name} imports {node.module}")

    def test_guard_never_constructs_or_calls_toss_adapter(self) -> None:
        guard_path = Path(broker.live.__file__).parent / "guard.py"
        tree = ast.parse(guard_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "TossBrokerAdapter":
                raise AssertionError("guard.py constructs a TossBrokerAdapter -- must only isinstance-check it")


class TestNoSecretOrNetworkAccess:
    def test_no_os_environ_or_getenv_anywhere(self) -> None:
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
                    if isinstance(node.value, ast.Name) and node.value.id == "os":
                        raise AssertionError(f"{py_file.name} references os.{node.attr}")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name != "os", f"{py_file.name} imports os"

    def test_no_network_module_imported_anywhere(self) -> None:
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name not in _FORBIDDEN_NETWORK_MODULES, f"{py_file.name} imports {alias.name}"
                if isinstance(node, ast.ImportFrom) and node.module in _FORBIDDEN_NETWORK_MODULES:
                    raise AssertionError(f"{py_file.name} imports from {node.module}")


class TestNoRiskLimitOrModelApprovalMutation:
    def test_no_risk_config_import(self) -> None:
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "risk.config":
                    raise AssertionError(f"{py_file.name} imports risk.config")

    def test_no_approved_or_deployed_attribute_reference(self) -> None:
        forbidden = {"APPROVED", "DEPLOYED"}
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in forbidden:
                    raise AssertionError(f"{py_file.name} references .{node.attr}")

    def test_no_forbidden_method_defined(self) -> None:
        forbidden = {"set_risk_limit", "set_position_limit", "approve", "deploy"}
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name in forbidden:
                    raise AssertionError(f"{py_file.name} defines forbidden method {node.name}")


class TestActivationApprovalIsHumanOnly:
    def test_live_activation_approval_constructed_nowhere_in_src_except_its_own_module(self) -> None:
        src_dir = Path(broker.live.__file__).parent.parent.parent  # src/
        for py_file in src_dir.rglob("*.py"):
            if "broker/live/approval.py" in str(py_file).replace("\\", "/"):
                continue
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "LiveActivationApproval":
                    raise AssertionError(f"{py_file} constructs LiveActivationApproval outside broker.live.approval")


class TestKillSwitchReleaseIsStructurallyUnreachableFromPipelineCode:
    def test_release_kill_switch_has_no_call_site_outside_its_own_module_and_session_wrapper(self) -> None:
        """`broker.live.session.LiveTradingSession.release_kill_switch` is
        the one allowed wrapper (it still requires the caller to supply a
        `LiveActivationApproval`) -- no *other* file in `src/` may call the
        module-level `release_kill_switch` function."""
        src_dir = Path(broker.live.__file__).parent.parent.parent  # src/
        allowed = {"kill_switch.py", "session.py"}
        for py_file in src_dir.rglob("*.py"):
            if py_file.name in allowed:
                continue
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "release_kill_switch":
                    raise AssertionError(f"{py_file} calls release_kill_switch directly")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "release_kill_switch":
                    # LiveTradingSession.release_kill_switch(...) is fine; a
                    # module-qualified call to the free function is not.
                    if isinstance(node.func.value, ast.Name) and node.func.value.id in ("broker_live_kill_switch", "kill_switch"):
                        raise AssertionError(f"{py_file} calls kill_switch.release_kill_switch directly")


class TestSafetyGateResultCarriesNoOrderShapedField:
    def test_no_order_or_risk_shaped_field_on_gate_result(self) -> None:
        import dataclasses

        from broker.live.safety_gate import SafetyGateResult

        field_names = {f.name for f in dataclasses.fields(SafetyGateResult)}
        forbidden = {"order_id", "quantity", "side", "price", "target_weight", "risk_limit"}
        assert field_names.isdisjoint(forbidden)


class TestGuardRejectsNonLiveBrokerInLiveEnvironmentByDefault:
    def test_paper_broker_rejected_in_live_environment_without_explicit_override(self) -> None:
        import pytest

        from broker.config import BrokerConfig
        from broker.live.guard import assert_live_environment_broker_safe
        from broker.mock import MockBrokerAdapter

        with pytest.raises(ValueError):
            assert_live_environment_broker_safe("live", MockBrokerAdapter(BrokerConfig()))

    def test_explicit_testing_override_permits_it(self) -> None:
        from broker.config import BrokerConfig
        from broker.live.guard import assert_live_environment_broker_safe
        from broker.mock import MockBrokerAdapter

        assert_live_environment_broker_safe(
            "live", MockBrokerAdapter(BrokerConfig()), allow_non_live_broker_for_testing=True,
        )  # must not raise

    def test_guard_is_a_no_op_outside_live_environment(self) -> None:
        from broker.live.guard import assert_live_environment_broker_safe

        assert_live_environment_broker_safe("paper", object())  # must not raise
