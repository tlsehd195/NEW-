# ADR-0022: Live Trading

**Status:** Accepted

## Context

`PROJECT_MASTER_PLAN.md` §9.4 already specifies the target shape
(`Trading Engine → Broker Interface → Paper Broker (default) / Toss
Broker (Live, explicit only)`), §1.5 requires the kill switch to be
designed so AI cannot release it, §12.1-12.3 specify kill-switch
triggers and reconciliation-before-resume, and §14.4 requires
`LIVE_TRADING = false` by default. This session's handoff is unusually
explicit and repetitive about one thing: Phase 16's job is safety
infrastructure around an already-built order pipeline, not a new
trading system.

This session's Git/Branch Integrity Check (see
`docs/specifications/PHASE-16-live-trading.md` §0) found the repository
in a clean, correctly-lineaged state on the prior session's
`claude/phase-15-paper-trading` branch and created
`claude/phase-16-live-trading` from that verified HEAD.

A critical fact discovered during implementation, not assumed going in:
`broker.toss.adapter.TossBrokerAdapter.get_capabilities()` (Phase 13,
ADR-0019) reports `ACCOUNT_BALANCE`/`POSITIONS`/`ORDER_STATUS`/
`CANCEL_ORDER` as `CapabilityStatus.UNKNOWN` — their endpoints were
never confirmed against Toss's official documentation. This shapes most
of this ADR's decisions: any Live Trading design that assumes it can
always query the real broker's account/position/order state is building
on a foundation Phase 13 explicitly does not have yet.

## Decision

### 1. The safety gate is a pure function over eleven independently-
   sourced conditions -- never a config flag or two

Every prior "activation" mechanism in this codebase (`BrokerConfig.
live_opt_in`, Phase 13; `PaperTradingConfig.environment`, Phase 15) was
a single dataclass-level guard. Live Trading's stakes are categorically
different (real capital, not a simulation or a still-unconfirmed
adapter), so `broker.live.safety_gate.evaluate_safety_gate` checks
eleven conditions independently and requires all eleven — environment,
the `live_trading_enabled` flag, a human-sourced
`LiveActivationApproval`, per-capability verification against the
adapter's own reported `BrokerCapabilities`, Monitoring's own computed
risk health, `broker.validation.build_validated_order`'s own
`OrderValidationStatus`, kill switch state, account/position state
known-ness, model state validity, and configuration integrity. No
single condition is trusted alone, and the function performs no I/O
itself — every input is caller-supplied, already computed by the system
that owns it (mirrors `monitoring.health.evaluate_*`'s own pure-
evaluator design, Phase 14).

### 2. The gate's capability check makes real Toss Live Trading
   structurally unreachable today -- a discovered consequence, not a
   new restriction

