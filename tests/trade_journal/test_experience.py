"""Category: Experience conversion.

See docs/specifications/PHASE-3-trade-journal.md sections 5.8, 10.2.
"""

from __future__ import annotations

from journal_helpers import make_fill, make_order, utc

from backtest.enums import OrderSide
from trade_journal.enums import DecisionAction, TradeProvenance
from trade_journal.experience import build_experience_records
from trade_journal.repository import InMemoryTradeJournalRepository


class TestExperienceConversion:
    def test_closing_trade_produces_a_reward_equal_to_realized_return(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                             decision=DecisionAction.SELL, order=make_order(side=OrderSide.SELL))
        trade = journal.record_trade(
            decision_id=decision.snapshot_id, fill=make_fill(side=OrderSide.SELL), position_after=0.0,
            realized_pnl=200.0, realized_return=0.2,
        )
        records = build_experience_records(journal, created_at=utc(2024, 2, 1))
        assert len(records) == 1
        record = records[0]
        assert record.reward == 0.2
        assert record.trade_id == trade.trade_id
        assert record.decision_id == decision.snapshot_id
        assert record.action == DecisionAction.SELL

    def test_opening_trade_has_no_fabricated_reward(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                             decision=DecisionAction.BUY, order=make_order())
        journal.record_trade(decision_id=decision.snapshot_id, fill=make_fill(), position_after=10.0)
        records = build_experience_records(journal, created_at=utc(2024, 2, 1))
        assert records[0].reward is None  # no realization yet — not fabricated as 0.0

    def test_experience_record_carries_provenance_and_lineage(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(
            decision_time=utc(2024, 1, 2), security_id="AAA", decision=DecisionAction.BUY,
            order=make_order(), strategy_version="test_v1", provenance=TradeProvenance.PAPER_TRADING,
        )
        journal.record_trade(decision_id=decision.snapshot_id, fill=make_fill(), position_after=10.0,
                               provenance=TradeProvenance.PAPER_TRADING)
        records = build_experience_records(journal, created_at=utc(2024, 2, 1))
        assert records[0].provenance == TradeProvenance.PAPER_TRADING
        assert records[0].strategy_version == "test_v1"

    def test_provenance_filter_scopes_experience_conversion(self) -> None:
        journal = InMemoryTradeJournalRepository()
        for i, provenance in enumerate([TradeProvenance.HISTORICAL_SIMULATION, TradeProvenance.LIVE_TRADING]):
            order = make_order(order_id=f"ORD-{i}")
            decision = journal.record_decision(decision_time=utc(2024, 1, 2 + i), security_id="AAA",
                                                 decision=DecisionAction.BUY, order=order, provenance=provenance)
            journal.record_trade(decision_id=decision.snapshot_id,
                                   fill=make_fill(order_id=f"ORD-{i}"), position_after=10.0, provenance=provenance)

        live_only = build_experience_records(journal, provenance=TradeProvenance.LIVE_TRADING)
        assert len(live_only) == 1
        assert live_only[0].provenance == TradeProvenance.LIVE_TRADING

    def test_prediction_error_and_counterfactual_are_included_when_available(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                             decision=DecisionAction.BUY, order=make_order())
        trade = journal.record_trade(decision_id=decision.snapshot_id, fill=make_fill(), position_after=10.0)

        journal.record_post_trade_analysis(trade.trade_id, execution_error=0.001, prediction_error=0.05)
        from trade_journal.models import AlternativeOutcome

        journal.record_counterfactual(
            trade.trade_id, selected_action=DecisionAction.BUY,
            alternatives=(AlternativeOutcome(action="HOLD", hypothetical_return=0.01, basis="post_hoc_price_replay"),),
        )

        records = build_experience_records(journal, created_at=utc(2024, 2, 1))
        assert records[0].prediction_error == 0.05
        assert records[0].counterfactual_results[0].action == "HOLD"
