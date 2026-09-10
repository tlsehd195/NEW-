"""TradeJournalRepository and its in-memory reference implementation.

See docs/specifications/PHASE-3-trade-journal.md sections 8, 9, 11, 14.

Mirrors the Repository-interface discipline Phase 1's DataRepository
established (data_infra/repository.py): consumers depend on the Protocol,
never on this in-memory implementation directly. Id allocation happens
inside record_* methods (never accepted from the caller), the same
pattern Phase 1's DataQualityFramework and Phase 2's OrderSimulator/
ExperimentTracker already use — this is what makes natural-key
idempotency (section 8) enforceable in one place.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol

from backtest.orders import Order

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


class TradeJournalRepository(Protocol):
    def record_decision(self, **fields) -> DecisionSnapshot: ...

    def record_trade(self, **fields) -> TradeRecord: ...

    def record_post_trade_analysis(self, trade_id: str, **fields) -> PostTradeAnalysis: ...

    def record_counterfactual(
        self, trade_id: str, selected_action: DecisionAction, alternatives: tuple[AlternativeOutcome, ...]
    ) -> CounterfactualRecord: ...

    def record_correction(
        self, target_type: CorrectionTargetType, target_id: str, reason: str,
        corrected_fields: dict, created_at: datetime, created_by: str = "system",
    ) -> CorrectionRecord: ...

    def get_decision(self, snapshot_id: str) -> Optional[DecisionSnapshot]: ...

    def get_trade(self, trade_id: str) -> Optional[TradeRecord]: ...

    def list_trades(
        self, *, security_id: Optional[str] = None, provenance: Optional[TradeProvenance] = None,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[TradeRecord]: ...

    def list_decisions(
        self, *, security_id: Optional[str] = None, provenance: Optional[TradeProvenance] = None,
    ) -> list[DecisionSnapshot]: ...

    def get_post_trade_analysis(self, trade_id: str) -> Optional[PostTradeAnalysis]: ...

    def get_counterfactual(self, trade_id: str) -> Optional[CounterfactualRecord]: ...

    def get_corrections(self, target_id: str) -> tuple[CorrectionRecord, ...]: ...

    def audit_trail(self, trade_id: str) -> AuditTrail: ...


class InMemoryTradeJournalRepository:
    """Phase 3 reference implementation. No persistence, matching Phase
    1's still-deferred DuckDB/Parquet backend (ADR-0002) and Phase 2's
    in-process ExperimentTracker — no new storage decision is made here."""

    def __init__(self) -> None:
        self._next_decision_id = 1
        self._next_trade_id = 1
        self._next_correction_id = 1

        self._decisions: dict[str, DecisionSnapshot] = {}
        self._decision_natural_keys: dict[tuple, str] = {}

        self._trades: dict[str, TradeRecord] = {}
        self._trade_natural_keys: dict[tuple, str] = {}

        self._post_trade_analyses: dict[str, list[PostTradeAnalysis]] = {}
        self._counterfactuals: dict[str, list[CounterfactualRecord]] = {}
        self._corrections: dict[str, list[CorrectionRecord]] = {}

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
        if key is not None and key in self._decision_natural_keys:
            return self._decisions[self._decision_natural_keys[key]]

        snapshot_id = f"DEC-{self._next_decision_id:06d}"
        self._next_decision_id += 1
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
        self._decisions[snapshot_id] = snapshot
        if key is not None:
            self._decision_natural_keys[key] = snapshot_id
        return snapshot

    def get_decision(self, snapshot_id: str) -> Optional[DecisionSnapshot]:
        return self._decisions.get(snapshot_id)

    def list_decisions(
        self, *, security_id: Optional[str] = None, provenance: Optional[TradeProvenance] = None,
    ) -> list[DecisionSnapshot]:
        results = list(self._decisions.values())
        if security_id is not None:
            results = [d for d in results if d.security_id == security_id]
        if provenance is not None:
            results = [d for d in results if d.provenance == provenance]
        return sorted(results, key=lambda d: d.decision_time)

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
        exit_reason: Optional[str] = None,
        provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
        recorded_at: Optional[datetime] = None,
    ) -> TradeRecord:
        # Phase 17 Production Safety Review bug fix: `fill.order_id` is
        # the client_order_id, identical across every partial fill of
        # one order (`backtest.fills.Fill.order_id = order.order_id`,
        # never a per-fill id). Keying only on it meant the *second and
        # later* partial fill of any order was silently dropped as a
        # "duplicate" of the first -- a real order that filled in three
        # pieces produced exactly one TradeRecord, permanently losing
        # two real fills from the Trade Journal (and therefore from
        # Experience/Learning). `fill.execution_time` distinguishes
        # genuinely different fills of the same order (each partial
        # fill happens at its own simulated time) while a true retry of
        # the *same* fill event (same execution_time) still dedupes
        # exactly as before -- see
        # tests/trade_journal/test_idempotency.py::
        # test_recording_the_same_fill_twice_does_not_duplicate, which
        # still passes unchanged.
        key = ("trade", experiment_id, fill.order_id, fill.execution_time)
        if key in self._trade_natural_keys:
            return self._trades[self._trade_natural_keys[key]]

        trade_id = f"TRD-{self._next_trade_id:06d}"
        self._next_trade_id += 1
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
            exit_reason=exit_reason,
            provenance=provenance,
            experiment_id=experiment_id,
            recorded_at=recorded_at or fill.execution_time,
        )
        self._trades[trade_id] = trade
        self._trade_natural_keys[key] = trade_id
        return trade

    def get_trade(self, trade_id: str) -> Optional[TradeRecord]:
        return self._trades.get(trade_id)

    def list_trades(
        self, *, security_id: Optional[str] = None, provenance: Optional[TradeProvenance] = None,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[TradeRecord]:
        results = list(self._trades.values())
        if security_id is not None:
            results = [t for t in results if t.security_id == security_id]
        if provenance is not None:
            results = [t for t in results if t.provenance == provenance]
        if start is not None:
            results = [t for t in results if t.timestamp >= start]
        if end is not None:
            results = [t for t in results if t.timestamp <= end]
        return sorted(results, key=lambda t: t.timestamp)

    # -- post trade analysis / counterfactual ---------------------------

    def record_post_trade_analysis(self, trade_id: str, **fields) -> PostTradeAnalysis:
        # PostTradeAnalysis has no id of its own (models.py section 5.5) —
        # it is keyed by trade_id, with history preserved as re-computation
        # becomes possible in later phases (see get_post_trade_analysis_history).
        analysis = PostTradeAnalysis(trade_id=trade_id, **fields)
        self._post_trade_analyses.setdefault(trade_id, []).append(analysis)
        return analysis

    def get_post_trade_analysis(self, trade_id: str) -> Optional[PostTradeAnalysis]:
        history = self._post_trade_analyses.get(trade_id)
        return history[-1] if history else None

    def get_post_trade_analysis_history(self, trade_id: str) -> tuple[PostTradeAnalysis, ...]:
        return tuple(self._post_trade_analyses.get(trade_id, ()))

    def record_counterfactual(
        self, trade_id: str, selected_action: DecisionAction, alternatives: tuple[AlternativeOutcome, ...],
        computed_at: Optional[datetime] = None,
    ) -> CounterfactualRecord:
        record = CounterfactualRecord(
            trade_id=trade_id, selected_action=selected_action, alternatives=alternatives,
            computed_at=computed_at,
        )
        self._counterfactuals.setdefault(trade_id, []).append(record)
        return record

    def get_counterfactual(self, trade_id: str) -> Optional[CounterfactualRecord]:
        history = self._counterfactuals.get(trade_id)
        return history[-1] if history else None

    # -- corrections -----------------------------------------------------

    def record_correction(
        self, target_type: CorrectionTargetType, target_id: str, reason: str,
        corrected_fields: dict, created_at: datetime, created_by: str = "system",
    ) -> CorrectionRecord:
        correction_id = f"COR-{self._next_correction_id:06d}"
        self._next_correction_id += 1
        correction = CorrectionRecord(
            correction_id=correction_id, target_type=target_type, target_id=target_id,
            reason=reason, corrected_fields=corrected_fields, created_at=created_at, created_by=created_by,
        )
        self._corrections.setdefault(target_id, []).append(correction)
        return correction

    def get_corrections(self, target_id: str) -> tuple[CorrectionRecord, ...]:
        return tuple(self._corrections.get(target_id, ()))

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
