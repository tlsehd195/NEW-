"""Category: Boundary Test -- `orchestration.paper_runner` stays
Paper-only (no Live/Toss coupling) and never touches Candidate model
approval/deployment, mirroring the same AST/source-level discipline
`tests/broker/paper/test_paper_boundary.py` and `tests/learning/
test_learning_boundary.py` already apply to their own packages."""

from __future__ import annotations

import ast
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[2] / "src" / "orchestration" / "paper_runner.py"


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


class TestNoLiveOrTossCoupling:
    def test_never_imports_broker_live_or_broker_toss(self) -> None:
        imported = _imported_names()
        assert not any(name.startswith("broker.live") for name in imported)
        assert not any(name.startswith("broker.toss") for name in imported)

    def test_never_references_live_trading_session_or_toss_adapter_by_name(self) -> None:
        source = _source()
        assert "LiveTradingSession" not in source
        assert "TossBrokerAdapter" not in source


class TestNoCandidateModelMutation:
    def test_never_references_approved_or_deployed_status(self) -> None:
        source = _source()
        assert "CandidateModelStatus.APPROVED" not in source
        assert "CandidateModelStatus.DEPLOYED" not in source
        assert "learning" not in _imported_names()
