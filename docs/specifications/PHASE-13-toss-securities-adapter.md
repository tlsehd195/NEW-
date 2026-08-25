# Phase 13 — Toss Securities Adapter

## 0. Git / Branch Integrity Check (performed before any implementation)

This session ("Session 14") started from the state the prior session
(Phase 12) left: on `claude/phase-12-ai-gateway`, HEAD
`3511d7b9fa534895e649dce4bb1bcf43f3dc4b85` ("Phase 12: AI Gateway"),
working tree clean. `git log --oneline --graph --decorate --all`
confirmed a single linear history (`Initial commit → Phase 0 → … →
Phase 12`), zero merge commits. Explicit checks:
`git merge-base HEAD origin/main` returned `origin/main`'s own HEAD
(`c3abad0`, "Initial commit") — `main` is a strict, non-diverged
ancestor, nothing on `main` outside this lineage. `git merge-base HEAD
origin/claude/autonomous-ai-investment-system-wvscwe` similarly returned
`wvscwe`'s own HEAD with zero commits on `wvscwe` absent from the
current branch. `git log <phase12-hash>..HEAD --oneline` was empty --
the current HEAD *is* the Phase 12 commit exactly, no undocumented
commits after it. A new branch, `claude/phase-13-toss-securities-adapter`,
was created from this verified HEAD (not `main`). The full suite was
run before any Phase 13 code was written: **768/768 tests passed**
(baseline).

## 1. Scope

