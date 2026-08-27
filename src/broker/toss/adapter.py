"""TossBrokerAdapter: the one `broker.protocol.BrokerAdapter`
implementation capable of a real order against a real Toss Securities
account.

See docs/specifications/PHASE-13-toss-securities-adapter.md sections 9,
"Toss API Verification", and docs/operations/TOSS-API-GAP-ANALYSIS.md's
Phase 20/21 addenda.

Construction alone requires `BrokerConfig.execution_mode ==
BrokerExecutionMode.LIVE` (which itself requires `live_opt_in=True` --
`broker.config.BrokerConfig.__post_init__`) -- there is no way to build
a `TossBrokerAdapter` configured for `OFFLINE`/`SANDBOX` that silently
does nothing, and no way to reach `LIVE` by setting one value alone.

**Phase 21**: all six `BrokerAdapter` Protocol methods are now
implemented against Tier 1 (official OpenAPI spec, provided by the user
directly in Phase 20) endpoints -- `submit_order` (Phase 13, unchanged)
plus `cancel_order`/`get_order_status`/`get_account`/`get_positions`
(new this phase). **This is code-complete, not operationally
verified**: no automated test in this repository ever calls the real
Toss API (instruction section 13/16/26), so `get_capabilities()`
deliberately still reports these four `CapabilityStatus.UNKNOWN`, not
`ENABLED` -- that status's own definition ("capability exists per
public research but could not be independently verified end-to-end",
`broker.enums.CapabilityStatus`) is exactly this situation. Flipping it
to `ENABLED` would silently pass `evaluate_safety_gate` for an endpoint
no one has ever actually called against a real account, which
instruction section 11 explicitly forbids. `ENABLED` is reserved for a
future phase's real, human-supervised operational verification.
"""

from __future__ import annotations

from datetime import datetime

from broker.capabilities import build_capabilities
from broker.config import BrokerConfig
from broker.enums import BrokerCapability, BrokerExecutionMode, BrokerOrderStatus, CapabilityStatus
from broker.models import BrokerAccountSnapshot, BrokerCapabilities, BrokerOrderResponse, BrokerPosition, OrderStatusObservation, ValidatedOrder
from broker.transport import BrokerTransport
from broker.toss.auth import TossAuthClient, resolve_credentials
from broker.toss.endpoints import (
    ACCOUNT_HEADER,
    BUYING_POWER_PATH,
    CANCEL_ORDER_PATH_TEMPLATE,
    CREATE_ORDER_PATH,
    HOLDINGS_PATH,
    ORDER_DETAIL_PATH_TEMPLATE,
)
from broker.toss.mapping import (
    parse_buying_power_response,
    parse_cancel_response,
    parse_holdings_response,
    parse_order_detail_response,
    parse_order_response,
)

