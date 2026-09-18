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

**Portfolio accounting mark-to-market (Session 38): now always
populated.** `session.adapter.accounting` (the real `backtest.portfolio.
PortfolioAccounting` every fill this cycle applies to) is now marked to
market once per cycle, with the same per-security reference prices this
function's own Prediction/Sizing/Risk stages already compute --
unconditional, not opt-in, since it only appends internal valuation
history (`value_series`/`turnover()`) and changes no existing return
value. Before this, nothing called `mark_to_market` on this instance,
so `broker.paper.performance.compute_paper_performance_report`'s own
`equity_history`/`turnover` inputs stayed permanently unavailable to any
caller driving Paper Trading through `run_cycle` -- see
`scripts/run_paper_trading_cycle.py` for the first real caller that now
reads them back out.

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

**Reentry cooldown (Session 36 continued, ADR-0093/ADR-0095/ADR-0096):
now sourced from real Trade Journal history, opt-in, READ AND WRITE.**
`run_cycle` accepts an optional `trade_journal_repository` -- when
supplied, it is used TWICE per cycle:

1. READ, once per security before that security's own chain runs:
   `list_trades(security_id=..., end=as_of_time)` (point-in-time safe
   -- a trade dated after this checkpoint is never queried) builds
   `last_exit_time_by_security` for `risk_engine.assess`'s own opt-in
   parameter (`RiskConfig.reentry_cooldown_days`, ratified at 5 trading
   days but still `None` by default). Only a FULL exit counts (`side ==
   SELL` AND `position_after == 0.0`) -- a partial trim that still
   leaves a nonzero position is ordinary rebalancing, not the "reentry"
   this concept is about.
2. WRITE, once per real fill this cycle actually produces (ADR-0096,
   closing a real, previously-undiscovered gap: this function used to
   discard `session.submit()`'s own fills entirely -- nothing in this
   codebase's production path had ever populated the Trade Journal from
   a Paper Trading run before this): each `PaperFillRecord` from
   `session.submit()` is turned into a real `TradeRecord`.
   **Realized PnL (Session 37, ADR-0113): now also real, not always
   `None`.** ADR-0096/ADR-0097's original `record_trade` call passed
   none of `realized_pnl`/`realized_return`/`holding_period` -- every
   real `TradeRecord` this module ever wrote therefore had them
   permanently `None`, even for a genuine closing SELL, which silently
   made `learning.pipeline.run_learning_pipeline` structurally unable
   to ever train from real Paper Trading experience (`learning.
   cleaning.DataCleaningConfig.require_realized_outcome=True`'s default
   excludes any sample without a real `realized_return`). A closing
   SELL now computes `realized_pnl`/`realized_return` from
   `portfolio.positions[security_id].average_cost` (the real cost
   basis as of the START of this cycle, before this cycle's own fills)
   and `holding_period` from `_position_opened_at`'s own real replay of
   this security's Trade Journal history -- both `None` (never
   fabricated) when the inputs needed to compute them are themselves
   unavailable (no average cost on record, or no BUY in the journal).

   **Decision join (Session 37, ADR-0113): the "not joinable" limitation
   below is now CLOSED, superseding ADR-0097's original documented gap.**
   Testing the realized-PnL fix above against a real `learning.pipeline.
   run_learning_pipeline` run surfaced a second, more fundamental gap in
   the SAME area: `learning.cleaning.DataCleaner.clean` unconditionally
   calls `journal.get_decision(record.decision_id)` and excludes the
   sample with reason `"missing_decision"` if that lookup returns `None`
   -- REGARDLESS of whether `realized_return` is present. Since this
   function never called `record_decision`, `TradeRecord.decision_id`
   (set to `decision.decision_id`, a Phase 7 `DecisionOutput` ID) never
   resolved through `trade_journal.repository.get_decision`, so EVERY
   real Paper Trading `TradeRecord` -- even a real closing SELL with a
   real `realized_return` -- was excluded before the realized-outcome
   check ever ran. Fixing only the realized-PnL gap above, alone, would
   not have made the Learning Engine usable at all; both had to be fixed
   together. Now, whenever `trade_journal_repository` is supplied and a
   security's decision produces a `ValidatedOrder`, this function calls
   `record_decision(...)` ONCE for that security this cycle (with an
   explicit `natural_key`, not `order=` -- see `DecisionSnapshot.order`'s
   own type note below) BEFORE submitting, and every `TradeRecord` this
   cycle writes for that security uses the resulting real
   `DecisionSnapshot.snapshot_id` as `decision_id` -- a real, joinable
   link, not the Phase 7 `DecisionOutput.decision_id` ADR-0097 used
   (still separately available via `decision_repository` if supplied,
   unchanged). `DecisionSnapshot.order` is deliberately always `None`
   here (never `validation.validated_order`) -- it is typed for
   `backtest.orders.Order` (`order.order_id`), and `broker.validation.
   build_validated_order` produces the structurally different `broker.
   models.ValidatedOrder` (`client_order_id`, no `order_id`); passing
   one through as the other breaks both `record_decision`'s own
   natural-key derivation and `storage.serialization.
   decision_snapshot_to_payload` identically, the same incompatibility
   `trade_journal.paper_adapter` (an earlier, since-superseded attempt
   at this same problem) had already found and avoided the same way.
   A decision is recorded only when a `ValidatedOrder` actually resulted
   (not for every HOLD/REJECT) -- narrower than `trade_journal.
   backtest_adapter.ingest_backtest_result`'s "record for every order
   regardless of status," a deliberate scope choice since only a
   decision that produces a real `TradeRecord` ever needs to be
   joinable at all.

