"""Position Sizing + Portfolio Risk data models.

See docs/specifications/PHASE-8-position-sizing-and-risk.md sections 5,
6, 7, 8, 16.

**Structural boundary enforcement**: `PositionSizingResult` and
`RiskCheckedPosition` compute `target_weight`/`target_quantity` -- that
*is* this layer's authoritative responsibility per
PROJECT_MASTER_PLAN.md section 8.3/8.4, unlike `decision.models.
DecisionOutput` which must never carry a quantity. What neither type
has, structurally, is any `order_id`, `broker_order`, `execution_price`,
or other order/execution-shaped field -- Order Creation/Validation/
Broker remain a later phase's responsibility.
`tests/risk/test_risk_boundary.py` verifies this by reflection, the same
discipline Phase 5/6/7 already used for their own boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from risk.enums import RiskCheckStatus

from trade_journal.enums import DecisionAction, TradeProvenance


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


@dataclass(frozen=True)
class PositionSizingResult:
    sizing_id: str  # "SIZE-000001"
    security_id: str
    as_of_time: datetime
    status: RiskCheckStatus
    reason: str  # factual rule name, e.g. "cash_shortage" -- never a fabricated narrative

    decision_id: Optional[str]
    decision_action: Optional[DecisionAction]  # None only when status is UNKNOWN and no decision was available at all

    proposed_target_weight: Optional[float]  # None only when status is UNKNOWN
    proposed_target_quantity: Optional[float]
    current_weight: Optional[float]
    current_quantity: float

    sizing_version: str  # this module's own version string, e.g. "deterministic_position_sizer_v1"
    feature_version: str
    prediction_id: Optional[str] = None
    decision_version: Optional[str] = None  # copied from the DecisionOutput used
    prediction_version: Optional[str] = None  # copied from the DecisionOutput used
    regime_version: Optional[str] = None  # copied from the DecisionOutput used
    data_version: tuple[str, ...] = ()

    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION
    experiment_id: Optional[str] = None
    recorded_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.sizing_id:
            raise ValueError("PositionSizingResult.sizing_id must not be empty")
        if not self.security_id:
            raise ValueError("PositionSizingResult.security_id must not be empty")
        if not self.reason:
            raise ValueError("PositionSizingResult.reason must not be empty")
        _require_aware("PositionSizingResult.as_of_time", self.as_of_time)


@dataclass(frozen=True)
class PortfolioRiskState:
    """Portfolio-level risk metrics computed at one point in time. Any
    field that cannot be honestly computed from the data supplied to
    `PortfolioRiskEngine.assess()` is `None` -- never estimated
    (instruction section 7: "알 수 없는 위험을 안전하다고 간주하지
    않는다"). `sector_exposure` is `None` unless the caller supplies a
    `sector_by_security` mapping to `assess()` (ADR-0062):
    `data_infra.models.SecurityMaster` itself still has no sector
    field, so this engine cannot look sectors up on its own -- the
    caller (e.g. sourcing `data_infra.universe`'s own real,
    provider-confirmed sector data, ADR-0058) must supply the mapping
    per call, opt-in, same pattern `turnover`/`liquidity_state` already
    established."""

    as_of_time: datetime
    portfolio_value: float
    cash: float
    gross_exposure: Optional[float]
    net_exposure: Optional[float]  # equals gross_exposure in this codebase today -- no short positions are representable (OrderSide has no SHORT)
    position_weights: dict[str, float] = field(default_factory=dict)
    sector_exposure: Optional[dict[str, float]] = None
    drawdown: Optional[float] = None
    max_drawdown: Optional[float] = None
    portfolio_volatility: Optional[float] = None
    turnover: Optional[float] = None
    concentration: Optional[float] = None  # largest single position's weight -- a simple proxy, not claimed to be HHI or any formal concentration index
    risk_budget_usage: Optional[float] = None
    risk_state_version: str = "portfolio_risk_state_v1"


@dataclass(frozen=True)
class RiskCheckedPosition:
    """The pipeline's final output (instruction section 13's own
    diagram names it exactly this): what `PositionSizer` proposed, after
    `PortfolioRiskEngine` independently re-checked it against
    portfolio-level hard limits. `PortfolioRiskEngine` is the final
    authority -- `status`/`final_target_weight`/`final_target_quantity`
    here are authoritative for this pipeline; a later Order
    Creation/Validation phase still applies its own checks before any
    order is built, but nothing upstream of this type can bypass what
    Risk Engine decided here."""

    risk_id: str  # "RISK-000001"
    security_id: str
    as_of_time: datetime
    status: RiskCheckStatus
    reason: str
    breached_limits: tuple[str, ...]

    final_target_weight: Optional[float]
    final_target_quantity: Optional[float]

    sizing_id: Optional[str]
    decision_id: Optional[str]
    prediction_id: Optional[str]
    risk_state: Optional[PortfolioRiskState]

    risk_version: str  # this module's own version string, e.g. "deterministic_portfolio_risk_engine_v1"
    feature_version: str
    sizing_version: Optional[str] = None  # copied from the PositionSizingResult used
    decision_version: Optional[str] = None  # copied from the PositionSizingResult used
    prediction_version: Optional[str] = None  # copied from the PositionSizingResult used
    regime_version: Optional[str] = None  # copied from the PositionSizingResult used
    data_version: tuple[str, ...] = ()
    strategy_version: Optional[str] = None  # reserved -- no Strategy consumer yet, same honesty Phase 7 already applied

    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION
    experiment_id: Optional[str] = None
    recorded_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.risk_id:
            raise ValueError("RiskCheckedPosition.risk_id must not be empty")
        if not self.security_id:
            raise ValueError("RiskCheckedPosition.security_id must not be empty")
        if not self.reason:
            raise ValueError("RiskCheckedPosition.reason must not be empty")
        _require_aware("RiskCheckedPosition.as_of_time", self.as_of_time)
