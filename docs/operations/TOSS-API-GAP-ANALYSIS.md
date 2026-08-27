# Toss Securities Open API -- Adapter Gap Analysis

Phase 17 Production Safety Review, Section 6. This document exists to
answer one question honestly, per capability: **is this safe to mark
`CapabilityStatus.ENABLED` on `TossBrokerAdapter` today, or not?**

**Status as of Phase 20: the official document now exists and has been
read (see "Phase 20 addendum" below) -- but no code change has been
made yet.** `TossBrokerAdapter` still reports `CapabilityStatus.UNKNOWN`
for `ACCOUNT_BALANCE`, `POSITIONS`, `ORDER_STATUS`, and `CANCEL_ORDER`
(`src/broker/toss/adapter.py::get_capabilities`), exactly as Phase 13
left it, and `evaluate_safety_gate` therefore still structurally blocks
any Live submission that requires one of them
(`tests/broker/live/test_live_safety_gate.py::
TestRealTossCapabilitiesStructurallyBlockLiveTrading`). Implementing
against the now-confirmed schema is deliberately deferred to a
dedicated next phase (see "Phase 20 addendum"), not done inline here,
per the process this project itself established in Phase 19 section
19 ("공식 문서가 제공되면 해당 문서와 Phase 13 adapter를 비교하여
필요한 추가 작업을 별도 Phase/task로 제안한다").

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

**What this Phase deliberately does NOT do**: change
`src/broker/toss/endpoints.py`'s `None` paths, implement
`get_account`/`get_positions`/`get_order_status`/`cancel_order` on
`TossBrokerAdapter`, change any `CapabilityStatus` from `UNKNOWN`, or
touch `broker.enums.BrokerOrderStatus`. Phase 20's own scope is market
data provider research, not Toss integration, and the process this
project established in Phase 19 (section 19) is explicit: read the
official document, compare it against the existing adapter, and
propose the resulting implementation work as its own dedicated next
phase -- not implement inline the moment a document arrives. See the
Phase 20 completion report's `NEXT RECOMMENDED PHASE` for that
proposal.

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
| **ACCOUNT_BALANCE** | `TossBrokerAdapter.get_account()` raises `BrokerCapabilityError` (`src/broker/toss/adapter.py`) | **Tier 1 -- official OpenAPI spec, read directly (Phase 20)** | `GET /api/v1/accounts` (list) + `GET /api/v1/buying-power` (cash) | Bearer (+`X-Tossinvest-Account` for `/buying-power`) | none / `currency` query param | `Account[]`; `BuyingPowerResponse` | Fully enumerated (400/401/403/404/429/500 per endpoint) | `CapabilityStatus.UNKNOWN` (**unchanged this phase, by design** -- see Phase 20 addendum above) | **Yes, until implemented** -- `evaluate_safety_gate` requires this whenever a `SafetyGateContext.required_capabilities` includes `ACCOUNT_BALANCE` (see `tests/integration/test_live_trading_lineage.py::test_toss_real_capabilities_block_the_gate_end_to_end`) |
| **POSITIONS** | `TossBrokerAdapter.get_positions()` raises `BrokerCapabilityError` | **Tier 1 (Phase 20)** | `GET /api/v1/holdings` | Bearer + `X-Tossinvest-Account` | optional `symbol` filter | `HoldingsOverview` (rich: quantity/avg cost/market value/P&L per item) | Fully enumerated | `CapabilityStatus.UNKNOWN` (unchanged this phase) | **Yes, until implemented** |
| **ORDER_STATUS** | `TossBrokerAdapter.get_order_status()` raises `BrokerCapabilityError` | **Tier 1 (Phase 20)** | `GET /api/v1/orders` (list) + `GET /api/v1/orders/{orderId}` (detail -- newly found, absent even from Phase 13's Tier 2 lead) | Bearer + `X-Tossinvest-Account` | `status` required; symbol/date-range/pagination optional | `Order` with a **10-value status enum** (`PENDING/PENDING_CANCEL/PENDING_REPLACE/PARTIAL_FILLED/FILLED/CANCELED/REJECTED/CANCEL_REJECTED/REPLACE_REJECTED/REPLACED`) -- 2 more than `broker.enums.BrokerOrderStatus` currently has | Fully enumerated | `CapabilityStatus.UNKNOWN` (unchanged this phase) | **Yes, until implemented** |
| **CANCEL_ORDER** | `TossBrokerAdapter.cancel_order()` raises `BrokerCapabilityError` | **Tier 1 (Phase 20) -- previously no lead at any tier** | `POST /api/v1/orders/{orderId}/cancel` | Bearer + `X-Tossinvest-Account` | empty/optional body | `OrderOperationResponse{orderId}` -- **a newly-issued id, explicitly documented as different from the original order's id** | Fully enumerated (404/409 conflict states/422 business rules) | `CapabilityStatus.UNKNOWN` (unchanged this phase) | **Yes, until implemented** -- also blocks the Runbook's "Emergency Halt" cancellation step (`docs/operations/LIVE-TRADING-RUNBOOK.md` "Shutdown") from being automatable today |

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
3. `broker/toss/endpoints.py`'s `CANCEL_ORDER_PATH`/`ORDER_STATUS_PATH`/
   `ACCOUNT_PATH`/`POSITIONS_PATH` updated from `None` to the confirmed
   path, `TossBrokerAdapter`'s corresponding methods implemented against
   the now-known schemas (mirroring `submit_order`'s existing pattern),
   `broker.enums.BrokerOrderStatus` extended with `CANCEL_REJECTED`/
   `REPLACE_REJECTED`, and `get_capabilities()` updated to report
   `ENABLED` -- **deliberately not done this phase**; proposed as the
   next dedicated phase's primary scope (see the Phase 20 completion
   report).
4. New contract tests for each endpoint's normal/error/malformed/
   timeout scenarios (mirroring this document's Table and Phase 17's
   `test_toss_production_safety_contract.py` pattern), before any
   capability flips to `ENABLED` -- part of that same future phase.
5. Real credential availability and a deliberate, human-approved
   decision to actually exercise these calls against a real account
   (even read-only ones) -- implementing the code is necessary but not
   sufficient for `ENABLED`; per this project's own discipline
   (`PROJECT_MASTER_PLAN.md`), no automated test in this repository may
   ever call the real Toss API, so even after implementation, the
   capability's correctness against production would need a human
   operator's own verification before being trusted, not just this
   codebase's test suite passing.

Until all four rows in the Gap Analysis Table read `ENABLED` (not just
Tier 1 *documented*), **Live activation remains structurally blocked**
for any operation requiring one of them, by design
(`docs/decisions/ADR-0022-live-trading.md` decision 2). Reaching Tier 1
evidence this phase is necessary progress, not by itself sufficient --
`CapabilityStatus.UNKNOWN` remains the honest state of the *code* until
the implementation in step 3 actually exists and is tested.
