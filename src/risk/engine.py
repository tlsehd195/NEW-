"""PortfolioRiskEngine Protocol + DeterministicPortfolioRiskEngine.

See docs/specifications/PHASE-8-position-sizing-and-risk.md sections 7,
8, 9, 10, 13.

`PortfolioRiskEngine.assess()` takes an already-computed
`PositionSizingResult` plus already-computed portfolio-level inputs
(`PortfolioView`, an optional portfolio-value `value_history`, an
optional `turnover`, an optional `liquidity_state`) -- it fetches no
data itself, exactly like `PositionSizer.size()` and `DecisionAgent.
decide()` before it. Point-in-time correctness is inherited entirely
from whoever produced those inputs.

`PortfolioRiskEngine` is the pipeline's final authority (instruction
section 31: "AI의 판단보다 Risk Engine이 우선한다"): every hard limit
check here can REDUCE or REJECT whatever `PositionSizer` proposed,
independently of what `PositionSizer` already applied -- a deliberate
defense-in-depth duplication for `single_position_limit`, not a trust
of the upstream result. A required check whose input data is missing
(drawdown/portfolio_volatility/turnover history, an unspecified
liquidity state when the axis itself reports UNKNOWN) always REJECTs --
"Risk check unavailable -> REJECT/NO_TRADE" (instruction section 8) --
never silently PASSes. See docs/decisions/ADR-0014 section 6 for the
distinction this module draws between "not configured" (a limit left
`None` in `RiskConfig`, simply not evaluated) and "configured but its
input data is unavailable right now" (always REJECT).
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Optional, Protocol, Sequence

from backtest.metrics import annualized_volatility, compute_max_drawdown, compute_returns
from backtest.portfolio import PortfolioView

from regime.enums import LiquidityState

from risk.config import RiskConfig
from risk.enums import RiskCheckStatus
from risk.models import PortfolioRiskState, PositionSizingResult, RiskCheckedPosition

from trade_journal.enums import DecisionAction, TradeProvenance

FEATURE_VERSION = "phase8_risk_features_v1"
RISK_STATE_VERSION = "portfolio_risk_state_v1"


def _finite(x: Optional[float]) -> bool:
    return x is not None and math.isfinite(x)


class PortfolioRiskEngine(Protocol):
    def assess(
        self,
        security_id: str,
        as_of_time: datetime,
        sizing_result: Optional[PositionSizingResult],
        portfolio_state: Optional[PortfolioView],
        *,
        current_price: Optional[float] = None,
        value_history: Optional[Sequence[float]] = None,
        turnover: Optional[float] = None,
        liquidity_state: Optional[str] = None,
        sector_by_security: Optional[dict[str, str]] = None,
        last_exit_time_by_security: Optional[dict[str, datetime]] = None,
        provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
        experiment_id: Optional[str] = None,
    ) -> RiskCheckedPosition: ...


class _IdAllocator:
    def __init__(self, start: int = 1) -> None:
        self._next_id = start

    def allocate(self) -> str:
        rid = f"RISK-{self._next_id:06d}"
        self._next_id += 1
        return rid


class DeterministicPortfolioRiskEngine:
    """A deterministic, hand-verifiable rule set -- no AI/ML. Kept
    interchangeable with a future model-based engine via the same
    `PortfolioRiskEngine` Protocol."""

    version = "deterministic_portfolio_risk_engine_v1"

    def __init__(self, config: RiskConfig = RiskConfig(), *, starting_id: int = 1) -> None:
        self._config = config
        self._ids = _IdAllocator(starting_id)

    def _compute_risk_state(
        self,
        as_of_time: datetime,
        portfolio_state: PortfolioView,
        *,
        value_history: Optional[Sequence[float]],
        turnover: Optional[float],
        sector_by_security: Optional[dict[str, str]] = None,
    ) -> PortfolioRiskState:
        config = self._config
        position_weights = {
            sid: (pos.quantity * pos.average_cost) / portfolio_state.portfolio_value
            for sid, pos in portfolio_state.positions.items()
            if pos.quantity != 0
        }
        gross_exposure = sum(position_weights.values()) if position_weights else 0.0
        concentration = max(position_weights.values()) if position_weights else 0.0

        # sector_exposure: only computed when the caller supplies a
        # sector_by_security mapping (e.g. sourced from data_infra.
        # universe's own real, provider-confirmed sector data -- ADR-0058)
        # -- SecurityMaster itself still has no sector field, so this
        # engine cannot look it up on its own (module docstring). A
        # security with a weight but no entry in sector_by_security is
        # simply excluded from every sector's total, never guessed.
        sector_exposure: Optional[dict[str, float]] = None
        if sector_by_security is not None:
            sector_exposure = {}
            for sid, w in position_weights.items():
                sector = sector_by_security.get(sid)
                if sector is None:
                    continue
                sector_exposure[sector] = sector_exposure.get(sector, 0.0) + w

        drawdown: Optional[float] = None
        max_drawdown: Optional[float] = None
        portfolio_volatility: Optional[float] = None
        if value_history is not None and len(value_history) >= config.min_history_for_volatility:
            clean_history = [v for v in value_history if _finite(v)]
            if len(clean_history) == len(value_history):
                peak = max(clean_history)
                last = clean_history[-1]
                drawdown = (last - peak) / peak if peak > 0 else 0.0
                max_drawdown = compute_max_drawdown(clean_history)
                returns = compute_returns(clean_history)
                if len(returns) >= 2:
                    portfolio_volatility = annualized_volatility(returns)

        risk_budget_usage = gross_exposure / config.max_gross_exposure if config.max_gross_exposure > 0 else None

        return PortfolioRiskState(
            as_of_time=as_of_time,
            portfolio_value=portfolio_state.portfolio_value,
            cash=portfolio_state.cash,
            gross_exposure=gross_exposure,
            net_exposure=gross_exposure,  # no short positions are representable in this codebase today
            position_weights=position_weights,
            sector_exposure=sector_exposure,
            drawdown=drawdown,
            max_drawdown=max_drawdown,
            portfolio_volatility=portfolio_volatility,
            turnover=turnover,
            concentration=concentration,
            risk_budget_usage=risk_budget_usage,
            risk_state_version=RISK_STATE_VERSION,
        )

    def assess(
        self,
        security_id: str,
        as_of_time: datetime,
        sizing_result: Optional[PositionSizingResult],
        portfolio_state: Optional[PortfolioView],
        *,
        current_price: Optional[float] = None,
        value_history: Optional[Sequence[float]] = None,
        turnover: Optional[float] = None,
        liquidity_state: Optional[str] = None,
        sector_by_security: Optional[dict[str, str]] = None,
        last_exit_time_by_security: Optional[dict[str, datetime]] = None,
        provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
        experiment_id: Optional[str] = None,
    ) -> RiskCheckedPosition:
        config = self._config

        def build(
            status: RiskCheckStatus, reason: str, *, breached: tuple[str, ...] = (),
            final_target_weight: Optional[float] = None, final_target_quantity: Optional[float] = None,
            risk_state: Optional[PortfolioRiskState] = None,
        ) -> RiskCheckedPosition:
            return RiskCheckedPosition(
                risk_id=self._ids.allocate(),
                security_id=security_id,
                as_of_time=as_of_time,
                status=status,
                reason=reason,
                breached_limits=breached,
                final_target_weight=final_target_weight,
                final_target_quantity=final_target_quantity,
                sizing_id=sizing_result.sizing_id if sizing_result is not None else None,
                decision_id=sizing_result.decision_id if sizing_result is not None else None,
                prediction_id=sizing_result.prediction_id if sizing_result is not None else None,
                risk_state=risk_state,
                risk_version=self.version,
                feature_version=FEATURE_VERSION,
                sizing_version=sizing_result.sizing_version if sizing_result is not None else None,
                decision_version=sizing_result.decision_version if sizing_result is not None else None,
                prediction_version=sizing_result.prediction_version if sizing_result is not None else None,
                regime_version=sizing_result.regime_version if sizing_result is not None else None,
                data_version=sizing_result.data_version if sizing_result is not None else (),
                provenance=provenance,
                experiment_id=experiment_id,
                recorded_at=as_of_time,
            )

        # -- fail-closed gates, in order --

        if portfolio_state is None:
            return build(RiskCheckStatus.UNKNOWN, "portfolio_state_unavailable")

        if not _finite(portfolio_state.portfolio_value) or portfolio_state.portfolio_value <= 0 or not _finite(portfolio_state.cash):
            return build(RiskCheckStatus.UNKNOWN, "invalid_portfolio_value")

        risk_state = self._compute_risk_state(
            as_of_time, portfolio_state, value_history=value_history, turnover=turnover,
            sector_by_security=sector_by_security,
        )

        if sizing_result is None:
            return build(RiskCheckStatus.UNKNOWN, "sizing_result_unavailable", risk_state=risk_state)

        if sizing_result.status == RiskCheckStatus.UNKNOWN:
            return build(RiskCheckStatus.UNKNOWN, sizing_result.reason, risk_state=risk_state)

        if sizing_result.status == RiskCheckStatus.REJECT:
            return build(
                RiskCheckStatus.REJECT, sizing_result.reason,
                final_target_weight=0.0, final_target_quantity=0.0, risk_state=risk_state,
            )

        if sizing_result.decision_action != DecisionAction.BUY:
            # HOLD/NO_TRADE (no change proposed) and SELL/EXIT (full exit,
            # always risk-reducing) are never blocked here -- Risk Limit
            # Enforcement gates new risk-taking, not maintaining or
            # reducing existing exposure.
            return build(
                RiskCheckStatus.PASS, "no_new_risk_limit_applicable",
                final_target_weight=sizing_result.proposed_target_weight,
                final_target_quantity=sizing_result.proposed_target_quantity,
                risk_state=risk_state,
            )

        # -- a new BUY is being proposed: apply hard portfolio-level limits --

        weight = sizing_result.proposed_target_weight
        quantity = sizing_result.proposed_target_quantity
        if not _finite(weight) or not _finite(quantity) or weight < 0 or quantity < 0:
            return build(RiskCheckStatus.UNKNOWN, "invalid_sizing_result", risk_state=risk_state)

        breached: list[str] = []

        def clamp_to(new_weight: float) -> None:
            nonlocal weight, quantity
            if weight and weight > 0:
                quantity = quantity * (new_weight / weight)
            weight = new_weight

        # cash_minimum
        trade_notional = weight * portfolio_state.portfolio_value
        post_trade_cash_ratio = (portfolio_state.cash - trade_notional) / portfolio_state.portfolio_value
        if post_trade_cash_ratio < config.minimum_cash_ratio:
            affordable_notional = max(0.0, portfolio_state.cash - config.minimum_cash_ratio * portfolio_state.portfolio_value)
            allowed_weight = affordable_notional / portfolio_state.portfolio_value
            if allowed_weight <= 0:
                return build(
                    RiskCheckStatus.REJECT, "cash_minimum_breach", breached=("cash_minimum",),
                    final_target_weight=0.0, final_target_quantity=0.0, risk_state=risk_state,
                )
            clamp_to(allowed_weight)
            breached.append("cash_minimum")

        # single_position_limit (independent of PositionSizer's own cap)
        if weight > config.max_position_weight:
            clamp_to(config.max_position_weight)
            breached.append("single_position_limit")

        # gross_exposure_limit
        existing_gross = risk_state.gross_exposure or 0.0
        if existing_gross + weight > config.max_gross_exposure:
            allowed_addition = max(0.0, config.max_gross_exposure - existing_gross)
            if allowed_addition <= 0:
                return build(
                    RiskCheckStatus.REJECT, "gross_exposure_limit_breached", breached=("gross_exposure",),
                    final_target_weight=0.0, final_target_quantity=0.0, risk_state=risk_state,
                )
            clamp_to(min(weight, allowed_addition))
            breached.append("gross_exposure")

        # concentration_limit
        if weight > config.concentration_limit:
            clamp_to(config.concentration_limit)
            breached.append("concentration")

        # max_order_notional -- an absolute dollar cap, independent of
        # every weight-based limit above. Recomputed from the current
        # (possibly already-clamped) weight, since this is the final
        # absolute-notional check on whatever the position-weight
        # clamps above already produced.
        if config.max_order_notional is not None:
            order_notional = weight * portfolio_state.portfolio_value
            if order_notional > config.max_order_notional:
                allowed_weight = config.max_order_notional / portfolio_state.portfolio_value
                clamp_to(min(weight, allowed_weight))
                breached.append("max_order_notional")

        # drawdown_limit -- configured means fail-closed on missing data
        if config.max_drawdown is not None:
            if risk_state.drawdown is None:
                return build(
                    RiskCheckStatus.REJECT, "drawdown_unknown", breached=tuple(breached) + ("drawdown_unknown",),
                    final_target_weight=0.0, final_target_quantity=0.0, risk_state=risk_state,
                )
            if abs(risk_state.drawdown) >= config.max_drawdown:
                return build(
                    RiskCheckStatus.REJECT, "drawdown_limit_breached", breached=tuple(breached) + ("drawdown_limit",),
                    final_target_weight=0.0, final_target_quantity=0.0, risk_state=risk_state,
                )

        # portfolio_volatility_limit -- configured means fail-closed on missing data
        if config.max_portfolio_volatility is not None:
            if risk_state.portfolio_volatility is None:
                return build(
                    RiskCheckStatus.REJECT, "portfolio_volatility_unknown",
                    breached=tuple(breached) + ("portfolio_volatility_unknown",),
                    final_target_weight=0.0, final_target_quantity=0.0, risk_state=risk_state,
                )
            if risk_state.portfolio_volatility > config.max_portfolio_volatility:
                return build(
                    RiskCheckStatus.REJECT, "portfolio_volatility_limit_breached",
                    breached=tuple(breached) + ("portfolio_volatility_limit",),
                    final_target_weight=0.0, final_target_quantity=0.0, risk_state=risk_state,
                )

        # turnover_limit -- configured means fail-closed on missing data
        if config.max_turnover is not None:
            if turnover is None:
                return build(
                    RiskCheckStatus.REJECT, "turnover_unknown", breached=tuple(breached) + ("turnover_unknown",),
                    final_target_weight=0.0, final_target_quantity=0.0, risk_state=risk_state,
                )
            if turnover > config.max_turnover:
                return build(
                    RiskCheckStatus.REJECT, "turnover_limit_breached", breached=tuple(breached) + ("turnover_limit",),
                    final_target_weight=0.0, final_target_quantity=0.0, risk_state=risk_state,
                )

        # sector_limit -- configured means fail-closed on missing data,
        # same pattern as turnover_limit above. Requires BOTH
        # config.max_sector_weight set AND the caller supplying
        # sector_by_security for this call; either without the other is
        # "cannot evaluate this configured check right now", not "not
        # configured" -- fail-closed, not silently skipped.
        if config.max_sector_weight is not None:
            sector = sector_by_security.get(security_id) if sector_by_security is not None else None
            if sector is None:
                return build(
                    RiskCheckStatus.REJECT, "sector_unknown", breached=tuple(breached) + ("sector_unknown",),
                    final_target_weight=0.0, final_target_quantity=0.0, risk_state=risk_state,
                )
            existing_sector_exposure = (risk_state.sector_exposure or {}).get(sector, 0.0)
            if existing_sector_exposure + weight > config.max_sector_weight:
                allowed_addition = max(0.0, config.max_sector_weight - existing_sector_exposure)
                if allowed_addition <= 0:
                    return build(
                        RiskCheckStatus.REJECT, "sector_limit_breached", breached=tuple(breached) + ("sector_limit",),
                        final_target_weight=0.0, final_target_quantity=0.0, risk_state=risk_state,
                    )
                clamp_to(min(weight, allowed_addition))
                breached.append("sector_limit")

        # liquidity_limit -- only evaluated when the caller supplies a
        # liquidity_state at all (see module docstring / RiskConfig)
        if config.enforce_liquidity_limit and liquidity_state is not None:
            if liquidity_state == LiquidityState.UNKNOWN.value:
                return build(
                    RiskCheckStatus.REJECT, "liquidity_unknown", breached=tuple(breached) + ("liquidity_unknown",),
                    final_target_weight=0.0, final_target_quantity=0.0, risk_state=risk_state,
                )
            if liquidity_state == LiquidityState.LOW.value:
                return build(
                    RiskCheckStatus.REJECT, "liquidity_limit_breached", breached=tuple(breached) + ("liquidity_limit",),
                    final_target_weight=0.0, final_target_quantity=0.0, risk_state=risk_state,
                )

        # reentry_cooldown -- only evaluated when the caller supplies
        # last_exit_time_by_security for this call, mirroring
        # liquidity_limit's own opt-in pattern (see RiskConfig.
        # reentry_cooldown_days's own docstring for why this is NOT the
        # sector_limit fail-closed-on-missing-entry pattern: "no recorded
        # recent exit for this security" is the ordinary case, not a data
        # gap). Blocks only a NEW BUY, exactly like every other limit in
        # this function -- a security with no entry in the mapping (never
        # exited, or exited longer ago than the cooldown) is unaffected.
        if config.reentry_cooldown_days is not None and last_exit_time_by_security is not None:
            last_exit_time = last_exit_time_by_security.get(security_id)
            if last_exit_time is not None:
                days_since_exit = (as_of_time - last_exit_time).total_seconds() / 86400.0
                if days_since_exit < config.reentry_cooldown_days:
                    return build(
                        RiskCheckStatus.REJECT, "reentry_cooldown_breached",
                        breached=tuple(breached) + ("reentry_cooldown",),
                        final_target_weight=0.0, final_target_quantity=0.0, risk_state=risk_state,
                    )

        if weight <= 0:
            return build(
                RiskCheckStatus.REJECT, breached[-1] if breached else "sized_to_zero_by_risk_checks",
                breached=tuple(breached), final_target_weight=0.0, final_target_quantity=0.0, risk_state=risk_state,
            )

        if breached:
            return build(
                RiskCheckStatus.REDUCE, breached[-1], breached=tuple(breached),
                final_target_weight=weight, final_target_quantity=quantity, risk_state=risk_state,
            )

        return build(
            RiskCheckStatus.PASS, "risk_checks_passed",
            final_target_weight=weight, final_target_quantity=quantity, risk_state=risk_state,
        )
