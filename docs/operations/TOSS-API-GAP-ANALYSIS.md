# Toss Securities Open API -- Adapter Gap Analysis

Phase 17 Production Safety Review, Section 6. This document exists to
answer one question honestly, per capability: **is this safe to mark
`CapabilityStatus.ENABLED` on `TossBrokerAdapter` today, or not?**

No code change accompanies this document for any of the four rows
below. The answer for all four remains **no** -- `TossBrokerAdapter`
still reports `CapabilityStatus.UNKNOWN` for `ACCOUNT_BALANCE`,
`POSITIONS`, `ORDER_STATUS`, and `CANCEL_ORDER`
(`src/broker/toss/adapter.py::get_capabilities`), exactly as Phase 13
left it, and `evaluate_safety_gate` therefore still structurally blocks
any Live submission that requires one of them
(`tests/broker/live/test_live_safety_gate.py::
TestRealTossCapabilitiesStructurallyBlockLiveTrading`).

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
| **ACCOUNT_BALANCE** | `TossBrokerAdapter.get_account()` raises `BrokerCapabilityError` (`src/broker/toss/adapter.py`) | Not reachable this phase (EGRESS_BLOCKED) | Tier 2 lead: `GET /api/v1/accounts` (`BEOKS/tossinvest-skill`) | Presumed `Authorization: Bearer` + `X-Tossinvest-Account` (confirmed pattern for account-scoped calls generally; not confirmed for this specific endpoint) | Unconfirmed | Unconfirmed | Unconfirmed | `CapabilityStatus.UNKNOWN` | **Yes** -- `evaluate_safety_gate` requires this whenever a `SafetyGateContext.required_capabilities` includes `ACCOUNT_BALANCE` (see `tests/integration/test_live_trading_lineage.py::test_toss_real_capabilities_block_the_gate_end_to_end`) |
| **POSITIONS** | `TossBrokerAdapter.get_positions()` raises `BrokerCapabilityError` | Not reachable this phase (EGRESS_BLOCKED) | Tier 2 lead: `GET /api/v1/holdings` (`BEOKS/tossinvest-skill`) | Presumed as above | Unconfirmed | Unconfirmed | Unconfirmed | `CapabilityStatus.UNKNOWN` | **Yes** |
| **ORDER_STATUS** | `TossBrokerAdapter.get_order_status()` raises `BrokerCapabilityError` | Not reachable this phase (EGRESS_BLOCKED) | Tier 2 lead: `GET /api/v1/orders` (list only; no single-order-by-ID variant found even at Tier 2) | Presumed as above | Unconfirmed | Unconfirmed | Unconfirmed | `CapabilityStatus.UNKNOWN` | **Yes** |
| **CANCEL_ORDER** | `TossBrokerAdapter.cancel_order()` raises `BrokerCapabilityError` | Not reachable this phase (EGRESS_BLOCKED) | **No lead found at any tier** -- absent even from the Tier 2 mirror | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | `CapabilityStatus.UNKNOWN` | **Yes** -- also blocks the Runbook's "Emergency Halt" cancellation step (`docs/operations/LIVE-TRADING-RUNBOOK.md` "Shutdown") from being automatable; manual cancellation via the Toss app/website remains the only path today |

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

1. Real, direct access to `developers.tossinvest.com` and/or
   `openapi.tossinvest.com/openapi-docs/latest/openapi.json` (Tier 1
   evidence) from an environment whose network egress is not blocked
   to those hosts.
2. For each capability: the exact endpoint path, required headers,
   request schema, response schema, and documented error shape, read
   directly from that source -- not inferred from the Tier 2 lead
   above, even though the lead's path guesses may well turn out correct.
3. `broker/toss/endpoints.py`'s `CANCEL_ORDER_PATH`/`ORDER_STATUS_PATH`/
   `ACCOUNT_PATH`/`POSITIONS_PATH` updated from `None` to the confirmed
   path, `TossBrokerAdapter`'s corresponding method implemented against
   it (mirroring `submit_order`'s existing pattern), and
   `get_capabilities()` updated to report `ENABLED` -- only then.
4. New contract tests for that specific endpoint's normal/error/
   malformed/timeout scenarios (mirroring this document's Table),
   before any capability flips to `ENABLED`.

Until all four rows in the Gap Analysis Table read something other
than `CapabilityStatus.UNKNOWN` with a Tier 1 citation, **Live
activation remains structurally blocked** for any operation requiring
one of them, by design (`docs/decisions/ADR-0022-live-trading.md`
decision 2).
