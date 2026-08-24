"""Category: Audit trail.

See docs/specifications/PHASE-3-trade-journal.md section 14.
"""

from __future__ import annotations

from journal_helpers import make_fill, make_order, utc

from trade_journal.enums import CorrectionTargetType, DecisionAction
from trade_journal.repository import InMemoryTradeJournalRepository


class TestAuditTrail:
    def test_audit_trail_composes_decision_and_trade(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(
            decision_time=utc(2024, 1, 2), security_id="AAA", decision=DecisionAction.BUY,
            order=make_order(), decision_reason="strategy=simple_momentum_v1",
            strategy_version="simple_momentum_v1",
        )
        trade = journal.record_trade(decision_id=decision.snapshot_id, fill=make_fill(), position_after=10.0)

        trail = journal.audit_trail(trade.trade_id)
        assert trail.trade is trade
        assert trail.decision is decision
        assert trail.post_trade_analysis is None
        assert trail.counterfactual is None
        assert trail.corrections == ()

    def test_audit_trail_answers_why_and_what_was_known(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(
            decision_time=utc(2024, 1, 2), security_id="AAA", decision=DecisionAction.BUY,
            order=make_order(), decision_reason="strategy=buy_and_hold_v1",
            market_state={"reference_price": 100.0},
        )
        trade = journal.record_trade(decision_id=decision.snapshot_id, fill=make_fill(), position_after=10.0)
        trail = journal.audit_trail(trade.trade_id)

        # "왜 이 거래가 발생했는가?"
        assert trail.decision.decision_reason == "strategy=buy_and_hold_v1"
        # "당시 AI가 무엇을 알고 있었는가?"
        assert trail.decision.market_state == {"reference_price": 100.0}
        # "어떤 가격으로 주문했는가?"
        assert trail.trade.execution_price == trade.fill.price

    def test_audit_trail_includes_post_trade_analysis_and_counterfactual_once_computed(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                             decision=DecisionAction.BUY, order=make_order())
        trade = journal.record_trade(decision_id=decision.snapshot_id, fill=make_fill(), position_after=10.0)

        journal.record_post_trade_analysis(trade.trade_id, execution_error=0.001)
        journal.record_counterfactual(trade.trade_id, selected_action=DecisionAction.BUY, alternatives=())

        trail = journal.audit_trail(trade.trade_id)
        assert trail.post_trade_analysis is not None
        assert trail.post_trade_analysis.execution_error == 0.001
        assert trail.counterfactual is not None
        assert trail.counterfactual.selected_action == DecisionAction.BUY

    def test_audit_trail_includes_corrections_on_either_decision_or_trade(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                             decision=DecisionAction.BUY, order=make_order())
        trade = journal.record_trade(decision_id=decision.snapshot_id, fill=make_fill(), position_after=10.0)

        journal.record_correction(
            target_type=CorrectionTargetType.DECISION, target_id=decision.snapshot_id,
            reason="strategy_version was recorded incorrectly", corrected_fields={"strategy_version": "v2"},
            created_at=utc(2024, 1, 6),
        )
        journal.record_correction(
            target_type=CorrectionTargetType.TRADE, target_id=trade.trade_id,
            reason="commission was double-counted upstream", corrected_fields={"transaction_cost": 0.5},
            created_at=utc(2024, 1, 6),
        )

        trail = journal.audit_trail(trade.trade_id)
        assert len(trail.corrections) == 2
        reasons = {c.reason for c in trail.corrections}
        assert "strategy_version was recorded incorrectly" in reasons
        assert "commission was double-counted upstream" in reasons

    def test_audit_trail_for_unknown_trade_id_returns_empty_shell(self) -> None:
        journal = InMemoryTradeJournalRepository()
        trail = journal.audit_trail("TRD-DOES-NOT-EXIST")
        assert trail.trade is None
        assert trail.decision is None
        assert trail.corrections == ()
