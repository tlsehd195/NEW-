"""AttributionRepository and its in-memory reference implementation.

See docs/specifications/PHASE-10-counterfactual-attribution.md section
4.5. AttributionResult has no field of its own that marks one version as
authoritative other than recency -- exactly like Phase 3's
PostTradeAnalysis/CounterfactualRecord (Phase 3 spec section 9,
"Immutability & Correction") -- so it gets the same append/latest-wins
discipline rather than a new one invented for this phase (ADR-0016 point
2). CounterfactualRecord itself is NOT re-persisted here: Phase 3's
TradeJournalRepository already does that.
"""

from __future__ import annotations

from typing import Optional, Protocol

from trade_journal.models import AttributionResult


class AttributionRepository(Protocol):
    def record(self, result: AttributionResult) -> AttributionResult:
        """Idempotent in the sense that recording a result is always
        safe to call again (e.g. after a recompute) -- it appends a new
        version rather than raising or silently discarding, matching
        PostTradeAnalysis/CounterfactualRecord."""
        ...

    def get(self, experiment_id: str) -> Optional[AttributionResult]:
        """Latest recorded AttributionResult for this experiment_id, or
        None if none has ever been recorded."""
        ...

    def get_history(self, experiment_id: str) -> tuple[AttributionResult, ...]:
        """All recorded versions for this experiment_id, oldest first."""
        ...

    def list_all(self) -> list[AttributionResult]: ...


class InMemoryAttributionRepository:
    """Phase 10 reference implementation. No persistence, matching every
    prior phase's in-memory reference (InMemoryTradeJournalRepository,
    InMemoryDecisionRepository, InMemoryRiskRepository, etc.)."""

    def __init__(self) -> None:
        self._by_experiment: dict[str, list[AttributionResult]] = {}

    def record(self, result: AttributionResult) -> AttributionResult:
        self._by_experiment.setdefault(result.experiment_id, []).append(result)
        return result

    def get(self, experiment_id: str) -> Optional[AttributionResult]:
        history = self._by_experiment.get(experiment_id)
        if not history:
            return None
        return history[-1]

    def get_history(self, experiment_id: str) -> tuple[AttributionResult, ...]:
        return tuple(self._by_experiment.get(experiment_id, ()))

    def list_all(self) -> list[AttributionResult]:
        return [result for history in self._by_experiment.values() for result in history]
