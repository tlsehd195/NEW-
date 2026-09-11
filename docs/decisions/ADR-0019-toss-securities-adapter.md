# ADR-0019: Toss Securities Adapter

**Status:** Accepted

## Context

`PROJECT_MASTER_PLAN.md` §18.1 lists Phase 13 as "Toss Securities
Adapter." §9.3 already specifies the architecture: core system depends
on a neutral Broker Interface, never on Toss directly, and the Toss
Adapter's exact endpoints/auth/schema must be confirmed against
official documentation at implementation time -- "추측해서 endpoint를
만들지 않는다." The handoff for this session added an extensive,
explicit safety framework on top: `execution_mode` must default to
disabled/offline, credential presence alone must never activate live
trading, no secret may ever be persisted/logged, and every operation
this codebase cannot independently verify against Toss's real API must
be `UNKNOWN`/`UNSUPPORTED` rather than guessed.

This session's Git/Branch Integrity Check (see
`docs/specifications/PHASE-13-toss-securities-adapter.md` §0) found the
repository in a clean, correctly-lineaged state on the prior session's
`claude/phase-12-ai-gateway` branch and created
`claude/phase-13-toss-securities-adapter` from that verified HEAD.

Research (`docs/specifications/PHASE-13-toss-securities-adapter.md`
§"Toss API Verification") found that Toss Securities' Open API reached
general availability on 2026-08-13 -- twelve days before this session --
with **no public sandbox environment**. This one fact shapes most of
this ADR's decisions: there is nowhere safe to point an automated test,
or even a careful manual integration check, without risking a real
order against real capital.

## Decision

### 1. `MockBrokerAdapter` is the only adapter this repository's own
   code ever calls -- `TossBrokerAdapter` exists but is reachable only
   by a caller's deliberate, explicit construction

Because no sandbox exists, this codebase cannot validate
`TossBrokerAdapter` end-to-end the way `ai_gateway.provider.
MockProviderAdapter` (Phase 12) could at least be validated against a
mental model of a well-documented, sandboxed API. The only responsible
choice is to make the real adapter maximally inert by default:
`BrokerConfig.execution_mode` defaults to `OFFLINE`,
`TossBrokerAdapter.__init__` refuses construction unless
`execution_mode == LIVE`, and `LIVE` itself requires a second,
independent `live_opt_in=True` flag
(`BrokerConfig.__post_init__`). No factory function, default wiring, or
test in this repository ever produces a live-mode `TossBrokerAdapter` --
`tests/broker/toss/test_toss_adapter.py` explicitly constructs one only
with `MockTransport`, never `TossHttpTransport`.

### 2. Unconfirmed Toss operations raise `BrokerCapabilityError` rather
   than being guessed

Research confirmed `POST /oauth2/token` (auth) and `POST /api/v1/orders`
(order creation) with enough detail (an actual example request body) to
implement responsibly. It also confirmed that cancellation,
status/history, and account/balance/position endpoints *exist*, but no
source available to this session named their exact paths --
`developers.tossinvest.com` and `openapi.tossinvest.com` are both
blocked by this environment's network egress proxy, so the OpenAPI spec
itself could not be read. `PROJECT_MASTER_PLAN.md` §9.3 and instruction
section 6 are both explicit: an unconfirmed capability is
`UNSUPPORTED`/`UNKNOWN`, never guessed. `broker.toss.endpoints.
CANCEL_ORDER_PATH`/`ORDER_STATUS_PATH`/`ACCOUNT_PATH`/`POSITIONS_PATH`
are therefore left `None`, and the corresponding
`TossBrokerAdapter` methods raise `BrokerCapabilityError` naming exactly
why (§ "Future Sandbox/Live Integration Requirements" in the spec is
what a future session needs to do before implementing them for real).

### 3. Order-response parsing is defensive, not confident, about field
   names it could not verify

