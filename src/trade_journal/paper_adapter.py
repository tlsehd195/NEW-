"""orchestration.paper_runner -> Trade Journal bridge (Session 37, ADR-0086).

`trade_journal.backtest_adapter`'s own module docstring anticipated
exactly this module: "the rest of the package (models, repository,
analysis, experience) has no Phase-2-specific dependency, so a future
Paper/Live adapter can populate the same Journal without touching them."
Until this session, nothing had actually built that adapter --
`orchestration.paper_runner.run_cycle` produced real Fills through
`PaperTradingSession.submit` but never recorded a `DecisionSnapshot` or
`TradeRecord` for any of them, so `trade_journal.experience.
build_experience_records` (and therefore `learning.pipeline.
run_learning_pipeline`) had nothing real to ever read from Paper Trading
-- the Learning Engine's Experience/Retrain pipeline and the actual
Paper/Live orchestration existed as two fully-built, fully-tested, but
never-connected halves (see ADR-0086 for the full account).

Unlike `trade_journal.backtest_adapter.ingest_backtest_result` (one bulk
pass over an already-finished `BacktestResult`), `run_cycle` is called
once per checkpoint, streaming -- so the local `PortfolioAccounting`
replay `ingest_backtest_result` builds fresh each call is instead carried
forward across calls in `PaperJournalState`, the same "opt-in state a
caller carries across successive `run_cycle` calls" shape
`orchestration.paper_runner.PaperRunnerState` already uses for
`value_history`. `PortfolioAccounting` (from `backtest.portfolio`) is
reused verbatim -- it is a general ledger-replay utility, not
Backtest-specific, exactly as `backtest_adapter.py` already established.

`record_decision_and_trades` is called once per security per `run_cycle`
checkpoint -- it ALWAYS records a `DecisionSnapshot` (mirrors
`ingest_backtest_result` recording one "for every Order regardless of
status"), and a `TradeRecord` for every real Fill this checkpoint
actually produced (zero, one, or more -- a partial-fill sequence
produces one `TradeRecord` per partial leg, matching the natural-key
dedup `trade_journal.repository.record_trade` already relies on (its own
Phase 17 Production Safety Review fix, keyed on
`(experiment_id, fill.order_id, fill.execution_time)`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Sequence

from backtest.enums import OrderSide
from backtest.portfolio import PortfolioAccounting

from broker.models import OrderValidationResult
from broker.paper.models import PaperFillRecord

from decision.models import DecisionOutput

from trade_journal.enums import TradeProvenance
from trade_journal.models import DecisionSnapshot, TradeRecord
from trade_journal.repository import TradeJournalRepository

# Distinct from trade_journal.backtest_adapter.EXECUTION_VERSION -- this
# adapter runs a genuinely different code path (real PaperTradingSession
# fills, not a replayed BacktestResult), so the two must never be
# confused when read back later.
EXECUTION_VERSION = "orchestration_paper_runner_v1"


@dataclass
class PaperJournalState:
    """Carries the local `PortfolioAccounting` replay + open-position
    timestamps a streaming Paper `run_cycle` loop needs to compute
    `realized_pnl`/`realized_return`/`holding_period` for its own Trade
    Journal records -- mirrors `trade_journal.backtest_adapter.
    ingest_backtest_result`'s own local replay exactly, just kept alive
    across many `run_cycle` calls instead of rebuilt for one bulk pass
    over an already-finished `BacktestResult`, since Paper has no such
    finished result to replay after the fact. A fresh
    `PaperJournalState()` is correct for a brand-new Paper session; this
    object never fabricates or backfills history for a resumed one --
    the same limitation `PaperRunnerState.value_history` already
    documents for the same reason (ADR-0068)."""

    accounting: PortfolioAccounting = field(default_factory=lambda: PortfolioAccounting(0.0))
    position_opened_at: dict = field(default_factory=dict)


def record_decision_and_trades(
    journal: TradeJournalRepository,
    state: PaperJournalState,
    *,
    security_id: str,
    as_of_time: datetime,
    decision: DecisionOutput,
    validation: OrderValidationResult,
    fills: Sequence[PaperFillRecord],
    portfolio_state,
    strategy_version: str,
    provenance: TradeProvenance,
    experiment_id: Optional[str],
) -> tuple[DecisionSnapshot, tuple[TradeRecord, ...]]:
    """Records exactly one `DecisionSnapshot` (regardless of whether a
    trade resulted -- HOLD/EXIT/NO_TRADE/a risk-REJECTED BUY all still
    produce one, matching `ingest_backtest_result`'s "for every Order
    regardless of status" precedent) and one `TradeRecord` per real fill
    in `fills` (0 for a HOLD/no-fill cycle, 1 for an ordinary fill, more
    than 1 for a partial-fill sequence spread across checkpoints).

    `DecisionSnapshot.order` is deliberately left `None` here, always --
    it is typed for `backtest.orders.Order` (Phase 2's shape,
    `order.order_id`), and `broker.validation.build_validated_order`
    produces the structurally different `broker.models.ValidatedOrder`
    (`client_order_id`, no `order_id`) -- passing one through as the
    other broke both `TradeJournalRepository.record_decision`'s own
    natural-key derivation and `storage.serialization.
    decision_snapshot_to_payload` identically (both read `order.
    order_id`), caught by this module's own tests before this ever
    reached a real caller. A `natural_key` is supplied explicitly
    instead, so idempotent dedup (calling this twice for the same
    security/checkpoint) still works without that field.
    """
    decision_snapshot = journal.record_decision(
        decision_time=as_of_time,
        security_id=security_id,
        decision=decision.action,
        natural_key=("paper_decision", experiment_id, security_id, as_of_time),
        portfolio_state=portfolio_state,
        market_state={},
        confidence=decision.confidence,
        decision_reason=decision.decision_reason,
        model_version=decision.model_version,
        strategy_version=strategy_version,
        feature_version=decision.feature_version,
        data_version=decision.data_version,
        execution_version=EXECUTION_VERSION,
        provenance=provenance,
        experiment_id=experiment_id,
    )

    trades: list[TradeRecord] = []
    for fill_record in fills:
        fill = fill_record.fill

        prior_position = state.accounting.positions.get(fill.security_id)
        prior_quantity = prior_position.quantity if prior_position is not None else 0.0
        if fill.side == OrderSide.BUY and prior_quantity == 0:
            state.position_opened_at[fill.security_id] = fill.execution_time

        state.accounting.apply_fill(fill)

        current_position = state.accounting.positions.get(fill.security_id)
        position_after = current_position.quantity if current_position is not None else 0.0

        realized_pnl: Optional[float] = None
        realized_return: Optional[float] = None
        holding_period = None
        if fill.side == OrderSide.SELL:
            closed = state.accounting.closed_trades[-1]  # the entry apply_fill() just appended
            realized_pnl = closed.realized_pnl
            cost_basis = closed.average_cost * closed.quantity
            realized_return = (realized_pnl / cost_basis) if cost_basis else None
            opened_at = state.position_opened_at.get(fill.security_id)
            holding_period = (fill.execution_time - opened_at) if opened_at is not None else None
            if position_after == 0:
                state.position_opened_at.pop(fill.security_id, None)

        trade = journal.record_trade(
            decision_id=decision_snapshot.snapshot_id,
            fill=fill,
            position_after=position_after,
            experiment_id=experiment_id,
            realized_pnl=realized_pnl,
            realized_return=realized_return,
            holding_period=holding_period,
            provenance=provenance,
        )
        trades.append(trade)

    return decision_snapshot, tuple(trades)


def reconstruct_journal_state(
    journal: TradeJournalRepository, *, provenance: TradeProvenance = TradeProvenance.PAPER_TRADING,
) -> PaperJournalState:
    """Rebuilds a `PaperJournalState`'s local `PortfolioAccounting`
    replay + `position_opened_at` map from every real `TradeRecord`
    this journal already has for `provenance`, in chronological order --
    the same replay `record_decision_and_trades` performs
    incrementally, run once as a bulk pass so a resumed run (mirroring
    `--resume`'s own `_reconstruct_value_history` precedent in
    `scripts/run_paper_trading_cycle.py`, ADR-0073) picks up with a
    real, not fabricated, replay state rather than restarting the local
    ledger from empty and silently mis-computing every subsequent
    `realized_pnl`/`holding_period`."""
    state = PaperJournalState()
    for trade in sorted(journal.list_trades(provenance=provenance), key=lambda t: t.timestamp):
        fill = trade.fill
        prior_position = state.accounting.positions.get(fill.security_id)
        prior_quantity = prior_position.quantity if prior_position is not None else 0.0
        if fill.side == OrderSide.BUY and prior_quantity == 0:
            state.position_opened_at[fill.security_id] = fill.execution_time

        state.accounting.apply_fill(fill)

        current_position = state.accounting.positions.get(fill.security_id)
        position_after = current_position.quantity if current_position is not None else 0.0
        if fill.side == OrderSide.SELL and position_after == 0:
            state.position_opened_at.pop(fill.security_id, None)
    return state
