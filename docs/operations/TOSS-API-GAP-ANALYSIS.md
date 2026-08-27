# Toss Securities Open API -- Adapter Gap Analysis

Phase 17 Production Safety Review, Section 6. This document exists to
answer one question honestly, per capability: **is this safe to mark
`CapabilityStatus.ENABLED` on `TossBrokerAdapter` today, or not?**

**Status as of Phase 21: all four capabilities are now implemented in
code (see "Phase 21 addendum" below), against the Tier 1 schema Phase
20 extracted -- but `TossBrokerAdapter.get_capabilities()` still
reports `CapabilityStatus.UNKNOWN` for all four, deliberately.**
`UNKNOWN`'s own definition ("capability exists per public research but
could not be independently verified end-to-end") is exactly this
situation: implemented, never operationally verified against a real
account. `evaluate_safety_gate` therefore still structurally blocks any
Live submission that requires one of them, completely unchanged from
Phase 13/20 (`tests/broker/live/test_live_safety_gate.py::
TestRealTossCapabilitiesStructurallyBlockLiveTrading`). See ADR-0027
for the full implementation record and why `ENABLED` was not set.

**Phase 20's original text (superseded by Phase 21, kept for history):**
"the official document now exists and has been read... but no code
change has been made yet... Implementing against the now-confirmed
schema is deliberately deferred to a dedicated next phase... per the
process this project itself established in Phase 19 section 19." That
next phase is Phase 21, below.

**Phase 18 addendum**: no new Toss API research was attempted this
phase -- the official documentation hosts remain unreachable from this
environment (unchanged since Phase 17), and Phase 18's own instruction
explicitly forbids guessing an endpoint without official confirmation.
This document's findings are otherwise unchanged. Phase 18 did fix a
related, previously-mismapped response-handling bug: a Toss `5xx`
response was mapped to a definitive `REJECTED` instead of `UNKNOWN`
(Phase 17, ADR-0023); Phase 18 re-verified this fix end to end through
the real `TossBrokerAdapter` + `LiveTradingSession`, not just the
isolated mapping function (`tests/broker/live/
test_live_partial_fill_and_5xx_regression.py`).

**Phase 19 addendum**: Phase 19's explicit first task was to determine
whether reliable access to Toss's official API documentation had
become available in this environment. It has not. Direct fetch
attempts against four distinct `tossinvest.com` subdomains all
returned `EGRESS_BLOCKED` this session: `openapi.tossinvest.com`
(the OpenAPI spec host), `developers.tossinvest.com` (the docs host,
both previously tested in Phase 13/17), and, newly tested this phase,
`home.tossinvest.com` and `corp.tossinvest.com` (the public marketing/
corporate pages, found via a fresh web search). All four are blocked,
confirming this is a domain-wide network restriction, not a
path-specific one -- there is no unblocked corner of `tossinvest.com`
this environment can reach. A web search this session surfaced no new
official source; the same third-party leads already recorded (Tier 2,
`BEOKS/tossinvest-skill`) reappeared, unchanged, and were not
re-promoted. **No capability status was changed this phase.**
`ACCOUNT_BALANCE`/`POSITIONS`/`ORDER_STATUS`/`CANCEL_ORDER` remain
`CapabilityStatus.UNKNOWN`. This is classified CASE C (BLOCKED by an
external dependency -- network access this environment does not
control) in `docs/PROJECT_STATUS.md`'s Phase 19 entry, not a task this
session could resolve by working harder at it.

**Phase 20 addendum -- Tier 1 evidence obtained.** Mid-session, the
user provided the full official Toss Securities Open API OpenAPI 3.1.0
specification (title "토스증권 Open API", version "1.2.14",
`servers: [https://openapi.tossinvest.com]`) directly in conversation
-- this is the primary-source document Phase 13/17/18/19 could never
reach through this environment's blocked network egress. It is
reproduced in full in this session's transcript; a placeholder at
`docs/operations/reference/toss-openapi-spec-v1.2.14.json` records
where to find it and notes it was not mechanically re-serialized into
that file (an ~80KB hand-pasted JSON document was extracted by direct
reading instead, to avoid transcription risk on a document this size
and this safety-relevant). Every fact below was read directly from
that document, not inferred or guessed.

**Extracted, per previously-UNKNOWN capability (all four now Tier 1):**

