"""Category: Reproducibility Test -- identical inputs produce identical
outputs everywhere in `broker.live.*`; no module uses `random`."""

from __future__ import annotations

import ast
from pathlib import Path

import broker.live

from live_helpers import make_passing_gate_context, utc

from broker.live.kill_switch import evaluate_kill_switch_triggers, KillSwitchTriggerContext
from broker.live.safety_gate import evaluate_safety_gate

from monitoring.enums import ComponentHealthStatus


def _package_files():
    return list(Path(broker.live.__file__).parent.rglob("*.py"))


class TestNoRandomImport:
    def test_no_random_import_anywhere(self) -> None:
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name != "random", f"{py_file.name} imports random"
                if isinstance(node, ast.ImportFrom) and node.module == "random":
                    raise AssertionError(f"{py_file.name} imports from random")


class TestDeterministicGate:
    def test_same_context_produces_identical_result(self) -> None:
        ctx = make_passing_gate_context()
        r1 = evaluate_safety_gate(ctx)
        r2 = evaluate_safety_gate(ctx)
        assert r1 == r2


class TestDeterministicKillSwitchTrigger:
    def test_same_context_produces_identical_reason(self) -> None:
        from broker.live.config import LiveTradingConfig

        ctx = KillSwitchTriggerContext(
            as_of_time=utc(2024, 1, 2), broker_health=ComponentHealthStatus.UNAVAILABLE,
            risk_health=ComponentHealthStatus.HEALTHY, monitoring_pipeline_health=ComponentHealthStatus.HEALTHY,
            account_state_known=True, position_state_known=True, daily_loss=None, orders_in_last_hour=None,
            config=LiveTradingConfig(),
        )
        assert evaluate_kill_switch_triggers(ctx) == evaluate_kill_switch_triggers(ctx)
