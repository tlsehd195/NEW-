"""Category: Version lineage.

See docs/specifications/PHASE-3-trade-journal.md section 6.
"""

from __future__ import annotations

from journal_helpers import make_fill, make_order, utc

from trade_journal.enums import DecisionAction
from trade_journal.repository import InMemoryTradeJournalRepository


class TestVersionLineage:
    def test_strategy_and_execution_version_are_recorded_on_decision(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(
            decision_time=utc(2024, 1, 2), security_id="AAA", decision=DecisionAction.BUY,
            order=make_order(), strategy_version="simple_momentum_v1",
            execution_version="phase2_backtest_engine_v1",
        )
        assert decision.strategy_version == "simple_momentum_v1"
        assert decision.execution_version == "phase2_backtest_engine_v1"

    def test_reserved_lineage_fields_default_to_none_not_fabricated(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(
            decision_time=utc(2024, 1, 2), security_id="AAA", decision=DecisionAction.BUY, order=make_order(),
        )
        # Phase 5/6/8 do not exist yet — these must be None, never guessed.
        assert decision.feature_version is None
        assert decision.model_version is None
        assert decision.risk_version is None
        assert decision.data_version is None

    def test_trade_carries_the_data_version_of_the_bar_that_priced_it(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                             decision=DecisionAction.BUY, order=make_order())
        fill = make_fill(data_version="v-2024-01-03-xyz")
        trade = journal.record_trade(decision_id=decision.snapshot_id, fill=fill, position_after=10.0)
        assert trade.fill.data_version == "v-2024-01-03-xyz"

    def test_explicit_data_version_can_be_set_when_known(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(
            decision_time=utc(2024, 1, 2), security_id="AAA", decision=DecisionAction.BUY,
            order=make_order(), data_version=("v-2024-01-02-aaa", "v-2024-01-02-bbb"),
        )
        assert decision.data_version == ("v-2024-01-02-aaa", "v-2024-01-02-bbb")