| Capability | Endpoint(s) | Auth | Key request fields | Key response fields | Notes |
|---|---|---|---|---|---|
| ACCOUNT_BALANCE | `GET /api/v1/accounts` (account list, no `X-Tossinvest-Account` needed); `GET /api/v1/buying-power?currency=KRW\|USD` (cash) | Bearer only for `/accounts`; Bearer + `X-Tossinvest-Account` for `/buying-power` | none / `currency` query param | `Account{accountNo, accountSeq, accountType}`; `BuyingPowerResponse{currency, cashBuyingPower}` | `accountSeq` from `/accounts` is the header value every other account-scoped call needs -- the true entry-point call. `accountType` currently only ever returns `"BROKERAGE"`. No single "get account snapshot" endpoint exists; a full picture requires composing `/accounts` + `/buying-power` + `/holdings`. |
| POSITIONS | `GET /api/v1/holdings` (optional `symbol` filter) | Bearer + `X-Tossinvest-Account` | optional `symbol` | `HoldingsOverview{totalPurchaseAmount, marketValue, profitLoss, dailyProfitLoss, items[]}`; each item: `symbol, name, marketCountry, currency, quantity, lastPrice, averagePurchasePrice, marketValue, profitLoss, dailyProfitLoss, cost{commission, tax}` | Rich schema -- quantity, average cost, and market value all present directly, no extra computation needed. Empty holdings return `items: []` with all summary amounts `"0"`, not an error. |
| ORDER_STATUS | `GET /api/v1/orders?status=OPEN\|CLOSED&symbol=&from=&to=&cursor=&limit=` (list); `GET /api/v1/orders/{orderId}` (single-order detail -- this specific variant was **never found at any evidence tier before now**, including Phase 13's original Tier 2 research) | Bearer + `X-Tossinvest-Account` | `status` required; symbol/date-range/pagination optional | `Order{orderId, symbol, side, orderType, timeInForce, status, price, quantity, orderAmount, currency, orderedAt, canceledAt, execution{filledQuantity, averageFilledPrice, filledAmount, commission, tax, filledAt, settlementDate}}` | **The official `status` vocabulary is `PENDING / PENDING_CANCEL / PENDING_REPLACE / PARTIAL_FILLED / FILLED / CANCELED / REJECTED / CANCEL_REJECTED / REPLACE_REJECTED / REPLACED`** -- ten values, not the eight `broker.enums.BrokerOrderStatus` currently defines. `CANCEL_REJECTED`/`REPLACE_REJECTED` do not exist in this codebase's enum at all today; they represent "a cancel/modify request was itself rejected, recorded as its own separate order entry" -- a materially different concept `map_order_status` has never had to handle. |
| CANCEL_ORDER | `POST /api/v1/orders/{orderId}/cancel` (previously: **no lead found at any tier**, including the Tier 2 mirror) | Bearer + `X-Tossinvest-Account` | empty/optional body | `OrderOperationResponse{orderId}` | **Critical, non-obvious detail: the response `orderId` is a newly-issued identifier for the cancel operation itself, explicitly documented as different from the original order's `orderId`** ("정정/취소로 새로 발급된 주문 식별자. 원주문의 orderId와 다릅니다"). A naive implementation that assumed the original id persists through cancellation would misattribute this correlation. Errors are richly enumerated: 404 `order-not-found`, 409 `already-filled`/`already-canceled`/`already-modified`/`already-rejected`/`already-processing` (with `retryAfterSeconds`), 422 `cancel-restricted`/`order-hours-closed`. |

**Also newly confirmed, not previously anywhere in this project's
capability model:** `POST /api/v1/orders/{orderId}/modify` (order
modification -- KR: price+quantity, US: price only, same
"new-id-on-success" semantics as cancel); conditional orders (`POST`/
`GET`/`DELETE /api/v1/conditional-orders*` -- SINGLE/OCO/OTO
stop-trigger orders, an entire capability category this project has
never modeled at all); `GET /api/v1/sellable-quantity`; `GET
/api/v1/commissions`; and a large Market Data / Stock Info / Market
Indicators / Ranking / exchange-rate / market-calendar surface
unrelated to the four previously-blocking capabilities.

**One correction to a Phase 17 finding**: Phase 17's web research
(Tier 2, from a secondary source) found a token TTL of 3600 seconds.
The official spec's own example shows `"expires_in": 86400` (24
hours) for `POST /oauth2/token`. The Tier 1 document supersedes the
Tier 2 figure -- Phase 17's number was simply wrong, not merely
approximate. Also newly confirmed: only one valid access token exists
per client at a time -- requesting a new one immediately invalidates
whichever token was previously issued ("client 당 유효한 access token은
1개입니다. 재발급 시 이전에 발급된 token은 즉시 무효화됩니다"), a
constraint `TossAuthClient` does not currently need to handle (it
never caches/reuses a token across calls) but a future
continuously-running Live process would need to respect.

**What Phase 20 deliberately did NOT do** (historical, all now done in
Phase 21 -- see below): change `src/broker/toss/endpoints.py`'s `None`
paths, implement `get_account`/`get_positions`/`get_order_status`/
`cancel_order` on `TossBrokerAdapter`, change any `CapabilityStatus`
from `UNKNOWN`, or touch `broker.enums.BrokerOrderStatus`. Phase 20's
own scope was market data provider research, not Toss integration, and
the process this project established in Phase 19 (section 19) was
explicit: read the official document, compare it against the existing
adapter, and propose the resulting implementation work as its own
dedicated next phase -- not implement inline the moment a document
arrives.

**Phase 21 addendum -- all four capabilities implemented in code.**
Following the plan Phase 20 proposed, Phase 21 implemented
`cancel_order`/`get_order_status`/`get_account`/`get_positions` on
`TossBrokerAdapter` against exactly the Tier 1 endpoint/schema facts
extracted above -- no new guessing, no new evidence tier introduced.
Summary (full detail in `docs/decisions/ADR-0027-toss-broker-adapter-completion.md`):

- `get_account` calls `GET /api/v1/buying-power?currency=USD`, reusing
  the same pre-configured `X-Tossinvest-Account` header
  `submit_order` already used since Phase 13 -- no new
  account-discovery logic was added.
- `get_positions` calls `GET /api/v1/holdings`; `items: []` on success
  is a genuine empty result, never an error; a malformed item causes
  the whole call to raise rather than silently returning a partial
  position list.
- `get_order_status` calls `GET /api/v1/orders/{orderId}` (the
  single-order-detail variant, not the list endpoint), resolving
  `client_order_id -> orderId` via an in-process map populated at
  `submit_order` time (mirrors `broker.mock.MockBrokerAdapter`'s own
  pattern). **Known limitation**: this map is in-memory only and does
  not survive a process restart -- see ADR-0027 decision 2.
- `cancel_order` calls `POST /api/v1/orders/{orderId}/cancel` and
  correctly preserves the new-orderId-on-cancel semantics: the
  original order's id stays in `broker_order_id`, and Toss's newly
  issued cancel-operation id is carried in a new, additive
  `BrokerOrderResponse.cancel_reference_id` field (ADR-0027 decision
  3). A 409 conflict response maps to a definitive status only for the
  three unambiguous codes (`already-filled`/`already-canceled`/
  `already-rejected`); everything else stays `UNKNOWN` with the error
  code preserved for audit.
- `broker.enums.BrokerOrderStatus` gained `CANCEL_REJECTED`/
  `REPLACE_REJECTED` (the official spec's 10-value `Order.status` enum,
  vs. the 8 this codebase originally modeled).

**`get_capabilities()` still reports all four `CapabilityStatus.UNKNOWN`,
unchanged.** This is the load-bearing decision of Phase 21 (ADR-0027
decision 5): `UNKNOWN` means "implemented, never independently
verified end-to-end" -- exactly this situation, since no automated
test in this repository ever calls the real Toss API. `evaluate_safety_gate`
therefore still blocks Live submissions requiring these capabilities,
identically to before this phase. Promoting any of them to `ENABLED`
requires a future, human-supervised operational verification against a
real account -- not merely this phase's code existing.

63 new tests were added across `tests/broker/toss/test_toss_mapping.py`,
`tests/broker/toss/test_toss_adapter.py`, and
`tests/integration/test_toss_live_reconciliation_integration.py`,
exercising every documented status/error path for all four endpoints,
the new-orderId cancel semantics, the client_order_id resolution
(including the "never submitted through this instance" UNKNOWN case),
and end-to-end reconciliation (MATCHED/MISMATCH/UNKNOWN) driven through
the real `TossBrokerAdapter` -- always against a stub transport, never
the real network.

## Evidence tiers

This document distinguishes three tiers of evidence, ranked from
strongest to weakest, and only the first ever justifies promoting a
capability to `ENABLED`:

1. **Official primary** -- read directly from
   `developers.tossinvest.com` or
   `openapi.tossinvest.com/openapi-docs/latest/openapi.json`. Not
   achieved for any of the four UNKNOWN capabilities in Phase 13 or
   Phase 17 -- both hosts remain blocked by this environment's network
   egress proxy (re-confirmed directly in this Phase 17 session:
   `https://openapi.tossinvest.com/openapi-docs/latest/openapi.json`
   and `https://developers.tossinvest.com/docs` both returned
   `EGRESS_BLOCKED`, not merely assumed unreachable from Phase 13
   notes).
2. **Secondary/community, with a named or inferable source** --
   third-party technical write-ups, SDK feature-support matrices, or a
   community-maintained OpenAPI mirror. This is what Phase 13's
   original research and this phase's new finding both are. Sufficient
   to name an endpoint as a documented *lead* for future official
   verification; never sufficient to mark a capability `ENABLED`.
3. **Guess** -- inferring a path/schema from naming convention alone,
   with no source. Never used anywhere in this codebase
   (`broker/toss/endpoints.py`'s own docstring, `PROJECT_MASTER_PLAN.md`
   section 9.3).

## New in Phase 17 (Tier 2, not yet Tier 1)

A community-maintained repository, `BEOKS/tossinvest-skill`, hosts a
file at `references/openapi.json` (title "토스증권 Open API", version
"1.1.1", declared as OpenAPI 3.1.0), reachable via
`raw.githubusercontent.com` in this environment (unlike the real Toss
domains). It lists, among other market-data GET endpoints:

- `GET /api/v1/accounts` -- "계좌 목록 조회" (account list query)
- `GET /api/v1/holdings` -- "보유 주식 조회" (holdings/positions query)
- `GET /api/v1/orders` -- both a `GET` (list) and the already-confirmed
  `POST` (creation)

Notably **absent** from the accessible portion of this file: any
cancellation endpoint, and any single-order-detail-by-ID endpoint. The
file carries no statement of its own provenance (official mirror vs.
independently reverse-engineered) -- this alone keeps it at Tier 2. It
is recorded here as a concrete lead for a future session with real
network access to `openapi.tossinvest.com`, not as a basis for any
code change this phase.

## Gap Analysis Table

| Capability | Current Code | Official Documentation | Endpoint | Authentication | Request Schema | Response Schema | Error Handling | Implementation Status | Production Blocking? |
|---|---|---|---|---|---|---|---|---|---|
| **ACCOUNT_BALANCE** | `TossBrokerAdapter.get_account()` **implemented (Phase 21)**, calls `GET /api/v1/buying-power?currency=USD` | Tier 1 -- official OpenAPI spec, read directly (Phase 20) | `GET /api/v1/buying-power` (`GET /api/v1/accounts` documented but not used -- see ADR-0027) | Bearer + `X-Tossinvest-Account` | `currency` query param | `BuyingPowerResponse` | Fully enumerated (400/401/403/404/429/500) | `CapabilityStatus.UNKNOWN` (**implemented, not operationally verified -- ADR-0027 decision 5**) | **Yes, until operationally verified** -- `evaluate_safety_gate` requires this whenever a `SafetyGateContext.required_capabilities` includes `ACCOUNT_BALANCE` (see `tests/integration/test_live_trading_lineage.py::test_toss_real_capabilities_block_the_gate_end_to_end`) |
| **POSITIONS** | `TossBrokerAdapter.get_positions()` **implemented (Phase 21)**, calls `GET /api/v1/holdings` | Tier 1 (Phase 20) | `GET /api/v1/holdings` | Bearer + `X-Tossinvest-Account` | optional `symbol` filter (not used) | `HoldingsOverview` (items[]: quantity/avg cost mapped to `BrokerPosition`) | Fully enumerated | `CapabilityStatus.UNKNOWN` (implemented, not operationally verified) | **Yes, until operationally verified** |
| **ORDER_STATUS** | `TossBrokerAdapter.get_order_status()` **implemented (Phase 21)**, calls `GET /api/v1/orders/{orderId}` | Tier 1 (Phase 20) | `GET /api/v1/orders/{orderId}` (single-order detail -- not the list endpoint; see ADR-0027) | Bearer + `X-Tossinvest-Account` | `orderId` path param | `Order` with a **10-value status enum**, all mapped, including the 2 new `broker.enums.BrokerOrderStatus` members (`CANCEL_REJECTED`/`REPLACE_REJECTED`, Phase 21) | Fully enumerated | `CapabilityStatus.UNKNOWN` (implemented, not operationally verified) | **Yes, until operationally verified** |
| **CANCEL_ORDER** | `TossBrokerAdapter.cancel_order()` **implemented (Phase 21)**, calls `POST /api/v1/orders/{orderId}/cancel` | Tier 1 (Phase 20) | `POST /api/v1/orders/{orderId}/cancel` | Bearer + `X-Tossinvest-Account` | empty/optional body | `OrderOperationResponse{orderId}` -- the newly-issued id is carried in the new `BrokerOrderResponse.cancel_reference_id` field, `broker_order_id` stays the original order's id (ADR-0027 decision 3) | Fully enumerated; only `already-filled`/`already-canceled`/`already-rejected` conflicts map to a definitive status, all others stay `UNKNOWN` with the code preserved | `CapabilityStatus.UNKNOWN` (implemented, not operationally verified) | **Yes, until operationally verified** -- also still blocks the Runbook's "Emergency Halt" cancellation step from being automated (cancel-on-shutdown remains a separate, undecided policy question regardless, per instruction section 22) |

## Confirmed rows, for contrast (no gap -- listed for completeness)

| Capability | Endpoint | Evidence Tier | Contract Tests |
|---|---|---|---|
| Authentication (token) | `POST /oauth2/token` | Tier 2 (GA announcement + multiple independent write-ups agree) | `tests/broker/toss/test_toss_auth.py` |
| `MARKET_ORDER` / order creation | `POST /api/v1/orders` | Tier 2 | `tests/broker/toss/test_toss_mapping.py`, `test_toss_adapter.py`, `test_toss_production_safety_contract.py` (Phase 17 additions: 5xx -> `BrokerProviderError`, PARTIAL_FILLED/CANCELED through the full response path) |
| Transport-level failure handling | n/a (applies to any endpoint) | n/a | `tests/broker/toss/test_toss_transport.py` |

## Phase 17 code change arising from this review

While building the contract tests above, this review found that
`parse_order_response` (`src/broker/toss/mapping.py`) mapped **any**
HTTP status >= 400, including 5xx, to `BrokerOrderStatus.REJECTED`. A
5xx is the broker's own infrastructure failing -- it is not evidence
the order was looked at and declined, and treating it as `REJECTED`
would have told `LiveTradingSession` "safe to treat as done" when the
true state is unknown. This is now a distinct `BrokerProviderError`
(new in `src/broker/errors.py`), raised the same way
`BrokerAuthError`/`BrokerRateLimitError` already are, which
`LiveTradingSession.submit`'s existing `except BrokerError` handler
already routes to `BrokerOrderStatus.UNKNOWN` +
`OperationalState.RECONCILIATION_REQUIRED` with no code change needed
in `session.py` itself. See `tests/broker/toss/
test_toss_production_safety_contract.py::
TestProviderErrorIsNeverConfusedWithADefinitiveRejection`.

## What would need to happen before any row above could change

1. ~~Real, direct access to the official spec~~ -- **done as of Phase
   20**: the user provided the full official OpenAPI 3.1.0 document
   directly, read in full this phase.
2. ~~For each capability: the exact endpoint path, required headers,
   request/response schema, and error shape, read directly from that
   source~~ -- **done as of Phase 20**, see the extraction table above.
3. ~~`broker/toss/endpoints.py`'s paths updated from `None` to the
   confirmed path, `TossBrokerAdapter`'s corresponding methods
   implemented against the now-known schemas, `broker.enums.
   BrokerOrderStatus` extended with `CANCEL_REJECTED`/
   `REPLACE_REJECTED`~~ -- **done as of Phase 21** (`ADR-0027`).
   `get_capabilities()` was deliberately **not** updated to report
   `ENABLED` -- see step 5.
4. ~~New contract tests for each endpoint's normal/error/malformed/
   timeout scenarios~~ -- **done as of Phase 21**, 63 new tests across
   `tests/broker/toss/test_toss_mapping.py`,
   `tests/broker/toss/test_toss_adapter.py`, and
   `tests/integration/test_toss_live_reconciliation_integration.py`.
5. Real credential availability and a deliberate, human-approved
   decision to actually exercise these calls against a real account
   (even read-only ones) -- **still not done, and cannot be done by an
   automated session**: implementing and testing the code (steps 3-4)
   is necessary but not sufficient for `ENABLED`; per this project's
   own discipline (`PROJECT_MASTER_PLAN.md`), no automated test in this
   repository may ever call the real Toss API, so the capability's
   correctness against production still needs a human operator's own
   verification before being trusted, regardless of how complete the
   code and test suite are.

Until all four rows in the Gap Analysis Table read `ENABLED` (not just
Tier 1 *documented and implemented*), **Live activation remains
structurally blocked** for any operation requiring one of them, by
design (`docs/decisions/ADR-0022-live-trading.md` decision 2). Phase 21
completed steps 3-4; step 5 -- real operational verification -- remains
the only thing standing between today's state and `ENABLED`, and it is
categorically not something a future automated session can complete on
its own.
