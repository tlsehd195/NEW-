"""build_trade_record: bridges a Live Trading fill into
`trade_journal.models.TradeRecord` (Phase 3) directly -- the same type
`broker.paper.journal.build_trade_record` (Phase 15) already bridges
into, reused unchanged rather than a parallel Live-only journal
representation (instruction section 24: "Phase 3 Trade Journal을
수정하지 않고 가능한 경우 재사용한다"). `provenance` is always
`TradeProvenance.LIVE_TRADING`
(`PROJECT_MASTER_PLAN.md` section 10.7/25).

**Known limitation, documented rather than silently fabricated**: Toss's
confirmed order-response schema (ADR-0019) gives `filled_quantity`/
`avg_fill_price` only -- no independent reference price, spread, or
slippage decomposition (`BrokerCapability.QUOTE` is itself `UNKNOWN`/
`UNSUPPORTED` on every adapter in this codebase). `reference_price` is
therefore set equal to `price` (arithmetically zero measured slippage)
-- not because there is no real slippage, but because this system has
no independently-sourced quote to compare against. `commission`
defaults to `0.0` unless the broker response itself supplies one, for
the same reason.

See docs/specifications/PHASE-16-live-trading.md section 10.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from broker.enums import BrokerOrderStatus
from broker.models import BrokerOrderResponse

from backtest.enums import OrderSide
from backtest.fills import Fill

from trade_journal.enums import TradeProvenance
from trade_journal.models import TradeRecord


def build_fill_from_broker_response(
    response: BrokerOrderResponse, *, security_id: str, side: OrderSide, decision_time: datetime,
    commission: float = 0.0,
) -> Fill:
    """Requires `response.status` to already be a terminal, filled state
    (`FILLED`/`PARTIAL_FILLED`) -- raises otherwise, since a `Fill`
    cannot honestly represent an order that never filled."""
    if response.status not in (BrokerOrderStatus.FILLED, BrokerOrderStatus.PARTIAL_FILLED):
        raise ValueError(f"cannot build a Fill from a non-filled BrokerOrderResponse (status={response.status!r})")
    if response.filled_quantity is None or response.avg_fill_price is None:
        raise ValueError("BrokerOrderResponse.filled_quantity/avg_fill_price must be present for a filled order")
    price = response.avg_fill_price
    return Fill(
        order_id=response.request_client_order_id, security_id=security_id, side=side,
        quantity=response.filled_quantity, reference_price=price, price=price, commission=commission,
        spread_cost=0.0, slippage_cost=0.0, decision_time=decision_time, execution_time=response.responded_at,
        data_version=f"toss_response_{response.response_id}",
    )


def build_trade_record(
    fill: Fill, *, trade_id: str, decision_id: str, position_after: float,
    realized_pnl: Optional[float] = None, realized_return: Optional[float] = None,
    exit_reason: Optional[str] = None, experiment_id: Optional[str] = None,
) -> TradeRecord:
    return TradeRecord(
        trade_id=trade_id, decision_id=decision_id, order_id=fill.order_id, security_id=fill.security_id,
        timestamp=fill.execution_time, side=fill.side, quantity=fill.quantity, execution_price=fill.price,
        reference_price=fill.reference_price, slippage=fill.slippage_cost,
        transaction_cost=fill.commission + fill.spread_cost, position_after=position_after, fill=fill,
        realized_pnl=realized_pnl, realized_return=realized_return, exit_reason=exit_reason,
        provenance=TradeProvenance.LIVE_TRADING, experiment_id=experiment_id,
    )
