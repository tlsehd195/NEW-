"""Category: Point-in-Time Test -- instruction section 17: the Broker
Adapter never queries market data directly or recomputes a past
decision; every timestamp it acts on is supplied explicitly by the
caller, and no module here imports `data_infra.repository`/
`backtest.asof`."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import broker

from broker.mock import MockBrokerAdapter
from broker.protocol import BrokerAdapter
from broker.validation import build_validated_order


class TestNoDataRepositoryOrAsOfDataViewAccess:
    def test_no_data_repository_or_asof_dataview_import_anywhere(self) -> None:
        package_dir = Path(broker.__file__).parent
        for py_file in package_dir.rglob("*.py"):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in ("data_infra.repository", "backtest.asof"):
                    raise AssertionError(f"{py_file.name} imports from {node.module}")


class TestEveryTimestampIsExplicit:
    def test_submit_order_requires_explicit_requested_at(self) -> None:
        params = inspect.signature(BrokerAdapter.submit_order).parameters
        assert "requested_at" in params
        assert params["requested_at"].default is inspect.Parameter.empty

    def test_get_order_status_requires_explicit_as_of(self) -> None:
        params = inspect.signature(BrokerAdapter.get_order_status).parameters
        assert "as_of" in params
        assert params["as_of"].default is inspect.Parameter.empty

    def test_build_validated_order_uses_the_risk_checked_positions_own_as_of_time(self) -> None:
        """`ValidatedOrder.as_of_time` is copied from
        `RiskCheckedPosition.as_of_time` -- it is never derived from a
        wall-clock call or a caller-supplied "now" that could disagree
        with when the risk decision was actually made."""
        from broker_helpers import make_risk_checked_position, utc

        rcp = make_risk_checked_position(as_of_time=utc(2024, 5, 1), final_target_quantity=30.0)
        order = build_validated_order(rcp, current_quantity=0.0, configuration_version="cfg-v1").validated_order
        assert order.as_of_time == utc(2024, 5, 1)
