"""Category: Reproducibility Test -- identical inputs produce identical
outputs everywhere in `broker.*`, and no module uses `random` or a
wall-clock call (the same discipline `learning`/`evolution`/
`ai_gateway` already established)."""

from __future__ import annotations

import ast
from pathlib import Path

import broker
from broker_helpers import make_broker_config, make_risk_checked_position, utc

from broker.mock import MockBrokerAdapter
from broker.validation import build_validated_order


class TestNoRandomOrWallClockCalls:
    def test_no_random_import_anywhere(self) -> None:
        package_dir = Path(broker.__file__).parent
        for py_file in package_dir.rglob("*.py"):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name != "random", f"{py_file.name} imports random"
                if isinstance(node, ast.ImportFrom) and node.module == "random":
                    raise AssertionError(f"{py_file.name} imports from random")

    def test_no_now_or_utcnow_call_anywhere(self) -> None:
        package_dir = Path(broker.__file__).parent
        for py_file in package_dir.rglob("*.py"):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in ("now", "utcnow"):
                    raise AssertionError(f"{py_file.name} calls datetime.{node.attr}()")


def _run_once():
    rcp = make_risk_checked_position(final_target_quantity=40.0)
    result = build_validated_order(rcp, current_quantity=10.0, configuration_version="cfg-v1")
    broker_adapter = MockBrokerAdapter(make_broker_config())
    response = broker_adapter.submit_order(result.validated_order, requested_at=utc(2024, 1, 2, 13))
    return result.validated_order.client_order_id, response.status, response.filled_quantity


class TestDeterministicEndToEnd:
    def test_same_inputs_produce_identical_client_order_id_and_response(self) -> None:
        r1 = _run_once()
        r2 = _run_once()
        assert r1 == r2
