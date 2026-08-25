"""Category: Backtest Integration Test -- instruction section 18: Phase
2's `BacktestEngine` is never touched by this phase, never calls a real
Toss adapter, and `MockBrokerAdapter` can deterministically simulate
every required broker-side scenario (accepted, rejected, partially
filled, filled, cancelled, timeout/unavailable) without ever producing a
real order."""

from __future__ import annotations

import ast
from pathlib import Path

import backtest
import pytest
from broker_helpers import make_broker_config, make_risk_checked_position, utc

from broker.enums import BrokerOrderStatus
from broker.errors import BrokerTransportError
from broker.mock import MockBrokerAdapter
from broker.validation import build_validated_order


def _order():
    rcp = make_risk_checked_position(final_target_quantity=40.0)
    return build_validated_order(rcp, current_quantity=0.0, configuration_version="cfg-v1").validated_order


class TestBacktestEngineUntouched:
    def test_backtest_package_never_imports_broker(self) -> None:
        package_dir = Path(backtest.__file__).parent
        for py_file in package_dir.rglob("*.py"):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module is not None and node.module.startswith("broker"):
                    raise AssertionError(f"{py_file.name} imports from {node.module}")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert not alias.name.startswith("broker"), f"{py_file.name} imports {alias.name}"


class TestMockBrokerSimulatesEveryRequiredScenario:
    def test_accepted(self) -> None:
        broker = MockBrokerAdapter(make_broker_config())
        response = broker.submit_order(_order(), requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.FILLED

    def test_rejected(self) -> None:
        broker = MockBrokerAdapter(make_broker_config(), failure_mode="rejected")
        response = broker.submit_order(_order(), requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.REJECTED

    def test_partially_filled(self) -> None:
        order = _order()
        broker = MockBrokerAdapter(make_broker_config(), failure_mode="partial_fill")
        response = broker.submit_order(order, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.PARTIAL_FILLED
        assert response.filled_quantity == order.quantity / 2.0

    def test_filled(self) -> None:
        broker = MockBrokerAdapter(make_broker_config())
        response = broker.submit_order(_order(), requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.FILLED

    def test_cancelled(self) -> None:
        order = _order()
        broker = MockBrokerAdapter(make_broker_config(), failure_mode="partial_fill")
        broker.submit_order(order, requested_at=utc(2024, 1, 2))
        response = broker.cancel_order(order.client_order_id, requested_at=utc(2024, 1, 2, 13))
        assert response.status == BrokerOrderStatus.CANCELED

    def test_timeout_broker_unavailable(self) -> None:
        broker = MockBrokerAdapter(make_broker_config(), failure_mode="unavailable")
        with pytest.raises(BrokerTransportError):
            broker.submit_order(_order(), requested_at=utc(2024, 1, 2))


class TestNoRealOrderIsEverProducedInTests:
    def test_no_test_file_in_this_repository_imports_toss_http_transport_except_its_own_unit_test(self) -> None:
        tests_dir = Path(__file__).resolve().parents[1]
        allowed = {"test_toss_transport.py", "test_broker_backtest_integration.py"}
        for py_file in tests_dir.rglob("*.py"):
            if py_file.name in allowed:
                continue
            source = py_file.read_text()
            assert "TossHttpTransport" not in source, f"{py_file} references the real network-capable transport"
