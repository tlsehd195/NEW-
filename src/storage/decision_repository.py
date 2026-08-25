"""DuckDBDecisionRepository: persistent implementation of Phase 7's
DecisionRepository Protocol.

See docs/specifications/PHASE-7-decision-agent.md section 11 and
ADR-0013. Stored as a DuckDB table (`decision_outputs`, deliberately
named apart from Trade Journal's own `decisions` table to avoid any
ambiguity between the two) -- the same point-lookup/filter/join-heavy
criterion ADR-0010 section 1 / ADR-0011 section 4 / ADR-0012 section 8
already applied to Benchmark, Regime, and Prediction data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from storage.engine import StorageEngine
from storage.serialization import (
    decision_output_to_payload,
    json_dumps,
    json_loads,
    payload_to_decision_output,
    to_utc_naive,
)

from decision.models import DecisionOutput

from trade_journal.enums import TradeProvenance


class DuckDBDecisionRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    @staticmethod
    def _natural_key(d: DecisionOutput) -> str:
        return "|".join([
            d.security_id, to_utc_naive(d.as_of_time).isoformat(), d.decision_version,
            str(d.prediction_id), d.provenance.value,
        ])

    def record(self, decision: DecisionOutput) -> DecisionOutput:
        conn = self._engine.connection
        key = self._natural_key(decision)
        existing = conn.execute(
            "SELECT payload_json FROM decision_outputs WHERE natural_key = ?", [key]
        ).fetchone()
        if existing is not None:
            return payload_to_decision_output(json_loads(existing[0]))

        payload = decision_output_to_payload(decision)
        conn.execute(
            "INSERT INTO decision_outputs (decision_id, natural_key, security_id, as_of_time, "
            "action, decision_reason, confidence, time_horizon_days, target_weight_hint, "
            "prediction_id, prediction_version, regime_version, feature_version, model_version, "
            "decision_version, strategy_version, risk_version, provenance, experiment_id, "
            "recorded_at, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                decision.decision_id, key, decision.security_id, to_utc_naive(decision.as_of_time),
                decision.action.value, decision.decision_reason, decision.confidence,
                decision.time_horizon_days, decision.target_weight_hint, decision.prediction_id,
                decision.prediction_version, decision.regime_version, decision.feature_version,
                decision.model_version, decision.decision_version, decision.strategy_version,
                decision.risk_version, decision.provenance.value, decision.experiment_id,
                to_utc_naive(decision.recorded_at), json_dumps(payload),
            ],
        )
        return decision

    def get(self, decision_id: str) -> Optional[DecisionOutput]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM decision_outputs WHERE decision_id = ?", [decision_id]
        ).fetchone()
        if row is None:
            return None
        return payload_to_decision_output(json_loads(row[0]))

    def list_all(
        self, *, security_id: Optional[str] = None, action: Optional[str] = None,
        provenance: Optional[TradeProvenance] = None,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[DecisionOutput]:
        sql = "SELECT payload_json FROM decision_outputs WHERE 1=1"
        params: list = []
        if security_id is not None:
            sql += " AND security_id = ?"
            params.append(security_id)
        if action is not None:
            sql += " AND action = ?"
            params.append(action)
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
        return [payload_to_decision_output(json_loads(r[0])) for r in cur.fetchall()]

    def get_as_of(
        self, security_id: str, as_of_time: datetime, *,
        provenance: Optional[TradeProvenance] = None,
    ) -> Optional[DecisionOutput]:
        sql = "SELECT payload_json FROM decision_outputs WHERE security_id = ? AND as_of_time <= ?"
        params: list = [security_id, to_utc_naive(as_of_time)]
        if provenance is not None:
            sql += " AND provenance = ?"
            params.append(provenance.value)
        sql += " ORDER BY as_of_time DESC LIMIT 1"
        row = self._engine.connection.execute(sql, params).fetchone()
        if row is None:
            return None
        return payload_to_decision_output(json_loads(row[0]))
