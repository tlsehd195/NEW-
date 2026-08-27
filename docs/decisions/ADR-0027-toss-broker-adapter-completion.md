# ADR-0027: Toss Broker Adapter Capability Completion

## Context

Phase 13 shipped `TossBrokerAdapter` with only `submit_order` implemented
against a confirmed endpoint; `cancel_order`/`get_order_status`/
`get_account`/`get_positions` all raised `BrokerCapabilityError` because
their endpoints could not be confirmed against official documentation
(network egress to Toss's domains was blocked from every prior
session's environment). Phase 20 changed that: the user provided the
full official Toss Securities Open API OpenAPI 3.1.0 specification
directly in-session, and Phase 20's own instruction explicitly deferred
implementation to a dedicated future phase rather than doing it inline
(`docs/operations/TOSS-API-GAP-ANALYSIS.md`'s "Phase 20 addendum").
Phase 21 is that phase.

**Source of truth for every endpoint/schema fact used below**: the
Tier 1 extraction already recorded in `TOSS-API-GAP-ANALYSIS.md`'s
Phase 20 addendum, itself read directly from the official spec in that
session. This phase did not guess or re-derive any endpoint, request
field, response field, or error code -- everything implemented traces
to that extraction.

## Decision 1 — implement all four capabilities in code

`cancel_order`, `get_order_status`, `get_account`, `get_positions` are
now implemented on `TossBrokerAdapter` (`src/broker/toss/adapter.py`),
each against its Tier 1 documented endpoint:

| Capability | Endpoint used | Why this one |
|---|---|---|
| `get_account` | `GET /api/v1/buying-power?currency=USD` | This system is US-equity-only (ADR-0025/ADR-0026) and reuses the exact same pre-configured `X-Tossinvest-Account` header pattern `submit_order` already established (Phase 13) -- no new account-discovery logic was added; `GET /api/v1/accounts` (account list/discovery) is Tier 1 documented but deliberately not wired up this phase, since the existing single-pre-configured-account model already serves this codebase's operating assumption. |
| `get_positions` | `GET /api/v1/holdings` | Direct mapping to `BrokerPosition` per item; `items: []` on success is a genuine empty-holdings result, never an error. |
| `get_order_status` | `GET /api/v1/orders/{orderId}` (single-order detail) | Not the list endpoint (`GET /api/v1/orders`) -- the `BrokerAdapter` Protocol's `get_order_status(client_order_id, ...)` needs exactly one order's status, and the detail endpoint returns a plain `Order` object with no array-wrapping ambiguity. See Decision 2 for how `client_order_id` resolves to the `orderId` this endpoint needs. |
| `cancel_order` | `POST /api/v1/orders/{orderId}/cancel` | See Decision 3 for the new-orderId-on-cancel semantics this endpoint's response carries. |

## Decision 2 — `client_order_id` -> Toss `orderId` resolution

Toss's `get_order_status`/`cancel_order` endpoints are keyed by Toss's
own `orderId`, not this system's `client_order_id`, and no documented
endpoint accepts a `clientOrderId` filter. `TossBrokerAdapter` now
keeps an in-process `dict[client_order_id, orderId]`, populated
whenever `submit_order` successfully learns a `orderId`
(`response.broker_order_id`), and consulted by both `get_order_status`
and `cancel_order`. This mirrors `broker.mock.MockBrokerAdapter`'s own
established pattern (`self._orders`/`self._status_history`) exactly --
not a new architecture, an application of the existing one.

**Known limitation, deliberately not solved this phase**: this map is
in-memory only. A process restart loses it -- an order submitted
through a prior `TossBrokerAdapter` instance cannot have its status
queried or be cancelled through a freshly constructed one until this is
rehydrated from a durable source. `broker_responses.broker_order_id` is
already persisted (`storage/broker_repository.py`, Phase 13, unchanged)
and would be the natural source for a future rehydration step,
mirroring how `PaperTradingSession.restore()` already does the
equivalent for Paper Trading (Phase 15) -- not built this phase, since
it was not explicitly requested and touches session/restart
orchestration beyond "complete the adapter's capability gap." Until
solved, `get_order_status`/`cancel_order` for an unmapped
`client_order_id` return an honest `UNKNOWN` outcome, never a guess or
a raised exception that would crash a caller like
`LiveTradingSession.reconcile_order` (which does not currently wrap
`get_order_status` in a `try/except`).

## Decision 3 — cancel's new-orderId semantics, preserved additively

Toss's cancel response (`OrderOperationResponse{orderId}`) returns a
**newly issued identifier for the cancel operation itself**, explicitly
documented as different from the original order's `orderId`. Overloading
`BrokerOrderResponse.broker_order_id` with this new id would have broken
its existing meaning everywhere else in the codebase (the id of the
order a response is about). Instead, `broker_order_id` on a
`cancel_order` response always stays the **original** order's id, and a
new, purely additive field, `BrokerOrderResponse.cancel_reference_id:
Optional[str] = None`, carries the new id -- `None` for every
pre-Phase-21 response and every non-cancel operation. No existing
caller of `BrokerOrderResponse` is affected (all construct it via
keyword arguments; verified before adding the field).

## Decision 4 — `BrokerOrderStatus` gains two values

The official spec's `Order.status` enum has 10 values, not the 8
`broker.enums.BrokerOrderStatus` originally modeled:
`CANCEL_REJECTED`/`REPLACE_REJECTED` are new (Toss represents a
rejected cancel/modify request as its own distinct terminal status, not
a no-op and not `REJECTED` on the original order). Both are added to
the enum and to `_CLOSED_STATUSES` (a rejected cancel/modify attempt is
a terminal outcome for that attempt). No existing code matches
exhaustively over every `BrokerOrderStatus` member (verified by
searching every use site before adding), so this is safe and additive.

## Decision 5 — `get_capabilities()` still reports `UNKNOWN`, not `ENABLED`

This is the most consequential decision in this ADR. `CapabilityStatus`
has exactly three values (`ENABLED`/`UNSUPPORTED`/`UNKNOWN`), and
`UNKNOWN`'s own definition is "capability exists per public research
but could not be independently verified end-to-end" -- which is
*exactly* this phase's outcome: the capability is documented (Tier 1)
and implemented (code), but never exercised against a real Toss
account, since no automated test in this repository may ever call the
real API. `get_capabilities()` therefore continues to report all four
as `UNKNOWN`, unchanged from Phase 13.

This is deliberate, not an oversight: flipping these to `ENABLED` would
silently change `evaluate_safety_gate`'s behavior -- any `SafetyGateContext`
requiring one of these capabilities would newly pass a condition it
previously failed, moving Live Trading measurably closer to activation
purely because code was written, with zero operational evidence it
works. `ENABLED` is reserved for a future phase's real, human-supervised
verification against an actual account -- see PRODUCTION READINESS
below.

## Consequences

- `tests/broker/toss/test_toss_adapter.py`'s `TestUnsupportedOperations`
  class (asserting all four raised `BrokerCapabilityError`) is now
  obsolete by design and was replaced with real behavioral tests
  (`TestGetAccount`/`TestGetPositions`/`TestGetOrderStatus`/
  `TestCancelOrder`) -- this is not a weakened test, it is the correct,
  intended consequence of implementing the capability the old test
  asserted didn't exist.
- `tests/broker/live/test_production_safety_cross_cutting.py`'s
  `test_order_status_unavailable_via_capability_gap_is_unknown_not_guessed`
  updated to assert the new (more correct) behavior: an unmapped
  `client_order_id` now returns an honest `UNKNOWN` observation rather
  than raising, which better satisfies the test's own name than the
  old raise-based behavior did.
- No change to `evaluate_safety_gate`, `LiveTradingConfig`,
  `LIVE_TRADING_ENABLED`, or any approval-generation logic. Live
  Trading remains exactly as blocked as before this phase, for the same
  reason (Toss capability status), even though the underlying adapter
  code is now far more complete.