from trade_journal.enums import TradeProvenance


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
        self._observation_ids = _IdAllocator("OSTAT")
        # client_order_id -> Toss's own orderId, populated whenever
        # submit_order successfully learns one (Phase 21). Toss's
        # get_order_status/cancel_order endpoints are keyed by their own
        # orderId, not our client_order_id, and no documented endpoint
        # accepts a clientOrderId filter -- this in-process map is the
        # only way to resolve one to the other.
        #
        # **Known limitation, deliberately not solved this phase**: this
        # map is in-memory only. A process restart loses it -- an order
        # submitted through a prior TossBrokerAdapter instance cannot
        # have its status queried or be cancelled through a freshly
        # constructed one until this is rehydrated from a durable source
        # (broker_responses.broker_order_id is already persisted,
        # storage/broker_repository.py -- a future phase could rebuild
        # this map from there on startup, mirroring how
        # PaperTradingSession.restore() already does the equivalent for
        # Paper, Phase 15). Until then, get_order_status/cancel_order for
        # an unmapped client_order_id honestly report UNKNOWN rather than
        # guessing -- never silently treated as "no such order."
        self._order_id_map: dict[str, str] = {}

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
        result = parse_order_response(
            response, response_id=self._response_ids.allocate(), client_order_id=order.client_order_id,
            broker_id=self.broker_id, operation="submit_order", attempt_count=1, responded_at=requested_at,
            provenance=TradeProvenance.LIVE_TRADING, experiment_id=order.experiment_id,
        )
        if result.broker_order_id is not None:
            self._order_id_map[order.client_order_id] = result.broker_order_id
        return result

    def cancel_order(self, client_order_id: str, *, requested_at: datetime) -> BrokerOrderResponse:
        broker_order_id = self._order_id_map.get(client_order_id)
        if broker_order_id is None:
            # Mirrors broker.mock.MockBrokerAdapter.cancel_order's own
            # "no order was ever submitted with this client_order_id"
            # branch -- honest UNKNOWN, never a blind retry against a
            # guessed orderId (instruction section 8, 9).
            return BrokerOrderResponse(
                response_id=self._response_ids.allocate(), request_client_order_id=client_order_id,
                broker_id=self.broker_id, operation="cancel_order", status=BrokerOrderStatus.UNKNOWN,
                broker_order_id=None, filled_quantity=None, avg_fill_price=None,
                error_code="unknown_client_order_id",
                error_message="no orderId is known for this client_order_id on this adapter instance "
                "(never submitted here, or submitted before a process restart)",
                attempt_count=1, latency_ms=None, responded_at=requested_at,
            )
        access_token = self._auth.fetch_access_token()
        headers = self._account_headers(access_token)
        path = CANCEL_ORDER_PATH_TEMPLATE.format(order_id=broker_order_id)
        response = self._transport.post(path, headers=headers, json_body={}, timeout=self._config.timeout_seconds)
        return parse_cancel_response(
            response, response_id=self._response_ids.allocate(), client_order_id=client_order_id,
            broker_id=self.broker_id, original_broker_order_id=broker_order_id, attempt_count=1,
            responded_at=requested_at,
        )

    def get_order_status(self, client_order_id: str, *, as_of: datetime) -> OrderStatusObservation:
        broker_order_id = self._order_id_map.get(client_order_id)
        if broker_order_id is None:
            return OrderStatusObservation(
                observation_id=self._observation_ids.allocate(), client_order_id=client_order_id,
                broker_id=self.broker_id, broker_order_id=None, status=BrokerOrderStatus.UNKNOWN,
                filled_quantity=None, avg_fill_price=None, observed_at=as_of, raw_status_code=None,
            )
        access_token = self._auth.fetch_access_token()
        headers = self._account_headers(access_token)
        path = ORDER_DETAIL_PATH_TEMPLATE.format(order_id=broker_order_id)
        response = self._transport.get(path, headers=headers, params={}, timeout=self._config.timeout_seconds)
        return parse_order_detail_response(
            response, observation_id=self._observation_ids.allocate(), client_order_id=client_order_id,
            broker_id=self.broker_id, observed_at=as_of,
        )

    def get_account(self, *, as_of: datetime) -> BrokerAccountSnapshot:
        access_token = self._auth.fetch_access_token()
        headers = self._account_headers(access_token)
        response = self._transport.get(
            BUYING_POWER_PATH, headers=headers, params={"currency": "USD"}, timeout=self._config.timeout_seconds,
        )
        return parse_buying_power_response(response, broker_id=self.broker_id, as_of_time=as_of)

    def get_positions(self, *, as_of: datetime) -> tuple[BrokerPosition, ...]:
        access_token = self._auth.fetch_access_token()
        headers = self._account_headers(access_token)
        response = self._transport.get(HOLDINGS_PATH, headers=headers, params={}, timeout=self._config.timeout_seconds)
        return parse_holdings_response(response, as_of_time=as_of)

    def get_capabilities(self, *, as_of: datetime) -> BrokerCapabilities:
        return build_capabilities(
            self.broker_id,
            {
                BrokerCapability.MARKET_ORDER: CapabilityStatus.ENABLED,
                BrokerCapability.LIMIT_ORDER: CapabilityStatus.ENABLED,
                BrokerCapability.IDEMPOTENT_CLIENT_ORDER_ID: CapabilityStatus.ENABLED,
                # Implemented in code this phase (Phase 21), against
                # Tier 1 documentation -- still UNKNOWN, not ENABLED,
                # because none of the four has been operationally
                # verified against a real Toss account (see this
                # module's docstring). Never promote these to ENABLED
                # without that verification actually happening.
                BrokerCapability.CANCEL_ORDER: CapabilityStatus.UNKNOWN,
                BrokerCapability.ORDER_STATUS: CapabilityStatus.UNKNOWN,
                BrokerCapability.ACCOUNT_BALANCE: CapabilityStatus.UNKNOWN,
                BrokerCapability.POSITIONS: CapabilityStatus.UNKNOWN,
                BrokerCapability.QUOTE: CapabilityStatus.UNKNOWN,
            },
            recorded_at=as_of,
        )
