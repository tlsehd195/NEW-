"""run_cycle: ties Regime -> Prediction -> Decision -> Position Sizing
-> Portfolio Risk Engine -> Order Validation -> `PaperTradingSession.
submit` into one call per security per checkpoint -- the composition
this repository's own components (Phase 5/6/7/8/13/15) already support
but nothing previously called in sequence outside a test
(`tests/integration/test_risk_lineage.py` demonstrates the same chain,
manually, for its own persistence-lineage assertions -- this module is
that chain made reusable, plus the Order Validation ->
`PaperTradingSession.submit` steps that test never took).

This is deliberately still NOT "a real, running Trading Engine loop"
(no timer/scheduler here) -- `run_cycle` is called once per checkpoint
by whatever drives it (a script, a notebook, a future scheduled
process), the same way `backtest.engine.BacktestEngine.run()` already
loops over checkpoints internally for backtest. Wiring an always-on
scheduled process remains out of scope
(docs/specifications/PHASE-15-paper-trading.md section 1.1).

Every intermediate stage's output is returned in `CycleOutcome`, never
silently discarded -- persisting any of it (mirroring
`tests/integration/test_risk_lineage.py`'s own five-repository
pattern) is the caller's job, matching `broker.pipeline.
submit_validated_order`'s own "return objects, caller decides what to
keep" precedent.

**Known, honestly-disclosed limitation (found while writing this
module's own tests, not discovered later)**: `run_cycle` does not
source `value_history` (past portfolio values) for `risk_engine.
assess`. `RiskConfig.max_drawdown`/`max_portfolio_volatility` default
to real numbers (`0.20`/`0.30`, Phase 8), and per `PortfolioRiskEngine`'s
own fail-closed design (`src/risk/engine.py`), a configured check with
no data to evaluate REJECTs (`drawdown_unknown`/
`portfolio_volatility_unknown`) rather than silently passing -- so a
caller using `risk_engine`'s default `RiskConfig` here will see every
BUY rejected on those grounds specifically. A caller must either pass
`RiskConfig(max_drawdown=None, max_portfolio_volatility=None)` (opting
out of those two checks, same posture several existing test suites
already take) or extend this module with real historical portfolio-
value sourcing (not built here) before those checks can pass. Every
other risk check (`max_position_weight`/`max_gross_exposure`/
`concentration_limit`/`max_sector_weight`/`max_order_notional`/
`minimum_cash_ratio`) is unaffected -- they need only the current
`PortfolioView`, which this module already builds correctly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from backtest.asof import AsOfDataView
from backtest.portfolio import PortfolioView, PositionView

from broker.models import BrokerOrderResponse, OrderValidationResult
from broker.paper.session import PaperTradingSession
from broker.validation import build_validated_order

from decision.agent import DecisionAgent
from decision.models import DecisionOutput

from predict.models import PredictionOutput
from predict.predictor import Predictor

from regime.detector import RegimeDetector
from regime.models import CompositeRegimeObservation

from risk.engine import PortfolioRiskEngine
from risk.models import PositionSizingResult, RiskCheckedPosition
from risk.sizing import PositionSizer

from trade_journal.enums import TradeProvenance

# Mirrors backtest.engine.BacktestEngine's own 1-day reference-price
# lookback exactly (src/backtest/engine.py) for the checkpoint-only
# case, widened slightly for Paper's own real-world data gaps (a
# weekend/holiday plus one missed provider update) -- still only ever
# returns the latest *available* bar, never interpolates or guesses.
_PRICE_LOOKBACK_DAYS = 5


@dataclass(frozen=True)
class CycleOutcome:
    security_id: str
    prediction: PredictionOutput
    regime: CompositeRegimeObservation
    decision: DecisionOutput
    sizing: PositionSizingResult
    risk_checked: RiskCheckedPosition
    validation: OrderValidationResult
    submission: Optional[BrokerOrderResponse] = None


def _reference_price(view: AsOfDataView, security_id: str, as_of_time: datetime) -> Optional[float]:
    bars = view.get_bars(security_id, as_of_time - timedelta(days=_PRICE_LOOKBACK_DAYS), as_of_time)
    if not bars:
        return None
    return bars[-1].close


def _portfolio_view(account, view: AsOfDataView, as_of_time: datetime) -> PortfolioView:
    """Builds the `PortfolioView` every downstream stage needs from
    `PaperTradingSession.account_summary()`'s own `BrokerPosition`
    records -- a position `BrokerPosition` reports `available=False`
    for (fail-closed on missing data, never defaulted to zero) is
    simply excluded, matching `BrokerPosition`'s own honesty
    discipline (`broker.models`)."""
    positions: dict[str, PositionView] = {}
    market_value = 0.0
    for security_id, broker_position in account.positions.items():
        if not broker_position.available or broker_position.quantity is None:
            continue
        average_cost = broker_position.average_cost or 0.0
        positions[security_id] = PositionView(security_id, broker_position.quantity, average_cost)
        price = _reference_price(view, security_id, as_of_time)
        # A real current price marks the position to market; absent
        # one, the position's own cost basis is the best honest
        # fallback still available (never a fabricated market price).
        market_value += broker_position.quantity * (price if price is not None else average_cost)
    return PortfolioView(
        as_of_time=as_of_time, cash=account.cash, positions=positions,
        portfolio_value=account.cash + market_value,
    )


def run_cycle(
    security_ids: Sequence[str],
    as_of_time: datetime,
    view: AsOfDataView,
    session: PaperTradingSession,
    *,
    predictor: Predictor,
    regime_detector: RegimeDetector,
    decision_agent: DecisionAgent,
    position_sizer: PositionSizer,
    risk_engine: PortfolioRiskEngine,
    sector_by_security: Optional[dict[str, str]] = None,
    provenance: TradeProvenance = TradeProvenance.PAPER_TRADING,
    experiment_id: Optional[str] = None,
) -> tuple[CycleOutcome, ...]:
    """Runs the full chain once for each of `security_ids`, in order,
    sharing ONE `PortfolioView` snapshot across all of them (taken
    once at the start of this call, from `session.account_summary`) --
    the same "one snapshot per checkpoint" discipline
    `backtest.engine.BacktestEngine.run()` already uses, so a decision
    for the second security in the list is not evaluated against a
    portfolio state that already reflects the first security's
    not-yet-filled order from this same cycle.

    `sector_by_security` is passed straight through to `risk_engine.
    assess` (ADR-0062) -- `None` here means the same as `None` there:
    `RiskConfig.max_sector_weight`, if configured on `risk_engine`'s
    own config, will REJECT every BUY with `sector_unknown` rather than
    silently skip the check (fail-closed, unchanged from ADR-0062's own
    design). A caller that wants sector enforcement active must supply
    a real mapping here, e.g. from `data_infra.universe`'s own
    `_REAL_SEC_SECTOR_AND_EXCHANGE`-derived data."""
    account = session.account_summary(as_of=as_of_time)
    portfolio = _portfolio_view(account, view, as_of_time)

    outcomes = []
    for security_id in security_ids:
        current_price = _reference_price(view, security_id, as_of_time)
        prediction = predictor.predict(view, security_id, provenance=provenance, experiment_id=experiment_id)
        regime = regime_detector.compute_composite(view, security_id, provenance=provenance, experiment_id=experiment_id)
        decision = decision_agent.decide(
            security_id, as_of_time, prediction, regime, portfolio,
            provenance=provenance, experiment_id=experiment_id,
        )
        sizing = position_sizer.size(
            security_id, as_of_time, decision, prediction, regime, portfolio,
            current_price=current_price, provenance=provenance, experiment_id=experiment_id,
        )
        risk_checked = risk_engine.assess(
            security_id, as_of_time, sizing, portfolio, current_price=current_price,
            sector_by_security=sector_by_security, provenance=provenance, experiment_id=experiment_id,
        )
        current_quantity = portfolio.positions[security_id].quantity if security_id in portfolio.positions else 0.0
        validation = build_validated_order(
            risk_checked, current_quantity, configuration_version=session.config.configuration_version(),
        )
        submission: Optional[BrokerOrderResponse] = None
        if validation.validated_order is not None:
            submission, _fills = session.submit(validation.validated_order, requested_at=as_of_time)

        outcomes.append(CycleOutcome(
            security_id=security_id, prediction=prediction, regime=regime, decision=decision,
            sizing=sizing, risk_checked=risk_checked, validation=validation, submission=submission,
        ))
    return tuple(outcomes)
