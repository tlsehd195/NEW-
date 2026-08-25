"""DuckDB persistent implementations of Phase 11's two Model Evolution
repository Protocols.

See docs/specifications/PHASE-11-model-evolution.md section 9 and
ADR-0017. Two new tables in Phase 4's existing catalog file -- the same
pattern ADR-0010/0011/0012/0013/0014/0015/0016 already applied to every
other Phase 5-10 dataset.
"""

from __future__ import annotations

from typing import Optional

from storage.engine import StorageEngine
from storage.serialization import (
    json_dumps,
    json_loads,
    model_lineage_to_payload,
    model_status_transition_to_payload,
    payload_to_model_lineage,
    payload_to_model_status_transition,
    to_utc_naive,
)

from evolution.models import ModelLineageRecord, ModelStatusTransition

from learning.enums import CandidateModelStatus


class DuckDBModelStatusTransitionRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, transition: ModelStatusTransition) -> ModelStatusTransition:
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT payload_json FROM model_status_transitions WHERE "
            "candidate_id = ? AND from_status = ? AND to_status = ? AND criteria_version = ?",
            [transition.candidate_id, transition.from_status.value, transition.to_status.value, transition.criteria_version],
        ).fetchone()
        if existing is not None:
            return payload_to_model_status_transition(json_loads(existing[0]))

        payload = model_status_transition_to_payload(transition)
        conn.execute(
            "INSERT INTO model_status_transitions (transition_id, candidate_id, from_status, to_status, "
            "criteria_version, passed, evaluated_at, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                transition.transition_id, transition.candidate_id, transition.from_status.value,
                transition.to_status.value, transition.criteria_version, transition.passed,
                to_utc_naive(transition.evaluated_at), json_dumps(payload),
            ],
        )
        return transition

    def get_history(self, candidate_id: str) -> tuple[ModelStatusTransition, ...]:
        cur = self._engine.connection.execute(
            "SELECT payload_json FROM model_status_transitions WHERE candidate_id = ? ORDER BY seq",
            [candidate_id],
        )
        return tuple(payload_to_model_status_transition(json_loads(r[0])) for r in cur.fetchall())

    def get_latest(self, candidate_id: str) -> Optional[ModelStatusTransition]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM model_status_transitions WHERE candidate_id = ? ORDER BY seq DESC LIMIT 1",
            [candidate_id],
        ).fetchone()
        return payload_to_model_status_transition(json_loads(row[0])) if row is not None else None

    def get_current_status(self, candidate_id: str) -> CandidateModelStatus:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM model_status_transitions WHERE candidate_id = ? AND passed = TRUE "
            "ORDER BY seq DESC LIMIT 1",
            [candidate_id],
        ).fetchone()
        if row is None:
            return CandidateModelStatus.CANDIDATE
        return payload_to_model_status_transition(json_loads(row[0])).to_status

    def list_all(self) -> list[ModelStatusTransition]:
        cur = self._engine.connection.execute("SELECT payload_json FROM model_status_transitions ORDER BY seq")
        return [payload_to_model_status_transition(json_loads(r[0])) for r in cur.fetchall()]


class DuckDBModelLineageRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, lineage: ModelLineageRecord) -> ModelLineageRecord:
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT payload_json FROM model_lineage WHERE candidate_id = ?", [lineage.candidate_id]
        ).fetchone()
        if existing is not None:
            return payload_to_model_lineage(json_loads(existing[0]))

        payload = model_lineage_to_payload(lineage)
        conn.execute(
            "INSERT INTO model_lineage (candidate_id, parent_candidate_id, generation, dataset_id, "
            "dataset_version, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            [
                lineage.candidate_id, lineage.parent_candidate_id, lineage.generation,
                lineage.dataset_id, lineage.dataset_version, json_dumps(payload),
            ],
        )
        return lineage

    def get(self, candidate_id: str) -> Optional[ModelLineageRecord]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM model_lineage WHERE candidate_id = ?", [candidate_id]
        ).fetchone()
        return payload_to_model_lineage(json_loads(row[0])) if row is not None else None

    def get_children(self, parent_candidate_id: str) -> list[ModelLineageRecord]:
        cur = self._engine.connection.execute(
            "SELECT payload_json FROM model_lineage WHERE parent_candidate_id = ? ORDER BY candidate_id",
            [parent_candidate_id],
        )
        return [payload_to_model_lineage(json_loads(r[0])) for r in cur.fetchall()]

    def list_all(self) -> list[ModelLineageRecord]:
        cur = self._engine.connection.execute("SELECT payload_json FROM model_lineage ORDER BY candidate_id")
        return [payload_to_model_lineage(json_loads(r[0])) for r in cur.fetchall()]
