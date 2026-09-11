"""Category: Prediction/Experience Linking Test --
`predict.experience.attach_prediction_context`'s own point-in-time
lookup and per-record security scoping (Phase 6 spec section 12, 13)."""

from __future__ import annotations

from datetime import datetime, timezone

from predict.enums import PredictionMethodType
from predict.experience import attach_prediction_context
from predict.models import PredictionOutput
from predict.repository import InMemoryPredictionRepository

from trade_journal.enums import DecisionAction, TradeProvenance
from trade_journal.models import ExperienceRecord
from trade_journal.repository import InMemoryTradeJournalRepository


def utc(year, month, day, hour=0):
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _prediction(security_id: str, as_of_time: datetime, expected_return: float) -> PredictionOutput:
    return PredictionOutput(
        prediction_id=f"PRED-{security_id}-{as_of_time.isoformat()}",
        security_id=security_id, as_of_time=as_of_time, horizon_days=5,
        expected_return=expected_return, probability=0.6, expected_volatility=0.2,
        uncertainty=0.1, confidence=0.8, method="drift_v1",
        method_type=PredictionMethodType.DETERMINISTIC_BASELINE,
        feature_version="fv1", data_version=("dv1",), method_version="drift_v1",
        configuration_version="cfg1",
    )


def _decision_and_record(journal, security_id: str, decision_time: datetime, experience_id: str) -> ExperienceRecord:
    decision = journal.record_decision(
        decision_time=decision_time, security_id=security_id, decision=DecisionAction.BUY,
        natural_key=("test", security_id, decision_time),
    )
    return ExperienceRecord(
        experience_id=experience_id, trade_id=f"TRADE-{experience_id}", decision_id=decision.snapshot_id,
        state={}, action=DecisionAction.BUY, actual_outcome={},
    )


class TestPerRecordSecurityScoping:
    def test_a_multi_security_batch_never_cross_contaminates_predictions(self) -> None:
        """Session 37 (ADR-0115, external review N-8): before this fix,
        every record in `records` was enriched using the single
        caller-supplied `security_id`, regardless of which security its
        OWN decision was actually for -- a record for "BBB" silently got
        "AAA"'s prediction attached whenever both securities' records
        were passed in the same call. This module's own prior tests
        never caught it because they only ever exercised a single
        security."""
        journal = InMemoryTradeJournalRepository()
        prediction_repo = InMemoryPredictionRepository()

        prediction_repo.record(_prediction("AAA", utc(2024, 1, 2), expected_return=0.05))
        prediction_repo.record(_prediction("BBB", utc(2024, 1, 2), expected_return=-0.03))

        record_a = _decision_and_record(journal, "AAA", utc(2024, 1, 3), "EXP-A")
        record_b = _decision_and_record(journal, "BBB", utc(2024, 1, 3), "EXP-B")

        enriched = attach_prediction_context([record_a, record_b], journal, prediction_repo)
        by_id = {r.experience_id: r for r in enriched}

        assert by_id["EXP-A"].expected_outcome["expected_return"] == 0.05
        assert by_id["EXP-B"].expected_outcome["expected_return"] == -0.03  # not AAA's 0.05

    def test_a_security_id_filter_restricts_enrichment_to_that_security_only(self) -> None:
        journal = InMemoryTradeJournalRepository()
        prediction_repo = InMemoryPredictionRepository()
        prediction_repo.record(_prediction("AAA", utc(2024, 1, 2), expected_return=0.05))
        prediction_repo.record(_prediction("BBB", utc(2024, 1, 2), expected_return=-0.03))

        record_a = _decision_and_record(journal, "AAA", utc(2024, 1, 3), "EXP-A")
        record_b = _decision_and_record(journal, "BBB", utc(2024, 1, 3), "EXP-B")

        enriched = attach_prediction_context([record_a, record_b], journal, prediction_repo, security_id="AAA")
        by_id = {r.experience_id: r for r in enriched}

        assert by_id["EXP-A"].expected_outcome["expected_return"] == 0.05
        assert by_id["EXP-B"].expected_outcome is None  # filtered out, not wrongly enriched with AAA's

    def test_an_already_populated_expected_outcome_is_never_overwritten(self) -> None:
        journal = InMemoryTradeJournalRepository()
        prediction_repo = InMemoryPredictionRepository()
        prediction_repo.record(_prediction("AAA", utc(2024, 1, 2), expected_return=0.05))

        decision = journal.record_decision(
            decision_time=utc(2024, 1, 3), security_id="AAA", decision=DecisionAction.BUY,
            natural_key=("test", "AAA", utc(2024, 1, 3)),
        )
        record = ExperienceRecord(
            experience_id="EXP-A", trade_id="TRADE-A", decision_id=decision.snapshot_id,
            state={}, action=DecisionAction.BUY, actual_outcome={},
            expected_outcome={"expected_return": 0.99},
        )
        enriched = attach_prediction_context([record], journal, prediction_repo)
        assert enriched[0].expected_outcome == {"expected_return": 0.99}