The confirmed *request* schema for order creation
(`clientOrderId`/`symbol`/`side`/`orderType`/`quantity`/`price`) was
quoted directly in a third-party technical write-up with an actual
example. The *response* schema's field name for the broker's own
assigned order id was not similarly confirmed. Rather than either (a)
guessing a field name and presenting a wrong value with false
confidence, or (b) refusing to parse a response at all,
`broker.toss.mapping.parse_order_response` reads `orderId` falling back
to `id`, and any order-status string it does not recognize maps to
`BrokerOrderStatus.UNKNOWN` (`map_order_status`) -- this system's own
"unknown broker response ≠ success" fail-closed rule already covers
exactly this uncertainty, so there is no need to be certain about every
field name to behave safely.

### 4. `broker_requests`/`broker_responses` trust the caller-assigned
   id and dedupe on it directly -- unlike Phase 9/11's content-addressed
   fix, but the same choice Phase 12 already made for `ai_requests`/
   `ai_responses`

ADR-0015 §6 and ADR-0017 §7 fixed a real defect class for
content-addressed artifacts (`TrainingDataset`, `CandidateModelArtifact`,
`ModelLineageRecord`) where independent in-process id allocators could
collide. ADR-0018 §4 already established why that fix does not transfer
to an event/request log: two requests with identical content sent at
different times are two distinct, legitimate events, not duplicates.
The same reasoning applies here unchanged -- `broker_requests`/
`broker_responses` follow Phase 5-8/12's precedent (trust the
caller-assigned id, dedupe on it directly) rather than Phase 9/11's.

### 5. `broker_requests` carries `decision_id`/`sizing_id`/
   `risk_assessment_id` as real columns, not only inside `payload_json`

Every other Phase 5-12 persisted type that participates in a lineage
SQL join (e.g. `risk_assessments.decision_id`, `candidate_models.
dataset_id`) exposes its lineage-linking ids as real columns, reserving
`payload_json` for the full record. `broker_requests` follows the same
convention -- instruction section 16 explicitly asks for
`Decision JOIN Sizing JOIN Risk JOIN Order JOIN BrokerSubmission JOIN
BrokerStatus` to be provable by SQL join, which requires these ids to
be indexable columns, not values buried inside a JSON blob.

### 6. `order_status_events` is its own append-only table, separate
   from the generic `broker_requests`/`broker_responses` log

An order's status changing over time (`PENDING` → `PARTIAL_FILLED` →
`FILLED`, for instance) is qualitatively different from one request/
response pair -- it is a *sequence of observations about the same
order*, the same reason `ai_gateway.models.ProviderQuotaState` (Phase
12) and `evolution.models.ModelStatusTransition` (Phase 11) each got
their own dedicated append-only table rather than being folded into a
generic request/response log. `OrderStatusObservation`'s own history
(`order_status_events`) is a first-class, independently queryable
timeline per `client_order_id`.

### 7. `os.environ`/`os.getenv` is confined to exactly one file

Every other external-integration boundary this project has built so far
(`ai_gateway.*`, Phase 12) chose to never resolve a real credential at
all, because Phase 12's own scope explicitly forbade any real provider
connection. Phase 13's scope is different -- §9.3's Toss Adapter is
meant to eventually be usable for real, and instruction section 3 talks
about "실제 HTTP client가 구현되어야 하는 경우" as an expected
possibility, not a forbidden one. Given that, credential *resolution*
(reading the actual environment variable value) has to live somewhere.
Rather than let it leak into `broker.config`/`broker.mock`/anywhere
callers might reasonably look, it is confined to a single file,
`broker/toss/auth.py`, reachable only from
`broker.toss.adapter.TossBrokerAdapter` (itself gated per decision 1).
`tests/broker/test_broker_boundary.py::TestSecretsOnlyResolvedInTossAuth`
AST-scans the entire package to enforce this structurally, not just by
code review.

### 8. `ValidatedOrder` restricted to `OrderType.MARKET` this phase,
   even though Toss confirms `LIMIT` support

