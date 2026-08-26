"""Category: Duplicate event / idempotency.

See docs/specifications/PHASE-3-trade-journal.md section 8.
"""

from __future__ import annotations

from journal_helpers import make_fill, make_order, utc

from trade_journal.enums import DecisionAction
from trade_journal.repository import InMemoryTradeJournalRepository


class TestIdempotency:
    def test_recording_the_same_order_twice_does_not_duplicate(self) -> None:
        journal = InMemoryTradeJournalRepository()
        order = make_order()
        s1 = journal.record_decision(decision_time=order.decision_time, security_id="AAA",
                                       decision=DecisionAction.BUY, order=order, experiment_id="BT-000001")
        s2 = journal.record_decision(decision_time=order.decision_time, security_id="AAA",
                                       decision=DecisionAction.BUY, order=order, experiment_id="BT-000001")
        assert s1.snapshot_id == s2.snapshot_id
        assert len(journal.list_decisions()) == 1

    def test_recording_the_same_fill_twice_does_not_duplicate(self) -> None:
        journal = InMemoryTradeJournalRepository()
        order = make_order()
        decision = journal.record_decision(decision_time=order.decision_time, security_id="AAA",
                                             decision=DecisionAction.BUY, order=order, experiment_id="BT-000001")
        fill = make_fill()
        t1 = journal.record_trade(decision_id=decision.snapshot_id, fill=fill, position_after=10.0,
                                   experiment_id="BT-000001")
        t2 = journal.record_trade(decision_id=decision.snapshot_id, fill=fill, position_after=10.0,
                                   experiment_id="BT-000001")
        assert t1.trade_id == t2.trade_id
        assert len(journal.list_trades()) == 1

    def test_two_distinct_partial_fills_of_the_same_order_are_not_deduplicated_against_each_other(self) -> None:
        """Phase 17 Production Safety Review regression test. Before
        this phase's fix, the natural key was `(experiment_id,
        fill.order_id)` alone -- since every partial fill of one order
        shares the same `order_id` (Fill.order_id is the
        client_order_id, never a per-fill id), the second and later
        partial fill of any order was silently discarded as a
        "duplicate" of the first, permanently losing real fills from
        the Trade Journal. Two fills of the *same order* at two
        different `execution_time`s must both be recorded."""
        from dataclasses import replace

        journal = InMemoryTradeJournalRepository()
        order = make_order()
        decision = journal.record_decision(decision_time=order.decision_time, security_id="AAA",
                                             decision=DecisionAction.BUY, order=order, experiment_id="BT-000001")
        first_fill = make_fill(quantity=100.0, execution_time=utc(2024, 1, 2))
        second_fill = replace(first_fill, quantity=50.0, execution_time=utc(2024, 1, 3))
        assert first_fill.order_id == second_fill.order_id  # same order, two separate fill events

        t1 = journal.record_trade(decision_id=decision.snapshot_id, fill=first_fill, position_after=100.0,
                                   experiment_id="BT-000001")
        t2 = journal.record_trade(decision_id=decision.snapshot_id, fill=second_fill, position_after=150.0,
                                   experiment_id="BT-000001")
        assert t1.trade_id != t2.trade_id
        assert len(journal.list_trades()) == 2

    def test_different_experiment_ids_are_not_deduplicated_against_each_other(self) -> None:
        # The natural key includes experiment_id — the same order_id
        # from two different backtest runs must not collide.
        journal = InMemoryTradeJournalRepository()
        order = make_order()
        s1 = journal.record_decision(decision_time=order.decision_time, security_id="AAA",
                                       decision=DecisionAction.BUY, order=order, experiment_id="BT-000001")
        s2 = journal.record_decision(decision_time=order.decision_time, security_id="AAA",
                                       decision=DecisionAction.BUY, order=order, experiment_id="BT-000002")
        assert s1.snapshot_id != s2.snapshot_id
        assert len(journal.list_decisions()) == 2

    def test_idempotent_decision_ingestion_does_not_waste_or_skip_ids(self) -> None:
        journal = InMemoryTradeJournalRepository()
        order_a = make_order(order_id="ORD-A")
        order_b = make_order(order_id="ORD-B")

        journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                  decision=DecisionAction.BUY, order=order_a, experiment_id="BT-000001")
        # duplicate of the first
        journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                  decision=DecisionAction.BUY, order=order_a, experiment_id="BT-000001")
        second = journal.record_decision(decision_time=utc(2024, 1, 3), security_id="BBB",
                                           decision=DecisionAction.BUY, order=order_b, experiment_id="BT-000001")

        assert len(journal.list_decisions()) == 2
        assert second.snapshot_id == "DEC-000002"
