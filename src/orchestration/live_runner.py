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

2. **`SafetyGateContext` is a REQUIRED, caller-supplied BASE parameter
   -- this module never builds one from scratch, but it DOES override
   every field it can determine with certainty from data it already
   has, rather than trusting a caller's placeholder for something this
   module can just know.** Of `evaluate_safety_gate`'s inputs, SEVEN
   fields (six independent items, the last one covering two fields
   derived together) are overridden by `run_cycle` itself, per
   submission, via `dataclasses.replace(gate_context, ...)`:
     - `order_validation_status` -- from that security's own real
       `build_validated_order(...).status` (`tests/integration/
       test_live_trading_lineage.py`'s own precedent for this field).
     - `as_of_time` -- the checkpoint's own real time.
     - `config` -- `session.config`, the session's own real config;
       there is no honest reason a caller-supplied copy could differ.
     - `broker_capabilities` -- `session.adapter.get_capabilities(
       as_of=as_of_time)`, a real, already-available broker call.
     - `kill_switch_engaged` -- `session.is_kill_switch_engaged()`,
       likewise already available and authoritative.
     - `account_state_known`/`position_state_known` -- reaching this
       point in `run_cycle` at all means `_live_portfolio_view` already
       obtained a real account snapshot AND a real positions read (it
       RAISES otherwise -- see that function's docstring), so both are
       genuinely `True` here, not a caller's guess.

   A repo-wide check (before writing this module) found that NOTHING in
   `src/` computes real values for the REMAINING fields --
   `risk_health`/`model_state_valid`/`configuration_integrity_valid`/
   `max_turnover`/`approval`/`required_capabilities` -- every existing
   caller (`tests/broker/live_helpers.py::make_passing_gate_context`)
   is a test fixture that hardcodes a "passing" value. These stay
   genuinely the caller's responsibility, for reasons specific to each,
   not merely "not gotten to yet":
     - `max_turnover` -- `risk_engine` is typed as the `PortfolioRiskEngine`
       Protocol, which exposes no public config; reading a specific
       implementation's private `RiskConfig` would silently break for
       any other implementation, so this module cannot get at the real
       number honestly.
     - `approval` (`LiveActivationApproval`) -- a human-signed
       attestation by construction (`approved_by` structurally rejects
       "AI"/"SYSTEM"/"CLAUDE"); no code may ever synthesize one.
     - `required_capabilities` -- depends on what order types the
       calling strategy actually issues, a caller-level fact this
       module has no way to infer.
     - `model_state_valid`/`configuration_integrity_valid` -- real,
       spec-faithful (`PHASE-16-live-trading.md` section 5) pure
       functions now exist for BOTH (`orchestration.
       live_safety_gate_inputs.compute_model_state_valid`/
       `compute_configuration_integrity_valid`, ADR-0072) -- but
       `run_cycle` still cannot call them itself: `model_state_valid`
       needs a real `candidate_id` to fetch the latest
       `ModelStatusTransition` for, and nothing in this codebase yet
       ties `run_cycle`'s deterministic `predictor`/`decision_agent` to
       any specific `CandidateModelArtifact` (a real, separate,
       still-open architecture question, not this module's to answer);
       `configuration_integrity_valid` needs a pinned reference hash
       only an operator can supply. The caller computes these two and
       passes the results in on the base `gate_context`.
     - `risk_health` -- `monitoring.health.evaluate_health_from_failure_rate`
       already exists and is the right generic evaluator
       (`MonitoringComponent.RISK`), but nothing tracks a real running
       failure-rate/sample-count for `risk_engine.assess()` calls to
       feed it (`DeterministicPortfolioRiskEngine.assess` structurally
       returns a REJECT rather than raising, so "failure" here would
       have to mean something more specific than "REJECTs a lot" --
       still an open design question, not attempted this session).

   `run_cycle` will neither build a `SafetyGateContext` from scratch
   nor accept `None` for it (unlike `sector_by_security`, which has a
   documented, tested fail-closed `None` behavior in the Risk Engine
   itself -- `SafetyGateContext` has no such fallback anywhere in this
   codebase, so `None` is not offered here at all).

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

    `gate_context` is REQUIRED and is the BASE context this cycle uses.
    Seven fields are overridden by this function itself before every
    `session.submit()` call -- `order_validation_status`, `as_of_time`,
    `config`, `broker_capabilities`, `kill_switch_engaged`,
    `account_state_known`, `position_state_known` -- each derived from
    real, already-available data (session/adapter calls, or the fact
    that `_live_portfolio_view` above did not raise), never from the
    caller's copy (module docstring point 2 explains why each). The
    remaining fields (`risk_health`, `model_state_valid`,
    `configuration_integrity_valid`, `max_turnover`, `approval`,
    `required_capabilities`) pass through completely unchanged -- a
    stale or wrong value in any of THOSE is entirely the caller's
    responsibility, exactly as it already is for every existing
    `LiveTradingSession.submit()` caller in this codebase.

    `sector_by_security`/`state`/the five `*_repository` parameters all
    match `paper_runner.run_cycle`'s own contract exactly (ADR-0062,
    ADR-0068) -- opt-in, `None`/absent preserves the same fail-closed or
    skip-persistence behavior described there."""
    portfolio = _live_portfolio_view(session, view, as_of_time)
    # Reaching this line at all means `_live_portfolio_view` obtained a
    # real, available account snapshot AND a real positions read (it
    # raises otherwise, see that function's own docstring) -- so
    # `account_state_known`/`position_state_known` are genuinely True
    # here, not a caller's guess. `broker_capabilities` and
    # `kill_switch_engaged` are likewise always real, already-available
    # facts (`session.adapter.get_capabilities`/`session.
    # is_kill_switch_engaged()`) -- there is no honest reason to make a
    # caller supply a stand-in for any of these four, so `run_cycle`
    # derives them itself, same as `order_validation_status`/`as_of_time`.
    broker_capabilities = session.adapter.get_capabilities(as_of=as_of_time)
    kill_switch_engaged = session.is_kill_switch_engaged()

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
            order_gate_context = replace(
                gate_context, order_validation_status=validation.status, as_of_time=as_of_time,
                config=session.config, broker_capabilities=broker_capabilities,
                kill_switch_engaged=kill_switch_engaged, account_state_known=True, position_state_known=True,
            )
            submission = session.submit(
                validation.validated_order, requested_at=as_of_time, gate_context=order_gate_context,
            )

        outcomes.append(LiveCycleOutcome(
            security_id=security_id, prediction=prediction, regime=regime, decision=decision,
            sizing=sizing, risk_checked=risk_checked, validation=validation, submission=submission,
        ))
    return tuple(outcomes)
