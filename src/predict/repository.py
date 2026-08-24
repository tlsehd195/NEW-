"""PredictionRepository: the interface Decision/Risk/Learning (and the
persistent backend, storage.prediction_repository) depend on, mirroring
the Repository-interface discipline Phase 1/3/5 already established.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol

from predict.models import PredictionOutput

from trade_journal.enums import TradeProvenance


class PredictionRepository(Protocol):
    def record(self, prediction: PredictionOutput) -> PredictionOutput:
        """Idempotent on (security_id, as_of_time, method, horizon_days,
        configuration_version, provenance) -- recomputing and
        re-recording the identical prediction returns the existing
        record rather than duplicating it."""
        ...

    def get(self, prediction_id: str) -> Optional[PredictionOutput]: ...

    def list_all(
        self, *, security_id: Optional[str] = None, method: Optional[str] = None,
        provenance: Optional[TradeProvenance] = None,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[PredictionOutput]: ...

    def get_as_of(
        self, security_id: str, as_of_time: datetime, *,
        method: Optional[str] = None, provenance: Optional[TradeProvenance] = None,
    ) -> Optional[PredictionOutput]:
        """The most recent prediction for `security_id` with
        `as_of_time <= as_of_time` -- a point-in-time query, same
        discipline as `DataRepository`'s as-of methods (ADR-0004) and
        `RegimeRepository.get_composite_as_of` (ADR-0011) -- used to
        answer "what was predicted when this decision was made"."""
        ...


class InMemoryPredictionRepository:
    def __init__(self) -> None:
        self._predictions: dict[str, PredictionOutput] = {}
        self._natural_keys: dict[tuple, str] = {}

    @staticmethod
    def _key(p: PredictionOutput) -> tuple:
        return (p.security_id, p.as_of_time, p.method, p.horizon_days, p.configuration_version, p.provenance)

    def record(self, prediction: PredictionOutput) -> PredictionOutput:
        key = self._key(prediction)
        existing_id = self._natural_keys.get(key)
        if existing_id is not None:
            return self._predictions[existing_id]
        self._predictions[prediction.prediction_id] = prediction
        self._natural_keys[key] = prediction.prediction_id
        return prediction

    def get(self, prediction_id: str) -> Optional[PredictionOutput]:
        return self._predictions.get(prediction_id)

    def list_all(
        self, *, security_id: Optional[str] = None, method: Optional[str] = None,
        provenance: Optional[TradeProvenance] = None,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[PredictionOutput]:
        results = list(self._predictions.values())
        if security_id is not None:
            results = [p for p in results if p.security_id == security_id]
        if method is not None:
            results = [p for p in results if p.method == method]
        if provenance is not None:
            results = [p for p in results if p.provenance == provenance]
        if start is not None:
            results = [p for p in results if p.as_of_time >= start]
        if end is not None:
            results = [p for p in results if p.as_of_time <= end]
        return sorted(results, key=lambda p: p.as_of_time)

    def get_as_of(
        self, security_id: str, as_of_time: datetime, *,
        method: Optional[str] = None, provenance: Optional[TradeProvenance] = None,
    ) -> Optional[PredictionOutput]:
        candidates = [
            p for p in self._predictions.values()
            if p.security_id == security_id and p.as_of_time <= as_of_time
            and (method is None or p.method == method)
            and (provenance is None or p.provenance == provenance)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.as_of_time)
