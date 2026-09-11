"""Category: Repository Test -- InMemoryPredictionRepository.get_as_of
tie-break determinism (ADR-0117)."""

from __future__ import annotations

from datetime import datetime, timezone

from predict.enums import PredictionMethodType
from predict.models import PredictionOutput
from predict.repository import InMemoryPredictionRepository


def utc(year: int, month: int, day: int, hour: int = 20) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _prediction(as_of_time: datetime, *, prediction_id: str, method: str) -> PredictionOutput:
    return PredictionOutput(
        prediction_id=prediction_id, security_id="AAA", as_of_time=as_of_time, horizon_days=5,
        expected_return=0.01, probability=0.55, expected_volatility=0.2, uncertainty=0.05, confidence=0.8,
        method=method, method_type=PredictionMethodType.DETERMINISTIC_BASELINE,
        feature_version="fv1", data_version=("dv1",), method_version="mv1", configuration_version="cv1",
    )


class TestGetAsOfTieBreak:
    def test_a_genuine_as_of_time_tie_deterministically_prefers_the_higher_prediction_id(self) -> None:
        # Two predictions from different methods, same as_of_time (a
        # different `method` so the natural-key dedup doesn't collapse
        # them into one row) -- `max(..., key=as_of_time)` alone resolved
        # a tie by dict insertion order, not a meaningful choice.
        T = utc(2024, 6, 1)
        repo = InMemoryPredictionRepository()
        repo.record(_prediction(T, prediction_id="PRED-000001", method="random_walk_v1"))
        repo.record(_prediction(T, prediction_id="PRED-000002", method="drift_v1"))

        result = repo.get_as_of("AAA", T)
        assert result is not None
        assert result.prediction_id == "PRED-000002"

    def test_tie_break_is_independent_of_insertion_order(self) -> None:
        T = utc(2024, 6, 1)
        repo = InMemoryPredictionRepository()
        repo.record(_prediction(T, prediction_id="PRED-000002", method="drift_v1"))
        repo.record(_prediction(T, prediction_id="PRED-000001", method="random_walk_v1"))

        result = repo.get_as_of("AAA", T)
        assert result is not None
        assert result.prediction_id == "PRED-000002"
