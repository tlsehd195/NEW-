"""TossBrokerAdapter: the one `broker.protocol.BrokerAdapter`
implementation capable of a real order against a real Toss Securities
account.

See docs/specifications/PHASE-13-toss-securities-adapter.md sections 9,
"Toss API Verification".

Construction alone requires `BrokerConfig.execution_mode ==
BrokerExecutionMode.LIVE` (which itself requires `live_opt_in=True` --
`broker.config.BrokerConfig.__post_init__`) -- there is no way to build
a `TossBrokerAdapter` configured for `OFFLINE`/`SANDBOX` that silently
does nothing, and no way to reach `LIVE` by setting one value alone.
`submit_order` is the only operation this phase implements against a
*confirmed* endpoint (`broker.toss.endpoints.CREATE_ORDER_PATH`);
`cancel_order`/`get_order_status`/`get_account`/`get_positions` all
raise `broker.errors.BrokerCapabilityError` -- their real endpoint paths
could not be confirmed against official documentation from this
environment (network egress to developers.tossinvest.com/
openapi.tossinvest.com is blocked), and instruction section 6 is
explicit: an unconfirmed capability is `UNKNOWN`/`UNSUPPORTED`, never
guessed at.
"""

from __future__ import annotations

from datetime import datetime

from broker.capabilities import build_capabilities
from broker.config import BrokerConfig
from broker.enums import BrokerCapability, BrokerExecutionMode, CapabilityStatus
from broker.errors import BrokerCapabilityError
from broker.models import BrokerAccountSnapshot, BrokerCapabilities, BrokerOrderResponse, BrokerPosition, OrderStatusObservation, ValidatedOrder
from broker.transport import BrokerTransport
from broker.toss.auth import TossAuthClient, resolve_credentials
from broker.toss.endpoints import ACCOUNT_HEADER, CREATE_ORDER_PATH
from broker.toss.mapping import parse_order_response

from trade_journal.enums import TradeProvenance

_UNSUPPORTED_REASON = (
    "endpoint path not confirmed against Toss Securities' official documentation "
    "at implementation time -- see docs/specifications/PHASE-13-toss-securities-adapter.md "
    "'Toss API Verification'; not guessed"
)


class _IdAllocator:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._next_id = 1

    def allocate(self) -> str:
        value = f"{self._prefix}-{self._next_id:06d}"
        self._next_id += 1
        return value


class TossBrokerAdapter:
    def __init__(self, config: BrokerConfig, transport: BrokerTransport) -> None:
        if config.execution_mode != BrokerExecutionMode.LIVE:
            raise ValueError(
                "TossBrokerAdapter requires BrokerConfig.execution_mode == LIVE -- "
                "use broker.mock.MockBrokerAdapter for OFFLINE/SANDBOX"
            )
        self.broker_id = config.broker_id
        self._config = config
        self._transport = transport
        self._auth = TossAuthClient(transport, config)
        self._response_ids = _IdAllocator("BROKRESP")

    def _account_headers(self, access_token: str) -> dict[str, str]:
        credentials = resolve_credentials(self._config)
        return {"Authorization": f"Bearer {access_token}", ACCOUNT_HEADER: credentials.account_id}

    def submit_order(self, order: ValidatedOrder, *, requested_at: datetime) -> BrokerOrderResponse:
        access_token = self._auth.fetch_access_token()
        headers = self._account_headers(access_token)
        body = {
            "clientOrderId": order.client_order_id,
            "symbol": order.security_id,
            "side": order.side.value,
            "orderType": order.order_type.value,
            "quantity": str(order.quantity),
        }
        response = self._transport.post(CREATE_ORDER_PATH, headers=headers, json_body=body, timeout=self._config.timeout_seconds)
        return parse_order_response(
            response, response_id=self._response_ids.allocate(), client_order_id=order.client_order_id,
            broker_id=self.broker_id, operation="submit_order", attempt_count=1, responded_at=requested_at,
            provenance=TradeProvenance.LIVE_TRADING, experiment_id=order.experiment_id,
        )

    def cancel_order(self, client_order_id: str, *, requested_at: datetime) -> BrokerOrderResponse:
        raise BrokerCapabilityError(f"cancel_order is unsupported on TossBrokerAdapter: {_UNSUPPORTED_REASON}")

    def get_order_status(self, client_order_id: str, *, as_of: datetime) -> OrderStatusObservation:
        raise BrokerCapabilityError(f"get_order_status is unsupported on TossBrokerAdapter: {_UNSUPPORTED_REASON}")

    def get_account(self, *, as_of: datetime) -> BrokerAccountSnapshot:
        raise BrokerCapabilityError(f"get_account is unsupported on TossBrokerAdapter: {_UNSUPPORTED_REASON}")

    def get_positions(self, *, as_of: datetime) -> tuple[BrokerPosition, ...]:
        raise BrokerCapabilityError(f"get_positions is unsupported on TossBrokerAdapter: {_UNSUPPORTED_REASON}")

    def get_capabilities(self, *, as_of: datetime) -> BrokerCapabilities:
        return build_capabilities(
            self.broker_id,
            {
                BrokerCapability.MARKET_ORDER: CapabilityStatus.ENABLED,
                BrokerCapability.LIMIT_ORDER: CapabilityStatus.ENABLED,
                BrokerCapability.IDEMPOTENT_CLIENT_ORDER_ID: CapabilityStatus.ENABLED,
                BrokerCapability.CANCEL_ORDER: CapabilityStatus.UNKNOWN,
                BrokerCapability.ORDER_STATUS: CapabilityStatus.UNKNOWN,
                BrokerCapability.ACCOUNT_BALANCE: CapabilityStatus.UNKNOWN,
                BrokerCapability.POSITIONS: CapabilityStatus.UNKNOWN,
                BrokerCapability.QUOTE: CapabilityStatus.UNKNOWN,
            },
            recorded_at=as_of,
        )
