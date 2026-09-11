"""DuckDBPositionSizingRepository / DuckDBRiskRepository: persistent
implementations of Phase 8's PositionSizingRepository/RiskRepository
Protocols.

See docs/specifications/PHASE-8-position-sizing-and-risk.md section 11
and ADR-0014. Two new DuckDB tables (`position_sizing_results`,
`risk_assessments`) in Phase 4's existing catalog file -- the same
point-lookup/filter/join-heavy criterion ADR-0010 section 1 /
ADR-0011 section 4 / ADR-0012 section 8 / ADR-0013 section 8 already
applied to Benchmark, Regime, Prediction, and Decision data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from storage.engine import StorageEngine
from storage.serialization import (
    json_dumps,
    json_loads,
    payload_to_position_sizing_result,
    payload_to_risk_checked_position,
    position_sizing_result_to_payload,
    risk_checked_position_to_payload,
    to_utc_naive,
)

from risk.models import PositionSizingResult, RiskCheckedPosition

from trade_journal.enums import TradeProvenance


class DuckDBPositionSizingRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    @staticmethod
    def _natural_key(r: PositionSizingResult) -> str:
        return "|".join([
            r.security_id, to_utc_naive(r.as_of_time).isoformat(), r.sizing_version,
            str(r.decision_id), r.provenance.value,
        ])

    def record(self, result: PositionSizingResult) -> PositionSizingResult:
        conn = self._engine.connection
        key = self._natural_key(result)
        existing = conn.execute(
            "SELECT payload_json FROM position_sizing_results WHERE natural_key = ?", [key]
        ).fetchone()
        if existing is not None:
            return payload_to_position_sizing_result(json_loads(existing[0]))

        payload = position_sizing_result_to_payload(result)
        conn.execute(
            "INSERT INTO position_sizing_results (sizing_id, natural_key, security_id, as_of_time, "
            "status, reason, decision_id, decision_action, proposed_target_weight, "
            "proposed_target_quantity, current_weight, current_quantity, sizing_version, "
            "feature_version, prediction_id, decision_version, prediction_version, regime_version, "
            "provenance, experiment_id, recorded_at, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                result.sizing_id, key, result.security_id, to_utc_naive(result.as_of_time),
                result.status.value, result.reason, result.decision_id,
                result.decision_action.value if result.decision_action is not None else None,
                result.proposed_target_weight, result.proposed_target_quantity, result.current_weight,
                result.current_quantity, result.sizing_version, result.feature_version,
                result.prediction_id, result.decision_version, result.prediction_version,
                result.regime_version, result.provenance.value, result.experiment_id,
                to_utc_naive(result.recorded_at), json_dumps(payload),
            ],
        )
        return result

    def get(self, sizing_id: str) -> Optional[PositionSizingResult]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM position_sizing_results WHERE sizing_id = ?", [sizing_id]
        ).fetchone()
        if row is None:
            return None
        return payload_to_position_sizing_result(json_loads(row[0]))

    def list_all(
        self, *, security_id: Optional[str] = None, provenance: Optional[TradeProvenance] = None,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[PositionSizingResult]:
        sql = "SELECT payload_json FROM position_sizing_results WHERE 1=1"
        params: list = []
        if security_id is not None:
            sql += " AND security_id = ?"
            params.append(security_id)
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
        return [payload_to_position_sizing_result(json_loads(r[0])) for r in cur.fetchall()]

    def get_as_of(
        self, security_id: str, as_of_time: datetime, *, provenance: Optional[TradeProvenance] = None,
    ) -> Optional[PositionSizingResult]:
        sql = "SELECT payload_json FROM position_sizing_results WHERE security_id = ? AND as_of_time <= ?"
        params: list = [security_id, to_utc_naive(as_of_time)]
        if provenance is not None:
            sql += " AND provenance = ?"
            params.append(provenance.value)
        # Tie-break on sizing_id (ADR-0117) -- see
        # storage.decision_repository's identical fix for the reasoning.
        sql += " ORDER BY as_of_time DESC, sizing_id DESC LIMIT 1"
        row = self._engine.connection.execute(sql, params).fetchone()
        if row is None:
            return None
        return payload_to_position_sizing_result(json_loads(row[0]))


class DuckDBRiskRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    @staticmethod
    def _natural_key(c: RiskCheckedPosition) -> str:
        return "|".join([
            c.security_id, to_utc_naive(c.as_of_time).isoformat(), c.risk_version,
            str(c.sizing_id), c.provenance.value,
        ])

    def record(self, checked: RiskCheckedPosition) -> RiskCheckedPosition:
        conn = self._engine.connection
        key = self._natural_key(checked)
        existing = conn.execute(
            "SELECT payload_json FROM risk_assessments WHERE natural_key = ?", [key]
        ).fetchone()
        if existing is not None:
            return payload_to_risk_checked_position(json_loads(existing[0]))

        payload = risk_checked_position_to_payload(checked)
        conn.execute(
            "INSERT INTO risk_assessments (risk_id, natural_key, security_id, as_of_time, status, "
            "reason, final_target_weight, final_target_quantity, sizing_id, decision_id, "
            "prediction_id, risk_version, feature_version, sizing_version, decision_version, "
            "prediction_version, regime_version, provenance, experiment_id, recorded_at, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                checked.risk_id, key, checked.security_id, to_utc_naive(checked.as_of_time),
                checked.status.value, checked.reason, checked.final_target_weight,
                checked.final_target_quantity, checked.sizing_id, checked.decision_id,
                checked.prediction_id, checked.risk_version, checked.feature_version,
                checked.sizing_version, checked.decision_version, checked.prediction_version,
                checked.regime_version, checked.provenance.value, checked.experiment_id,
                to_utc_naive(checked.recorded_at), json_dumps(payload),
            ],
        )
        return checked

    def get(self, risk_id: str) -> Optional[RiskCheckedPosition]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM risk_assessments WHERE risk_id = ?", [risk_id]
        ).fetchone()
        if row is None:
            return None
        return payload_to_risk_checked_position(json_loads(row[0]))

    def list_all(
        self, *, security_id: Optional[str] = None, provenance: Optional[TradeProvenance] = None,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[RiskCheckedPosition]:
        sql = "SELECT payload_json FROM risk_assessments WHERE 1=1"
        params: list = []
        if security_id is not None:
            sql += " AND security_id = ?"
            params.append(security_id)
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
        return [payload_to_risk_checked_position(json_loads(r[0])) for r in cur.fetchall()]

    def get_as_of(
        self, security_id: str, as_of_time: datetime, *, provenance: Optional[TradeProvenance] = None,
    ) -> Optional[RiskCheckedPosition]:
        sql = "SELECT payload_json FROM risk_assessments WHERE security_id = ? AND as_of_time <= ?"
        params: list = [security_id, to_utc_naive(as_of_time)]
        if provenance is not None:
            sql += " AND provenance = ?"
            params.append(provenance.value)
        # Tie-break on risk_id (ADR-0117) -- see
        # storage.decision_repository's identical fix for the reasoning.
        sql += " ORDER BY as_of_time DESC, risk_id DESC LIMIT 1"
        row = self._engine.connection.execute(sql, params).fetchone()
        if row is None:
            return None
        return payload_to_risk_checked_position(json_loads(row[0]))
