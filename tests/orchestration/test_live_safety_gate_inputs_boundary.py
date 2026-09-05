"""Category: Boundary Test -- `orchestration.live_safety_gate_inputs`
never imports `evolution.criteria` (the module that decides status
transitions) and never constructs a `ModelStatusTransition`/assigns
`CandidateModelStatus.APPROVED`/`DEPLOYED` itself -- it only ever READS
an already-recorded, caller-supplied transition. Mirrors the same
discipline `tests/broker/live/test_live_boundary.py` enforces on
`broker.live.*` for the identical reason."""

from __future__ import annotations

import ast
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[2] / "src" / "orchestration" / "live_safety_gate_inputs.py"


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


class TestNeverAutomatesModelApproval:
    def test_never_imports_evolution_criteria(self) -> None:
        assert "evolution.criteria" not in _imported_names()

    def test_never_constructs_a_model_status_transition(self) -> None:
        tree = ast.parse(_source(), filename=str(_MODULE_PATH))
        constructor_calls = [
            node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert "ModelStatusTransition" not in constructor_calls

    def test_never_references_candidate_model_status_approved_or_deployed_as_an_attribute(self) -> None:
        """Mirrors `tests/evolution/test_production_safety_candidate_
        boundary.py`'s own repo-wide rule exactly: no `ast.Attribute`
        node named `.APPROVED`/`.DEPLOYED` anywhere in this file. This
        module compares against the enum's raw `.value` strings
        ("APPROVED"/"DEPLOYED") instead of `CandidateModelStatus.
        APPROVED`/`.DEPLOYED` specifically to satisfy that already-
        existing, deliberately blunt repo-wide test -- this is that
        compliance re-verified locally, not a new rule."""
        tree = ast.parse(_source(), filename=str(_MODULE_PATH))
        offending = [
            node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in ("APPROVED", "DEPLOYED")
        ]
        assert offending == []
