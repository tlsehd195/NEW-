"""Category: Repository Test -- InMemoryDecisionRepository.get_as_of
tie-break determinism (ADR-0117)."""

from __future__ import annotations

from risk_helpers import make_decision, utc

from decision.repository import InMemoryDecisionRepository


class TestGetAsOfTieBreak:
    def test_a_genuine_as_of_time_tie_deterministically_prefers_the_higher_decision_id(self) -> None:
        # Two decisions recorded for the SAME security at the exact same
        # as_of_time (a different prediction feeding each, so the
        # natural-key dedup doesn't collapse them into one row) used to
        # resolve via `max(..., key=as_of_time)` alone -- on a tie, this
        # returns whichever candidate the backing dict happens to
        # iterate first (insertion order), an arbitrary choice rather
        # than a meaningful one.
        T = utc(2024, 6, 1)
        repo = InMemoryDecisionRepository()
        repo.record(make_decision(T, decision_id="DEC-OUT-000001", prediction_id="PRED-000001"))
        repo.record(make_decision(T, decision_id="DEC-OUT-000002", prediction_id="PRED-000002"))

        result = repo.get_as_of("AAA", T)
        assert result is not None
        assert result.decision_id == "DEC-OUT-000002"

    def test_tie_break_is_independent_of_insertion_order(self) -> None:
        T = utc(2024, 6, 1)
        repo = InMemoryDecisionRepository()
        # Recorded in the OPPOSITE order from the test above.
        repo.record(make_decision(T, decision_id="DEC-OUT-000002", prediction_id="PRED-000002"))
        repo.record(make_decision(T, decision_id="DEC-OUT-000001", prediction_id="PRED-000001"))

        result = repo.get_as_of("AAA", T)
        assert result is not None
        assert result.decision_id == "DEC-OUT-000002"
