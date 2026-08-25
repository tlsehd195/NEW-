"""Category: Reproducibility Test -- identical inputs produce identical
outputs everywhere in `ai_gateway.*`, and no module uses `random` or a
wall-clock call (the same discipline `learning`/`counterfactual`/
`evolution` already established, Phase 9/10/11)."""

from __future__ import annotations

import ast
from pathlib import Path

import ai_gateway
from ai_gateway_helpers import make_gateway_config, make_provider_config, make_request, utc

from ai_gateway.gateway import AIGateway
from ai_gateway.provider import MockProviderAdapter
from ai_gateway.quota_manager import QuotaManager
from ai_gateway.repository import InMemoryQuotaStateRepository


class TestNoRandomOrWallClockCalls:
    def test_no_random_import_anywhere(self) -> None:
        package_dir = Path(ai_gateway.__file__).parent
        for py_file in package_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name != "random", f"{py_file.name} imports random"
                if isinstance(node, ast.ImportFrom) and node.module == "random":
                    raise AssertionError(f"{py_file.name} imports from random")

    def test_no_now_or_utcnow_call_anywhere(self) -> None:
        package_dir = Path(ai_gateway.__file__).parent
        for py_file in package_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in ("now", "utcnow"):
                    raise AssertionError(f"{py_file.name} calls datetime.{node.attr}()")


def _run_once():
    a = make_provider_config("a", priority=0)
    b = make_provider_config("b", priority=1)
    config = make_gateway_config(a, b)
    qm = QuotaManager(InMemoryQuotaStateRepository())
    qm.initialize(a, at=utc(2024, 1, 1))
    qm.initialize(b, at=utc(2024, 1, 1))
    adapters = {"a": MockProviderAdapter(a), "b": MockProviderAdapter(b)}
    gateway = AIGateway(config, adapters, qm)
    request = make_request(response_schema=("action", "confidence"))
    response = gateway.generate(request, as_of=utc(2024, 1, 2))
    return response.content, response.provider_id, response.status, response.parsed


class TestDeterministicEndToEnd:
    def test_same_request_same_as_of_time_produces_identical_response(self) -> None:
        r1 = _run_once()
        r2 = _run_once()
        assert r1 == r2
