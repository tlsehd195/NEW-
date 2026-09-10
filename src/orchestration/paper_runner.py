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

**`value_history` (Session 36 continued): now sourced, opt-in.** The
limitation above was real when first written; `run_cycle` now accepts
an optional `state: PaperRunnerState` a caller carries across
successive calls. When supplied, `run_cycle` appends this cycle's real
`portfolio.portfolio_value` to it and passes the running series to
`risk_engine.assess` as `value_history` -- the same "last element is
the current checkpoint's value" shape `risk.engine`'s own tests already
use. `state=None` (the default) preserves the original behavior exactly:
no `value_history` is passed, so `max_drawdown`/`max_portfolio_volatility`
still REJECT unless the caller's `RiskConfig` sets them `None`. A
resumed session should seed `PaperRunnerState.value_history` from
whatever real, already-persisted portfolio-value log it has -- never
fabricated or backfilled with guessed values for a gap.

**Persistence (Session 36 continued): now available, opt-in.**
`run_cycle` accepts optional `prediction_repository`/
`regime_repository`/`decision_repository`/`sizing_repository`/
`risk_repository` parameters -- when supplied, each stage's real output
is recorded through them (the exact repository classes/methods
`tests/integration/test_risk_lineage.py` already demonstrates,
e.g. `storage.prediction_repository.DuckDBPredictionRepository`).
`PaperTradingSession.submit` already persists its own order/fill/status
records internally (`broker.paper.*`'s own repositories, unchanged,
untouched here) -- these five parameters cover exactly the five stages
that session does not already persist. All default to `None` (skip),
matching `broker.pipeline.submit_validated_order`'s own "persist only
if a repository is supplied" precedent.

**Trade Journal (Session 37, ADR-0086): now available, opt-in.**
`run_cycle` accepts an optional `trade_journal`/`journal_state` pair --
when both are supplied, every checkpoint's `DecisionSnapshot` and any
real `TradeRecord`(s) it produced are recorded through
`trade_journal.paper_adapter.record_decision_and_trades`, the adapter
`trade_journal.backtest_adapter`'s own docstring had anticipated but
nothing had built until now. Before this, `PaperTradingSession.submit`'s
real fills were persisted only in `broker.paper.*`'s own order/fill
repositories -- never in the Trade Journal -- so
`trade_journal.experience.build_experience_records` (and therefore
`learning.pipeline.run_learning_pipeline`) had no real Paper Trading
experience to ever read, despite both halves of that pipeline being
fully built and tested independently (see ADR-0086). `journal_state`
must be created once by the caller (`trade_journal.paper_adapter.
PaperJournalState()`) and carried across every `run_cycle` call for the
same session, the same "caller-owned state carried forward" shape
`state: PaperRunnerState` already uses for `value_history` -- supplying
`trade_journal` without `journal_state` (or vice versa) raises
`ValueError` rather than silently skipping half the wiring. Both default
to `None` (skip), so every existing caller's behavior is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Protocol, Sequence

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
from trade_journal.paper_adapter import PaperJournalState, record_decision_and_trades
from trade_journal.repository import TradeJournalRepository

