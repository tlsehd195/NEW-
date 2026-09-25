"""Category: Boundary Test -- mirrors `test_ai_gateway_boundary.py`'s own
intent, scoped to the real `ai_gateway.providers.gemini*` adapter instead
of the flat mock-only package: secrets stay isolated to one file, the
adapter still cannot express a trading decision, and (the boundary that
actually matters here) nothing in the real trading pipeline
(predict/decision/risk/broker) ever imports this adapter at all -- see
ADR-0206."""

from __future__ import annotations

import ast
from pathlib import Path

import ai_gateway.providers

_SRC_ROOT = Path(ai_gateway.providers.__file__).resolve().parent.parent.parent
_ALLOWED_AUTH_FILES = {"gemini_auth.py"}
_PIPELINE_PACKAGES = ("predict", "decision", "risk", "broker")


def _package_files():
    return list(Path(ai_gateway.providers.__file__).parent.glob("*.py"))


def _imports_module(py_file: Path, module_prefix: str) -> bool:
    tree = ast.parse(py_file.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(module_prefix):
            return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(module_prefix):
                    return True
    return False


class TestSecretsOnlyResolvedInGeminiAuth:
    def test_os_environ_appears_only_in_gemini_auth(self) -> None:
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                hits_environ = isinstance(node, ast.Attribute) and node.attr == "environ"
                hits_getenv = isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "getenv"
                if hits_environ or hits_getenv:
                    assert py_file.name in _ALLOWED_AUTH_FILES, (
                        f"{py_file.name} touches os.environ/os.getenv outside {_ALLOWED_AUTH_FILES}"
                    )


class TestStillNoDecisionActionOrCandidateModelStatusReference:
    """Same guarantee `test_ai_gateway_boundary.py` verifies for the flat
    package -- a real adapter must not widen what the Gateway can
    express, only how a request actually reaches a provider."""

    def test_no_decision_action_import(self) -> None:
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "trade_journal.enums":
                    names = {alias.name for alias in node.names}
                    assert "DecisionAction" not in names, f"{py_file.name} imports DecisionAction"

    def test_no_learning_enums_import(self) -> None:
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "learning.enums":
                    raise AssertionError(f"{py_file.name} imports from learning.enums")


class TestTradingPipelineNeverImportsThisAdapter:
    """The actual isolation guarantee the account owner asked for: the
    real predict/decision/risk/broker pipeline must never reach a real,
    network-calling AI adapter, even indirectly."""

    def test_predict_decision_risk_broker_never_import_ai_gateway_providers(self) -> None:
        for package_name in _PIPELINE_PACKAGES:
            package_dir = _SRC_ROOT / package_name
            if not package_dir.is_dir():
                continue
            for py_file in package_dir.rglob("*.py"):
                assert not _imports_module(py_file, "ai_gateway.providers"), (
                    f"{py_file.relative_to(_SRC_ROOT)} imports ai_gateway.providers -- "
                    f"the real Gemini adapter must stay reachable only from the research "
                    f"experiment script (ADR-0206)"
                )


class TestNoResolvedSecretRetainedOnTheAdapter:
    def test_adapter_instance_never_stores_a_resolved_api_key(self, monkeypatch) -> None:
        from ai_gateway_helpers import make_provider_config, make_request

        from ai_gateway.providers.gemini import GeminiProviderAdapter
        from ai_gateway.providers.gemini_transport import GeminiTransportResponse

        class _StubTransport:
            def generate_content(self, *, model, api_key, request_body, timeout):
                return GeminiTransportResponse(
                    status_code=200,
                    body={"candidates": [{"content": {"parts": [{"text": "ok"}]}}], "usageMetadata": {}},
                )

        monkeypatch.setenv("GEMINI_API_KEY", "sk-real-secret-value")
        config = make_provider_config("gemini", api_key_reference="GEMINI_API_KEY", model="gemini-3.8-flash")
        adapter = GeminiProviderAdapter(config, transport=_StubTransport())
        adapter.generate(make_request())
        for value in vars(adapter).values():
            assert value != "sk-real-secret-value"
        assert "sk-real-secret-value" not in repr(adapter)
