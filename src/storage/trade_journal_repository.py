"""DuckDBTradeJournalRepository: a persistent implementation of Phase 3's
TradeJournalRepository Protocol.

See docs/specifications/PHASE-4-baseline-models-and-storage.md section 4
and ADR-0010. Preserves every Phase 3 guarantee (ADR-0009):
- No `update_*`/`delete_*` method exists -- mutation is structurally
  unreachable through this class, the same as
  `InMemoryTradeJournalRepository` (Immutability + Correction, Phase 3
  spec section 9).
- Idempotency is enforced by a natural-key UNIQUE constraint
  (`decisions.natural_key` / `trades.natural_key`), checked before
  insert -- a duplicate call returns the existing record, never a second
  row (Phase 3 spec section 8).
- `provenance` is always copied verbatim, never inferred (Phase 3 spec
  section 10).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from backtest.orders import Order

from storage.engine import StorageEngine
from storage.serialization import (
    correction_to_row,
    counterfactual_to_payload,
    decision_snapshot_to_payload,
    json_dumps,
    json_loads,
    payload_to_counterfactual,
    payload_to_decision_snapshot,
    payload_to_post_trade_analysis,
    payload_to_trade_record,
    post_trade_analysis_to_payload,
    row_to_correction,
    to_utc_naive,
    trade_record_to_payload,
)

from trade_journal.enums import CorrectionTargetType, DecisionAction, TradeProvenance
from trade_journal.models import (
    AlternativeOutcome,
    AuditTrail,
    CorrectionRecord,
    CounterfactualRecord,
    DecisionSnapshot,
    PostTradeAnalysis,
    TradeRecord,
)


def _rows(cursor) -> list[dict]:
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


class DuckDBTradeJournalRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    # -- decisions ---------------------------------------------------

    def record_decision(
        self,
        *,
        decision_time: datetime,
        security_id: str,
        decision: DecisionAction,
        order: Optional[Order] = None,
        experiment_id: Optional[str] = None,
        natural_key: Optional[tuple] = None,
        recorded_at: Optional[datetime] = None,
        **fields,
    ) -> DecisionSnapshot:
        key = natural_key
        if key is None and order is not None:
            key = ("decision", experiment_id, order.order_id)
        key_str = "|".join(str(part) for part in key) if key is not None else None

        conn = self._engine.connection
        if key_str is not None:
            existing = conn.execute(
                "SELECT payload_json FROM decisions WHERE natural_key = ?", [key_str]
            ).fetchone()
            if existing is not None:
                return payload_to_decision_snapshot(json_loads(existing[0]))

        snapshot_id = self._allocate_id("decision_id_seq", "DEC")
        snapshot = DecisionSnapshot(
            snapshot_id=snapshot_id,
            decision_time=decision_time,
            security_id=security_id,
            decision=decision,
            order=order,
            experiment_id=experiment_id,
            recorded_at=recorded_at or decision_time,
            **fields,
        )
        payload = decision_snapshot_to_payload(snapshot)
        conn.execute(
            "INSERT INTO decisions (snapshot_id, natural_key, decision_time, security_id, decision, "
            "strategy_version, execution_version, provenance, experiment_id, data_version, "
            "feature_version, model_version, risk_version, confidence, expected_return, "
            "expected_risk, target_weight, decision_reason, recorded_at, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                snapshot.snapshot_id, key_str, to_utc_naive(snapshot.decision_time), snapshot.security_id,
                snapshot.decision.value, snapshot.strategy_version, snapshot.execution_version,
                snapshot.provenance.value, snapshot.experiment_id,
                json_dumps(list(snapshot.data_version)) if snapshot.data_version is not None else None,
                snapshot.feature_version, snapshot.model_version, snapshot.risk_version,
                snapshot.confidence, snapshot.expected_return, snapshot.expected_risk,
                snapshot.target_weight, snapshot.decision_reason, to_utc_naive(snapshot.recorded_at),
                json_dumps(payload),
            ],
        )
        return snapshot

    def _allocate_id(self, sequence: str, prefix: str) -> str:
        value = self._engine.connection.execute(f"SELECT nextval('{sequence}')").fetchone()[0]
        return f"{prefix}-{value:06d}"

    def get_decision(self, snapshot_id: str) -> Optional[DecisionSnapshot]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM decisions WHERE snapshot_id = ?", [snapshot_id]
        ).fetchone()
        if row is None:
            return None
        return payload_to_decision_snapshot(json_loads(row[0]))

    def list_decisions(
        self, *, security_id: Optional[str] = None, provenance: Optional[TradeProvenance] = None,
    ) -> list[DecisionSnapshot]:
        sql = "SELECT payload_json FROM decisions WHERE 1=1"
        params: list = []
        if security_id is not None:
            sql += " AND security_id = ?"
            params.append(security_id)
        if provenance is not None:
            sql += " AND provenance = ?"
            params.append(provenance.value)
        sql += " ORDER BY decision_time"
        cur = self._engine.connection.execute(sql, params)
        return [payload_to_decision_snapshot(json_loads(r[0])) for r in cur.fetchall()]

    # -- trades --------------------------------------------------------

    def record_trade(
        self,
        *,
        decision_id: str,
        fill,
        position_after: float,
        experiment_id: Optional[str] = None,
        realized_pnl: Optional[float] = None,
        realized_return: Optional[float] = None,
        holding_period=None,
        provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
        recorded_at: Optional[datetime] = None,
    ) -> TradeRecord:
        # Phase 17 Production Safety Review bug fix -- see the identical
        # fix and full explanation in
        # trade_journal.repository.InMemoryTradeJournalRepository.record_trade:
        # fill.order_id alone collides across every partial fill of one
        # order, silently dropping all but the first from the Trade
        # Journal.
        key_str = f"trade|{experiment_id}|{fill.order_id}|{fill.execution_time.isoformat()}"
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT payload_json FROM trades WHERE natural_key = ?", [key_str]
        ).fetchone()
        if existing is not None:
            return payload_to_trade_record(json_loads(existing[0]))

        trade_id = self._allocate_id("trade_id_seq", "TRD")
        trade = TradeRecord(
            trade_id=trade_id,
            decision_id=decision_id,
            order_id=fill.order_id,
            security_id=fill.security_id,
            timestamp=fill.execution_time,
            side=fill.side,
            quantity=fill.quantity,
            execution_price=fill.price,
            reference_price=fill.reference_price,
            slippage=fill.slippage_cost,
            transaction_cost=fill.total_cost,
            position_after=position_after,
            fill=fill,
            realized_pnl=realized_pnl,
            realized_return=realized_return,
            holding_period=holding_period,
            provenance=provenance,
            experiment_id=experiment_id,
            recorded_at=recorded_at or fill.execution_time,
        )
        payload = trade_record_to_payload(trade)
        conn.execute(
            "INSERT INTO trades (trade_id, natural_key, decision_id, order_id, security_id, timestamp, "
            "side, quantity, execution_price, reference_price, slippage, transaction_cost, "
            "position_after, realized_pnl, realized_return, holding_period_seconds, provenance, "
            "experiment_id, recorded_at, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                trade.trade_id, key_str, trade.decision_id, trade.order_id, trade.security_id,
                to_utc_naive(trade.timestamp), trade.side.value, trade.quantity, trade.execution_price,
                trade.reference_price, trade.slippage, trade.transaction_cost, trade.position_after,
                trade.realized_pnl, trade.realized_return,
                trade.holding_period.total_seconds() if trade.holding_period is not None else None,
                trade.provenance.value, trade.experiment_id, to_utc_naive(trade.recorded_at),
                json_dumps(payload),
            ],
        )
        return trade

    def get_trade(self, trade_id: str) -> Optional[TradeRecord]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM trades WHERE trade_id = ?", [trade_id]
        ).fetchone()
        if row is None:
            return None
        return payload_to_trade_record(json_loads(row[0]))

    def list_trades(
        self, *, security_id: Optional[str] = None, provenance: Optional[TradeProvenance] = None,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[TradeRecord]:
        sql = "SELECT payload_json FROM trades WHERE 1=1"
        params: list = []
        if security_id is not None:
            sql += " AND security_id = ?"
            params.append(security_id)
        if provenance is not None:
            sql += " AND provenance = ?"
            params.append(provenance.value)
        if start is not None:
            sql += " AND timestamp >= ?"
            params.append(to_utc_naive(start))
        if end is not None:
            sql += " AND timestamp <= ?"
            params.append(to_utc_naive(end))
        sql += " ORDER BY timestamp"
        cur = self._engine.connection.execute(sql, params)
        return [payload_to_trade_record(json_loads(r[0])) for r in cur.fetchall()]

    # -- post trade analysis / counterfactual ---------------------------

    def record_post_trade_analysis(self, trade_id: str, **fields) -> PostTradeAnalysis:
        analysis = PostTradeAnalysis(trade_id=trade_id, **fields)
        payload = post_trade_analysis_to_payload(analysis)
        self._engine.connection.execute(
            "INSERT INTO post_trade_analyses (trade_id, computed_at, payload_json) VALUES (?, ?, ?)",
            [trade_id, to_utc_naive(analysis.computed_at), json_dumps(payload)],
        )
        return analysis

    def get_post_trade_analysis(self, trade_id: str) -> Optional[PostTradeAnalysis]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM post_trade_analyses WHERE trade_id = ? ORDER BY seq DESC LIMIT 1",
            [trade_id],
        ).fetchone()
        if row is None:
            return None
        return payload_to_post_trade_analysis(json_loads(row[0]))

    def get_post_trade_analysis_history(self, trade_id: str) -> tuple[PostTradeAnalysis, ...]:
        cur = self._engine.connection.execute(
            "SELECT payload_json FROM post_trade_analyses WHERE trade_id = ? ORDER BY seq", [trade_id]
        )
        return tuple(payload_to_post_trade_analysis(json_loads(r[0])) for r in cur.fetchall())

    def record_counterfactual(
        self, trade_id: str, selected_action: DecisionAction, alternatives: tuple[AlternativeOutcome, ...],
        computed_at: Optional[datetime] = None,
    ) -> CounterfactualRecord:
        record = CounterfactualRecord(
            trade_id=trade_id, selected_action=selected_action, alternatives=alternatives,
            computed_at=computed_at,
        )
        payload = counterfactual_to_payload(record)
        self._engine.connection.execute(
            "INSERT INTO counterfactuals (trade_id, computed_at, payload_json) VALUES (?, ?, ?)",
            [trade_id, to_utc_naive(computed_at), json_dumps(payload)],
        )
        return record

    def get_counterfactual(self, trade_id: str) -> Optional[CounterfactualRecord]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM counterfactuals WHERE trade_id = ? ORDER BY seq DESC LIMIT 1",
            [trade_id],
        ).fetchone()
        if row is None:
            return None
        return payload_to_counterfactual(json_loads(row[0]))

    # -- corrections -----------------------------------------------------

    def record_correction(
        self, target_type: CorrectionTargetType, target_id: str, reason: str,
        corrected_fields: dict, created_at: datetime, created_by: str = "system",
    ) -> CorrectionRecord:
        correction_id = self._allocate_id("correction_id_seq", "COR")
        correction = CorrectionRecord(
            correction_id=correction_id, target_type=target_type, target_id=target_id,
            reason=reason, corrected_fields=corrected_fields, created_at=created_at, created_by=created_by,
        )
        row = correction_to_row(correction)
        self._engine.connection.execute(
            "INSERT INTO corrections (correction_id, target_type, target_id, reason, "
            "corrected_fields_json, created_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                row["correction_id"], row["target_type"], row["target_id"], row["reason"],
                row["corrected_fields_json"], row["created_at"], row["created_by"],
            ],
        )
        return correction

    def get_corrections(self, target_id: str) -> tuple[CorrectionRecord, ...]:
        cur = self._engine.connection.execute(
            "SELECT * FROM corrections WHERE target_id = ? ORDER BY created_at", [target_id]
        )
        return tuple(row_to_correction(r) for r in _rows(cur))

    # -- audit -------------------------------------------------------------

    def audit_trail(self, trade_id: str) -> AuditTrail:
        trade = self.get_trade(trade_id)
        decision = self.get_decision(trade.decision_id) if trade is not None else None
        corrections = self.get_corrections(trade_id) + (
            self.get_corrections(decision.snapshot_id) if decision is not None else ()
        )
        return AuditTrail(
            decision=decision,
            trade=trade,
            post_trade_analysis=self.get_post_trade_analysis(trade_id),
            counterfactual=self.get_counterfactual(trade_id),
            corrections=corrections,
        )
