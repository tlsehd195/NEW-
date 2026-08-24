"""ExperienceRepository: persistent storage for `ExperienceRecord`
(Phase 3 spec section 5.8), the substrate the Phase 9 Learning Engine
will eventually train on.

See docs/specifications/PHASE-4-baseline-models-and-storage.md section
13-15 (Part C, Paper Trading Data Foundation). Persisting experience
records is built now; a Learning Engine that consumes them is explicitly
*not* built in this phase (PROJECT_MASTER_PLAN.md section 11 / this
phase's instruction).
"""

from __future__ import annotations

import dataclasses
from typing import Optional, Protocol, Sequence

from storage.engine import StorageEngine
from storage.serialization import (
    experience_record_to_payload,
    json_dumps,
    json_loads,
    payload_to_experience_record,
    to_utc_naive,
)

from trade_journal.enums import TradeProvenance
from trade_journal.models import ExperienceRecord


class ExperienceRepository(Protocol):
    def record_many(self, records: Sequence[ExperienceRecord]) -> int:
        """Idempotent on trade_id (see DuckDBExperienceRepository
        docstring for why trade_id, not experience_id, is the dedup key).
        Returns the number of new rows actually written."""
        ...

    def list_all(self, *, provenance: Optional[TradeProvenance] = None) -> list[ExperienceRecord]: ...


class DuckDBExperienceRepository:
    """Note on the dedup key: `trade_journal.experience.build_experience_records`
    documents its own `experience_id` ("XR-000001", ...) as scoped to a
    single call, not a globally monotonic sequence (trade_journal/experience.py
    module docstring) -- calling it twice against a growing journal (the
    normal Part C / paper-trading pattern: journal accumulates trades over
    days, and build_experience_records is re-run periodically) legitimately
    produces the *same* "XR-000001" for two *different* trades. Persisting
    on that id verbatim would silently drop every record after the first
    call. `trade_id` is globally unique instead (it comes from the
    persistent Trade Journal's own monotonic TRD- sequence), so this
    repository dedupes on `trade_id` and allocates its own, storage-level
    globally-unique `experience_id` via `experience_id_seq` rather than
    trusting the caller-supplied one.
    """

    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record_many(self, records: Sequence[ExperienceRecord]) -> int:
        conn = self._engine.connection
        written = 0
        for record in records:
            existing = conn.execute(
                "SELECT 1 FROM experience_records WHERE trade_id = ?", [record.trade_id]
            ).fetchone()
            if existing is not None:
                continue
            storage_id = conn.execute("SELECT nextval('experience_id_seq')").fetchone()[0]
            record = dataclasses.replace(record, experience_id=f"XR-{storage_id:06d}")
            payload = experience_record_to_payload(record)
            conn.execute(
                "INSERT INTO experience_records (experience_id, trade_id, decision_id, action, "
                "provenance, reward, strategy_version, model_version, data_version, created_at, "
                "payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    record.experience_id, record.trade_id, record.decision_id, record.action.value,
                    record.provenance.value, record.reward, record.strategy_version, record.model_version,
                    json_dumps(list(record.data_version)) if record.data_version is not None else None,
                    to_utc_naive(record.created_at), json_dumps(payload),
                ],
            )
            written += 1
        return written

    def list_all(self, *, provenance: Optional[TradeProvenance] = None) -> list[ExperienceRecord]:
        sql = "SELECT payload_json FROM experience_records WHERE 1=1"
        params: list = []
        if provenance is not None:
            sql += " AND provenance = ?"
            params.append(provenance.value)
        sql += " ORDER BY experience_id"
        cur = self._engine.connection.execute(sql, params)
        return [payload_to_experience_record(json_loads(r[0])) for r in cur.fetchall()]