Because `evaluate_safety_gate` checks `BrokerCapabilities.is_enabled(...)`
for every capability an order needs, and `TossBrokerAdapter` reports
`ACCOUNT_BALANCE`/`POSITIONS`/`ORDER_STATUS`/`CANCEL_ORDER` as
`UNKNOWN` (not `ENABLED`), the gate will refuse to authorize any Live
submission that needs account/position verification or a cancel/status
capability against the real Toss adapter, regardless of every other
condition being satisfied. This was verified directly (not asserted):
constructing a fully-healthy `SafetyGateContext` against Toss's actual
`get_capabilities()` output still fails with
`broker_capability_not_verified_account_balance`. This is the correct,
desired behavior, not a bug to work around — it means the gate cannot
be fooled into authorizing real trading against an adapter whose
account-reading capability was never confirmed safe. Resolving it
requires confirming those endpoints against Toss's official
`/openapi-docs/latest/openapi.json` (Phase 13's own deferred item), not
a change to `broker.live.*`.

### 3. `LiveActivationApproval` is a real, validated dataclass with a
   confirmation-phrase check -- not a boolean

A bare `human_approved: bool = True` field is trivially satisfiable by
any code, including AI-generated code, defeating its own purpose.
`LiveActivationApproval` requires a non-empty `approved_by` that is
structurally rejected if it equals `"AI"`/`"SYSTEM"`/`"CLAUDE"` (a
literal check, not cryptographic proof of humanity, but enough to make
"a human forgot to fill in a real name" and "code auto-generates this
object" both fail loudly), a timezone-aware `approved_at`, an explicit
`checklist_completed=True`, and a `confirmation_token` that must exactly
match a fixed literal phrase documented in the operational runbook
(`docs/operations/LIVE-TRADING-RUNBOOK.md`) — a deliberate manual step,
not a secret, but one more barrier against an accidental or scripted
`True`. No constructor of this type appears anywhere in `src/` outside
`broker.live.approval` itself, verified by AST scan
(`tests/broker/live/test_live_boundary.py`).

### 4. `engage_kill_switch` is callable by deterministic pipeline code;
   `release_kill_switch` structurally requires the same human-approval
   object

`PROJECT_MASTER_PLAN.md` §12.1 explicitly wants automatic engagement
("자동으로 중단할 수 있어야 한다") but §1.5 explicitly wants AI to be
unable to release it. Rather than a single `set_kill_switch(bool)`
function relying on caller discipline, `broker.live.kill_switch` exposes
two functions with deliberately different signatures:
`engage_kill_switch(event_id, reason, occurred_at, configuration_version)`
takes no approval and is called by `LiveTradingSession` itself when
`evaluate_kill_switch_triggers` fires; `release_kill_switch(event_id,
approval, occurred_at, configuration_version)` requires a
`LiveActivationApproval` and is never called by `LiveTradingSession` or
any other deterministic code path — grepping for its call sites finds
only its own test. The asymmetry is the whole point: it is trivial to
verify "nothing except a human-approval-carrying call can turn this
off" by reading the two function signatures, rather than auditing every
call site of one shared function for whether it happened to pass
`True` or `False`.

### 5. `KillSwitchEvent`/`ReconciliationResult` are both append-only;
   current state is always the *latest* event, never a separately
   mutated flag

The same "one observation per point in time" pattern ADR-0012/0018/0020
already established for `ComponentHealth`/`ProviderQuotaState` applies
here — a kill switch that is a single mutable boolean field could, in
principle, be overwritten by a bug without leaving a trace of what it
was before; an append-only event log cannot silently lose history.
`InMemoryKillSwitchRepository.get_latest()`/`is_engaged()` derive
current state purely from the event with the latest `(occurred_at,
event_id)`, never a cached flag that could drift from the log.

### 6. Reconciliation is three separate pure comparison functions, not
   one generic "compare states" function

Account (cash/buying_power), position (per-security quantity), and
order status (a `BrokerOrderStatus` enum, not a float) are different
enough in shape and comparison semantics (numeric tolerance vs. exact
enum equality) that one polymorphic function would need internal
branching per target anyway. `compare_account`/`compare_positions`/
`compare_order_status` are separately named, separately testable, and
each returns the identical `ReconciliationResult` shape — the same
"multiple small pure functions sharing one result type" pattern
`monitoring.drift`'s three detectors (Phase 14) already established.
Every one returns `ReconciliationStatus.UNKNOWN` when either side's
state is itself unavailable — never coerced to `MATCHED`.

### 7. `LiveTradingSession` needs no local order/fill ledger the way
   `PaperTradingSession` needed `paper_orders`/`paper_fills`

`PaperBrokerAdapter` (Phase 15) *is* the source of truth for its own
simulated state — nothing else knows what happened, so restart safety
required replaying persisted orders/fills to reconstruct it.
`TossBrokerAdapter` is never authoritative for Live — the real broker
is. `LiveTradingSession` therefore never needs to "replay" anything on
restart; it re-establishes truth by calling `reconcile_order`/comparing
against the broker's own `get_account`/`get_positions`/
`get_order_status` (once those capabilities are confirmed, §2). This is
why Phase 16 needs only two new tables (`kill_switch_events`,
`reconciliation_events`) where Phase 15 needed two of a fundamentally
different, replay-oriented kind — not an oversight, a direct consequence
of who owns the ground truth in each case.

### 8. A submission exception is recorded as `UNKNOWN` and blocks
   further submissions session-wide, never retried

`LiveTradingSession.submit` catches `broker.errors.BrokerError` (the
same exception hierarchy `TossBrokerAdapter`/`MockBrokerAdapter` already
raise, Phase 13) and does not retry — "no response" is never treated as
"no order was created." The affected `client_order_id`'s internal status
becomes `BrokerOrderStatus.UNKNOWN`, and the *whole session* transitions
to `OperationalState.RECONCILIATION_REQUIRED`, refusing every further
`submit()` call (not just for the affected security) until
`reconcile_order` resolves it. This is deliberately more conservative
than "only block the affected security" — instruction section 15's own
framing ("duplicate order 가능성이 있으면 안전한 reconciliation을
우선한다") reads as a session-wide caution, and a narrower per-security
block would need to reason about correlated risk (e.g. cash shared
across securities) that this phase does not model.

### 9. `build_trade_record` sets `reference_price = price` rather than
   fabricating a slippage/spread breakdown

Toss's confirmed order-response schema (ADR-0019) gives
`filled_quantity`/`avg_fill_price` only. `backtest.fills.Fill` (reused
unchanged, the same type Phase 15's Paper journal bridge uses) has no
`Optional[float]` fields for `reference_price`/`spread_cost`/
`slippage_cost` — they are required floats. Rather than guess a
reference price (which would silently fabricate a "measured" slippage
number that was never actually measured, this project's own repeated
prohibition), `broker.live.journal.build_fill_from_broker_response` sets
`reference_price = price` (arithmetically zero measured slippage) and
documents in both code and spec that this reflects absence of an
independently-sourced quote (`BrokerCapability.QUOTE` is itself
`UNKNOWN`/`UNSUPPORTED` everywhere in this codebase), not an actual
absence of slippage.

### 10. `assert_live_environment_broker_safe` defaults to rejecting a
    non-live broker in a live environment, with one explicit,
    named-per-call escape hatch

Mirrors `broker.paper.guard.assert_paper_environment_safe` (Phase 15)
in the opposite direction. Instruction section 9 explicitly allows "a
documented operational/test mode" exception for Live-environment code
running against a non-real broker (this is exactly what every
`broker.live.*` test itself needs to do, since no test may call the real
Toss API). Rather than silently permit this whenever a broker happens
not to be `TossBrokerAdapter`, the function requires
`allow_non_live_broker_for_testing=True` passed explicitly at each call
site — grep-able, auditable, never a default.

## Alternatives Considered

1. **A single boolean `live_trading_enabled` plus `live_opt_in` (mirroring
   Phase 13's `BrokerConfig`) as the entire gate.** Rejected — see
   decision 1; two booleans cannot express "risk engine is currently
   unhealthy" or "the broker's account-reading capability was never
   confirmed," both of which are real-time facts a static config cannot
   capture.
2. **Skip the capability check in the safety gate, since Phase 13
   already gates unconfirmed operations with `BrokerCapabilityError` at
   the adapter level.** Rejected — an adapter-level exception is a
   *reactive* fail-closed (the call already happened and failed); the
   gate's job is to prevent the call from happening at all when it is
   already known it cannot succeed safely, which is a stronger,
   earlier safety property.
3. **Model the kill switch as a single row updated in place (`UPDATE
   kill_switch_state SET engaged = ?`).** Rejected — see decision 5;
   loses history, and reintroduces exactly the kind of "who changed
   this and when" audit gap `PROJECT_MASTER_PLAN.md` §15 (Logging &
   Auditability) exists to prevent.
4. **Give `LiveTradingSession` its own `live_orders` ledger table
   mirroring Phase 15's `paper_orders`.** Rejected — see decision 7; the
   real broker is authoritative for Live, so a local ledger would be
   redundant state that could itself drift from the broker, the exact
   failure mode reconciliation exists to catch.
5. **Only block the specific security involved in an `UNKNOWN` order,
   not the whole session.** Rejected for now — see decision 8; a
   narrower policy is plausible but requires reasoning about
   cross-security risk correlation (shared cash, portfolio-level
   exposure) this phase's instruction explicitly defers as a financial-
   policy question, not a purely technical one.
6. **Guess a Toss quote/reference-price endpoint to compute real
   slippage for Live trades.** Rejected outright — direct violation of
   instruction section 24/37/47's repeated "공식 문서에서 확인할 수 없는
   endpoint/schema는 추측하지 않는다."

## Consequences

### Positive

- Zero modifications to Phase 1-15 source files; `git diff | grep '^-'`
  on `src/storage/schema.py` and `src/storage/serialization.py` shows no
  deleted/changed lines, only additions.
- The safety gate is verifiably, structurally unable to authorize real
  Live Trading against `TossBrokerAdapter` today — proven directly by
  constructing the gate's context from Toss's actual reported
  capabilities and observing the failure, not merely asserted in prose.
- `release_kill_switch` has exactly one reachable call site in the
  entire repository (its own test) — auditable by grep, not by trusting
  every caller's discipline.
- No code path anywhere in `broker.live.*` can reach `ai_gateway.
  gateway`, `decision.agent`, `risk.sizing`/`risk.engine`, or
  `os.environ`/`os.getenv` — verified structurally (AST scan), not by
  convention.

### Negative / Trade-offs

- Real Live Trading remains unreachable until a future session confirms
  Toss's account/position/order-status/cancel endpoints — this phase
  builds and fully tests the safety infrastructure, but cannot itself
  close that gap (it is Phase 13's own deferred research item, not
  something `broker.live.*` can resolve by writing more code).
- Live fills cannot carry a genuinely measured slippage/spread
  breakdown — `reference_price = price` is an honest placeholder, not a
  real measurement, until a quote source exists.
- The session-wide (not per-security) block on `UNKNOWN` state is
  conservative to the point of being operationally inconvenient in a
  true multi-security live deployment — a future session revisiting
  this needs an explicit financial-policy decision about cross-security
  risk before narrowing it.
