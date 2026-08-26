"""Category: Reproducibility Test -- identical inputs produce identical
outputs everywhere in `broker.paper.*`; no module uses `random`."""

from __future__ import annotations

import ast
from pathlib import Path

import broker.paper

from paper_helpers import make_bar, make_paper_config, make_validated_order, utc

from broker.paper.adapter import PaperBrokerAdapter
from broker.paper.market_data import InMemoryPaperMarketDataSource


def _package_files():
    return list(Path(broker.paper.__file__).parent.rglob("*.py"))


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


def _run_once():
    config = make_paper_config(max_participation=0.10)
    mds = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2), volume=1_000.0)])
    adapter = PaperBrokerAdapter(config, mds)
    order = make_validated_order(quantity=250.0)
    response = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
    mds.register(make_bar(timestamp=utc(2024, 1, 3), available_time=utc(2024, 1, 3), volume=1_000.0))
    updates = adapter.advance_simulation(utc(2024, 1, 3))
    account = adapter.get_account(as_of=utc(2024, 1, 3))
    return response.status, response.filled_quantity, tuple(u.status for u in updates), account.cash


class TestDeterministicEndToEnd:
    def test_same_inputs_produce_identical_results(self) -> None:
        r1 = _run_once()
        r2 = _run_once()
        assert r1 == r2

    def test_config_configuration_version_is_deterministic(self) -> None:
        c1 = make_paper_config(initial_cash=250_000.0).configuration_version()
        c2 = make_paper_config(initial_cash=250_000.0).configuration_version()
        assert c1 == c2
