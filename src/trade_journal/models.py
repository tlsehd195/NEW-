"""Trade Journal data model.

See docs/specifications/PHASE-3-trade-journal.md sections 5, 6, 9, 10,
and ADR-0009.

Every record type here is a frozen dataclass: immutability is enforced
by the language (dataclasses.FrozenInstanceError on assignment), not by
convention (ADR-0009 point 2). Optional fields that require a module not
yet built (Prediction, Regime, Risk, sector/factor data) are always None
here — nothing in this module estimates a value it cannot actually
compute (ADR-0009 point 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from backtest.enums import OrderSide
from backtest.fills import Fill
from backtest.orders import Order
from backtest.portfolio import PortfolioView

from trade_journal.enums import CorrectionTargetType, DecisionAction, TradeProvenance


@dataclass(frozen=True)
class DecisionSnapshot:
    snapshot_id: str
    decision_time: datetime
    security_id: str
    decision: DecisionAction
    order: Optional[Order] = None
    portfolio_state: Optional[PortfolioView] = None
    market_state: dict = field(default_factory=dict)
    features: Optional[dict] = None
    prediction: Optional[dict] = None
    confidence: Optional[float] = None
    decision_reason: Optional[str] = None
    expected_return: Optional[float] = None
    expected_risk: Optional[float] = None
    risk_state: Optional[dict] = None
    target_weight: Optional[float] = None
    model_version: Optional[str] = None
    strategy_version: str = "unknown"
    feature_version: Optional[str] = None
    data_version: Optional[tuple[str, ...]] = None
    risk_version: Optional[str] = None
    execution_version: str = "unknown"
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION
    experiment_id: Optional[str] = None
    recorded_at: Optional[datetime] = None  # set by the repository at record time

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            raise ValueError("DecisionSnapshot.snapshot_id must not be empty")
        if self.decision_time.tzinfo is None:
            raise ValueError("DecisionSnapshot.decision_time must be timezone-aware")


@dataclass(frozen=True)
class TradeRecord:
    trade_id: str
    decision_id: str
    order_id: str
    security_id: str
    timestamp: datetime
    side: OrderSide
    quantity: float
    execution_price: float
    reference_price: float
    slippage: float
    transaction_cost: float
    position_after: float
    fill: Fill
    realized_pnl: Optional[float] = None
    realized_return: Optional[float] = None
    holding_period: Optional[timedelta] = None
    # -- Session 36 continued: found comparing this project against an
    # external repository (dragon1086/prism-insight), needed before a
    # reentry-cooldown risk rule can be built at all -- this project had
    # no way to distinguish a normal strategy-driven SELL from a
    # risk-engine-forced exit (e.g. "risk_limit_breach", "stop_loss").
    # Free-text/tag, not an Enum: whoever converts a Fill into a
    # TradeRecord decides the vocabulary; `None` (never a fabricated
    # reason) when the producer does not distinguish exit kinds yet --
    # additive, same "Optional[...] = None" schema convention every
    # earlier Trade Journal field addition has used (ADR-0009 point 4).
    exit_reason: Optional[str] = None
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION
    experiment_id: Optional[str] = None
    recorded_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.trade_id or not self.decision_id or not self.order_id:
            raise ValueError("TradeRecord requires non-empty trade_id, decision_id, order_id")
        if self.timestamp.tzinfo is None:
            raise ValueError("TradeRecord.timestamp must be timezone-aware")


@dataclass(frozen=True)
class PostTradeAnalysis:
    trade_id: str
    prediction_error: Optional[float] = None
    timing_error: Optional[float] = None
    risk_estimation_error: Optional[float] = None
    execution_error: Optional[float] = None
    regime_error: Optional[float] = None
    signal_error: Optional[float] = None
    notes: Optional[str] = None
    computed_at: Optional[datetime] = None


@dataclass(frozen=True)
class AlternativeOutcome:
    action: str
    hypothetical_return: Optional[float] = None
    basis: Optional[str] = None
    horizon: Optional[timedelta] = None


@dataclass(frozen=True)
class CounterfactualRecord:
    trade_id: str
    selected_action: DecisionAction
    alternatives: tuple[AlternativeOutcome, ...] = ()
    computed_at: Optional[datetime] = None


@dataclass(frozen=True)
class AttributionResult:
    experiment_id: str
    market: Optional[float] = None
    sector: Optional[float] = None
    factor: Optional[float] = None
    selection: Optional[float] = None
    timing: Optional[float] = None
    execution: Optional[float] = None
    computed_at: Optional[datetime] = None


@dataclass(frozen=True)
class ExperienceRecord:
    experience_id: str
    trade_id: str
    decision_id: str
    state: dict
    action: DecisionAction
    actual_outcome: dict
    expected_outcome: Optional[dict] = None
    reward: Optional[float] = None
    market_regime: Optional[str] = None
    risk_state: Optional[dict] = None
    prediction_error: Optional[float] = None
    counterfactual_results: Optional[tuple] = None
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION
    data_version: Optional[tuple[str, ...]] = None
    strategy_version: str = "unknown"
    model_version: Optional[str] = None
    created_at: Optional[datetime] = None


@dataclass(frozen=True)
class CorrectionRecord:
    correction_id: str
    target_type: CorrectionTargetType
    target_id: str
    reason: str
    corrected_fields: dict
    created_at: datetime
    created_by: str = "system"

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("CorrectionRecord.reason must not be empty (ADR-0009 / Phase 3 spec section 9)")
        if not self.target_id:
            raise ValueError("CorrectionRecord.target_id must not be empty")


@dataclass(frozen=True)
class AuditTrail:
    """A read-only, on-demand composition — not itself a stored record.
    See Phase 3 spec section 14."""

    decision: Optional[DecisionSnapshot]
    trade: Optional[TradeRecord]
    post_trade_analysis: Optional[PostTradeAnalysis]
    counterfactual: Optional[CounterfactualRecord]
    corrections: tuple[CorrectionRecord, ...] = ()
