"""PositionSizingRepository / RiskRepository: the interfaces a persistent
backend (storage.risk_repository) implements, mirroring the
Repository-interface discipline Phase 1/3/5/6/7 already established.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol

from risk.models import PositionSizingResult, RiskCheckedPosition

from trade_journal.enums import TradeProvenance


class PositionSizingRepository(Protocol):
    def record(self, result: PositionSizingResult) -> PositionSizingResult:
        """Idempotent on (security_id, as_of_time, sizing_version,
        decision_id, provenance)."""
        ...

    def get(self, sizing_id: str) -> Optional[PositionSizingResult]: ...

    def list_all(
        self, *, security_id: Optional[str] = None, provenance: Optional[TradeProvenance] = None,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[PositionSizingResult]: ...

    def get_as_of(
        self, security_id: str, as_of_time: datetime, *, provenance: Optional[TradeProvenance] = None,
    ) -> Optional[PositionSizingResult]: ...


class InMemoryPositionSizingRepository:
    def __init__(self) -> None:
        self._results: dict[str, PositionSizingResult] = {}
        self._natural_keys: dict[tuple, str] = {}

    @staticmethod
    def _key(r: PositionSizingResult) -> tuple:
        return (r.security_id, r.as_of_time, r.sizing_version, r.decision_id, r.provenance)

    def record(self, result: PositionSizingResult) -> PositionSizingResult:
        key = self._key(result)
        existing_id = self._natural_keys.get(key)
        if existing_id is not None:
            return self._results[existing_id]
        self._results[result.sizing_id] = result
        self._natural_keys[key] = result.sizing_id
        return result

    def get(self, sizing_id: str) -> Optional[PositionSizingResult]:
        return self._results.get(sizing_id)

    def list_all(
        self, *, security_id: Optional[str] = None, provenance: Optional[TradeProvenance] = None,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[PositionSizingResult]:
        results = list(self._results.values())
        if security_id is not None:
            results = [r for r in results if r.security_id == security_id]
        if provenance is not None:
            results = [r for r in results if r.provenance == provenance]
        if start is not None:
            results = [r for r in results if r.as_of_time >= start]
        if end is not None:
            results = [r for r in results if r.as_of_time <= end]
        return sorted(results, key=lambda r: r.as_of_time)

    def get_as_of(
        self, security_id: str, as_of_time: datetime, *, provenance: Optional[TradeProvenance] = None,
    ) -> Optional[PositionSizingResult]:
        candidates = [
            r for r in self._results.values()
            if r.security_id == security_id and r.as_of_time <= as_of_time
            and (provenance is None or r.provenance == provenance)
        ]
        if not candidates:
            return None
        # Tie-break on sizing_id (ADR-0117) -- see decision.repository's
        # identical fix for the full reasoning.
        return max(candidates, key=lambda r: (r.as_of_time, r.sizing_id))


class RiskRepository(Protocol):
    def record(self, checked: RiskCheckedPosition) -> RiskCheckedPosition:
        """Idempotent on (security_id, as_of_time, risk_version,
        sizing_id, provenance)."""
        ...

    def get(self, risk_id: str) -> Optional[RiskCheckedPosition]: ...

    def list_all(
        self, *, security_id: Optional[str] = None, provenance: Optional[TradeProvenance] = None,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[RiskCheckedPosition]: ...

    def get_as_of(
        self, security_id: str, as_of_time: datetime, *, provenance: Optional[TradeProvenance] = None,
    ) -> Optional[RiskCheckedPosition]: ...


class InMemoryRiskRepository:
    def __init__(self) -> None:
        self._checked: dict[str, RiskCheckedPosition] = {}
        self._natural_keys: dict[tuple, str] = {}

    @staticmethod
    def _key(c: RiskCheckedPosition) -> tuple:
        return (c.security_id, c.as_of_time, c.risk_version, c.sizing_id, c.provenance)

    def record(self, checked: RiskCheckedPosition) -> RiskCheckedPosition:
        key = self._key(checked)
        existing_id = self._natural_keys.get(key)
        if existing_id is not None:
            return self._checked[existing_id]
        self._checked[checked.risk_id] = checked
        self._natural_keys[key] = checked.risk_id
        return checked

    def get(self, risk_id: str) -> Optional[RiskCheckedPosition]:
        return self._checked.get(risk_id)

    def list_all(
        self, *, security_id: Optional[str] = None, provenance: Optional[TradeProvenance] = None,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[RiskCheckedPosition]:
        results = list(self._checked.values())
        if security_id is not None:
            results = [c for c in results if c.security_id == security_id]
        if provenance is not None:
            results = [c for c in results if c.provenance == provenance]
        if start is not None:
            results = [c for c in results if c.as_of_time >= start]
        if end is not None:
            results = [c for c in results if c.as_of_time <= end]
        return sorted(results, key=lambda c: c.as_of_time)

    def get_as_of(
        self, security_id: str, as_of_time: datetime, *, provenance: Optional[TradeProvenance] = None,
    ) -> Optional[RiskCheckedPosition]:
        candidates = [
            c for c in self._checked.values()
            if c.security_id == security_id and c.as_of_time <= as_of_time
            and (provenance is None or c.provenance == provenance)
        ]
        if not candidates:
            return None
        # Tie-break on risk_id (ADR-0117) -- see decision.repository's
        # identical fix for the full reasoning.
        return max(candidates, key=lambda c: (c.as_of_time, c.risk_id))
