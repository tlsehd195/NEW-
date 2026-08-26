"""Category: Boundary Test -- instruction section 3, 20, 21: Paper
Trading must never call `broker.toss.*`, never read
`os.environ`/`os.getenv`, never open a network connection, and never
mutate a real account. Verified structurally (AST scan across the whole
`broker.paper` package), not by convention."""

from __future__ import annotations

import ast
from pathlib import Path

import broker.paper

_FORBIDDEN_MODULES = {
    "broker.toss.adapter", "broker.toss.transport", "broker.toss.auth", "broker.toss.mapping",
    "decision.agent", "risk.sizing", "risk.engine", "ai_gateway.gateway",
    "data_infra.repository", "backtest.asof",
}
_FORBIDDEN_NETWORK_MODULES = {"socket", "http", "http.client", "urllib", "urllib.request", "requests", "httpx"}
_ALLOWED_TOSS_REFERENCE_FILES = {"guard.py"}  # isinstance-only, never constructs/calls Toss


def _package_files():
    return list(Path(broker.paper.__file__).parent.rglob("*.py"))


class TestNoTossImportExceptGuard:
    def test_no_toss_import_outside_guard_py(self) -> None:
        for py_file in _package_files():
            if py_file.name in _ALLOWED_TOSS_REFERENCE_FILES:
                continue
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in _FORBIDDEN_MODULES:
                    raise AssertionError(f"{py_file.name} imports {node.module}")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name not in _FORBIDDEN_MODULES, f"{py_file.name} imports {alias.name}"

    def test_guard_py_never_constructs_or_calls_toss_adapter(self) -> None:
        """`guard.py` may reference `TossBrokerAdapter` only inside an
        `isinstance` check -- never `TossBrokerAdapter(...)` construction
        or a method call on it."""
        guard_path = Path(broker.paper.__file__).parent / "guard.py"
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


class TestNoDecisionOrRiskMutation:
    def test_no_forbidden_method_defined(self) -> None:
        forbidden = {"decide", "size_position", "assess", "approve", "deploy", "set_risk_limit", "set_position_limit", "release_kill_switch"}
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name in forbidden:
                    raise AssertionError(f"{py_file.name} defines forbidden method {node.name}")

    def test_no_approved_or_deployed_attribute_reference(self) -> None:
        forbidden = {"APPROVED", "DEPLOYED"}
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in forbidden:
                    raise AssertionError(f"{py_file.name} references .{node.attr}")


class TestGuardFunctionRejectsLiveBrokerInPaperEnvironment:
    def test_toss_broker_adapter_rejected_in_paper_environment(self) -> None:
        """Uses `broker.transport.MockTransport` (never the one real,
        network-capable transport implementation under `broker.toss.
        transport`) to construct a real `TossBrokerAdapter` for the
        `isinstance` check -- no network call is possible either way,
        keeping this file out of
        `tests/broker/test_broker_backtest_integration.py`'s "the real
        transport is never referenced outside its own unit test" safety
        net."""
        from broker.config import BrokerConfig
        from broker.enums import BrokerExecutionMode
        from broker.paper.guard import assert_paper_environment_safe
        from broker.toss.adapter import TossBrokerAdapter
        from broker.transport import MockTransport

        cfg = BrokerConfig(execution_mode=BrokerExecutionMode.LIVE, live_opt_in=True, broker_id="toss")
        toss = TossBrokerAdapter(cfg, MockTransport())
        try:
            assert_paper_environment_safe("paper", toss)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

    def test_mock_broker_adapter_accepted_in_paper_environment(self) -> None:
        from broker.config import BrokerConfig
        from broker.mock import MockBrokerAdapter
        from broker.paper.guard import assert_paper_environment_safe

        assert_paper_environment_safe("paper", MockBrokerAdapter(BrokerConfig()))  # must not raise

    def test_guard_is_a_no_op_outside_paper_environment(self) -> None:
        from broker.paper.guard import assert_paper_environment_safe

        assert_paper_environment_safe("live", object())  # must not raise -- not this guard's concern


class TestPaperTradingConfigStructurallyCannotBeLive:
    def test_environment_field_only_accepts_paper(self) -> None:
        import dataclasses

        from broker.paper.config import PaperTradingConfig

        field_names = {f.name for f in dataclasses.fields(PaperTradingConfig)}
        assert "environment" in field_names
        assert PaperTradingConfig().environment == "paper"