# Mirrors backtest.engine.BacktestEngine's own 1-day reference-price
# lookback exactly (src/backtest/engine.py) for the checkpoint-only
# case, widened slightly for Paper's own real-world data gaps (a
# weekend/holiday plus one missed provider update) -- still only ever
# returns the latest *available* bar, never interpolates or guesses.
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
class PaperRunnerState:
    """Mutable state a caller carries across successive `run_cycle`
    calls for the same Paper session -- currently just the running
    portfolio-value history `risk_engine.assess`'s `max_drawdown`/
    `max_portfolio_volatility` checks need (`RiskConfig`, Phase 8). A
    fresh `PaperRunnerState()` is correct for a brand-new session; a
    caller resuming a previous one should seed `value_history` from
    whatever real, already-persisted portfolio-value log it has --
    this object never fabricates or backfills a gap with guessed
    values."""

    value_history: list[float] = field(default_factory=list)


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
    state: Optional[PaperRunnerState] = None,
    prediction_repository: Optional[PredictionRepository] = None,
    regime_repository: Optional[RegimeRepository] = None,
    decision_repository: Optional[DecisionRepository] = None,
    sizing_repository: Optional[SizingRepository] = None,
    risk_repository: Optional[RiskRepository] = None,
    trade_journal: Optional[TradeJournalRepository] = None,
    journal_state: Optional[PaperJournalState] = None,
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
    `_REAL_SEC_SECTOR_AND_EXCHANGE`-derived data.

    `state`, when supplied, makes this cycle's real `portfolio_value`
    the newest point in a running series carried forward across calls,
    passed to `risk_engine.assess` as `value_history` (see module
    docstring). The five `*_repository` parameters, when supplied,
    persist that stage's real output through the exact repository
    classes `tests/integration/test_risk_lineage.py` already uses --
    `PaperTradingSession.submit` already persists its own order/fill/
    status records independently of these. `trade_journal`/
    `journal_state`, when BOTH supplied, additionally record a real
    `DecisionSnapshot` (every security, every checkpoint) and any real
    `TradeRecord`(s) into the Trade Journal (see module docstring) --
    the only stage this project's own Learning Engine actually reads
    from."""
    if (trade_journal is None) != (journal_state is None):
        raise ValueError("trade_journal and journal_state must be supplied together or not at all")

    account = session.account_summary(as_of=as_of_time)
    portfolio = _portfolio_view(account, view, as_of_time)

    value_history: Optional[tuple[float, ...]] = None
    if state is not None:
        value_history = tuple(state.value_history) + (portfolio.portfolio_value,)
        state.value_history.append(portfolio.portfolio_value)

    outcomes = []
    for security_id in security_ids:
        current_price = _reference_price(view, security_id, as_of_time)
        prediction = predictor.predict(view, security_id, provenance=provenance, experiment_id=experiment_id)
        if prediction_repository is not None:
            prediction_repository.record(prediction)

        regime = regime_detector.compute_composite(view, security_id, provenance=provenance, experiment_id=experiment_id)
        if regime_repository is not None:
            regime_repository.record_composite(regime)

        decision = decision_agent.decide(
            security_id, as_of_time, prediction, regime, portfolio,
            provenance=provenance, experiment_id=experiment_id,
        )
        if decision_repository is not None:
            decision_repository.record(decision)

        sizing = position_sizer.size(
            security_id, as_of_time, decision, prediction, regime, portfolio,
            current_price=current_price, provenance=provenance, experiment_id=experiment_id,
        )
        if sizing_repository is not None:
            sizing_repository.record(sizing)

        risk_checked = risk_engine.assess(
            security_id, as_of_time, sizing, portfolio, current_price=current_price,
            sector_by_security=sector_by_security, value_history=value_history,
            provenance=provenance, experiment_id=experiment_id,
        )
        if risk_repository is not None:
            risk_repository.record(risk_checked)

        current_quantity = portfolio.positions[security_id].quantity if security_id in portfolio.positions else 0.0
        validation = build_validated_order(
            risk_checked, current_quantity, configuration_version=session.config.configuration_version(),
        )
        submission: Optional[BrokerOrderResponse] = None
        fills: tuple = ()
        if validation.validated_order is not None:
            submission, fills = session.submit(validation.validated_order, requested_at=as_of_time)

        if trade_journal is not None:
            record_decision_and_trades(
                trade_journal, journal_state,
                security_id=security_id, as_of_time=as_of_time, decision=decision, validation=validation,
                fills=fills, portfolio_state=portfolio,
                strategy_version=decision.strategy_version or "unknown",
                provenance=provenance, experiment_id=experiment_id,
            )

        outcomes.append(CycleOutcome(
            security_id=security_id, prediction=prediction, regime=regime, decision=decision,
            sizing=sizing, risk_checked=risk_checked, validation=validation, submission=submission,
        ))
    return tuple(outcomes)
