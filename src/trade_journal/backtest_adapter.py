"""Phase 2 integration: BacktestResult -> Trade Journal.

See docs/specifications/PHASE-3-trade-journal.md section 13.

This is the only module in trade_journal that imports from
backtest.engine — the rest of the package (models, repository, analysis,
experience) has no Phase-2-specific dependency, so a future Paper/Live
adapter can populate the same Journal without touching them (Phase 3
spec section 3.1).

Does not modify BacktestEngine, BacktestResult, or any other Phase 2
type — read-only with respect to Phase 2's outputs (ADR-0009).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backtest.engine import BacktestConfig, BacktestResult
from backtest.enums import OrderSide
from backtest.portfolio import PortfolioAccounting

from trade_journal.enums import DecisionAction, TradeProvenance
from trade_journal.repository import TradeJournalRepository

EXECUTION_VERSION = "phase2_backtest_engine_v1"


@dataclass(frozen=True)
class IngestSummary:
    decisions_recorded: int
    trades_recorded: int
    experiment_id: Optional[str]


def ingest_backtest_result(
    journal: TradeJournalRepository,
    result: BacktestResult,
    config: BacktestConfig,
    *,
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
    experiment_id: Optional[str] = None,
) -> IngestSummary:
    """Walks result.orders and result.fills, in their original
    (chronological) order, recording a DecisionSnapshot for every Order
    regardless of status, and a TradeRecord for every Fill (Phase 3 spec
    section 12). Idempotent: calling this twice with the same result and
    experiment_id records no new entries the second time (natural-key
    dedup in the repository, Phase 3 spec section 8).

    KNOWN LIMITATIONS (Phase 3 spec section 13.2-13.3, ADR-0009):
    - DecisionSnapshot.data_version is left None — BacktestResult does
      not expose per-decision data versions, only a run-level aggregate
      (result.experiment.data_version).
    - portfolio_state is reconstructed by replaying fills through a
      fresh PortfolioAccounting; this is exact with respect to fills but
      does not reflect corporate-action-driven cash/quantity changes
      that occurred inside the original BacktestEngine run between
      fills, since those events are not exposed on BacktestResult.
    - DecisionSnapshot.market_state is left {} — Phase 2's Order does not
      retain the decision-time reference price it was validated against.
    """
    exp_id = experiment_id or result.experiment.experiment_id
    strategy_version = result.experiment.strategy_version

    decisions_before = len(journal.list_decisions())
    trades_before = len(journal.list_trades())

    fills_by_order_id = {fill.order_id: fill for fill in result.fills}

    portfolio = PortfolioAccounting(config.initial_capital)
    position_opened_at: dict[str, object] = {}

    for order in result.orders:
        decision_action = DecisionAction(order.side.value)  # BUY or SELL — Phase 2 never emits HOLD/EXIT/NO_TRADE

        decision = journal.record_decision(
            decision_time=order.decision_time,
            security_id=order.security_id,
            decision=decision_action,
            order=order,
            portfolio_state=portfolio.snapshot_view(order.decision_time),
            market_state={},
            strategy_version=strategy_version,
            execution_version=EXECUTION_VERSION,
            provenance=provenance,
            experiment_id=exp_id,
            data_version=None,  # documented limitation — see docstring
        )

        fill = fills_by_order_id.get(order.order_id)
        if fill is None:
            continue  # REJECTED / NOT_EXECUTED / CANCELLED — decision recorded, no trade

        prior_position = portfolio.positions.get(fill.security_id)
        prior_quantity = prior_position.quantity if prior_position is not None else 0.0
        if fill.side == OrderSide.BUY and prior_quantity == 0:
            position_opened_at[fill.security_id] = fill.execution_time

        portfolio.apply_fill(fill)

        current_position = portfolio.positions.get(fill.security_id)
        position_after = current_position.quantity if current_position is not None else 0.0

        realized_pnl = None
        realized_return = None
        holding_period = None
        if fill.side == OrderSide.SELL:
            closed = portfolio.closed_trades[-1]  # the entry apply_fill() just appended
            realized_pnl = closed.realized_pnl
            cost_basis = closed.average_cost * closed.quantity
            realized_return = (realized_pnl / cost_basis) if cost_basis else None
            opened_at = position_opened_at.get(fill.security_id)
            holding_period = (fill.execution_time - opened_at) if opened_at is not None else None
            if position_after == 0:
                position_opened_at.pop(fill.security_id, None)

        journal.record_trade(
            decision_id=decision.snapshot_id,
            fill=fill,
            position_after=position_after,
            experiment_id=exp_id,
            realized_pnl=realized_pnl,
            realized_return=realized_return,
            holding_period=holding_period,
            provenance=provenance,
        )

    return IngestSummary(
        decisions_recorded=len(journal.list_decisions()) - decisions_before,
        trades_recorded=len(journal.list_trades()) - trades_before,
        experiment_id=exp_id,
    )
