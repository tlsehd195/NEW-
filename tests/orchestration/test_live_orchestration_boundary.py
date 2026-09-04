"""Category: Boundary Test -- `orchestration.live_runner` stays
Live-only (no Paper/Toss-adapter coupling) and never touches Candidate
model approval/deployment, mirroring `tests/orchestration/
test_orchestration_boundary.py`'s own discipline for `paper_runner.py`."""

from __future__ import annotations

import ast
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[2] / "src" / "orchestration" / "live_runner.py"


def _source() -> str:
    return _MODULE_PATH.read_text()


def _imported_names() -> set[str]:
    tree = ast.parse(_source(), filename=str(_MODULE_PATH))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
    return names


class TestNoPaperOrTossAdapterCoupling:
    def test_never_imports_broker_paper_or_orchestration_paper_runner(self) -> None:
        imported = _imported_names()
        assert not any(name.startswith("broker.paper") for name in imported)
        assert not any(name.startswith("orchestration.paper_runner") for name in imported)

    def test_never_imports_broker_toss_or_references_toss_adapter_by_name(self) -> None:
        imported = _imported_names()
        assert not any(name.startswith("broker.toss") for name in imported)
        source = _source()
        assert "TossBrokerAdapter" not in source

    def test_never_instantiates_a_paper_trading_session(self) -> None:
        """The module docstring legitimately DISCUSSES `PaperTradingSession`
        (explaining how Live's portfolio-state sourcing differs from
        Paper's) -- what must never happen is actually constructing one,
        i.e. calling it as a function. A plain text-containment check
        would false-positive on that prose, so this checks AST call
        nodes specifically."""
        tree = ast.parse(_source(), filename=str(_MODULE_PATH))
        constructor_calls = [
            node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert "PaperTradingSession" not in constructor_calls


class TestNoCandidateModelMutation:
    def test_never_references_approved_or_deployed_status(self) -> None:
        source = _source()
        assert "CandidateModelStatus.APPROVED" not in source
        assert "CandidateModelStatus.DEPLOYED" not in source
        assert "learning" not in _imported_names()


class TestNeverFabricatesSafetyGateContext:
    """The whole point of this module's design (see its own docstring
    point 2): it must never construct a `SafetyGateContext` from
    scratch -- only accept one, and `dataclasses.replace` exactly two of
    its fields (`order_validation_status`, `as_of_time`)."""

    def test_never_calls_safety_gate_context_as_a_constructor(self) -> None:
        tree = ast.parse(_source(), filename=str(_MODULE_PATH))
        constructor_calls = [
            node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert "SafetyGateContext" not in constructor_calls
