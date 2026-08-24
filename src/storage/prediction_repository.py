"""DuckDBPredictionRepository: persistent implementation of Phase 6's
PredictionRepository Protocol.

See docs/specifications/PHASE-6-prediction.md section 11 and ADR-0012.
Stored as a DuckDB table (not Parquet) -- the same criterion ADR-0010
section 1 / ADR-0011 section 4 already applied to Benchmark and Regime
data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from storage.engine import StorageEngine
from storage.serialization import (
    json_dumps,
    json_loads,
    payload_to_prediction_output,
    prediction_output_to_payload,
    to_utc_naive,
)

from predict.models import PredictionOutput

from trade_journal.enums import TradeProvenance


class DuckDBPredictionRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    @staticmethod
    def _natural_key(p: PredictionOutput) -> str:
        return "|".join([
            p.security_id, to_utc_naive(p.as_of_time).isoformat(), p.method,
            str(p.horizon_days), p.configuration_version, p.provenance.value,
        ])

    def record(self, prediction: PredictionOutput) -> PredictionOutput:
        conn = self._engine.connection
        key = self._natural_key(prediction)
        existing = conn.execute(
            "SELECT payload_json FROM predictions WHERE natural_key = ?", [key]
        ).fetchone()
        if existing is not None:
            return payload_to_prediction_output(json_loads(existing[0]))

        payload = prediction_output_to_payload(prediction)
        conn.execute(
            "INSERT INTO predictions (prediction_id, natural_key, security_id, as_of_time, "
            "horizon_days, expected_return, probability, expected_volatility, uncertainty, "
            "confidence, method, method_type, feature_version, method_version, "
            "configuration_version, model_version, provenance, experiment_id, recorded_at, "
            "payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                prediction.prediction_id, key, prediction.security_id, to_utc_naive(prediction.as_of_time),
                prediction.horizon_days, prediction.expected_return, prediction.probability,
                prediction.expected_volatility, prediction.uncertainty, prediction.confidence,
                prediction.method, prediction.method_type.value, prediction.feature_version,
                prediction.method_version, prediction.configuration_version, prediction.model_version,
                prediction.provenance.value, prediction.experiment_id, to_utc_naive(prediction.recorded_at),
                json_dumps(payload),
            ],
        )
        return prediction

    def get(self, prediction_id: str) -> Optional[PredictionOutput]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM predictions WHERE prediction_id = ?", [prediction_id]
        ).fetchone()
        if row is None:
            return None
        return payload_to_prediction_output(json_loads(row[0]))

    def list_all(
        self, *, security_id: Optional[str] = None, method: Optional[str] = None,
        provenance: Optional[TradeProvenance] = None,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[PredictionOutput]:
        sql = "SELECT payload_json FROM predictions WHERE 1=1"
        params: list = []
        if security_id is not None:
            sql += " AND security_id = ?"
            params.append(security_id)
        if method is not None:
            sql += " AND method = ?"
            params.append(method)
        if provenance is not None:
            sql += " AND provenance = ?"
            params.append(provenance.value)
        if start is not None:
            sql += " AND as_of_time >= ?"
            params.append(to_utc_naive(start))
        if end is not None:
            sql += " AND as_of_time <= ?"
            params.append(to_utc_naive(end))
        sql += " ORDER BY as_of_time"
        cur = self._engine.connection.execute(sql, params)
        return [payload_to_prediction_output(json_loads(r[0])) for r in cur.fetchall()]

    def get_as_of(
        self, security_id: str, as_of_time: datetime, *,
        method: Optional[str] = None, provenance: Optional[TradeProvenance] = None,
    ) -> Optional[PredictionOutput]:
        sql = "SELECT payload_json FROM predictions WHERE security_id = ? AND as_of_time <= ?"
        params: list = [security_id, to_utc_naive(as_of_time)]
        if method is not None:
            sql += " AND method = ?"
            params.append(method)
        if provenance is not None:
            sql += " AND provenance = ?"
            params.append(provenance.value)
        sql += " ORDER BY as_of_time DESC LIMIT 1"
        row = self._engine.connection.execute(sql, params).fetchone()
        if row is None:
            return None
        return payload_to_prediction_output(json_loads(row[0]))
