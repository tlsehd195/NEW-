"""Decision data model.

See docs/specifications/PHASE-7-decision-agent.md sections 5, 9.

`DecisionOutput.action` reuses `trade_journal.enums.DecisionAction`
directly rather than redefining it -- that enum was reserved by Phase 3
specifically for this phase ("HOLD/EXIT/NO_TRADE are reserved for Phase
7's Decision Agent", trade_journal/enums.py), the same "reuse an
existing type instead of a parallel schema" discipline ADR-0009/ADR-0011
already established.

**Structural boundary enforcement**: this type has no `quantity`,
`order_id`, `broker_order`, `execution_price`, or any other order/
execution-shaped field -- `target_weight_hint` is explicitly named
"hint," not `target_weight`, to make clear it is not Position Sizing's
authoritative output (Phase 8). `tests/decision/test_boundary.py`
verifies this by reflection, mirroring Phase 5/6's identical structural
checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from trade_journal.enums import DecisionAction, TradeProvenance


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


@dataclass(frozen=True)
class DecisionOutput:
    decision_id: str  # "DEC-OUT-000001"
    security_id: str
    as_of_time: datetime
    action: DecisionAction
    decision_reason: str  # factual rule name, e.g. "confidence_below_threshold" -- never a fabricated narrative (mirrors Phase 3 spec section 5.2)

    confidence: Optional[float]  # copied from the PredictionOutput that informed this decision
    time_horizon_days: Optional[int]  # copied from the PredictionOutput's horizon_days
    target_weight_hint: Optional[float]  # a hint only -- never authoritative (see module docstring)

    regime: Optional[dict]  # composite regime axis states used as an input, if any (mirrors predict.models.PredictionOutput.regime_context)

    prediction_id: Optional[str]
    prediction_version: Optional[str]  # the PredictionOutput.method_version used
    regime_version: Optional[str]  # the RegimeObservation.configuration_version used
    feature_version: Optional[str]
    data_version: tuple[str, ...]
    model_version: Optional[str]  # reserved -- None for every Phase 7 agent (no trained model)
    decision_version: str  # this agent's own version string, e.g. "baseline_rule_decision_agent_v1"
    strategy_version: Optional[str] = None  # reserved -- Phase 7 has no Strategy consumer yet
    risk_version: Optional[str] = None  # reserved -- Risk Engine is Phase 8

    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION
    experiment_id: Optional[str] = None
    recorded_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.decision_id:
            raise ValueError("DecisionOutput.decision_id must not be empty")
        if not self.security_id:
            raise ValueError("DecisionOutput.security_id must not be empty")
        if not self.decision_reason:
            raise ValueError("DecisionOutput.decision_reason must not be empty")
        _require_aware("DecisionOutput.as_of_time", self.as_of_time)
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"DecisionOutput.confidence must be in [0, 1]: {self.confidence!r}")
