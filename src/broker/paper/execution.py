"""simulate_fill: the one function in `broker.paper.*` that turns a
reference bar into an actual fill. Re-derives
`backtest.fills.FillSimulator.execute`'s exact math (spread, then
slippage, against the execution bar's own close, capped by
`max_participation` of that bar's volume) rather than calling
`FillSimulator` itself, because `FillSimulator` is coupled to
`backtest.orders.Order`/`backtest.portfolio.PortfolioView` -- types
Paper Trading does not use (a `ValidatedOrder` plus a plain remaining-
quantity float is enough context here). The cost/slippage *models*
(`backtest.costs.TransactionCostModel`/`SlippageModel`) and the
resulting `backtest.fills.Fill` type are reused unchanged (instruction
section 4/28).

Deliberately never reaches for market data itself -- `bar` is always
supplied by the caller (`broker.paper.adapter.PaperBrokerAdapter`,
itself fed by a caller-supplied `PaperMarketDataSource`).

See docs/specifications/PHASE-15-paper-trading.md section 8.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

from data_infra.models import PriceBar

from backtest.costs import SlippageModel, TransactionCostModel
from backtest.enums import OrderSide
from backtest.fills import Fill


def simulate_fill(
    *,
    order_id: str,
    security_id: str,
    side: OrderSide,
    remaining_quantity: float,
    bar: PriceBar,
    cost_model: TransactionCostModel,
    slippage_model: SlippageModel,
    max_participation: float,
    partial_fill_enabled: bool,
    decision_time: datetime,
    execution_time: datetime,
) -> Optional[Fill]:
    """`None` when nothing can be filled this attempt (no liquidity) --
    never a zero-quantity `Fill`."""
    if remaining_quantity <= 0:
        return None

    max_fillable = math.floor(bar.volume * max_participation)
    if max_fillable <= 0:
        return None

    fill_quantity = remaining_quantity if not partial_fill_enabled else min(remaining_quantity, max_fillable)
    if not partial_fill_enabled and remaining_quantity > max_fillable:
        # Partial fill disabled: an order that cannot be filled in full
        # against this bar's liquidity fills nothing at all this attempt
        # (fail-closed -- never silently fills only part of an order the
        # config says should be all-or-nothing).
        return None
    if fill_quantity <= 0:
        return None

    reference_price = bar.close
    price_after_spread = cost_model.apply_spread(reference_price, side)
    price_after_slippage = slippage_model.adjust(price_after_spread, fill_quantity, side, bar.volume)
    commission = cost_model.commission(fill_quantity)
    spread_cost = abs(price_after_spread - reference_price) * fill_quantity
    slippage_cost = abs(price_after_slippage - price_after_spread) * fill_quantity

    return Fill(
        order_id=order_id, security_id=security_id, side=side, quantity=fill_quantity,
        reference_price=reference_price, price=price_after_slippage, commission=commission,
        spread_cost=spread_cost, slippage_cost=slippage_cost, decision_time=decision_time,
        execution_time=execution_time, data_version=bar.provenance.data_version,
    )
