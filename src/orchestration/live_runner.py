"""run_cycle: the Live-side equivalent of `orchestration.paper_runner.
run_cycle` -- Regime -> Prediction -> Decision -> Position Sizing ->
Portfolio Risk Engine -> Order Validation -> `LiveTradingSession.submit`,
one call per security per checkpoint, mirroring `paper_runner`'s own
chain structure exactly (Session 36, requested as the direct follow-up
to ADR-0067/ADR-0068 once the Paper pipeline was validated against real
data -- "Live 쪽 동등 파이프라인은 c 한 후에").

**This module deliberately does NOT reuse `paper_runner`'s types**, even
where the shape happens to match (e.g. a `value_history`-carrying state
object) -- `broker.paper`/`broker.live` are two structurally separate
implementations by design (ADR-0002-style separation for real-money
safety, `tests/broker/live/test_live_boundary.py`), and this module
follows the same discipline: no import of `broker.paper.*` or
`orchestration.paper_runner` here (`tests/orchestration/
test_live_orchestration_boundary.py`).

**Two structural differences from Paper, both forced by real
differences in what Live actually is, not by choice:**

1. **Portfolio state comes from the broker, not a local ledger.**
   `PaperTradingSession` keeps its own account_summary(); `LiveTradingSession`
   has no such method -- a real account's cash/positions live at the
   broker, never duplicated locally (instruction section 14's own
   "an unavailable/incomplete read is preserved as `available=False`,
   never defaulted" discipline, `broker.models.BrokerAccountSnapshot`/
   `BrokerPosition`). `_live_portfolio_view` reads `session.adapter.
   get_account`/`get_positions` directly and raises rather than
   fabricating a cash value of 0.0 when the broker reports the account
   unavailable -- a `PortfolioView` this module hands to Decision/Sizing/
   Risk must never encode a false "resting on $0".

2. **`SafetyGateContext` is a REQUIRED, caller-supplied parameter --
   this module never assembles one itself.** `evaluate_safety_gate`
   (`broker.live.safety_gate`) needs `risk_health`/`order_validation_
   status`/`account_state_known`/`position_state_known`/`model_state_
   valid`/`configuration_integrity_valid`/`max_turnover`/`approval` --
   a repo-wide check this session (before writing this module) found
   that NOTHING in `src/` currently computes real values for most of
   these fields; every existing caller (`tests/broker/live_helpers.py`'s
   `make_passing_gate_context`) is a test fixture that hardcodes a
   "passing" context. Building real, honest computations for each of
   those fields (wiring `monitoring.health`'s existing `evaluate_account_
   health`/`evaluate_pipeline_health`/etc., deciding what "model_state_
   valid" even means against the Candidate approval boundary this
   project deliberately keeps automation-free) is real, separate,
   safety-critical work this module does not attempt -- exactly the
   same "found a bigger gap, documented it honestly rather than
   fabricating a fix" precedent ADR-0067 already set for `value_history`.
   A caller of `run_cycle` here MUST supply a real, base `SafetyGateContext`;
   this module will neither build one from scratch nor accept `None` for
   it (unlike `sector_by_security`, which has a documented, tested
   fail-closed `None` behavior in the Risk Engine itself --
   `SafetyGateContext` has no such fallback anywhere in this codebase,
   so `None` is not offered here at all).

   One field IS this module's own to set: `order_validation_status`.
   `tests/integration/test_live_trading_lineage.py` (the one existing
   real end-to-end example of assembling a `SafetyGateContext`)
   populates it from that specific order's own `build_validated_order(...)
   .status` -- a value only known once this module has actually run
   Risk/Validation for that security, which differs security to
   security within the same cycle. `run_cycle` therefore takes the
   caller's base `gate_context` and, per security, derives the context
   actually handed to `session.submit()` via `dataclasses.replace(
   gate_context, order_validation_status=validation.status,
   as_of_time=as_of_time)` -- every other field passes through
   unchanged, exactly as the caller supplied it.

Still deliberately NOT "a real, running Trading Engine loop" (no timer/
scheduler) -- same scope boundary `paper_runner`'s own module docstring
states, `docs/specifications/PHASE-15-paper-trading.md` section 1.1 (its
reasoning applies identically to Live).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Optional, Protocol, Sequence

from backtest.asof import AsOfDataView
from backtest.portfolio import PortfolioView, PositionView

from broker.live.safety_gate import SafetyGateContext
from broker.live.session import LiveSubmissionOutcome, LiveTradingSession
from broker.models import OrderValidationResult
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

# Mirrors paper_runner.py's own reference-price lookback exactly -- kept
# as a separate constant (not imported from paper_runner) per this
# module's own no-cross-import discipline (see module docstring).
_PRICE_LOOKBACK_DAYS = 5


class PredictionRepository(Protocol):
    def record(self, prediction: PredictionOutput) -> None: ...


class RegimeRepository(Protocol):
    def record_composite(self, regime: CompositeRegimeObservation) -> None: ...


class DecisionRepository(Protocol):
    def record(self, decision: DecisionOutput) -> None: ...


class SizingRepository(Protocol):
    def record(self, sizing: PositionSizingResult) -> None: ...


class RiskRepository(Protocol):
    def record(self, risk_checked: RiskCheckedPosition) -> None: ...


@dataclass
class LiveRunnerState:
    """The Live-side equivalent of `paper_runner.PaperRunnerState` --
    same shape, kept as a distinct type per this module's no-cross-import
    discipline. A fresh `LiveRunnerState()` is correct for a brand-new
    session; a caller resuming a previous one should seed `value_history`
    from whatever real, already-persisted portfolio-value log it has --
    never fabricated or backfilled with guessed values for a gap."""

    value_history: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class LiveCycleOutcome:
    security_id: str
    prediction: PredictionOutput
    regime: CompositeRegimeObservation
    decision: DecisionOutput
    sizing: PositionSizingResult
    risk_checked: RiskCheckedPosition
    validation: OrderValidationResult
    submission: Optional[LiveSubmissionOutcome] = None


def _reference_price(view: AsOfDataView, security_id: str, as_of_time: datetime) -> Optional[float]:
    bars = view.get_bars(security_id, as_of_time - timedelta(days=_PRICE_LOOKBACK_DAYS), as_of_time)
    if not bars:
        return None
    return bars[-1].close


def _live_portfolio_view(session: LiveTradingSession, view: AsOfDataView, as_of_time: datetime) -> PortfolioView:
    """Reads real account/position state from the broker adapter
    (`session.adapter`) -- never a local ledger, unlike Paper's
    `session.account_summary()` (see module docstring point 1). Raises
    rather than defaulting to a fabricated $0 balance when the broker
    itself reports the read as unavailable -- a caller whose broker is
    down should see that failure, not a silently-empty portfolio."""
    account = session.adapter.get_account(as_of=as_of_time)
    if not account.available or account.cash is None:
        raise RuntimeError(
            f"live_account_unavailable: cannot build a PortfolioView without a real cash balance "
            f"(broker={session.adapter.broker_id!r}, reason={account.unavailable_reason!r})"
        )

    positions: dict[str, PositionView] = {}
    market_value = 0.0
    for broker_position in session.adapter.get_positions(as_of=as_of_time):
        if not broker_position.available or broker_position.quantity is None:
            continue
        average_cost = broker_position.average_cost or 0.0
        positions[broker_position.security_id] = PositionView(broker_position.security_id, broker_position.quantity, average_cost)
        price = _reference_price(view, broker_position.security_id, as_of_time)
        # A real current price marks the position to market; absent one,
        # the position's own cost basis is the best honest fallback still
        # available (never a fabricated market price) -- mirrors
        # paper_runner._portfolio_view's identical choice.
        market_value += broker_position.quantity * (price if price is not None else average_cost)

    return PortfolioView(
        as_of_time=as_of_time, cash=account.cash, positions=positions,
        portfolio_value=account.cash + market_value,
    )


def run_cycle(
    security_ids: Sequence[str],
    as_of_time: datetime,
    view: AsOfDataView,
    session: LiveTradingSession,
    *,
    predictor: Predictor,
    regime_detector: RegimeDetector,
    decision_agent: DecisionAgent,
    position_sizer: PositionSizer,
    risk_engine: PortfolioRiskEngine,
    gate_context: SafetyGateContext,
    sector_by_security: Optional[dict[str, str]] = None,
    state: Optional[LiveRunnerState] = None,
    prediction_repository: Optional[PredictionRepository] = None,
    regime_repository: Optional[RegimeRepository] = None,
    decision_repository: Optional[DecisionRepository] = None,
    sizing_repository: Optional[SizingRepository] = None,
    risk_repository: Optional[RiskRepository] = None,
    experiment_id: Optional[str] = None,
) -> tuple[LiveCycleOutcome, ...]:
    """Runs the full chain once for each of `security_ids`, in order,
    sharing ONE `PortfolioView` snapshot (read from the broker once at
    the start of this call) across all of them -- same "one snapshot per
    checkpoint" discipline `paper_runner.run_cycle`/`backtest.engine.
    BacktestEngine.run()` already use.

    `gate_context` is REQUIRED and is the BASE context this cycle uses --
    every field except `order_validation_status`/`as_of_time` is passed
    straight through to every `session.submit()` call this cycle,
    unchanged (see module docstring point 2: real, honest values for
    those fields are a separate, unbuilt piece of work this module does
    not attempt). `order_validation_status` IS this module's own to set,
    per security, from that security's real `build_validated_order(...)
    .status` -- matching `tests/integration/test_live_trading_lineage.py`'s
    own precedent for how that one field gets populated. A stale or
    wrong value in any of the OTHER fields is entirely the caller's
    responsibility, exactly as it already is for every existing
    `LiveTradingSession.submit()` caller in this codebase.

    `sector_by_security`/`state`/the five `*_repository` parameters all
    match `paper_runner.run_cycle`'s own contract exactly (ADR-0062,
    ADR-0068) -- opt-in, `None`/absent preserves the same fail-closed or
    skip-persistence behavior described there."""
    portfolio = _live_portfolio_view(session, view, as_of_time)

    value_history: Optional[tuple[float, ...]] = None
    if state is not None:
        value_history = tuple(state.value_history) + (portfolio.portfolio_value,)
        state.value_history.append(portfolio.portfolio_value)

    outcomes = []
    for security_id in security_ids:
        current_price = _reference_price(view, security_id, as_of_time)
        prediction = predictor.predict(view, security_id, provenance=TradeProvenance.LIVE_TRADING, experiment_id=experiment_id)
        if prediction_repository is not None:
            prediction_repository.record(prediction)

        regime = regime_detector.compute_composite(view, security_id, provenance=TradeProvenance.LIVE_TRADING, experiment_id=experiment_id)
        if regime_repository is not None:
            regime_repository.record_composite(regime)

        decision = decision_agent.decide(
            security_id, as_of_time, prediction, regime, portfolio,
            provenance=TradeProvenance.LIVE_TRADING, experiment_id=experiment_id,
        )
        if decision_repository is not None:
            decision_repository.record(decision)

        sizing = position_sizer.size(
            security_id, as_of_time, decision, prediction, regime, portfolio,
            current_price=current_price, provenance=TradeProvenance.LIVE_TRADING, experiment_id=experiment_id,
        )
        if sizing_repository is not None:
            sizing_repository.record(sizing)

        risk_checked = risk_engine.assess(
            security_id, as_of_time, sizing, portfolio, current_price=current_price,
            sector_by_security=sector_by_security, value_history=value_history,
            provenance=TradeProvenance.LIVE_TRADING, experiment_id=experiment_id,
        )
        if risk_repository is not None:
            risk_repository.record(risk_checked)

        current_quantity = portfolio.positions[security_id].quantity if security_id in portfolio.positions else 0.0
        validation = build_validated_order(
            risk_checked, current_quantity, configuration_version=session.config.configuration_version(),
        )
        submission: Optional[LiveSubmissionOutcome] = None
        if validation.validated_order is not None:
            order_gate_context = replace(gate_context, order_validation_status=validation.status, as_of_time=as_of_time)
            submission = session.submit(
                validation.validated_order, requested_at=as_of_time, gate_context=order_gate_context,
            )

        outcomes.append(LiveCycleOutcome(
            security_id=security_id, prediction=prediction, regime=regime, decision=decision,
            sizing=sizing, risk_checked=risk_checked, validation=validation, submission=submission,
        ))
    return tuple(outcomes)
