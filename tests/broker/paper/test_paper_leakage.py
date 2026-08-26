"""Category: Leakage / Point-in-Time Test -- instruction section 7, 35.
`PaperMarketDataSource` must never return a bar that would not yet have
been available at `as_of`; adding a future bar must never change a past
fill's result; `submit_order`/`advance_simulation`/`get_order_status`
all require explicit timestamps with no default."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import broker.paper

from paper_helpers import make_bar, make_paper_config, make_validated_order, utc

from broker.paper.adapter import PaperBrokerAdapter
from broker.paper.market_data import InMemoryPaperMarketDataSource


def _package_files():
    return list(Path(broker.paper.__file__).parent.rglob("*.py"))


class TestMarketDataSourceNeverReturnsFutureBar:
    def test_bar_registered_in_the_future_is_not_returned_for_a_past_as_of(self) -> None:
        mds = InMemoryPaperMarketDataSource([
            make_bar(timestamp=utc(2024, 1, 5), available_time=utc(2024, 1, 5), close=999.0),
        ])
        bar = mds.get_reference_bar("AAA", as_of=utc(2024, 1, 2))
        assert bar is None

    def test_bar_becomes_visible_only_at_or_after_its_available_time(self) -> None:
        mds = InMemoryPaperMarketDataSource([
            make_bar(timestamp=utc(2024, 1, 2), available_time=utc(2024, 1, 2), close=100.0),
        ])
        assert mds.get_reference_bar("AAA", as_of=utc(2024, 1, 1)) is None
        assert mds.get_reference_bar("AAA", as_of=utc(2024, 1, 2)) is not None


class TestFutureDataDoesNotChangePastResult:
    def test_adding_a_future_bar_does_not_change_an_already_submitted_fill(self) -> None:
        config = make_paper_config()
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2), close=100.0)])
        adapter = PaperBrokerAdapter(config, mds)
        order = make_validated_order(quantity=10.0)
        response_before = adapter.submit_order(order, requested_at=utc(2024, 1, 2))

        # a wildly different future bar becomes registered -- must not
        # retroactively change the fill that already happened at T
        mds.register(make_bar(timestamp=utc(2024, 6, 1), available_time=utc(2024, 6, 1), close=999.0))

        status_after = adapter.get_order_status(order.client_order_id, as_of=utc(2024, 1, 2))
        assert status_after.status == response_before.status
        assert status_after.filled_quantity == response_before.filled_quantity
        assert status_after.avg_fill_price == response_before.avg_fill_price

    def test_advance_simulation_at_a_past_as_of_ignores_a_later_registered_bar(self) -> None:
        """No bar at all exists for the order's security until a *future*
        one is registered -- advancing the simulation to a time still
        before that future bar's own `available_time` must see nothing,
        even though the bar object already exists in the source (it
        would not exist at that point in a real broker either)."""
        config = make_paper_config(max_participation=0.10)
        mds = InMemoryPaperMarketDataSource([])  # nothing available yet
        adapter = PaperBrokerAdapter(config, mds)
        order = make_validated_order(quantity=250.0)
        response = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert response.status.value == "PENDING"

        mds.register(make_bar(timestamp=utc(2024, 6, 1), available_time=utc(2024, 6, 1), volume=1_000.0))
        # advancing to a time still before the future bar's availability
        # must not see it
        updates = adapter.advance_simulation(utc(2024, 1, 3))
        assert updates == ()  # nothing new available at 2024-01-03


class TestExplicitTimestampsRequired:
    def test_submit_order_requested_at_has_no_default(self) -> None:
        params = inspect.signature(PaperBrokerAdapter.submit_order).parameters
        assert "requested_at" in params
        assert params["requested_at"].default is inspect.Parameter.empty

    def test_advance_simulation_as_of_has_no_default(self) -> None:
        params = inspect.signature(PaperBrokerAdapter.advance_simulation).parameters
        assert "as_of" in params
        assert params["as_of"].default is inspect.Parameter.empty

    def test_get_order_status_as_of_has_no_default(self) -> None:
        params = inspect.signature(PaperBrokerAdapter.get_order_status).parameters
        assert "as_of" in params
        assert params["as_of"].default is inspect.Parameter.empty

    def test_get_reference_bar_as_of_has_no_default(self) -> None:
        params = inspect.signature(InMemoryPaperMarketDataSource.get_reference_bar).parameters
        assert "as_of" in params
        assert params["as_of"].default is inspect.Parameter.empty


class TestNoWallClockCall:
    def test_no_now_or_utcnow_call_anywhere(self) -> None:
        for py_file in _package_files():
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in ("now", "utcnow"):
                    raise AssertionError(f"{py_file.name} calls datetime.{node.attr}()")
