"""BrokerAdapter Protocol: PROJECT_MASTER_PLAN.md section 9.3's neutral
Broker Interface -- `place_order, cancel_order, get_position, get_cash,
get_order_status` -- named and shaped to match this codebase's existing
Order/lineage vocabulary (`submit_order` over a `ValidatedOrder`, a
single `get_positions()` covering both cash and holdings via
`get_account()`/`get_positions()`, matching instruction section 7's
"Account / balance / position read abstraction").

See docs/specifications/PHASE-13-toss-securities-adapter.md section 8.

Every implementation (`broker.mock.MockBrokerAdapter`,
`broker.toss.adapter.TossBrokerAdapter`) is interchangeable behind this
Protocol -- PROJECT_MASTER_PLAN.md section 9.3: "Toss Adapter 대신
Paper Broker Adapter로 즉시 교체 가능해야 한다."
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from broker.models import BrokerAccountSnapshot, BrokerCapabilities, BrokerOrderResponse, BrokerPosition, OrderStatusObservation, ValidatedOrder


class BrokerAdapter(Protocol):
    broker_id: str

    def submit_order(self, order: ValidatedOrder, *, requested_at: datetime) -> BrokerOrderResponse: ...
    def cancel_order(self, client_order_id: str, *, requested_at: datetime) -> BrokerOrderResponse: ...
    def get_order_status(self, client_order_id: str, *, as_of: datetime) -> OrderStatusObservation: ...
    def get_account(self, *, as_of: datetime) -> BrokerAccountSnapshot: ...
    def get_positions(self, *, as_of: datetime) -> tuple[BrokerPosition, ...]: ...
    def get_capabilities(self, *, as_of: datetime) -> BrokerCapabilities: ...