Per `PROJECT_MASTER_PLAN.md` §9.3 ("core system은 Toss API에 직접
의존하지 않는다... Broker Interface는 broker에 중립적으로 설계") and
the handoff's 29-section instruction, this phase implements:

- **Broker domain abstraction**: `broker.protocol.BrokerAdapter` --
  `submit_order/cancel_order/get_order_status/get_account/
  get_positions/get_capabilities`, matching §9.3's neutral interface.
- **Order domain models**: `broker.models.ValidatedOrder` (the sole
  authoritative order intent) and `broker.models.OrderValidationResult`.
- **Order Validation boundary**: `broker.validation.build_validated_order`
  -- turns an already risk-approved `risk.models.RiskCheckedPosition`
  plus the caller's freshly-known current position into a
  `ValidatedOrder`, or an explicit `VALIDATION_REJECTED` verdict.
- **Broker Capability Model**: `broker.capabilities`/`broker.enums.
  BrokerCapability`/`CapabilityStatus` -- nothing is assumed `ENABLED`
  without confirmation.
- **Authentication/configuration boundary**: `broker.config.BrokerConfig`
  (credential *references*, execution mode) + `broker.auth`
  (the resolved-credential shape) + `broker.toss.auth` (the one real
  resolution/token-exchange implementation).
- **Transport abstraction**: `broker.transport.BrokerTransport` Protocol
  + `MockTransport` (deterministic, offline) +
  `broker.toss.transport.TossHttpTransport` (the one real,
  stdlib-`urllib`-based implementation).
- **Toss Securities adapter**: `broker.toss.adapter.TossBrokerAdapter`
  -- `submit_order` real against the one confirmed endpoint;
  everything else `CapabilityStatus.UNKNOWN`/`BrokerCapabilityError`.
- **Error mapping**: `broker.errors` (transport-level exceptions) +
  `broker.toss.mapping` (Toss's real order-status/error-code vocabulary
  → domain types).
- **Idempotency**: `broker.validation.compute_client_order_id` --
  deterministic, content-derived from full lineage.
- **MockBrokerAdapter**: the only adapter any Phase 0-13 pipeline,
  backtest, or test may call.
- **Persistence + lineage**: three new DuckDB tables
  (`broker_requests`, `broker_responses`, `order_status_events`).

### 1.1 Explicitly out of scope

- **Automated live trading, Paper Trading, Live Trading, Monitoring.**
  This phase builds the boundary, never a system that decides to trade
  or watches the market on its own.
- **AI-driven execution.** No code path in `broker.*` calls
  `ai_gateway.gateway.AIGateway`; nothing here lets an AI response
  decide an order's fate (`tests/broker/test_broker_boundary.py`).
- **Learning Engine changes, Model Registry completion, automatic
  `CandidateModelStatus.APPROVED`/`DEPLOYED`.** `learning.enums` is
  never imported anywhere in `broker.*`.
- **Portfolio optimizer, new prediction model, new decision strategy,
  risk limit redesign, broker-side position sizing/risk judgment.**
  `decision.agent`/`risk.sizing`/`risk.engine`/`predict.predictor` are
  never imported anywhere in `broker.*` (AST-verified) -- a
  `ValidatedOrder` only ever carries forward what those layers already
  decided.
- **`cancel_order`/`get_order_status`/`get_account`/`get_positions`
  against the real Toss API.** Their exact endpoint paths could not be
  confirmed from this environment (§ "Toss API Verification" below);
  `TossBrokerAdapter` declares them `UNKNOWN`/raises
  `BrokerCapabilityError` rather than guessing.
- **`LIMIT` orders.** Confirmed supported by Toss itself
  (`BrokerCapability.LIMIT_ORDER` is `ENABLED` on
  `TossBrokerAdapter.get_capabilities()`), but `broker.validation`
  only ever builds `OrderType.MARKET` orders this phase -- there is no
  price-sourcing input anywhere upstream (Decision/Sizing/Risk, Phase
  7/8) that supplies a limit price, so building one would require
  inventing that input rather than reading it from an existing layer.

## 2. Architecture Boundary

```
Decision (Phase 7) → Position Sizing + Risk (Phase 8) → [Order Validation] → Broker Adapter → Toss API
```

`broker.*` sits after Risk and before the external broker, exactly
where `PROJECT_MASTER_PLAN.md` §4.2/§9 place "Order Validator / Safety"
and "Broker Adapter." It is not, and structurally cannot become, any of:

| It is **not** | Why |
|---|---|
| Decision Agent | never imports `decision.agent`; never produces a `DecisionAction` |
| Position Sizer / Risk Engine | never imports `risk.sizing`/`risk.engine`; `ValidatedOrder.quantity` is a delta derived from `RiskCheckedPosition.final_target_quantity`, never an independently computed target |
| AI Gateway | never imports `ai_gateway.gateway`; no AI response can decide an order |
| Model Registry | never imports `learning.enums`; cannot reference `APPROVED`/`DEPLOYED` |
| Live/Paper Trading system | `BrokerExecutionMode.OFFLINE` is the only default; `LIVE` requires two independent explicit signals (§10) |

`tests/broker/test_broker_boundary.py` verifies every row structurally
(AST scan across the whole package + reflection on the Protocol/adapter
classes), not just by convention.

## 3. Order Validation

`build_validated_order(risk_checked_position, current_quantity, *,
configuration_version)` is the only function in this codebase that
computes a trade side/quantity from a target position --
`RiskCheckedPosition.final_target_quantity` (Phase 8) is an *absolute*
target, not a delta, so nothing upstream already knows what to actually
buy or sell. Checks, in order, each recorded in the result's `checks`
dict:

1. `risk_status_is_pass_or_reduce` -- `REJECT`/`UNKNOWN` never proceeds.
2. `has_decision_id`/`has_sizing_id`/`has_risk_assessment_id` -- full
   lineage required.
3. `final_target_quantity_present`.
4. `current_quantity_finite` -- the caller's freshly-known position.
5. `trade_quantity_finite`/`trade_quantity_nonzero` -- a target equal to
   the current position needs no order at all (`"no_trade_needed"`).

Any failure returns `OrderValidationResult(status=
OrderValidationStatus.VALIDATION_REJECTED, validated_order=None,
reason=<specific check name>)` -- never an exception, never a partially
built order (`OrderValidationResult.__post_init__` enforces the
ACCEPTED↔validated_order/REJECTED↔no-validated_order invariant
structurally).

## 4. Idempotency

`compute_client_order_id(decision_id, sizing_id, risk_assessment_id,
security_id, side, quantity, as_of_time)` is a deterministic content
hash (reuses `data_infra.versioning.compute_data_version`, Phase 1 --
no new hashing logic) -- the same logical order always produces the
same `client_order_id`, so a caller retrying after an ambiguous
transport failure resubmits the *same* idempotency key. Toss's
confirmed order-creation request schema includes a caller-supplied
`clientOrderId` field, corroborating that this is the intended usage
pattern for that API. `MockBrokerAdapter.submit_order` demonstrates the
expected broker-side behavior: resubmitting an already-seen
`client_order_id` returns the existing response rather than creating a
second order.

## 5. Broker Capability Model

| Capability | `MockBrokerAdapter` | `TossBrokerAdapter` |
|---|---|---|
| `MARKET_ORDER` | `ENABLED` | `ENABLED` (confirmed) |
| `LIMIT_ORDER` | `UNSUPPORTED` (out of this phase's Order Validation scope, §1.1) | `ENABLED` (confirmed Toss itself supports it) |
| `CANCEL_ORDER` | `ENABLED` | `UNKNOWN` (exists per research, exact path unconfirmed) |
| `ORDER_STATUS` | `ENABLED` | `UNKNOWN` |
| `ACCOUNT_BALANCE` | `ENABLED` | `UNKNOWN` |
| `POSITIONS` | `ENABLED` | `UNKNOWN` |
| `QUOTE` | `UNSUPPORTED` | `UNKNOWN` |
| `IDEMPOTENT_CLIENT_ORDER_ID` | `ENABLED` | `ENABLED` (confirmed -- `clientOrderId` request field) |

Any capability not explicitly declared by a `build_capabilities(...)`
call defaults to `UNKNOWN` (never silently `ENABLED`).
`TossBrokerAdapter`'s `UNKNOWN`-capability operations all raise
`broker.errors.BrokerCapabilityError` if called -- there is no fallback
behavior for them.

## 6. Live Execution Safety

`BrokerExecutionMode.OFFLINE` is `BrokerConfig`'s only default.
Reaching `LIVE` requires **two independent, explicit signals**:
`execution_mode=BrokerExecutionMode.LIVE` *and* `live_opt_in=True`
(`BrokerConfig.__post_init__` raises otherwise) -- the exact
"credential presence alone activates live trading" anti-pattern
instruction section 10 names is structurally impossible, since neither
signal can be derived from whether an environment variable happens to
be set (`tests/broker/test_broker_boundary.py::TestExecutionModeGuard`
additionally AST-scans for a dynamically-computed `live_opt_in` keyword
anywhere in the package -- it is only ever a literal `True`/`False` a
caller passes). `TossBrokerAdapter.__init__` further requires
`execution_mode == LIVE` at construction time -- there is no way to
build a "Toss adapter" configured for `OFFLINE`/`SANDBOX` that silently
no-ops; `MockBrokerAdapter` is what `OFFLINE` actually means.

## 7. Fail-Closed Behavior

| Situation | Result |
|---|---|
| Broker unavailable / connection failure | `BrokerTransportError` -- never a fabricated success |
| Timeout | `BrokerTimeoutError` |
| Authentication failure (`expired-token` etc.) | `BrokerAuthError` |
| Rate limit | `BrokerRateLimitError` |
| Malformed/unparseable response | `BrokerOrderStatus.UNKNOWN`, `error_code="malformed_response"` |
| Unrecognized order-status string | `BrokerOrderStatus.UNKNOWN` (`broker.toss.mapping.map_order_status`) -- never guessed |
| Unsupported/unverified capability | `BrokerCapabilityError` |
| Invalid order (missing lineage, non-finite quantity, etc.) | `OrderValidationStatus.VALIDATION_REJECTED` -- never reaches a `BrokerAdapter` at all |
| Duplicate `client_order_id` | The existing response is returned, not a new order |
| Account/position read unavailable | `available=False`, `cash`/`quantity` left `None` -- never defaulted to `0` (`BrokerAccountSnapshot`/`BrokerPosition.__post_init__` structurally forbid carrying a value alongside `available=False`) |
| Order status genuinely unknown (never submitted, or broker disconnected) | `BrokerOrderStatus.UNKNOWN` -- `PROJECT_MASTER_PLAN.md` §9.1's required disconnected state |

`unknown broker response ≠ success` holds everywhere: `BrokerOrderResponse.
__post_init__` requires `status`, and nothing in this codebase maps an
unrecognized/malformed input to `FILLED`/`ACCEPTED`.

## 8. Toss API Verification

Researched on 2026-08-25 (Toss Securities' Open API reached general
availability on 2026-08-13; the official documentation host,
`developers.tossinvest.com`, and the API host,
`openapi.tossinvest.com`, are both blocked by this environment's
network egress proxy, so nothing below was read directly from the
OpenAPI spec -- everything is corroborated by the official GA
announcement plus independent third-party technical write-ups quoting
example requests/fields):

**Confirmed:**
- Base URL: `https://openapi.tossinvest.com`.
- Auth: OAuth2 Client Credentials grant. Token endpoint:
  `POST /oauth2/token`. All calls: `Authorization: Bearer {token}`.
  Account-scoped calls (order/account/position) additionally require
  an `X-Tossinvest-Account` header (one user can have multiple
  accounts).
- Order creation: `POST /api/v1/orders`, supporting both domestic
  (KRX) and US equities through one unified endpoint. Request fields
  (quoted in an example): `clientOrderId`, `symbol`, `side`
  (`BUY`/`SELL`), `orderType` (`LIMIT`/`MARKET`), `quantity` (integer,
  except MARKET+SELL on US stocks which may be decimal), `price` (for
  `LIMIT`).
- Order status vocabulary: open orders return
  `PENDING`/`PARTIAL_FILLED`/`PENDING_CANCEL`/`PENDING_REPLACE`; closed
  orders return `FILLED`/`CANCELED`/`REJECTED`/`REPLACED`.
- Error response shape: `code`/`message`/`data`/`requestId`. Example
  codes: `expired-token`, `insufficient-buying-power`,
  `order-hours-closed`, `price-out-of-range`.
- Rate limits exist on the order API specifically (more conservative
  than the market-data API); a `Retry-After` header is returned on
  limit, exponential backoff recommended.
- **No public sandbox environment.** Testing is recommended against
  production with a single share. This is the primary reason this
  phase treats `OFFLINE`/`MockBrokerAdapter` as the only environment
  this repository's own tests, backtests, or CI may ever exercise
  (§1.1, §11 of the instruction) -- there is nowhere safe to point an
  automated test at the real API.
- Order modification/cancellation, order list/detail queries, and
  account/balance/holdings queries all exist as endpoints (confirmed by
  an unofficial SDK's documented feature support matrix), and an
  OpenAPI JSON spec is published at `/openapi-docs/latest/openapi.json`.

**Not confirmed (left `CapabilityStatus.UNKNOWN`, not guessed):**
- The exact path for order cancellation, order status/history query, or
  account/balance/holdings query.
- The exact response-body field name for the broker's own assigned
  order id (`parse_order_response` reads `orderId` falling back to
  `id`, defensively, and is honest that this is unconfirmed).
- Exact numeric rate limits (rpm/rpd).
- The OpenAPI spec's full schema (the JSON file itself could not be
  fetched from this environment).

## 9. Secrets

`BrokerConfig.api_key_reference`/`api_secret_reference`/
`account_reference` default to `TOSS_API_KEY`/`TOSS_API_SECRET`/
`TOSS_ACCOUNT_ID` -- the exact placeholders `.env.example` already
reserved in Phase 0. `os.environ`/`os.getenv` appear **only** in
`broker/toss/auth.py` (`tests/broker/test_broker_boundary.py::
TestSecretsOnlyResolvedInTossAuth`, an AST scan across the whole
package) -- resolution happens transiently inside
`TossAuthClient.fetch_access_token`/`resolve_credentials` and the
resolved `ResolvedCredentials`/bearer token are never returned beyond
that immediate call, never a field on any persisted model
(`tests/broker/test_broker_secret_safety.py`). `TossHttpTransport`
filters every real HTTP response down to a small, known-safe header
allowlist (`content-type`/`retry-after`/`x-request-id`) before
constructing a `TransportResponse` -- there is no path through which an
`Authorization` header value could reach domain code or a log line.

## 10. Persistence

Three new tables in Phase 4's existing DuckDB catalog file
(`src/storage/schema.py`, purely additive -- `git diff | grep '^-'`
shows zero deleted/changed lines against the Phase 12 baseline):

- `broker_requests`/`broker_responses` -- a generic, uniform audit log
  for every `BrokerAdapter` operation (submit/cancel/status/account/
  positions), dedupe on the caller-assigned id directly (the same
  Phase 5-8/12 `decisions`/`predictions`/`ai_requests` pattern -- see
  ADR-0019 for why this differs from Phase 9/11's content-addressed
  dedup fix). `broker_requests` carries `decision_id`/`sizing_id`/
  `risk_assessment_id` as real, queryable columns (not buried in
  `payload_json`) specifically so the lineage chain is directly
  SQL-joinable.
- `order_status_events` -- append-only (seq-ordered), the same
  `regime_observations`/`provider_quota_states` pattern (Phase 5/12).

Nothing in `payload`/`metadata` ever contains a resolved secret --
nothing that constructs a persisted record anywhere in `broker.*` has
access to one in the first place.

## 11. Lineage Traceability

```
DecisionOutput (Phase 7) → RiskCheckedPosition (Phase 8)
   → ValidatedOrder → BrokerRequestRecord/BrokerResponseRecord → OrderStatusObservation
```

`tests/integration/test_broker_lineage.py` proves this is SQL-joinable
across five tables in one DuckDB catalog (`decision_outputs`⋈
`risk_assessments`⋈`broker_requests`⋈`broker_responses`⋈
`order_status_events`) and survives a process restart. `broker.*` never
regenerates a `DecisionAction` or a target weight/quantity of its own
-- every id and every quantity in `ValidatedOrder` is carried forward
from what Phase 7/8 already decided.

## 12. Point-in-Time

`BrokerAdapter.submit_order`/`get_order_status` require explicit
`requested_at`/`as_of` parameters with no default; nothing in
`broker.*` imports `data_infra.repository.DataRepository`/
`backtest.asof.AsOfDataView` (AST-verified,
`tests/broker/test_broker_point_in_time.py`). `ValidatedOrder.as_of_time`
is copied directly from `RiskCheckedPosition.as_of_time` -- it is never
derived from a wall-clock call. Backtests use `MockBrokerAdapter`
exclusively; `backtest.*` never imports `broker.*` at all
(`tests/broker/test_broker_backtest_integration.py`).

## 13. Reproducibility

No module in `broker.*` imports `random` or calls
`datetime.now()`/`datetime.utcnow()`
(`tests/broker/test_broker_reproducibility.py`, an AST scan). The same
`RiskCheckedPosition` + `current_quantity` always produces the same
`client_order_id` and the same `MockBrokerAdapter` response.

## 14. Test Strategy

| Category | File |
|---|---|
| Broker domain model | `tests/broker/test_broker_models.py` |
| Order validation | `tests/broker/test_broker_validation.py` |
| Mock broker / capability / idempotency / account-position reads | `tests/broker/test_broker_mock.py` |
| Boundary (no Decision/Risk/AI Gateway bypass, execution-mode guard, secret scope) | `tests/broker/test_broker_boundary.py` |
| Secret leakage | `tests/broker/test_broker_secret_safety.py` |
| Reproducibility | `tests/broker/test_broker_reproducibility.py` |
| Point-in-time | `tests/broker/test_broker_point_in_time.py` |
| Backtest integration | `tests/broker/test_broker_backtest_integration.py` |
| Toss response mapping | `tests/broker/toss/test_toss_mapping.py` |
| Toss transport (timeout/malformed/connection failure) | `tests/broker/toss/test_toss_transport.py` |
| Toss authentication | `tests/broker/toss/test_toss_auth.py` |
| Toss adapter (execution-mode guard, unsupported capabilities) | `tests/broker/toss/test_toss_adapter.py` |
| Persistence / restart / idempotency | `tests/storage/test_broker_repository.py` |
| Integration lineage | `tests/integration/test_broker_lineage.py` |

## 15. Future Sandbox/Live Integration Requirements

Before any real order is ever submitted (a decision this phase does not
make): (1) confirm the unconfirmed endpoint paths (§8) directly against
`/openapi-docs/latest/openapi.json` from an environment with network
access to `openapi.tossinvest.com`; (2) confirm the order-response body
schema (this phase's `parse_order_response` reads defensively but has
not been validated against a real response); (3) since no sandbox
exists, validate `TossBrokerAdapter.submit_order` against production
with a single share under close supervision before any larger use;
(4) decide and implement `cancel_order`/`get_order_status`/
`get_account`/`get_positions` once their paths are confirmed, each
gated the same way `submit_order` already is; (5) Phase 15 (Paper
Trading)/Phase 16 (Live Trading) own the actual `execution_mode=LIVE`
activation workflow and capital limits (`PROJECT_MASTER_PLAN.md`
§13.12) -- this phase only builds the adapter boundary they will use.

## 16. Definition of Done

- [x] Implementation matching this spec
- [x] Unit + integration tests, all passing (see completion report for exact counts)
- [x] Error handling: every failure mode produces a typed, factual
      result -- never an unhandled exception treated as success, never
      a fabricated fill
- [x] Logging/audit: `broker_requests`/`broker_responses`/
      `order_status_events` is the audit trail for every operation
- [x] Documentation: this spec + ADR-0019
- [x] Configuration: `BrokerConfig` -- no hardcoded credentials, no
      hardcoded endpoint paths beyond what was independently confirmed
- [x] Validation: structural boundary tests confirm no Decision/Risk/
      AI Gateway bypass, no path to `LIVE` without explicit dual
      opt-in, and no secret access outside `broker/toss/auth.py`
