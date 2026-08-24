"""DuckDBRegimeRepository: persistent implementation of Phase 5's
RegimeRepository Protocol.

See docs/specifications/PHASE-5-market-regime.md section 11 and
ADR-0011. Stored as DuckDB tables (not Parquet) -- see schema.py's
comment on `regime_observations`/`regime_composites` for the criterion
applied (same one ADR-0010 section 1 already used for Benchmark data).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from storage.engine import StorageEngine
from storage.serialization import (
    composite_regime_to_payload,
    json_dumps,
    json_loads,
    payload_to_composite_regime,
    payload_to_regime_observation,
    regime_observation_to_payload,
    to_utc_naive,
)

from regime.enums import RegimeAxis, SubjectKind
from regime.models import CompositeRegimeObservation, RegimeObservation

from trade_journal.enums import TradeProvenance


class DuckDBRegimeRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    @staticmethod
    def _observation_natural_key(o: RegimeObservation) -> str:
        return "|".join([
            o.subject_id, o.subject_kind.value, o.axis.value,
            to_utc_naive(o.as_of_time).isoformat(), o.configuration_version, o.provenance.value,
        ])

    @staticmethod
    def _composite_natural_key(c: CompositeRegimeObservation) -> str:
        return "|".join([c.subject_id, c.subject_kind.value, to_utc_naive(c.as_of_time).isoformat(), c.provenance.value])

    def record_observation(self, observation: RegimeObservation) -> RegimeObservation:
        conn = self._engine.connection
        key = self._observation_natural_key(observation)
        existing = conn.execute(
            "SELECT payload_json FROM regime_observations WHERE natural_key = ?", [key]
        ).fetchone()
        if existing is not None:
            return payload_to_regime_observation(json_loads(existing[0]))

        payload = regime_observation_to_payload(observation)
        conn.execute(
            "INSERT INTO regime_observations (regime_id, natural_key, axis, subject_id, subject_kind, "
            "timestamp, as_of_time, state, value, reliability, feature_version, method_version, "
            "configuration_version, provenance, experiment_id, recorded_at, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                observation.regime_id, key, observation.axis.value, observation.subject_id,
                observation.subject_kind.value, to_utc_naive(observation.timestamp),
                to_utc_naive(observation.as_of_time), observation.state, observation.value,
                observation.reliability, observation.feature_version, observation.method_version,
                observation.configuration_version, observation.provenance.value, observation.experiment_id,
                to_utc_naive(observation.recorded_at), json_dumps(payload),
            ],
        )
        return observation

    def record_composite(self, composite: CompositeRegimeObservation) -> CompositeRegimeObservation:
        conn = self._engine.connection
        key = self._composite_natural_key(composite)
        existing = conn.execute(
            "SELECT payload_json FROM regime_composites WHERE natural_key = ?", [key]
        ).fetchone()
        if existing is not None:
            return payload_to_composite_regime(json_loads(existing[0]))

        for observation in composite.axes.values():
            self.record_observation(observation)

        payload = composite_regime_to_payload(composite)
        conn.execute(
            "INSERT INTO regime_composites (composite_id, natural_key, subject_id, subject_kind, "
            "as_of_time, composite_label, provenance, experiment_id, recorded_at, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                composite.composite_id, key, composite.subject_id, composite.subject_kind.value,
                to_utc_naive(composite.as_of_time), composite.composite_label, composite.provenance.value,
                composite.experiment_id, to_utc_naive(composite.recorded_at), json_dumps(payload),
            ],
        )
        return composite

    def get_observation(self, regime_id: str) -> Optional[RegimeObservation]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM regime_observations WHERE regime_id = ?", [regime_id]
        ).fetchone()
        if row is None:
            return None
        return payload_to_regime_observation(json_loads(row[0]))

    def list_observations(
        self, *, subject_id: Optional[str] = None, axis: Optional[RegimeAxis] = None,
        provenance: Optional[TradeProvenance] = None,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[RegimeObservation]:
        sql = "SELECT payload_json FROM regime_observations WHERE 1=1"
        params: list = []
        if subject_id is not None:
            sql += " AND subject_id = ?"
            params.append(subject_id)
        if axis is not None:
            sql += " AND axis = ?"
            params.append(axis.value)
        if provenance is not None:
            sql += " AND provenance = ?"
            params.append(provenance.value)
        if start is not None:
            sql += " AND as_of_time >= ?"
            params.append(to_utc_naive(start))
        if end is not None:
            sql += " AND as_of_time <= ?"
            params.append(to_utc_naive(end))
        sql += " ORDER BY as_of_time, axis"
        cur = self._engine.connection.execute(sql, params)
        return [payload_to_regime_observation(json_loads(r[0])) for r in cur.fetchall()]

    def get_composite(self, composite_id: str) -> Optional[CompositeRegimeObservation]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM regime_composites WHERE composite_id = ?", [composite_id]
        ).fetchone()
        if row is None:
            return None
        return payload_to_composite_regime(json_loads(row[0]))

    def get_composite_as_of(
        self, subject_id: str, subject_kind: SubjectKind, as_of_time: datetime,
        *, provenance: Optional[TradeProvenance] = None,
    ) -> Optional[CompositeRegimeObservation]:
        sql = (
            "SELECT payload_json FROM regime_composites WHERE subject_id = ? AND subject_kind = ? "
            "AND as_of_time <= ?"
        )
        params: list = [subject_id, subject_kind.value, to_utc_naive(as_of_time)]
        if provenance is not None:
            sql += " AND provenance = ?"
            params.append(provenance.value)
        sql += " ORDER BY as_of_time DESC LIMIT 1"
        row = self._engine.connection.execute(sql, params).fetchone()
        if row is None:
            return None
        return payload_to_composite_regime(json_loads(row[0]))

    def list_composites(
        self, *, subject_id: Optional[str] = None, provenance: Optional[TradeProvenance] = None,
    ) -> list[CompositeRegimeObservation]:
        sql = "SELECT payload_json FROM regime_composites WHERE 1=1"
        params: list = []
        if subject_id is not None:
            sql += " AND subject_id = ?"
            params.append(subject_id)
        if provenance is not None:
            sql += " AND provenance = ?"
            params.append(provenance.value)
        sql += " ORDER BY as_of_time"
        cur = self._engine.connection.execute(sql, params)
        return [payload_to_composite_regime(json_loads(r[0])) for r in cur.fetchall()]
