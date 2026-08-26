"""Category: Leakage / Point-in-Time Test -- every timestamp-sensitive
`broker.live.*` function requires an explicit parameter with no
default; nothing calls `datetime.now()`/`datetime.utcnow()`."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import broker.live

from broker.live.kill_switch import engage_kill_switch, evaluate_kill_switch_triggers, release_kill_switch
from broker.live.reconciliation import compare_account, compare_order_status, compare_positions
from broker.live.safety_gate import evaluate_safety_gate
from broker.live.session import LiveTradingSession, run_shutdown_checks, run_startup_checks


def _package_files():
    return list(Path(broker.live.__file__).parent.rglob("*.py"))


class TestNoWallClockCall:
    def test_no_now_or_utcnow_call_anywhere(self) -> None:
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in ("now", "utcnow"):
                    raise AssertionError(f"{py_file.name} calls datetime.{node.attr}()")


class TestExplicitTimestampsRequired:
    def test_engage_kill_switch_occurred_at_has_no_default(self) -> None:
        params = inspect.signature(engage_kill_switch).parameters
        assert params["occurred_at"].default is inspect.Parameter.empty

    def test_release_kill_switch_occurred_at_has_no_default(self) -> None:
        params = inspect.signature(release_kill_switch).parameters
        assert params["occurred_at"].default is inspect.Parameter.empty

    def test_compare_account_as_of_time_has_no_default(self) -> None:
        params = inspect.signature(compare_account).parameters
        assert params["as_of_time"].default is inspect.Parameter.empty

    def test_compare_positions_as_of_time_has_no_default(self) -> None:
        params = inspect.signature(compare_positions).parameters
        assert params["as_of_time"].default is inspect.Parameter.empty

    def test_compare_order_status_as_of_time_has_no_default(self) -> None:
        params = inspect.signature(compare_order_status).parameters
        assert params["as_of_time"].default is inspect.Parameter.empty

    def test_session_submit_requested_at_has_no_default(self) -> None:
        params = inspect.signature(LiveTradingSession.submit).parameters
        assert params["requested_at"].default is inspect.Parameter.empty

    def test_session_reconcile_order_as_of_has_no_default(self) -> None:
        params = inspect.signature(LiveTradingSession.reconcile_order).parameters
        assert params["as_of"].default is inspect.Parameter.empty

    def test_run_shutdown_checks_shutdown_at_has_no_default(self) -> None:
        params = inspect.signature(run_shutdown_checks).parameters
        assert params["shutdown_at"].default is inspect.Parameter.empty


class TestGateContextRequiresAwareTimestamp:
    def test_evaluate_safety_gate_rejects_naive_as_of_time(self) -> None:
        import pytest

        from datetime import datetime

        from broker.live.safety_gate import SafetyGateContext

        with pytest.raises(ValueError):
            SafetyGateContext(
                as_of_time=datetime(2024, 1, 2), config=None, approval=None, required_capabilities=(),
                broker_capabilities=None, risk_health=None, order_validation_status=None,
                kill_switch_engaged=False, account_state_known=False, position_state_known=False,
                model_state_valid=False, configuration_integrity_valid=False,
            )
