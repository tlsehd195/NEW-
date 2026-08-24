"""RegimeRepository: the interface Prediction/Decision/Risk/Learning (and
the persistent backend, storage.regime_repository) depend on, mirroring
the Repository-interface discipline Phase 1's `DataRepository` and Phase
3's `TradeJournalRepository` already established.

`InMemoryRegimeRepository` is the Phase 5 reference implementation --
consumers depend only on the `RegimeRepository` Protocol, never on this
class directly, so a persistent DuckDB-backed implementation (Phase 4's
already-built storage layer, wired up in `storage.regime_repository`)
satisfies the exact same Protocol without any consumer code changing
(the same swap Phase 1's ADR-0002 and Phase 4's ADR-0010 already made for
`DataRepository`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol

from regime.enums import RegimeAxis, SubjectKind
from regime.models import CompositeRegimeObservation, RegimeObservation

from trade_journal.enums import TradeProvenance


class RegimeRepository(Protocol):
    def record_observation(self, observation: RegimeObservation) -> RegimeObservation:
        """Idempotent on (subject_id, subject_kind, axis, as_of_time,
        configuration_version, provenance) -- recomputing and re-recording
        the identical regime observation returns the existing record
        rather than duplicating it (Phase 5 spec section 13, "duplicate
        ingestion")."""
        ...

    def record_composite(self, composite: CompositeRegimeObservation) -> CompositeRegimeObservation:
        """Idempotent on (subject_id, subject_kind, as_of_time,
        provenance)."""
        ...

    def get_observation(self, regime_id: str) -> Optional[RegimeObservation]: ...

    def list_observations(
        self, *, subject_id: Optional[str] = None, axis: Optional[RegimeAxis] = None,
        provenance: Optional[TradeProvenance] = None,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[RegimeObservation]: ...

    def get_composite(self, composite_id: str) -> Optional[CompositeRegimeObservation]: ...

    def get_composite_as_of(
        self, subject_id: str, subject_kind: SubjectKind, as_of_time: datetime,
        *, provenance: Optional[TradeProvenance] = None,
    ) -> Optional[CompositeRegimeObservation]:
        """The most recent composite observation for `subject_id` with
        `as_of_time <= as_of_time` (point-in-time query, same discipline
        as `DataRepository`'s as-of methods, ADR-0004) -- used to answer
        "what regime was in effect when this decision was made" (Phase 5
        spec section 12)."""
        ...

    def list_composites(
        self, *, subject_id: Optional[str] = None, provenance: Optional[TradeProvenance] = None,
    ) -> list[CompositeRegimeObservation]: ...


class InMemoryRegimeRepository:
    def __init__(self) -> None:
        self._observations: dict[str, RegimeObservation] = {}
        self._observation_natural_keys: dict[tuple, str] = {}
        self._composites: dict[str, CompositeRegimeObservation] = {}
        self._composite_natural_keys: dict[tuple, str] = {}

    @staticmethod
    def _observation_key(o: RegimeObservation) -> tuple:
        return (o.subject_id, o.subject_kind, o.axis, o.as_of_time, o.configuration_version, o.provenance)

    @staticmethod
    def _composite_key(c: CompositeRegimeObservation) -> tuple:
        return (c.subject_id, c.subject_kind, c.as_of_time, c.provenance)

    def record_observation(self, observation: RegimeObservation) -> RegimeObservation:
        key = self._observation_key(observation)
        existing_id = self._observation_natural_keys.get(key)
        if existing_id is not None:
            return self._observations[existing_id]
        self._observations[observation.regime_id] = observation
        self._observation_natural_keys[key] = observation.regime_id
        return observation

    def record_composite(self, composite: CompositeRegimeObservation) -> CompositeRegimeObservation:
        key = self._composite_key(composite)
        existing_id = self._composite_natural_keys.get(key)
        if existing_id is not None:
            return self._composites[existing_id]
        for observation in composite.axes.values():
            self.record_observation(observation)
        self._composites[composite.composite_id] = composite
        self._composite_natural_keys[key] = composite.composite_id
        return composite

    def get_observation(self, regime_id: str) -> Optional[RegimeObservation]:
        return self._observations.get(regime_id)

    def list_observations(
        self, *, subject_id: Optional[str] = None, axis: Optional[RegimeAxis] = None,
        provenance: Optional[TradeProvenance] = None,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[RegimeObservation]:
        results = list(self._observations.values())
        if subject_id is not None:
            results = [o for o in results if o.subject_id == subject_id]
        if axis is not None:
            results = [o for o in results if o.axis == axis]
        if provenance is not None:
            results = [o for o in results if o.provenance == provenance]
        if start is not None:
            results = [o for o in results if o.as_of_time >= start]
        if end is not None:
            results = [o for o in results if o.as_of_time <= end]
        return sorted(results, key=lambda o: (o.as_of_time, o.axis.value))

    def get_composite(self, composite_id: str) -> Optional[CompositeRegimeObservation]:
        return self._composites.get(composite_id)

    def get_composite_as_of(
        self, subject_id: str, subject_kind: SubjectKind, as_of_time: datetime,
        *, provenance: Optional[TradeProvenance] = None,
    ) -> Optional[CompositeRegimeObservation]:
        candidates = [
            c for c in self._composites.values()
            if c.subject_id == subject_id and c.subject_kind == subject_kind and c.as_of_time <= as_of_time
            and (provenance is None or c.provenance == provenance)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda c: c.as_of_time)

    def list_composites(
        self, *, subject_id: Optional[str] = None, provenance: Optional[TradeProvenance] = None,
    ) -> list[CompositeRegimeObservation]:
        results = list(self._composites.values())
        if subject_id is not None:
            results = [c for c in results if c.subject_id == subject_id]
        if provenance is not None:
            results = [c for c in results if c.provenance == provenance]
        return sorted(results, key=lambda c: c.as_of_time)
