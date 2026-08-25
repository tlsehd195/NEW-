"""DecisionRepository: the interface Risk/Position Sizing/Learning (and
the persistent backend, storage.decision_repository) depend on, mirroring
the Repository-interface discipline Phase 1/3/5/6 already established.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol

from decision.models import DecisionOutput

from trade_journal.enums import TradeProvenance


class DecisionRepository(Protocol):
    def record(self, decision: DecisionOutput) -> DecisionOutput:
        """Idempotent on (security_id, as_of_time, decision_version,
        prediction_id, provenance) -- recomputing and re-recording the
        identical decision returns the existing record rather than
        duplicating it."""
        ...

    def get(self, decision_id: str) -> Optional[DecisionOutput]: ...

    def list_all(
        self, *, security_id: Optional[str] = None, action: Optional[str] = None,
        provenance: Optional[TradeProvenance] = None,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[DecisionOutput]: ...

    def get_as_of(
        self, security_id: str, as_of_time: datetime, *,
        provenance: Optional[TradeProvenance] = None,
    ) -> Optional[DecisionOutput]:
        """The most recent decision for `security_id` with
        `as_of_time <= as_of_time` -- point-in-time, same discipline as
        `PredictionRepository.get_as_of`/`RegimeRepository.get_composite_as_of`."""
        ...


class InMemoryDecisionRepository:
    def __init__(self) -> None:
        self._decisions: dict[str, DecisionOutput] = {}
        self._natural_keys: dict[tuple, str] = {}

    @staticmethod
    def _key(d: DecisionOutput) -> tuple:
        return (d.security_id, d.as_of_time, d.decision_version, d.prediction_id, d.provenance)

    def record(self, decision: DecisionOutput) -> DecisionOutput:
        key = self._key(decision)
        existing_id = self._natural_keys.get(key)
        if existing_id is not None:
            return self._decisions[existing_id]
        self._decisions[decision.decision_id] = decision
        self._natural_keys[key] = decision.decision_id
        return decision

    def get(self, decision_id: str) -> Optional[DecisionOutput]:
        return self._decisions.get(decision_id)

    def list_all(
        self, *, security_id: Optional[str] = None, action: Optional[str] = None,
        provenance: Optional[TradeProvenance] = None,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[DecisionOutput]:
        results = list(self._decisions.values())
        if security_id is not None:
            results = [d for d in results if d.security_id == security_id]
        if action is not None:
            results = [d for d in results if d.action.value == action]
        if provenance is not None:
            results = [d for d in results if d.provenance == provenance]
        if start is not None:
            results = [d for d in results if d.as_of_time >= start]
        if end is not None:
            results = [d for d in results if d.as_of_time <= end]
        return sorted(results, key=lambda d: d.as_of_time)

    def get_as_of(
        self, security_id: str, as_of_time: datetime, *,
        provenance: Optional[TradeProvenance] = None,
    ) -> Optional[DecisionOutput]:
        candidates = [
            d for d in self._decisions.values()
            if d.security_id == security_id and d.as_of_time <= as_of_time
            and (provenance is None or d.provenance == provenance)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda d: d.as_of_time)