Building a `LIMIT` order correctly requires a limit price, and no
upstream layer (Decision, Position Sizing, Risk -- Phase 7/8) computes
or carries one; Phase 2's own `backtest.orders.OrderSimulator` already
established the identical precedent (`OrderType.LIMIT` reserved,
`NotImplementedError` if attempted, ADR-0006) for exactly this reason.
Inventing a price-sourcing mechanism just to exercise `LIMIT` orders
would be scope creep this phase's instruction explicitly warns against
("Portfolio optimizer... 새로운 decision strategy"). `TossBrokerAdapter.
get_capabilities()` still reports `LIMIT_ORDER: ENABLED` honestly (Toss
itself supports it) -- the limitation is this phase's Order Validation
layer, not a false claim about the broker.

## Alternatives Considered

1. **Implement all of `cancel_order`/`get_order_status`/`get_account`/
   `get_positions` against a best-guess REST convention (e.g.
   `DELETE /api/v1/orders/{id}`).** Rejected -- see decision 2; directly
   contradicts `PROJECT_MASTER_PLAN.md` §9.3's explicit "추측해서
   endpoint를 만들지 않는다," and a wrong guess presented with the same
   confidence as the confirmed `submit_order` path would be worse than
   an honest `BrokerCapabilityError`.
2. **Skip building `TossHttpTransport` entirely this phase** (mirroring
   Phase 12's "no real network code at all" choice). Rejected -- Phase
   13's own scope and the instruction's explicit allowance for a real
   HTTP client differ meaningfully from Phase 12's; a stdlib-only,
   narrowly-scoped real transport that is never wired by default gives
   a genuine, tested starting point for future sandbox/live work without
   adding a dependency or a default-reachable network path.
3. **Attempt a numeric guess at Toss's order-API rate limit** (to
   pre-emptively throttle `TossHttpTransport`). Rejected -- research
   confirmed a `Retry-After` header exists and should be honored, but no
   source gave an actual rpm/rpd number; inventing one would be exactly
   the kind of fabricated-but-confident detail this project's discipline
   forbids (`PROJECT_MASTER_PLAN.md` §6.3: "실제로 제공하는 제한사항...
   구현 시점에 해당 provider의 공식 문서를 확인하여 설정한다").
4. **Fold `order_status_events` into `broker_responses`** (a
   `get_order_status` call is, after all, just another response).
   Rejected -- see decision 6; loses the "sequence of observations over
   time for one order" semantics a dedicated append-only table gives for
   free, and breaks parity with the `ProviderQuotaState`/
   `ModelStatusTransition` precedent.

## Consequences

### Positive

- Zero modifications to Phase 1-12 source files; `git diff | grep '^-'`
  on `src/storage/schema.py` and `src/storage/serialization.py` shows no
  deleted/changed lines, only additions.
- A real, tested (via stubbed `urllib`, never the network) HTTP
  transport and OAuth2 client-credentials flow exist for the two
  endpoints this session could actually confirm, ready for a future
  session with network access to verify the rest.
- No code path anywhere in `broker.*` can reach `LIVE` execution, call
  Decision/Risk/AI Gateway directly, or read a secret outside one
  file -- all verified structurally (AST scan), not by convention.
- The full `Decision → Risk → ValidatedOrder → BrokerRequest →
  BrokerResponse → OrderStatusObservation` chain is SQL-joinable and
  survives a restart, proven by an actual integration test rather than
  asserted.

### Negative / Trade-offs

- `TossBrokerAdapter` cannot cancel an order, check its status, or read
  account/position data -- a genuinely incomplete adapter until a future
  session with network access to `developers.tossinvest.com`/
  `openapi.tossinvest.com` confirms the remaining endpoints. This is a
  deliberate, documented gap (§ "Future Sandbox/Live Integration
  Requirements"), not an oversight.
- `submit_order`'s real-response parsing has never been exercised
  against an actual Toss response (no sandbox to test against) -- its
  defensive field-reading (decision 3) is a reasoned hedge, not a
  verified behavior.
- Restricting Order Validation to `MARKET` orders (decision 8) means
  this phase cannot express a limit-price strategy even though Toss
  supports it -- a future phase adding limit-price sourcing to
  Decision/Position Sizing would need to extend `broker.validation`
  accordingly.
