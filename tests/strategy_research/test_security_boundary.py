"""Category: Security / architecture boundary (instruction sections 33,
40, 41, 35-T). Static source scan over every file in
`src/strategy_research/` -- no wall-clock reads, no `random`, no new
`os.environ`/`os.getenv`, no network or broker imports, no Live
activation / model approval path."""

from __future__ import annotations

from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[2] / "src" / "strategy_research"

_FORBIDDEN_SUBSTRINGS = (
    "datetime.now(",
    "datetime.utcnow(",
    "import random",
    "from random",
    "os.environ",
    "os.getenv",
    "urllib.request",
    "requests.",
    "socket.",
    "broker.toss",
    "broker.live",
    "LiveTradingSession",
    "LiveActivationApproval",
    "CapabilityStatus.ENABLED",
)


def _all_source_files():
    return sorted(_SRC_DIR.rglob("*.py"))


class TestNoForbiddenPatterns:
    def test_strategy_research_package_contains_no_forbidden_substring(self) -> None:
        files = _all_source_files()
        assert len(files) >= 8, "sanity check: the strategy_research package should have several modules by now"
        violations = []
        for path in files:
            text = path.read_text()
            for forbidden in _FORBIDDEN_SUBSTRINGS:
                if forbidden in text:
                    violations.append(f"{path.relative_to(_SRC_DIR.parent.parent)}: contains {forbidden!r}")
        assert violations == [], "\n".join(violations)

    def test_no_module_imports_broker_or_network_modules(self) -> None:
        import ast

        forbidden_import_roots = {"broker", "urllib", "requests", "socket", "httpx"}
        violations = []
        for path in _all_source_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".")[0]
                        if root in forbidden_import_roots:
                            violations.append(f"{path.name}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    root = (node.module or "").split(".")[0]
                    if root in forbidden_import_roots:
                        violations.append(f"{path.name}: from {node.module} import ...")
        assert violations == [], "\n".join(violations)
