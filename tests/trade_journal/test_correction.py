"""Category: Correction/audit record.

See docs/specifications/PHASE-3-trade-journal.md section 9, ADR-0009.
"""

from __future__ import annotations

import dataclasses

import pytest
from journal_helpers import make_fill, make_order, utc

from trade_journal.enums import CorrectionTargetType, DecisionAction
from trade_journal.repository import InMemoryTradeJournalRepository


class TestCorrection:
    def test_correction_never_mutates_the_original_record(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                             decision=DecisionAction.BUY, order=make_order(),
                                             strategy_version="v1")
        journal.record_correction(
            target_type=CorrectionTargetType.DECISION, target_id=decision.snapshot_id,
            reason="strategy_version was wrong", corrected_fields={"strategy_version": "v2"},
            created_at=utc(2024, 1, 6),
        )
        # The original, already-recorded object is untouched.
        assert decision.strategy_version == "v1"
        refetched = journal.get_decision(decision.snapshot_id)
        assert refetched.strategy_version == "v1"

    def test_correction_is_discoverable_via_get_corrections(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                             decision=DecisionAction.BUY, order=make_order())
        journal.record_correction(
            target_type=CorrectionTargetType.DECISION, target_id=decision.snapshot_id,
            reason="test correction", corrected_fields={}, created_at=utc(2024, 1, 6),
        )
        corrections = journal.get_corrections(decision.snapshot_id)
        assert len(corrections) == 1
        assert corrections[0].reason == "test correction"
        assert corrections[0].correction_id.startswith("COR-")

    def test_correction_without_a_reason_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            journal = InMemoryTradeJournalRepository()
            journal.record_correction(
                target_type=CorrectionTargetType.DECISION, target_id="DEC-000001",
                reason="", corrected_fields={}, created_at=utc(2024, 1, 6),
            )

    def test_multiple_corrections_accumulate_without_overwriting(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                             decision=DecisionAction.BUY, order=make_order())
        journal.record_correction(target_type=CorrectionTargetType.DECISION, target_id=decision.snapshot_id,
                                    reason="first correction", corrected_fields={}, created_at=utc(2024, 1, 6))
        journal.record_correction(target_type=CorrectionTargetType.DECISION, target_id=decision.snapshot_id,
                                    reason="second correction", corrected_fields={}, created_at=utc(2024, 1, 7))
        corrections = journal.get_corrections(decision.snapshot_id)
        assert [c.reason for c in corrections] == ["first correction", "second correction"]

    def test_correction_record_itself_is_immutable(self) -> None:
        journal = InMemoryTradeJournalRepository()
        correction = journal.record_correction(
            target_type=CorrectionTargetType.TRADE, target_id="TRD-000001",
            reason="test", corrected_fields={}, created_at=utc(2024, 1, 6),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            correction.reason = "hacked"  # type: ignore[misc]

    def test_post_trade_analysis_recomputation_preserves_history(self) -> None:
        # Not literally a CorrectionRecord, but the same append-don't-
        # overwrite discipline applies to PostTradeAnalysis (Phase 3 spec
        # section 11) — verified here alongside the correction tests.
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                             decision=DecisionAction.BUY, order=make_order())
        trade = journal.record_trade(decision_id=decision.snapshot_id, fill=make_fill(), position_after=10.0)

        journal.record_post_trade_analysis(trade.trade_id, execution_error=0.001)
        journal.record_post_trade_analysis(trade.trade_id, execution_error=0.001, prediction_error=0.02)

        history = journal.get_post_trade_analysis_history(trade.trade_id)
        assert len(history) == 2
        assert history[0].prediction_error is None
        assert history[1].prediction_error == 0.02
        # get_post_trade_analysis returns the latest.
        assert journal.get_post_trade_analysis(trade.trade_id).prediction_error == 0.02
