"""Category: Decision snapshot integrity.
Category: Immutable snapshot.
Category: Point-in-time snapshot.

See docs/specifications/PHASE-3-trade-journal.md sections 4, 5.1, 9.
"""

from __future__ import annotations

import dataclasses

import pytest
from journal_helpers import make_order, utc

from backtest.portfolio import PortfolioAccounting
from trade_journal.enums import DecisionAction, TradeProvenance
from trade_journal.repository import InMemoryTradeJournalRepository


class TestDecisionSnapshotIntegrity:
    def test_record_decision_populates_required_fields(self) -> None:
        journal = InMemoryTradeJournalRepository()
        order = make_order()
        snapshot = journal.record_decision(
            decision_time=order.decision_time,
            security_id="AAA",
            decision=DecisionAction.BUY,
            order=order,
            strategy_version="test_strategy_v1",
            execution_version="test_engine_v1",
        )
        assert snapshot.snapshot_id.startswith("DEC-")
        assert snapshot.security_id == "AAA"
        assert snapshot.decision == DecisionAction.BUY
        assert snapshot.order is order
        assert snapshot.strategy_version == "test_strategy_v1"
        assert snapshot.execution_version == "test_engine_v1"
        assert snapshot.provenance == TradeProvenance.HISTORICAL_SIMULATION

    def test_snapshot_ids_are_monotonic(self) -> None:
        journal = InMemoryTradeJournalRepository()
        s1 = journal.record_decision(
            decision_time=utc(2024, 1, 2), security_id="AAA", decision=DecisionAction.BUY,
            order=make_order(order_id="ORD-A"),
        )
        s2 = journal.record_decision(
            decision_time=utc(2024, 1, 3), security_id="BBB", decision=DecisionAction.SELL,
            order=make_order(order_id="ORD-B"),
        )
        assert s1.snapshot_id == "DEC-000001"
        assert s2.snapshot_id == "DEC-000002"

    def test_naive_decision_time_rejected(self) -> None:
        from datetime import datetime

        journal = InMemoryTradeJournalRepository()
        with pytest.raises(ValueError):
            journal.record_decision(
                decision_time=datetime(2024, 1, 2),  # naive
                security_id="AAA", decision=DecisionAction.BUY, order=make_order(),
            )

    def test_no_trade_decision_can_be_recorded_without_an_order(self) -> None:
        # Forward-compatible with Phase 7's explicit NO_TRADE decisions —
        # Phase 3 spec section 5.4. order is Optional.
        journal = InMemoryTradeJournalRepository()
        snapshot = journal.record_decision(
            decision_time=utc(2024, 1, 2), security_id="AAA", decision=DecisionAction.NO_TRADE,
            order=None, natural_key=("no_trade", "AAA", "2024-01-02"),
        )
        assert snapshot.order is None
        assert snapshot.decision == DecisionAction.NO_TRADE


class TestImmutableSnapshot:
    def test_snapshot_is_frozen(self) -> None:
        journal = InMemoryTradeJournalRepository()
        snapshot = journal.record_decision(
            decision_time=utc(2024, 1, 2), security_id="AAA", decision=DecisionAction.BUY, order=make_order(),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            snapshot.security_id = "HACKED"  # type: ignore[misc]

    def test_portfolio_state_embedded_is_itself_immutable(self) -> None:
        journal = InMemoryTradeJournalRepository()
        portfolio = PortfolioAccounting(10_000.0)
        view = portfolio.snapshot_view(utc(2024, 1, 2))
        snapshot = journal.record_decision(
            decision_time=utc(2024, 1, 2), security_id="AAA", decision=DecisionAction.BUY,
            order=make_order(), portfolio_state=view,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            snapshot.portfolio_state.cash = 999.0  # type: ignore[misc]


class TestPointInTimeSnapshot:
    def test_mutating_source_portfolio_after_snapshot_does_not_change_recorded_decision(self) -> None:
        journal = InMemoryTradeJournalRepository()
        portfolio = PortfolioAccounting(10_000.0)
        view_at_decision = portfolio.snapshot_view(utc(2024, 1, 2))

        snapshot = journal.record_decision(
            decision_time=utc(2024, 1, 2), security_id="AAA", decision=DecisionAction.BUY,
            order=make_order(), portfolio_state=view_at_decision,
        )
        recorded_cash = snapshot.portfolio_state.cash

        # Mutate the *source* portfolio well after the snapshot was taken
        # (e.g. more trades happen later in the same backtest run).
        from journal_helpers import make_fill

        portfolio.apply_fill(make_fill(quantity=10, price=100.0))

        # The already-recorded snapshot must be unaffected — it captured
        # a value, not a live reference (Phase 3 spec section 4).
        assert snapshot.portfolio_state.cash == recorded_cash
        assert snapshot.portfolio_state.cash != portfolio.cash

    def test_snapshot_is_not_reconstructed_by_requerying_repository(self) -> None:
        # The DecisionSnapshot returned by record_decision is a value
        # object built once; retrieving it again by id must return the
        # exact same, unchanged object (not a freshly re-derived one).
        journal = InMemoryTradeJournalRepository()
        snapshot = journal.record_decision(
            decision_time=utc(2024, 1, 2), security_id="AAA", decision=DecisionAction.BUY, order=make_order(),
        )
        fetched = journal.get_decision(snapshot.snapshot_id)
        assert fetched is snapshot