`None` (the default, omitted) means exactly what it already means to
`risk_engine.assess` directly for the read side, and simply skips all
persistence for the write side (matching the five `*_repository`
parameters' own "persist only if supplied" contract) -- a caller that
has not wired up a Trade Journal repository sees no behavior change at
all, same as before ADR-0096.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Protocol, Sequence

from backtest.asof import AsOfDataView
from backtest.enums import OrderSide
from backtest.portfolio import PortfolioView, PositionView

from data_infra.models import CorporateAction

from broker.models import BrokerOrderResponse, OrderValidationResult
from broker.paper.models import PaperFillRecord
from broker.paper.session import AccountSummary, PaperTradingSession
from broker.validation import build_validated_order

from decision.agent import DecisionAgent
from decision.models import DecisionOutput

from predict.models import PredictionOutput
from predict.predictor import Predictor

from regime.detector import RegimeDetector
from regime.enums import AXIS_STATE_ENUM
from regime.models import CompositeRegimeObservation

from risk.engine import PortfolioRiskEngine
from risk.models import PositionSizingResult, RiskCheckedPosition
from risk.sizing import PositionSizer

from trade_journal.enums import TradeProvenance
from trade_journal.models import DecisionSnapshot, TradeRecord

# Mirrors backtest.engine.BacktestEngine's own 1-day reference-price
# lookback exactly (src/backtest/engine.py) for the checkpoint-only
# case, widened slightly for Paper's own real-world data gaps (a
# weekend/holiday plus one missed provider update) -- still only ever
# returns the latest *available* bar, never interpolates or guesses.
_PRICE_LOOKBACK_DAYS = 5

# ADR-0155: the EXACT same 400-day corporate-action lookback window
# `backtest.engine.BacktestEngine.run()` uses (src/backtest/engine.py,
# ~line 116) -- deliberately not a different number, so Paper Trading
# and Backtest never diverge on how far back a split/dividend can still
# be discovered.
_CORPORATE_ACTION_LOOKBACK_DAYS = 400

# Session 37 (ADR-0113): tags every DecisionSnapshot this module writes
# to the Trade Journal -- distinct from any Phase 7 DecisionOutput
# version string, and from trade_journal.backtest_adapter.
# EXECUTION_VERSION (a different code path: real Paper fills, never a
# replayed BacktestResult), so the two are never confused when read back.
_EXECUTION_VERSION = "orchestration_paper_runner_v1"


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


class TradeJournalRepositoryLike(Protocol):
    """Read+write, deliberately narrow (only the three methods `run_cycle`
    actually calls, mirroring every other narrow Protocol in this
    module) -- satisfied structurally by both `trade_journal.repository.
    InMemoryTradeJournalRepository` and `storage.trade_journal_repository.
    DuckDBTradeJournalRepository` without either needing to reference
    this Protocol at all."""

    def list_trades(
        self, *, security_id: Optional[str] = None, provenance: Optional[TradeProvenance] = None,
        start: Optional[datetime] = None, end: Optional[datetime] = None,
    ) -> list[TradeRecord]: ...

    def record_decision(self, **fields) -> DecisionSnapshot: ...

    def get_decision_by_natural_key(self, natural_key: tuple) -> Optional[DecisionSnapshot]: ...

    def record_trade(
        self, *, decision_id: str, fill, position_after: float,
        realized_pnl: Optional[float] = None, realized_return: Optional[float] = None,
        holding_period: Optional[timedelta] = None,
        provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
        experiment_id: Optional[str] = None,
    ) -> TradeRecord: ...


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
    values.

    `mark_to_market_missing` (external review, Session 38 continued):
    each cycle's own `mark_to_market` call returns the security_ids it
    had no real price for and had to fall back to average cost for
    (`backtest.portfolio.PortfolioAccounting.mark_to_market`'s own
    second return value) -- previously discarded entirely by
    `run_cycle`, silently turning a missing-price gap into an
    unflagged, cost-basis valuation. Recorded here (one entry per
    cycle where the list was non-empty) so a caller can surface it --
    e.g. `scripts/run_paper_trading_cycle.py` prints a warning and
    writes it into the run's own report JSON."""

    value_history: list[float] = field(default_factory=list)
    mark_to_market_missing: list[tuple[datetime, tuple[str, ...]]] = field(default_factory=list)

    # ADR-0155: same "recorded here, one entry per cycle where the list
    # was non-empty, so a caller can surface it" treatment
    # `mark_to_market_missing` above already established -- each
    # cycle's own `session.apply_corporate_actions(...)` call returns
    # whatever warnings `backtest.corporate_actions.CorporateActionApplier.
    # apply()` produced for this cycle's newly-applied actions (an
    # unparseable split ratio, a missing dividend amount, or an
    # unhandled action type such as MERGER) -- never raised, never
    # silently discarded.
    corporate_action_warnings: list[tuple[datetime, tuple[str, ...]]] = field(default_factory=list)


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


def _prediction_features(prediction: PredictionOutput) -> Optional[dict]:
    """Session 38: `DecisionSnapshot.features` (and therefore
    `LabeledSample.features`) has been real, structured data since
    Phase 3/9 existed, but nothing in this codebase ever populated it
    for a real Paper/Live decision -- `scripts/run_learning_cycle.py`'s
    own module docstring already disclosed this honestly ("no Strategy/
    DecisionAgent... sets OrderIntent.features yet"), which is why
    `learning.linear_trainer.LinearRegressionTrainer` always reported
    `fitted=False, train_sample_count=0` against real data. Reuses the
    five real, already-computed `PredictionOutput` fields PROJECT_
    MASTER_PLAN.md section 8.1 itself names -- no new computation, no
    new data source. Each is `Optional[float]` on `PredictionOutput`
    itself; a `None` value is OMITTED from the dict entirely, never
    written as `"key": None` -- `LinearRegressionTrainer._samples_
    with_required_features` only checks KEY PRESENCE (`required <=
    set(s.features)`), so a present-but-`None` value would pass that
    check and then crash `LinearRegressionModel.fit`'s own arithmetic;
    omitting the key instead makes that sample correctly excluded for
    lacking that feature, matching every other "never fabricate/never
    leave a landmine" convention already in this codebase. Returns
    `None` (not `{}`) when every field is `None`, so `DecisionSnapshot.
    features` stays a real "no features available" rather than an
    empty-but-present dict that reads differently downstream."""
    raw = {
        "expected_return": prediction.expected_return,
        "probability": prediction.probability,
        "expected_volatility": prediction.expected_volatility,
        "uncertainty": prediction.uncertainty,
        "confidence": prediction.confidence,
    }
    features = {k: v for k, v in raw.items() if v is not None}
    return features or None


def _regime_features(regime: CompositeRegimeObservation) -> Optional[dict]:
    """External review (Session 38 continued, ADR-0141's own disclosed
    trade-off): "regime axis observations (categorical, e.g.
    LiquidityState) are not encoded into numeric features" -- closes
    that gap. Each axis contributes independently, since a
    `RegimeObservation`'s own `.value` (numeric) and `.state`
    (categorical) are independent facts -- `compute_volatility` can
    return a real `.value` (the raw annualized vol estimate) even while
    `.state` is still `UNKNOWN` (insufficient percentile history to
    classify it), so this function never assumes one implies the other
    is present.

    `.value` (already numeric): included as `regime_<axis>_value`
    whenever not `None` -- no new computation, the same value
    `RegimeObservation` already carries.

    `.state` (categorical): one-hot encoded as `regime_<axis>_is_<state>`
    -- one key per state THIS axis can real-take (from `regime.enums.
    AXIS_STATE_ENUM`, excluding `UNKNOWN` itself), 1.0 for the active
    state and 0.0 for every other real state of that SAME axis (a true,
    not fabricated, fact: the axis genuinely is not in that other
    state). The entire one-hot block for an axis is OMITTED when that
    axis's own state is `UNKNOWN` -- writing an all-zero block would
    read downstream as "confidently observed none of these states,"
    which is a different (false) claim from "this axis was never
    classified," the same "never leave a landmine for downstream
    arithmetic" distinction `_prediction_features` above already
    applies to `None`.

    Returns `None` (not `{}`) when every axis is missing/`UNKNOWN`."""
    features: dict = {}
    for axis, observation in regime.axes.items():
        axis_name = axis.value.lower()
        if observation.value is not None:
            features[f"regime_{axis_name}_value"] = observation.value
        state_enum = AXIS_STATE_ENUM[axis]
        if observation.state != state_enum.UNKNOWN.value:
            for member in state_enum:
                if member == state_enum.UNKNOWN:
                    continue
                features[f"regime_{axis_name}_is_{member.value.lower()}"] = (
                    1.0 if observation.state == member.value else 0.0
                )
    return features or None


def _decision_features(prediction: PredictionOutput, regime: CompositeRegimeObservation) -> Optional[dict]:
    """Combines `_prediction_features`/`_regime_features` into the one
    dict `record_decision(features=...)` takes -- kept as two separate,
    independently-testable functions above rather than one, since a
    caller with only a `PredictionOutput` (no regime context) can still
    use `_prediction_features` alone."""
    merged = {**(_prediction_features(prediction) or {}), **(_regime_features(regime) or {})}
    return merged or None


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
        price = _reference_price(view, security_id, as_of_time)
        # A real current price marks the position to market; absent
        # one, the position's own cost basis is the best honest
        # fallback still available (never a fabricated market price).
        position_market_value = broker_position.quantity * price if price is not None else None
        positions[security_id] = PositionView(
            security_id, broker_position.quantity, average_cost, market_value=position_market_value,
        )
        market_value += position_market_value if position_market_value is not None else broker_position.quantity * average_cost
    return PortfolioView(
        as_of_time=as_of_time, cash=account.cash, positions=positions,
        portfolio_value=account.cash + market_value,
    )


def _tracked_security_ids(security_ids: Sequence[str], session: PaperTradingSession) -> list[str]:
    """`security_ids` plus any currently-held position not already in
    that list -- mirrors `backtest.engine.BacktestEngine.run()`'s own
    `tracked_ids = universe_today | set(portfolio.positions.keys())`
    (engine.py ~line 112) exactly: a corporate action on a security this
    account still HOLDS but no longer actively trades must still be
    applied, or that position would silently drift un-split-adjusted/
    un-paid forever, with no error."""
    return sorted(set(security_ids) | set(session.adapter.accounting.positions.keys()))


def apply_due_corporate_actions(
    security_ids: Sequence[str],
    session: PaperTradingSession,
    view: AsOfDataView,
    as_of_time: datetime,
    state: Optional[PaperRunnerState] = None,
) -> None:
    """Shared by `run_cycle` below and `scripts.run_multi_strategy_
    paper_trading_cycle._run_buy_and_hold_strategy` (ADR-0163): fetches
    every corporate action effective as of `as_of_time` for
    `security_ids` plus any currently-held position not already in
    that list (`_tracked_security_ids`, mirroring `backtest.engine.
    BacktestEngine.run()`'s own `tracked_ids`), over the same
    `_CORPORATE_ACTION_LOOKBACK_DAYS` window `run_cycle` has always
    used, and applies them via `session.apply_corporate_actions` --
    safe every call, including across a restart, because that method
    checks a real persisted ledger before applying anything (ADR-0155).

    Must be called BEFORE `session.advance(as_of_time)`/any same-cycle
    fill attempt (ADR-0158) -- this function never calls `advance`
    itself, so that ordering is the caller's own responsibility.

    Any warning `session.apply_corporate_actions` returns (an
    unparseable ratio, a missing dividend amount, an unhandled type
    such as MERGER) is appended to `state.corporate_action_warnings`
    when `state` is supplied -- the same opt-in surfacing
    `mark_to_market_missing` already gets elsewhere in this module --
    never raised, never silently discarded."""
    all_corporate_actions: list[CorporateAction] = []
    for security_id in _tracked_security_ids(security_ids, session):
        all_corporate_actions.extend(
            view.get_corporate_actions(
                security_id, as_of_time - timedelta(days=_CORPORATE_ACTION_LOOKBACK_DAYS), as_of_time,
            )
        )
    if all_corporate_actions:
        corporate_action_warnings = session.apply_corporate_actions(all_corporate_actions, as_of_time)
        if corporate_action_warnings and state is not None:
            state.corporate_action_warnings.append((as_of_time, tuple(corporate_action_warnings)))


def _last_exit_time_by_security(
    security_ids: Sequence[str], as_of_time: datetime, repository: TradeJournalRepositoryLike, provenance: TradeProvenance,
) -> dict[str, datetime]:
    """Real exit history for the reentry-cooldown check (ADR-0093/
    ADR-0095), one `list_trades` query per security bounded by `end=
    as_of_time` -- point-in-time safe, a trade dated after this
    checkpoint is never queried at all. Only a FULL exit counts (`side
    == SELL` AND `position_after == 0.0`) -- a partial trim that still
    leaves a nonzero position is ordinary rebalancing, not the
    "reentry" this concept is about. A security with no full exit on
    record is simply absent from the returned mapping -- the ordinary
    case (never exited, or a resumed session with no journal yet), not
    a data gap; see `RiskConfig.reentry_cooldown_days`'s own docstring
    for why `risk_engine.assess` treats an absent entry as PASS, not a
    fail-closed REJECT."""
    result: dict[str, datetime] = {}
    for security_id in security_ids:
        trades = repository.list_trades(security_id=security_id, provenance=provenance, end=as_of_time)
        exits = [t for t in trades if t.side == OrderSide.SELL and t.position_after == 0.0]
        if exits:
            result[security_id] = max(t.timestamp for t in exits)
    return result


def _position_opened_at(
    security_id: str, as_of_time: datetime, repository: TradeJournalRepositoryLike, provenance: TradeProvenance,
) -> Optional[datetime]:
    """The real timestamp the currently-open position in `security_id`
    was first opened -- the BUY that most recently took a flat position
    nonzero (since the last full exit, or ever if none) -- replayed from
    the Trade Journal's own already-persisted history (`end=as_of_time`,
    point-in-time safe, mirroring `_last_exit_time_by_security`'s own
    query bound). Used only to compute a closing SELL's `TradeRecord.
    holding_period` (Session 37, ADR-0113 -- closing the gap ADR-0097
    left: `record_trade` was called with no `realized_pnl`/
    `realized_return`/`holding_period` at all, which meant every real
    fill this module ever wrote had them permanently `None`, silently
    making `learning.pipeline.run_learning_pipeline` structurally unable
    to ever train on real Paper Trading experience -- `learning.cleaning.
    DataCleaningConfig.require_realized_outcome=True`'s default excludes
    any sample without a real `realized_return`). Returns `None` (never
    guessed) when the journal has no BUY on record for this security."""
    trades = sorted(
        repository.list_trades(security_id=security_id, provenance=provenance, end=as_of_time),
        key=lambda t: t.timestamp,
    )
    running = 0.0
    opened_at: Optional[datetime] = None
    for t in trades:
        if t.side == OrderSide.BUY:
            if running == 0.0:
                opened_at = t.timestamp
            running += t.quantity
        else:
            running -= t.quantity
            if running == 0.0:
                opened_at = None
    return opened_at


def _record_fills_to_journal(
    trade_journal_repository: TradeJournalRepositoryLike,
    decision_snapshot: DecisionSnapshot,
    fill_records: Sequence[PaperFillRecord],
    *,
    running_quantity: float,
    position_average_cost: Optional[float],
    opened_at: Optional[datetime],
    provenance: TradeProvenance,
    experiment_id: Optional[str],
) -> float:
    """ADR-0154: the shared "given a decision + a sequence of fills +
    starting quantity/avg-cost/opened_at, write TradeRecords" logic,
    extracted so the same-cycle path (a fresh order's own fill from
    `session.submit`) and the delayed-fill path (an OLDER order's fill
    surfacing only via `session.advance`) compute realized_pnl/
    realized_return/holding_period identically rather than maintaining
    two copies of this arithmetic. Returns the running signed quantity
    after every fill in `fill_records`, so a caller processing several
    orders for the same security in sequence can thread it through."""
    for fill_record in fill_records:
        fill = fill_record.fill
        signed = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity
        running_quantity += signed

        realized_pnl: Optional[float] = None
        realized_return: Optional[float] = None
        holding_period: Optional[timedelta] = None
        if fill.side == OrderSide.SELL and position_average_cost is not None:
            # commission ONLY, not fill.total_cost -- see
            # backtest.portfolio.PortfolioAccounting.apply_fill's own
            # comment (Session 37, ADR-0114): fill.price already nets
            # out spread/slippage on both the entry and exit leg, so
            # subtracting spread_cost/slippage_cost again here
            # double-counts them.
            realized_pnl = (fill.price - position_average_cost) * fill.quantity - fill.commission
            cost_basis = position_average_cost * fill.quantity
            realized_return = (realized_pnl / cost_basis) if cost_basis else None
            if opened_at is not None:
                holding_period = fill.execution_time - opened_at

        trade_journal_repository.record_trade(
            decision_id=decision_snapshot.snapshot_id, fill=fill, position_after=running_quantity,
            realized_pnl=realized_pnl, realized_return=realized_return, holding_period=holding_period,
            provenance=provenance, experiment_id=experiment_id,
        )
    return running_quantity


def _record_delayed_advance_fills(
    trade_journal_repository: TradeJournalRepositoryLike,
    session: PaperTradingSession,
    pre_advance_account: AccountSummary,
    advance_fills: Sequence[PaperFillRecord],
    as_of_time: datetime,
) -> None:
    """ADR-0154: mirrors the same-cycle Trade Journal write below, but
    for fills `session.advance(as_of_time)` produces for an OLDER
    order (the T+1 fill this order's own submission cycle deferred --
    see `PaperBrokerAdapter.submit_order`'s own docstring). Closes the
    gap this module's docstring ("Decision join") used to disclose as
    a known limitation: once fills are deferred, EVERY first fill is
    exactly this delayed case, so leaving it unrecorded would silently
    stop Paper Trading from ever populating the Trade Journal at all.

    Groups `advance_fills` by `client_order_id` (preserving `advance`'s
    own relative ordering) so a partially-filled order's own several
    fills this call produces still accumulate the correct cumulative
    `running_quantity`, and further by `security_id` so two different
    orders for the same security in one `advance()` call share one
    running quantity/avg-cost/opened_at, exactly like the same-cycle
    path already does across fills of one order.

    Each order's original `DecisionSnapshot` is re-located by
    `get_decision_by_natural_key` using the exact natural_key tuple the
    same-cycle path already records it under
    (`("paper_decision", experiment_id, security_id, requested_at)`,
    read from the order's own persisted `PaperOrderRecord` --
    `record.validated_order.experiment_id`/`.security_id`/
    `record.requested_at`). A `None` result (the decision was never
    recorded, e.g. `trade_journal_repository` was absent during the
    original submission) means this fill is skipped silently -- never
    a fabricated/missing-but-pretended link."""
    fills_by_order: dict[str, list[PaperFillRecord]] = {}
    order_sequence: list[str] = []
    for fill_record in advance_fills:
        if fill_record.client_order_id not in fills_by_order:
            fills_by_order[fill_record.client_order_id] = []
            order_sequence.append(fill_record.client_order_id)
        fills_by_order[fill_record.client_order_id].append(fill_record)

    running_quantity_by_security: dict[str, float] = {}
    position_average_cost_by_security: dict[str, Optional[float]] = {}
    opened_at_by_security: dict[str, Optional[datetime]] = {}
    decision_cache: dict[tuple, Optional[DecisionSnapshot]] = {}

    for client_order_id in order_sequence:
        order_record = session.adapter.get_order_record(client_order_id)
        if order_record is None:
            continue  # structurally should not happen -- never fabricate a link
        validated_order = order_record.validated_order
        security_id = validated_order.security_id
        experiment_id = validated_order.experiment_id
        provenance = validated_order.provenance

        natural_key = ("paper_decision", experiment_id, security_id, order_record.requested_at)
        if natural_key not in decision_cache:
            decision_cache[natural_key] = trade_journal_repository.get_decision_by_natural_key(natural_key)
        decision_snapshot = decision_cache[natural_key]
        if decision_snapshot is None:
            continue  # this order's decision was never recorded -- skip, never fabricate

        if security_id not in running_quantity_by_security:
            account_position = pre_advance_account.positions.get(security_id)
            running_quantity_by_security[security_id] = (
                account_position.quantity
                if account_position is not None and account_position.available and account_position.quantity is not None
                else 0.0
            )
            position_average_cost_by_security[security_id] = (
                account_position.average_cost
                if account_position is not None and account_position.available
                else None
            )
            opened_at_by_security[security_id] = _position_opened_at(
                security_id, as_of_time, trade_journal_repository, provenance,
            )

        running_quantity_by_security[security_id] = _record_fills_to_journal(
            trade_journal_repository, decision_snapshot, fills_by_order[client_order_id],
            running_quantity=running_quantity_by_security[security_id],
            position_average_cost=position_average_cost_by_security[security_id],
            opened_at=opened_at_by_security[security_id],
            provenance=provenance, experiment_id=experiment_id,
        )


def compute_portfolio_snapshot(session: PaperTradingSession, view: AsOfDataView, as_of_time: datetime) -> PortfolioView:
    """Public wrapper around the exact same mark-to-market snapshot
    `run_cycle` itself takes at the start of every checkpoint (cash +
    reference-priced positions, cost-basis fallback for a security with
    no available price -- see `_portfolio_view`'s own docstring) --
    reusable by a caller that needs a checkpoint's real portfolio value
    without running the full Prediction/Regime/Decision/Sizing/Risk
    chain (Session 36 continued: `PaperStrategyKind.BUY_AND_HOLD`'s own
    per-checkpoint valuation loop, `scripts/run_multi_strategy_paper_
    trading_cycle.py`, needs exactly this and nothing more -- it never
    calls a `Predictor`/`DecisionAgent` at all after its one initial
    allocation)."""
    account = session.account_summary(as_of=as_of_time)
    return _portfolio_view(account, view, as_of_time)


def equity_history_from_risk_repository(
    risk_repository, representative_security_id: str, *, up_to: Optional[datetime] = None,
) -> list[tuple[datetime, float]]:
    """Real, already-persisted `(as_of_time, portfolio_value)` pairs for
    one security's own `RiskCheckedPosition` history, in chronological
    order -- reconstructed from `.as_of_time`/`.risk_state.
    portfolio_value` (one real snapshot per checkpoint, shared across
    every security assessed that cycle, so any one security already
    assessed is a valid representative proxy) rather than guessed or
    interpolated. Never fabricates a point for a checkpoint whose
    `risk_state` is unexpectedly absent -- that checkpoint is simply
    skipped, matching this project's fail-closed discipline.

    Unlike `session.adapter.accounting.value_series` (real only within
    ONE process -- `PaperTradingSession.restore()` replays fills, never
    replays the `mark_to_market` calls that build that series), this
    repository-backed history is durable across every past `--resume`
    invocation against the same `--paper-store` -- why it, not
    `accounting.value_series`, is every real caller's source for
    `broker.paper.performance.compute_paper_performance_report`'s own
    `equity_history` input (ADR-0136).

    External review, LOW-1 (Session 38 continued): this exact
    reconstruction previously existed as three separate, independently
    written copies -- `scripts/run_paper_trading_cycle.py`'s own
    `_equity_history`/`_reconstruct_value_history`,
    `scripts/generate_paper_performance_tearsheet.py`'s own
    `_equity_history`, and `scripts/run_multi_strategy_paper_trading_
    cycle.py`'s own `_reconstruct_value_history` -- promoted here to one
    shared source all three now call. `up_to`, when supplied, filters to
    checkpoints at or before it (a resumed run's own already-processed
    history); omitted, every real checkpoint on record is returned."""
    records = risk_repository.list_all(security_id=representative_security_id, end=up_to)
    return sorted(
        ((r.as_of_time, r.risk_state.portfolio_value) for r in records if r.risk_state is not None),
        key=lambda pair: pair[0],
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
    trade_journal_repository: Optional[TradeJournalRepositoryLike] = None,
    state: Optional[PaperRunnerState] = None,
    prediction_repository: Optional[PredictionRepository] = None,
    regime_repository: Optional[RegimeRepository] = None,
    decision_repository: Optional[DecisionRepository] = None,
    sizing_repository: Optional[SizingRepository] = None,
    risk_repository: Optional[RiskRepository] = None,
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
    status records independently of these.

    `trade_journal_repository`, when supplied, is queried once per
    security for real exit history and passed to `risk_engine.assess`
    as `last_exit_time_by_security` (see module docstring) -- `None`
    (the default) means the reentry-cooldown check is simply not
    evaluated for this call, same opt-in contract `sector_by_security`
    already has.

    **Stuck-order retry (Session 38): always attempted, right after
    corporate actions above (ADR-0158 reordered this to run AFTER
    `apply_due_corporate_actions`, not before -- see that paragraph
    below for why).** `session.advance(as_of_time)` runs before this
    cycle's own `account`/`portfolio` snapshot below -- confirmed by
    reading every real caller of this function that
    nothing previously called `PaperTradingSession.advance`/`adapter.
    advance_simulation` anywhere in this pipeline, so an order that only
    partially filled on its own submission day (e.g. `PaperTradingConfig.
    max_participation`'s default 10%-of-bar-volume cap on a large order)
    stayed PARTIAL_FILLED/PENDING forever -- never retried against a
    later day's fresh market data, a real "zombie order" bug, not a
    hypothetical one. Any fill this produces is already persisted
    through `broker.paper.*`'s own order/fill/status repositories (the
    same ones `session.submit` already writes to) via `advance()`
    itself, and reflected in `account`/`portfolio` below like any other
    prior fill.

    **Decision-journal join for a delayed fill (ADR-0154): the gap this
    docstring used to disclose here is now CLOSED.** `PaperBrokerAdapter.
    submit_order` no longer attempts a fill synchronously (ADR-0154's
    T+1 fix for Paper Trading's own same-bar-decide-and-fill leak) -- so
    EVERY order's first fill now surfaces only through this `advance()`
    call, one cycle later. `pre_advance_account` (captured immediately
    BEFORE `advance()` runs, so it reflects state as of the END of the
    PRIOR cycle -- the correct pre-fill `average_cost`/`quantity` for
    realized-PnL math, the exact same "read before this cycle's own
    fills land" discipline the same-cycle path below already applies to
    `account`) is handed to `_record_delayed_advance_fills`, which
    re-locates each delayed fill's originating `DecisionSnapshot` via
    `get_decision_by_natural_key` and writes a real, joinable
    `TradeRecord` for it -- see that helper's own docstring. A decision
    that was never recorded (e.g. `trade_journal_repository` was absent
    during the original submission) is skipped silently, never
    fabricated.

    **Corporate actions (ADR-0155, reordered by ADR-0158): always
    applied FIRST, before the stuck-order retry/T+1 fill attempt below
    and before this cycle's own `account`/`portfolio` snapshot.**
    Closes the gap Paper Trading had before this: `broker/paper/*` had
    zero corporate-action handling at all, so a real split/dividend on
    a held position would silently corrupt `PaperBrokerAdapter.
    accounting`'s `quantity`/`average_cost` forever.
    `session.apply_corporate_actions(...)` is called with every
    corporate action `view.get_corporate_actions` returns for
    `security_ids` plus any currently-held position not in that list
    (`_tracked_security_ids`, mirroring `backtest.engine.BacktestEngine.
    run()`'s own `tracked_ids`), over the SAME 400-day lookback window
    that engine uses. Safe to call every cycle with a full lookback
    window's worth of actions, including across a restart between
    cycles, because `PaperTradingSession.apply_corporate_actions` checks
    a real PERSISTED ledger (not `CorporateActionApplier`'s own
    in-process `_applied` set, which is empty again every fresh
    process) before applying anything -- see that method's own
    docstring and ADR-0155 for why a naive per-cycle `.apply()` call
    would otherwise re-apply the same action forever. Any warning
    (an unparseable ratio, a missing dividend amount, or an unhandled
    type such as MERGER) is recorded on `state.corporate_action_warnings`
    when `state` is supplied, the same opt-in surfacing
    `mark_to_market_missing` already gets below -- never raised, never
    silently discarded.

    **ADR-0158 (external review): corporate actions must be applied
    BEFORE this cycle's T+1 fill attempt below, never after.** An
    earlier version of this function applied actions AFTER
    `session.advance(as_of_time)` -- the exact same same-time-boundary
    corruption `backtest.engine.BacktestEngine.run()` already had to
    fix once (ADR-0115): a same-`as_of_time` fill landing on an
    already-split-adjusted market price would then get the position's
    own `PortfolioAccounting.apply_split` blindly multiplied onto it a
    SECOND time; a same-`as_of_time` BUY would wrongly receive a
    dividend declared for holders as of the prior close; and a same-
    `as_of_time` SELL that fully closed a position would already have
    removed it from `accounting.positions` by the time the dividend
    that position WAS entitled to (held through the prior close) would
    have been applied -- `apply_dividend`'s own `if pos is None or
    pos.quantity == 0: return` guard makes that a silent no-op, not an
    error. Applying every action effective as of `as_of_time` FIRST
    fixes all three the same way engine.py's own next_checkpoint block
    already does: existing holdings are correctly adjusted/paid BEFORE
    any new fill lands (so a new fill is never double-adjusted or
    wrongly paid), and a same-cycle closing SELL still receives the
    dividend it earned before its fill removes the position."""
    apply_due_corporate_actions(security_ids, session, view, as_of_time, state)

    # ADR-0158: captured AFTER corporate actions above, so a split/
    # dividend effective this same as_of_time is already reflected --
    # the correct pre-fill baseline for _record_delayed_advance_fills's
    # realized_pnl math even on a cycle where an action and a delayed
    # fill land at the same as_of_time.
    pre_advance_account = session.account_summary(as_of=as_of_time)
    advance_updates, advance_fills = session.advance(as_of_time)
    if trade_journal_repository is not None and advance_fills:
        _record_delayed_advance_fills(trade_journal_repository, session, pre_advance_account, advance_fills, as_of_time)

    account = session.account_summary(as_of=as_of_time)
    portfolio = _portfolio_view(account, view, as_of_time)

    value_history: Optional[tuple[float, ...]] = None
    if state is not None:
        value_history = tuple(state.value_history) + (portfolio.portfolio_value,)
        state.value_history.append(portfolio.portfolio_value)

    last_exit_time_by_security: Optional[dict[str, datetime]] = None
    if trade_journal_repository is not None:
        last_exit_time_by_security = _last_exit_time_by_security(
            security_ids, as_of_time, trade_journal_repository, provenance,
        )

    outcomes = []
    prices_by_security: dict[str, float] = {}
    for security_id in security_ids:
        current_price = _reference_price(view, security_id, as_of_time)
        if current_price is not None:
            prices_by_security[security_id] = current_price
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
            last_exit_time_by_security=last_exit_time_by_security,
            provenance=provenance, experiment_id=experiment_id,
        )
        if risk_repository is not None:
            risk_repository.record(risk_checked)

        current_quantity = portfolio.positions[security_id].quantity if security_id in portfolio.positions else 0.0
        validation = build_validated_order(
            risk_checked, current_quantity, configuration_version=session.config.configuration_version(),
        )
        submission: Optional[BrokerOrderResponse] = None
        if validation.validated_order is not None:
            submission, fills = session.submit(validation.validated_order, requested_at=as_of_time)
            if trade_journal_repository is not None:
                # Session 37 (ADR-0113): a real, joinable DecisionSnapshot
                # -- see module docstring's "Decision join" section for
                # why this is required, not optional, for real Paper
                # Trading experience to ever be usable by the Learning
                # Engine. `order=` is deliberately never set (see
                # docstring); `natural_key` makes this idempotent if
                # `run_cycle` is ever invoked twice for the same real
                # security/checkpoint/experiment.
                decision_snapshot = trade_journal_repository.record_decision(
                    decision_time=as_of_time, security_id=security_id, decision=decision.action,
                    natural_key=("paper_decision", experiment_id, security_id, as_of_time),
                    portfolio_state=portfolio, market_state={}, confidence=decision.confidence,
                    features=_decision_features(prediction, regime),
                    decision_reason=decision.decision_reason, model_version=decision.model_version,
                    strategy_version=decision.strategy_version or "unknown",
                    feature_version=decision.feature_version, data_version=decision.data_version,
                    execution_version=_EXECUTION_VERSION, provenance=provenance, experiment_id=experiment_id,
                )
                # Cumulative, not re-queried per fill: a partial fill's
                # own resulting position is exactly current_quantity plus
                # every signed fill quantity seen so far this order --
                # deriving it this way needs no extra broker/session
                # query and cannot be stale relative to what was just
                # submitted.
                running_quantity = current_quantity
                # Real realized_pnl/realized_return/holding_period for a
                # closing SELL, computed from real inputs already on hand
                # rather than left permanently None (ADR-0097's own
                # original gap -- see _position_opened_at's docstring).
                # `position_average_cost`/`opened_at` are both read ONCE,
                # from state as of the START of this cycle (before any of
                # this cycle's own fills are recorded) -- correct for
                # every fill in a single order's own fill sequence, since
                # a SELL sequence never reopens the position it is closing.
                # Session 37 (ADR-0115, external review N-16): read
                # DIRECTLY from `account.positions` (the raw
                # `BrokerPosition`, whose `average_cost` is genuinely
                # `Optional[float]`), never from `portfolio.positions`
                # (`_portfolio_view`'s own `PositionView.average_cost`,
                # which is a non-Optional `float` field and therefore
                # MUST fabricate `0.0` whenever the broker's own
                # average_cost is unknown -- that fallback is correct
                # for `_portfolio_view`'s other consumers, e.g. a
                # cost-basis-only market_value estimate, but reading it
                # back HERE silently turned "cost basis unknown" into
                # "cost basis is exactly zero," making every SELL's
                # realized_pnl the entire sale proceeds instead of the
                # honest `None` this project's fail-closed discipline
                # (and this module's own docstring) requires.
                account_position = account.positions.get(security_id)
                position_average_cost = (
                    account_position.average_cost
                    if account_position is not None and account_position.available
                    else None
                )
                opened_at = _position_opened_at(security_id, as_of_time, trade_journal_repository, provenance)
                # ADR-0154: this fill-writing arithmetic (signed running
                # quantity, realized_pnl/realized_return/holding_period)
                # is shared verbatim with the delayed-fill path
                # (`_record_delayed_advance_fills` below) via
                # `_record_fills_to_journal`, rather than duplicated --
                # behavior here is unchanged from before this refactor.
                _record_fills_to_journal(
                    trade_journal_repository, decision_snapshot, fills,
                    running_quantity=running_quantity, position_average_cost=position_average_cost,
                    opened_at=opened_at, provenance=provenance, experiment_id=experiment_id,
                )

        outcomes.append(CycleOutcome(
            security_id=security_id, prediction=prediction, regime=regime, decision=decision,
            sizing=sizing, risk_checked=risk_checked, validation=validation, submission=submission,
        ))

    # Always populated (Session 38, same "on by default" treatment
    # `trade_journal_repository` recording already got, ADR-0096) --
    # `session.adapter.accounting` is the one `PortfolioAccounting`
    # instance this cycle's fills were actually applied to, but nothing
    # previously called its own `mark_to_market` on it, so its
    # `value_series`/`turnover()` stayed permanently empty even after a
    # real multi-checkpoint run. Marking with this cycle's own
    # `prices_by_security` (the same per-security reference price every
    # other stage above already used, reused rather than re-derived)
    # makes both real for the first time, at zero extra network/DB cost
    # and no change to any of this function's own return values.
    _, mtm_missing = session.adapter.accounting.mark_to_market(prices_by_security, as_of_time)
    if mtm_missing and state is not None:
        state.mark_to_market_missing.append((as_of_time, tuple(mtm_missing)))

    return tuple(outcomes)
