"""PositionSizer Protocol + DeterministicPositionSizer.

See docs/specifications/PHASE-8-position-sizing-and-risk.md sections 5,
6, 9, 13.

`PositionSizer.size()` takes already-computed `DecisionOutput`/
`PredictionOutput`/`CompositeRegimeObservation`/`PortfolioView` as plain
data, plus an already-fetched `current_price` -- it does not call
`AsOfDataView` or any repository itself, exactly like `DecisionAgent.
decide()` (ADR-0013 section 3). Point-in-time correctness is therefore
entirely inherited from whoever produced those inputs and fetched that
price; this module adds no new leakage-guard code.

Every rule is evaluated in a fixed, fail-closed order: the first
condition not satisfied produces a `RiskCheckStatus.UNKNOWN` or
`RiskCheckStatus.REJECT` result with a factual `reason` naming exactly
which condition failed. `DecisionAction.HOLD`/`NO_TRADE` are handled as
"no new sizing needed" pass-throughs, never as errors. Every one of the
five `DecisionAction` members is handled explicitly -- no branch falls
through to an unhandled case
(`tests/risk/test_sizing.py::TestDeterministicOutput::
test_never_falls_through_to_an_undeclared_status`).
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Optional, Protocol

from backtest.portfolio import PortfolioView

from decision.models import DecisionOutput

from predict.models import PredictionOutput

from regime.enums import LiquidityState, RegimeAxis
from regime.models import CompositeRegimeObservation

from risk.config import PositionSizingConfig
from risk.enums import RiskCheckStatus
from risk.models import PositionSizingResult

from trade_journal.enums import DecisionAction, TradeProvenance

FEATURE_VERSION = "phase8_position_sizing_features_v1"


def _finite(x: Optional[float]) -> bool:
    return x is not None and math.isfinite(x)


class PositionSizer(Protocol):
    def size(
        self,
        security_id: str,
        as_of_time: datetime,
        decision: Optional[DecisionOutput],
        prediction: Optional[PredictionOutput],
        regime: Optional[CompositeRegimeObservation],
        portfolio_state: Optional[PortfolioView],
        *,
        current_price: Optional[float] = None,
        risk_budget: float = 1.0,
        provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
        experiment_id: Optional[str] = None,
    ) -> PositionSizingResult: ...


class _IdAllocator:
    def __init__(self) -> None:
        self._next_id = 1

    def allocate(self) -> str:
        sid = f"SIZE-{self._next_id:06d}"
        self._next_id += 1
        return sid


class DeterministicPositionSizer:
    """A deterministic, hand-verifiable rule set -- no AI/ML. Kept
    interchangeable with a future model-based sizer via the same
    `PositionSizer` Protocol: only the class implementing `size()` would
    change, never the callers or the `PositionSizingResult` shape."""

    version = "deterministic_position_sizer_v1"

    def __init__(self, config: PositionSizingConfig = PositionSizingConfig()) -> None:
        self._config = config
        self._ids = _IdAllocator()

    def size(
        self,
        security_id: str,
        as_of_time: datetime,
        decision: Optional[DecisionOutput],
        prediction: Optional[PredictionOutput],
        regime: Optional[CompositeRegimeObservation],
        portfolio_state: Optional[PortfolioView],
        *,
        current_price: Optional[float] = None,
        risk_budget: float = 1.0,
        provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
        experiment_id: Optional[str] = None,
    ) -> PositionSizingResult:
        config = self._config

        current_quantity = 0.0
        current_weight: Optional[float] = None
        if portfolio_state is not None and _finite(portfolio_state.portfolio_value) and portfolio_state.portfolio_value > 0:
            current_quantity = portfolio_state.quantity_of(security_id)
            pos = portfolio_state.positions.get(security_id)
            current_weight = (pos.quantity * pos.average_cost) / portfolio_state.portfolio_value if pos is not None else 0.0
        elif portfolio_state is not None:
            current_quantity = portfolio_state.quantity_of(security_id)

        def build(status: RiskCheckStatus, reason: str, *, target_weight: Optional[float] = None, target_quantity: Optional[float] = None) -> PositionSizingResult:
            return PositionSizingResult(
                sizing_id=self._ids.allocate(),
                security_id=security_id,
                as_of_time=as_of_time,
                status=status,
                reason=reason,
                decision_id=decision.decision_id if decision is not None else None,
                decision_action=decision.action if decision is not None else None,
                proposed_target_weight=target_weight,
                proposed_target_quantity=target_quantity,
                current_weight=current_weight,
                current_quantity=current_quantity,
                sizing_version=self.version,
                feature_version=FEATURE_VERSION,
                prediction_id=decision.prediction_id if decision is not None else None,
                decision_version=decision.decision_version if decision is not None else None,
                prediction_version=decision.prediction_version if decision is not None else None,
                regime_version=decision.regime_version if decision is not None else None,
                data_version=decision.data_version if decision is not None else (),
                provenance=provenance,
                experiment_id=experiment_id,
                recorded_at=as_of_time,
            )

        # -- fail-closed gates, in order; the first violated gate wins --

        if decision is None:
            return build(RiskCheckStatus.UNKNOWN, "decision_unavailable")

        if decision.action in (DecisionAction.HOLD, DecisionAction.NO_TRADE):
            return build(
                RiskCheckStatus.PASS, f"no_new_sizing_for_{decision.action.value.lower()}",
                target_weight=current_weight, target_quantity=current_quantity,
            )

        if portfolio_state is None:
            return build(RiskCheckStatus.UNKNOWN, "portfolio_state_unavailable")

        if not _finite(portfolio_state.portfolio_value) or portfolio_state.portfolio_value <= 0 or not _finite(portfolio_state.cash):
            return build(RiskCheckStatus.UNKNOWN, "invalid_portfolio_value")

        if decision.action in (DecisionAction.SELL, DecisionAction.EXIT):
            return build(RiskCheckStatus.PASS, "full_exit", target_weight=0.0, target_quantity=0.0)

        # -- decision.action == DecisionAction.BUY from here on --

        if current_quantity != 0:
            return build(RiskCheckStatus.UNKNOWN, "unexpected_existing_position_for_buy")

        confidence = decision.confidence
        if not _finite(confidence) or not 0.0 <= confidence <= 1.0:
            return build(RiskCheckStatus.UNKNOWN, "invalid_confidence")

        if not _finite(risk_budget) or not 0.0 < risk_budget <= 1.0:
            return build(RiskCheckStatus.UNKNOWN, "invalid_risk_budget")

        expected_volatility = prediction.expected_volatility if prediction is not None else None
        if expected_volatility is None:
            return build(RiskCheckStatus.REJECT, "volatility_unavailable", target_weight=0.0, target_quantity=0.0)
        if not _finite(expected_volatility) or expected_volatility < 0:
            return build(RiskCheckStatus.REJECT, "invalid_volatility", target_weight=0.0, target_quantity=0.0)
        if expected_volatility >= config.max_volatility_for_full_size:
            return build(RiskCheckStatus.REJECT, "volatility_exceeds_limit", target_weight=0.0, target_quantity=0.0)

        vol_scale = 1.0
        if expected_volatility > config.reference_volatility:
            vol_scale = max(config.min_volatility_scale, config.reference_volatility / expected_volatility)

        liquidity_scale = 1.0
        if regime is not None:
            liquidity_obs = regime.get(RegimeAxis.LIQUIDITY)
            if liquidity_obs is not None:
                if liquidity_obs.state == LiquidityState.UNKNOWN.value:
                    return build(RiskCheckStatus.REJECT, "liquidity_unknown", target_weight=0.0, target_quantity=0.0)
                if liquidity_obs.state == LiquidityState.LOW.value:
                    liquidity_scale = config.low_liquidity_scale

        if not _finite(current_price) or current_price <= 0:
            return build(RiskCheckStatus.REJECT, "missing_price_data", target_weight=0.0, target_quantity=0.0)

        base_weight = config.max_position_weight * confidence * vol_scale * liquidity_scale

        cash_available = max(0.0, portfolio_state.cash * (1.0 - config.cost_safety_margin))
        max_weight_by_cash = cash_available / portfolio_state.portfolio_value
        budget_weight = risk_budget * config.max_position_weight

        bound = min(base_weight, max_weight_by_cash, budget_weight)
        raw_quantity = bound * portfolio_state.portfolio_value / current_price
        quantity = math.floor(raw_quantity / config.lot_size) * config.lot_size

        if quantity <= 0:
            return build(RiskCheckStatus.REJECT, "sized_to_zero", target_weight=0.0, target_quantity=0.0)

        achieved_weight = quantity * current_price / portfolio_state.portfolio_value

        if bound < base_weight - 1e-12:
            if max_weight_by_cash <= budget_weight:
                reason = "cash_shortage"
            else:
                reason = "risk_budget_exceeded"
            return build(RiskCheckStatus.REDUCE, reason, target_weight=achieved_weight, target_quantity=quantity)

        return build(RiskCheckStatus.PASS, "normal_sizing", target_weight=achieved_weight, target_quantity=quantity)
