"""build_trade_record: bridges a Paper Trading `PaperFillRecord` into
`trade_journal.models.TradeRecord` -- the *same* type Phase 3 already
defined and Phase 2's `backtest.fills.Fill` already nests
(`TradeRecord.fill: Fill`), reused unchanged rather than inventing a
parallel Paper-only journal representation (instruction section 23:
"Paper Trading이라고 해서 별도의 독립적인 journal 체계를 만들지
않는다"). `provenance` must always be `TradeProvenance.PAPER_TRADING`
for a Paper Trading fill -- `PROJECT_MASTER_PLAN.md` section 10.7's
"Historical vs Live 구분(provenance)은 필수다."

See docs/specifications/PHASE-15-paper-trading.md section 15.
"""

from __future__ import annotations

from typing import Optional

from broker.paper.models import PaperFillRecord

from trade_journal.enums import TradeProvenance
from trade_journal.models import TradeRecord


def build_trade_record(
    fill_record: PaperFillRecord,
    *,
    trade_id: str,
    decision_id: str,
    position_after: float,
    realized_pnl: Optional[float] = None,
    realized_return: Optional[float] = None,
    experiment_id: Optional[str] = None,
) -> TradeRecord:
    """`decision_id`/`position_after`/`realized_pnl` are caller-supplied
    (never re-derived here) -- `decision_id` is already on the
    `ValidatedOrder` that produced this fill's originating order
    (`PaperOrderRecord.validated_order.decision_id`), and
    `position_after`/`realized_pnl` require the account state at the
    moment this fill was applied, which this module deliberately does
    not hold (no side-effecting account access -- a pure bridge
    function only)."""
    fill = fill_record.fill
    return TradeRecord(
        trade_id=trade_id, decision_id=decision_id, order_id=fill_record.client_order_id,
        security_id=fill.security_id, timestamp=fill.execution_time, side=fill.side, quantity=fill.quantity,
        execution_price=fill.price, reference_price=fill.reference_price, slippage=fill.slippage_cost,
        transaction_cost=fill.commission + fill.spread_cost, position_after=position_after, fill=fill,
        realized_pnl=realized_pnl, realized_return=realized_return,
        provenance=TradeProvenance.PAPER_TRADING, experiment_id=experiment_id,
    )
