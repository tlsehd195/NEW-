"""Repository Protocols + InMemory reference implementations for Model
Evolution's two persisted types, mirroring the Repository Protocol
discipline every prior phase already established.

See docs/specifications/PHASE-11-model-evolution.md section 9.
"""

from __future__ import annotations

from typing import Optional, Protocol

from evolution.models import ModelLineageRecord, ModelStatusTransition

from learning.enums import CandidateModelStatus


class ModelStatusTransitionRepository(Protocol):
    def record(self, transition: ModelStatusTransition) -> ModelStatusTransition:
        """Append-only -- idempotent on `(candidate_id, from_status,
        to_status, criteria_version)`: retrying the exact same attempted
        transition returns the existing record rather than duplicating
        it, but a transition with a different outcome (e.g. re-evaluated
        after new criteria) is still recorded as a new, distinct
        attempt."""
        ...

    def get_latest(self, candidate_id: str) -> Optional[ModelStatusTransition]: ...
    def get_current_status(self, candidate_id: str) -> CandidateModelStatus:
        """`CandidateModelStatus.CANDIDATE` when no transition has been
        recorded yet; otherwise the `to_status` of the most recent
        *passed* transition (a failed attempt never advances the
        candidate's current status)."""
        ...

    def get_history(self, candidate_id: str) -> tuple[ModelStatusTransition, ...]: ...
    def list_all(self) -> list[ModelStatusTransition]: ...


class InMemoryModelStatusTransitionRepository:
    def __init__(self) -> None:
        self._transitions: list[ModelStatusTransition] = []
        self._natural_keys: dict[tuple, ModelStatusTransition] = {}

    @staticmethod
    def _key(t: ModelStatusTransition) -> tuple:
        # Session 37 (ADR-0115, external review N-9): `passed` included
        # -- without it, a candidate that FAILS evaluation against
        # `criteria_version` once and later PASSES the identical
        # (candidate_id, from_status, to_status, criteria_version)
        # transition on a retry (e.g. after a fix, still against the
        # same criteria version) collided with the earlier failed
        # attempt's key and was silently discarded, permanently
        # preventing that candidate from ever being promoted -- directly
        # contradicting this Protocol's own docstring ("a transition
        # with a different outcome ... is still recorded as a new,
        # distinct attempt").
        return (t.candidate_id, t.from_status, t.to_status, t.criteria_version, t.passed)

    def record(self, transition: ModelStatusTransition) -> ModelStatusTransition:
        key = self._key(transition)
        existing = self._natural_keys.get(key)
        if existing is not None:
            return existing
        self._transitions.append(transition)
        self._natural_keys[key] = transition
        return transition

    def get_history(self, candidate_id: str) -> tuple[ModelStatusTransition, ...]:
        return tuple(t for t in self._transitions if t.candidate_id == candidate_id)

    def get_latest(self, candidate_id: str) -> Optional[ModelStatusTransition]:
        history = self.get_history(candidate_id)
        if not history:
            return None
        return max(history, key=lambda t: (t.evaluated_at, t.transition_id))

    def get_current_status(self, candidate_id: str) -> CandidateModelStatus:
        passed = [t for t in self.get_history(candidate_id) if t.passed]
        if not passed:
            return CandidateModelStatus.CANDIDATE
        latest = max(passed, key=lambda t: (t.evaluated_at, t.transition_id))
        return latest.to_status

    def list_all(self) -> list[ModelStatusTransition]:
        return sorted(self._transitions, key=lambda t: (t.evaluated_at, t.transition_id))


class ModelLineageRepository(Protocol):
    def record(self, lineage: ModelLineageRecord) -> ModelLineageRecord:
        """Idempotent on `candidate_id` -- a candidate has exactly one
        lineage record."""
        ...

    def get(self, candidate_id: str) -> Optional[ModelLineageRecord]: ...
    def get_children(self, parent_candidate_id: str) -> list[ModelLineageRecord]: ...
    def list_all(self) -> list[ModelLineageRecord]: ...


class InMemoryModelLineageRepository:
    def __init__(self) -> None:
        self._lineage: dict[str, ModelLineageRecord] = {}

    def record(self, lineage: ModelLineageRecord) -> ModelLineageRecord:
        existing = self._lineage.get(lineage.candidate_id)
        if existing is not None:
            return existing
        self._lineage[lineage.candidate_id] = lineage
        return lineage

    def get(self, candidate_id: str) -> Optional[ModelLineageRecord]:
        return self._lineage.get(candidate_id)

    def get_children(self, parent_candidate_id: str) -> list[ModelLineageRecord]:
        return [r for r in self._lineage.values() if r.parent_candidate_id == parent_candidate_id]

    def list_all(self) -> list[ModelLineageRecord]:
        return sorted(self._lineage.values(), key=lambda r: r.candidate_id)
