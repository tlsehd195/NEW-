# Phase 16 — Live Trading

## 0. Git / Branch Integrity Check (performed before any implementation)

This session started from the state Phase 15 left: on
`claude/phase-15-paper-trading`, HEAD
`eae021270f409b30fb36791e5518545876fa1d48` ("Phase 15: Paper Trading"),
working tree clean. `git log --oneline --graph --decorate --all`
confirmed a single linear history (`Initial commit → Phase 0 → … →
Phase 15`), zero merge commits (`git log --merges --oneline | wc -l` →
`0`). `git merge-base HEAD origin/main` returned `origin/main`'s own
HEAD (`c3abad0eb9b2ba1ed4dda5ee158b448606a87d59`) — `main` is a
strict, non-diverged ancestor. No `claude/phase-16-live-trading` branch
existed on the remote. A new branch, `claude/phase-16-live-trading`,
was created from this verified HEAD. The full suite was run before any
Phase 16 code was written: **1127/1127 tests passed** (baseline).

## 1. Purpose

Build the safety infrastructure that lets the *same* trading pipeline
Phase 15 already proved in simulation run against a real broker
(`broker.toss.adapter.TossBrokerAdapter`, Phase 13), per
`PROJECT_MASTER_PLAN.md` §9.4:

```
Trading Engine → Broker Interface → Paper Broker   (default)
Trading Engine → Broker Interface → Toss Broker    (Live, explicit only)
```

The goal is **not** "implement the order API" — Phase 13 already did
that for the one confirmed endpoint. The goal is a Live Trading layer
that is deterministic, auditable, restart-safe, fail-closed, idempotent,
observable, and reproducible at every boundary where a real order could
be created — and that structurally cannot activate without an explicit,
human-sourced decision.

## 2. Scope

- **Environment & activation model** (`broker/live/config.py`,
  `broker/live/approval.py`) — `LiveTradingConfig.environment` fixed to
  `"live"`; `live_trading_enabled` defaults `False`
  (`PROJECT_MASTER_PLAN.md` §14.4); a separate, explicit
  `LiveActivationApproval` object (human-sourced identity + timestamp +
  confirmation token) is a hard prerequisite the deterministic code
  requires and never constructs itself.
- **Multi-condition safety gate** (`broker/live/safety_gate.py`) — every
  one of eleven independently-sourced conditions must hold before a
  single order reaches the broker.
- **Kill switch** (`broker/live/kill_switch.py`) — append-only,
  auto-engage on any of the configured trigger conditions, never
  auto-release; release requires an explicit human-sourced approval
  object, structurally unreachable from any deterministic pipeline code
  path.
- **Reconciliation** (`broker/live/reconciliation.py`) — pure comparison
  functions between internal state and the broker's own authoritative
  `get_account()`/`get_positions()`/`get_order_status()` responses;
  mismatch blocks new orders rather than being silently resolved.
- **`LiveTradingSession`** (`broker/live/session.py`) — orchestration:
  gate evaluation → idempotent submission → **no blind retry on
  timeout/UNKNOWN, reconciliation first** → audit persistence; startup/
  shutdown checks.
- **Trade Journal bridge** (`broker/live/journal.py`) —
  `provenance=TradeProvenance.LIVE_TRADING`, with an honestly-documented
  limitation on cost/slippage decomposition (§10).
- **Monitoring integration** — Phase 14's `monitoring.collectors.
  collect_broker` observes Live's `broker_requests`/`broker_responses`
  exactly as it already does for Paper (Phase 15), zero Monitoring code
  changes; kill-switch/reconciliation events are raised as `Alert`s via
  Phase 14's existing pure mapping functions.
- **Persistence** — two new DuckDB tables (`kill_switch_events`,
  `reconciliation_events`); everything else reuses Phase 13's existing
  `broker_requests`/`broker_responses`/`order_status_events` unchanged
  (§12).
- **Operational runbook** (`docs/operations/LIVE-TRADING-RUNBOOK.md`).

### 2.1 Explicitly out of scope

- **Actually enabling Live Trading against a real account.** No
  `.env`/deployment configuration in this repository sets
  `live_trading_enabled=True`; no test constructs a
  `LiveActivationApproval`; nothing in this commit changes the fact
  that this repository has never sent, and cannot send without a
  human's own separate, out-of-band action, a real order.
- **Confirming Toss's `cancel_order`/`get_order_status`/`get_account`/
  `get_positions` endpoints.** These remain `CapabilityStatus.UNKNOWN`
  on `TossBrokerAdapter` exactly as Phase 13 left them (ADR-0019) — see
  §6's structural consequence.
- **A specific daily-loss-limit or drawdown-limit number, or a capital
  allocation policy.** `PROJECT_MASTER_PLAN.md` §13.12 explicitly defers
  the capital-ratio decision; `LiveTradingConfig.max_daily_loss`
  defaults to `None` ("not enforced") — the same convention
  `risk.config.RiskConfig.max_turnover`/`max_sector_weight` already use
  for an intentionally-unconfigured limit. Setting a real number is an
  operational decision for whoever runs this system, not this phase.
- **`APPROVED`/`DEPLOYED` `CandidateModelStatus` transitions, or any
  code path that could produce one.** Phase 11 already established that
  nothing in this codebase can assign either value; Phase 16 does not
  change that (§9).
- **An always-on scheduler process.** Phase 15 already deferred this;
  Phase 16 does not build it either (`PROJECT_MASTER_PLAN.md`'s own
  phase-by-phase incrementalism, §18.4).
- **Undoing an already-executed live trade.** §11's "이미 실행된 거래를
  되돌리는 기능을 임의로 구현하지 않는다" — rollback here means halting
  further activity and reverting to a known-good model/configuration,
  never reversing a fill.

## 3. Architecture

```
Decision (7) → Sizing + Risk (8) → Order Validation (13) → BrokerAdapter
                                                                ├── PaperBrokerAdapter (15)
                                                                └── TossBrokerAdapter  (13)
                                                                        ↑
                                                    LiveTradingSession (16, this phase)
                                                    -- gate, idempotency, reconciliation,
                                                       audit -- wraps the adapter, never
                                                       replaces Core Trading Logic
```

Core Trading Logic (Decision/Sizing/Risk/Order Validation) is byte-for-
byte the same code Phase 15 already exercises against
`PaperBrokerAdapter` — `LiveTradingSession` differs from
`PaperTradingSession` only in what sits *between* a `ValidatedOrder` and
`BrokerAdapter.submit_order`: a safety gate, idempotent-with-
reconciliation semantics, and a kill switch, none of which touch
Decision/Sizing/Risk at all.

| It is **not** | Why |
|---|---|
| A second Decision/Risk implementation | `broker.live.*` never imports `decision.agent`/`risk.sizing`/`risk.engine`/`learning.*`; every order it ever sees is an already-built `ValidatedOrder` |
| An AI-driven activation path | `broker.live.*` never imports `ai_gateway.gateway`; `LiveActivationApproval` is never constructed anywhere in `src/` outside a human-invoked operational entrypoint (`tests/broker/live/test_live_boundary.py`) |
| A credential store | `broker.live.*` never reads `os.environ`/`os.getenv` — exactly like `broker.paper.*`, credential resolution stays confined to `broker/toss/auth.py` alone |
| A risk-limit editor | never imports/writes `risk.config.RiskConfig`; the safety gate only *reads* the latest computed risk health, never adjusts a threshold |
| The kill switch's release mechanism | `broker.live.kill_switch.release_kill_switch` requires a `LiveActivationApproval`-shaped human token; no deterministic pipeline code path calls it (AST-verified) |

## 4. Live Trading Activation Model

`LiveTradingConfig.environment` is structurally fixed to `"live"`
(`__post_init__` rejects any other value — the same pattern
`PaperTradingConfig.environment` already established, Phase 15).
`live_trading_enabled: bool = False` is the `LIVE_TRADING` flag
`PROJECT_MASTER_PLAN.md` §14.4 requires default off. Neither field alone
is sufficient to submit a real order — `evaluate_safety_gate` (§5) is
the single function that decides whether a submission may proceed, and
it requires all eleven conditions independently, not just these two
config fields.

## 5. The Safety Gate

`broker.live.safety_gate.evaluate_safety_gate(context: SafetyGateContext) -> SafetyGateResult`
is a pure function over an already-assembled `SafetyGateContext` — it
performs no I/O, no broker call, no database query itself (mirrors every
other evaluator this codebase has built: `monitoring.health.
evaluate_*`, `broker.validation.build_validated_order`). Every condition
must independently hold:

| Condition | Source |
|---|---|
| `environment == "live"` | `LiveTradingConfig.environment` |
| `live_trading_enabled == True` | `LiveTradingConfig.live_trading_enabled` |
| `activation_approval` present and valid | caller-supplied `LiveActivationApproval` |
| `broker_capability_verified` | `BrokerCapabilities.is_enabled(...)` for every capability this specific order needs |
| `risk_engine_health == HEALTHY` | caller-supplied `ComponentHealth` (Phase 14, `MonitoringComponent.RISK`) |
| `order_validator_result.status == ACCEPTED` | `broker.validation.build_validated_order`'s own result for this order |
| `kill_switch_engaged == False` | latest `KillSwitchEvent` |
| `account_state_known == True` | latest `BrokerAccountSnapshot.available` |
| `position_state_known == True` | latest `BrokerPosition.available` for the order's security |
| `model_state_valid == True` | latest `ModelStatusTransition.to_status in {APPROVED, DEPLOYED}` and `passed == True` (Phase 11) |
| `configuration_integrity_valid == True` | caller-supplied hash comparison against a pinned `configuration_version` |

Any single condition failing produces `SafetyGateResult(passed=False,
failed_conditions=(...))` — never a partial pass. `SafetyGateResult`
never carries an order/quantity/price field of its own (structural
boundary test) — it is a verdict about whether to proceed, not a new
order-shaped object.

## 6. Structural Consequence of Phase 13's Honest Capability Reporting

`TossBrokerAdapter.get_capabilities()` (Phase 13, ADR-0019) reports
`ACCOUNT_BALANCE`/`POSITIONS`/`ORDER_STATUS`/`CANCEL_ORDER` as
`CapabilityStatus.UNKNOWN` — their real endpoints were never confirmed
against Toss's official documentation, and Phase 13 deliberately chose
`BrokerCapabilityError` over a guessed path. The safety gate's
`broker_capability_verified` condition checks `is_enabled(...)`, which
is `False` for `UNKNOWN` exactly as it is for `UNSUPPORTED`
(`CapabilityStatus.is_enabled` only returns `True` for `ENABLED`) —
**meaning `evaluate_safety_gate` structurally refuses to authorize live
trading through `TossBrokerAdapter` for any operation that needs
account/position/order-status/cancel capability today.** This is not a
new restriction this phase invents; it is the correct, self-enforcing
consequence of Phase 13's own honest "don't guess an unconfirmed
endpoint" decision, surfaced all the way up to the activation gate. A
future session that confirms those endpoints against Toss's official
`/openapi-docs/latest/openapi.json` (Phase 13's own §"Future Sandbox/
Live Integration Requirements") changes `TossBrokerAdapter.
get_capabilities()`'s return value, and the gate's behavior updates
automatically — no change to `broker.live.*` itself would be needed.

## 7. Kill Switch

`broker.live.kill_switch` — `KillSwitchEvent` (frozen dataclass:
`event_id`, `engaged: bool`, `reason`, `triggered_by` — `"SYSTEM"` for
an automatic engage, an operator identity for a release — `occurred_at`,
`configuration_version`) persisted append-only
(`kill_switch_events`, the same "one observation per point in time"
pattern `ComponentHealth`/`ProviderQuotaState` already use). Current
state is always the *latest* event — never a separately mutated flag
that could drift from the event log.

`evaluate_kill_switch_triggers(context: KillSwitchTriggerContext) ->
Optional[str]` is a pure function checking, in order: critical
component health (`UNAVAILABLE`/`UNKNOWN` for Broker/Risk/Monitoring),
account/position/order state unknown, a configured `max_daily_loss`
breached (only if `LiveTradingConfig.max_daily_loss` is set — §2.1),
and a configured `max_order_frequency_per_hour` exceeded. Returns the
first triggered reason, or `None`. `engage_kill_switch(...)` is callable
by `LiveTradingSession` itself (an automatic, deterministic reaction to
a detected condition — this *is* allowed, matching
`PROJECT_MASTER_PLAN.md` §12.1's "자동으로 중단할 수 있어야 한다").
`release_kill_switch(...)` requires a `LiveActivationApproval`-shaped
argument and is never called by `LiveTradingSession`, `evaluate_*`, or
any other deterministic code path in `src/` — the only caller in this
repository is its own unit test, constructing the human-approval object
directly (`tests/broker/live/test_live_kill_switch.py`,
`tests/broker/live/test_live_boundary.py` AST-verifies no other call
site exists).

## 8. Reconciliation

`broker.live.reconciliation` provides three pure comparison functions —
`compare_account`, `compare_positions`, `compare_order_status` — each
returning a `ReconciliationResult(status: ReconciliationStatus, ...)`
where `ReconciliationStatus` is `MATCHED`/`MISMATCH`/`UNKNOWN` (`UNKNOWN`
when either side's state is itself unavailable — never coerced to
`MATCHED`). A `MISMATCH` or `UNKNOWN` result is never silently resolved
by overwriting internal state with the broker's — `LiveTradingSession`
transitions to `OperationalState.RECONCILIATION_REQUIRED` and blocks new
order submission until an operator-level reconciliation step
(`PROJECT_MASTER_PLAN.md` §12.3's own reconciliation-before-resume
principle) records a resolution. Every comparison is persisted
append-only to `reconciliation_events`, tolerance-bounded via
`LiveTradingConfig.reconciliation_tolerance` (a small numeric epsilon
for float comparison, not a policy decision).

## 9. Idempotency, UNKNOWN, and No Blind Retry

`LiveTradingSession.submit` reuses `broker.validation.
compute_client_order_id` (Phase 13) unchanged — the same
decision/sizing/risk/symbol/side/quantity/as_of_time always produces the
same `client_order_id`. On a transport exception
(`BrokerTimeoutError`/`BrokerTransportError`) during `submit_order`, the
session does **not** retry — "no response" is never treated as "no
order was created" (§9 of the handoff's own framing). Instead it records
the order's status as `UNKNOWN` and requires a `reconcile(client_order_id,
...)` call (which queries `adapter.get_order_status`, itself gated by
the same capability-verification consequence §6 describes for
`TossBrokerAdapter` today) before that security's cash/position is
eligible for a new order. `UNKNOWN` is never coerced to `FAILED` — a
dedicated `ReconciliationStatus.UNKNOWN`/`OperationalState.
RECONCILIATION_REQUIRED` state exists specifically so this distinction
survives past the moment of the failure.

## 10. Trade Journal Integration

`broker.live.journal.build_trade_record` bridges a live fill into
`trade_journal.models.TradeRecord` (Phase 3), `provenance` always
`TradeProvenance.LIVE_TRADING`. **Known limitation, documented rather
than silently fabricated:** Toss's confirmed order-response schema
(ADR-0019) gives `filled_quantity`/`avg_fill_price` only — no
independent reference price, spread, or slippage decomposition (Toss's
`QUOTE` capability is itself `UNKNOWN`/`UNSUPPORTED` on every adapter in
this codebase). `build_trade_record` therefore sets
`Fill.reference_price = Fill.price` (arithmetically zero measured
slippage) and `commission = 0.0` unless the broker response supplies one
— not because there is no real slippage/commission, but because this
system has no independently-sourced reference price to compare against.
This is the same category of honest gap Phase 13 already accepted for
Toss's unconfirmed endpoints, carried through to the one place a
`Fill`'s type shape forces a float rather than an `Optional[float]`.

## 11. Fail-Closed Behavior

| Situation | Result |
|---|---|
| `live_trading_enabled == False` (default) | gate `BLOCKED`, no order |
| Environment != `"live"` | gate `BLOCKED` |
| No `LiveActivationApproval` supplied | gate `BLOCKED` |
| Broker capability for this operation not `ENABLED` (includes Toss's current `UNKNOWN` account/position/status/cancel capabilities, §6) | gate `BLOCKED` |
| Risk engine health not `HEALTHY` | gate `BLOCKED` |
| Kill switch engaged | gate `BLOCKED` |
| Account/position state unavailable | gate `BLOCKED` |
| Model state not `APPROVED`/`DEPLOYED` (true by construction today — Phase 11 built no path to either) | gate `BLOCKED` |
| Configuration integrity mismatch | gate `BLOCKED` |
| Submission times out / connection lost | order recorded `UNKNOWN`, no retry, reconciliation required |
| Reconciliation finds a mismatch | `OperationalState.RECONCILIATION_REQUIRED`, new orders blocked |
| A trigger condition fires mid-session | kill switch auto-engages, orders blocked until human release |
| Duplicate `client_order_id` submitted | existing response returned, never a second order (Phase 13 idempotency, unchanged) |

## 12. Persistence

Two new tables in Phase 4's existing DuckDB catalog file
(`src/storage/schema.py`, purely additive — `git diff src/storage/
schema.py src/storage/serialization.py | grep '^-'` shows zero
deleted/changed lines against the Phase 15 baseline):

- `kill_switch_events` — append-only (seq-ordered), the same
  `provider_quota_states`/`model_status_transitions` pattern.
- `reconciliation_events` — append-only (seq-ordered), same pattern.

Everything else reuses Phase 13's existing schema unchanged:
`broker_requests`/`broker_responses` (generic request/response audit,
any `broker_id`), `order_status_events` (order status history). Unlike
Phase 15's `PaperBrokerAdapter` (which is its own source of truth and
needed local `paper_orders`/`paper_fills` tables to replay on restart),
`TossBrokerAdapter` is never authoritative — the real broker is — so
`LiveTradingSession` never needs to replay local state on restart; it
re-establishes truth via reconciliation instead (§8). This asymmetry is
why Phase 16 needs only two new tables where Phase 15 needed two of a
different, replay-oriented kind.

## 13. Monitoring Integration

Phase 14's `monitoring.collectors.collect_broker`/`compute_broker_metrics`
observe Live's `broker_requests`/`broker_responses` unmodified, exactly
as they already do for Paper (Phase 15) — Live is "yet another
`broker_id`." Kill-switch-engaged and reconciliation-mismatch events are
raised as `monitoring.models.Alert`s via Phase 14's existing pure
mapping functions (`monitoring.alerts.raise_alert_from_health`), never a
new alerting mechanism. No change was made to `src/monitoring/*.py`.

## 14. Startup / Shutdown Safety

`broker.live.session.run_startup_checks(context)` and
`run_shutdown_checks(context)` are pure functions over caller-supplied,
already-computed state (mirrors §5's gate design) — they never perform
I/O themselves. Startup aggregates the same conditions the safety gate
checks (§5) plus reconciliation status; any critical `UNKNOWN` blocks
new-order eligibility from the first tick.  Shutdown records open-order
state and an explicit `SHUTTING_DOWN` transition; it never
force-cancels open orders — cancellation-on-shutdown is a distinct
financial policy decision this phase does not make unilaterally (handoff
§29).

## 15. Test Strategy

| Category | File |
|---|---|
| Config / activation model | `tests/broker/live/test_live_config.py` |
| Safety gate (all 11 conditions, individually and combined) | `tests/broker/live/test_live_safety_gate.py` |
| Kill switch (trigger evaluation, engage, release-requires-approval) | `tests/broker/live/test_live_kill_switch.py` |
| Reconciliation (account/position/order comparisons) | `tests/broker/live/test_live_reconciliation.py` |
| Session (submit/idempotency/UNKNOWN/no-blind-retry/startup/shutdown) | `tests/broker/live/test_live_session.py` |
| Human approval | `tests/broker/live/test_live_approval.py` |
| Trade Journal bridge | `tests/broker/live/test_live_journal.py` |
| Boundary (no AI/Decision/Risk/secret access, kill switch release unreachable) | `tests/broker/live/test_live_boundary.py` |
| Leakage / point-in-time | `tests/broker/live/test_live_leakage.py` |
| Reproducibility | `tests/broker/live/test_live_reproducibility.py` |
| In-memory repository | `tests/broker/live/test_live_repository_inmemory.py` |
| Persistence / restart (DuckDB) | `tests/storage/test_live_repository.py` |
| Integration lineage (SQL join, Monitoring reuse, Trade Journal, gate end-to-end) | `tests/integration/test_live_trading_lineage.py` |

No test in this repository constructs a `TossHttpTransport` outside its
own Phase 13 unit test, and no test constructs a
`LiveActivationApproval` anywhere except `test_live_kill_switch.py`/
`test_live_session.py`/`test_live_approval.py` themselves — every other
test exercises the gate via its `BLOCKED` path.

## 16. Operational Requirements

See `docs/operations/LIVE-TRADING-RUNBOOK.md` for the full manual
procedure. In summary: configuration/credential/broker-connectivity/
account-identity/reconciliation/risk/monitoring/kill-switch verification,
then explicit human confirmation, then `live_trading_enabled=True`, then
a restricted first execution — none of which this repository's own code
can perform on its own behalf.

## 17. Security Requirements

No secret value is ever persisted to DuckDB, logged, or embedded in an
exception message anywhere in `broker.live.*` (AST + runtime-verified,
`tests/broker/live/test_live_boundary.py`) — `os.environ`/`os.getenv`
access remains confined to `broker/toss/auth.py` alone, exactly as Phase
13 established. `LiveActivationApproval.confirmation_token` is compared
against a fixed literal, never logged verbatim in a way that could be
replayed (it is not a secret in the credential sense, but is treated
with the same discipline).

## 18. Known Limitations

- **Live Trading against the real Toss account cannot fully activate
  today** — the safety gate structurally blocks it, because
  `TossBrokerAdapter`'s account/position/order-status/cancel
  capabilities remain `UNKNOWN` (§6). This is Phase 13's own unresolved
  gap, not a new one; resolving it is a prerequisite for any real
  activation, tracked in Phase 13's own "Future Sandbox/Live Integration
  Requirements."
- **Live fills cannot carry a measured slippage/spread decomposition**
  (§10) — `reference_price` is set equal to `price` for lack of an
  independently-sourced quote.
- **No specific daily-loss/drawdown number is set** — `max_daily_loss`
  defaults to `None` (not enforced); an operator must set one
  explicitly before it has any effect (§2.1).
- **No cancellation-on-shutdown policy** — shutdown records state but
  never force-cancels open orders (§14).
- **No always-on scheduler** — `LiveTradingSession` provides
  `submit`/`reconcile`/lifecycle primitives; nothing in this repository
  drives them on a timer.

## 19. Phase Boundary

Phase 16's scope is Live Trading infrastructure, safety, broker
execution orchestration, and reconciliation/operational readiness. It
does not implement capital allocation policy, an always-on scheduler,
Toss endpoint confirmation beyond what Phase 13 already did, or any
mechanism for a candidate model to reach `APPROVED`/`DEPLOYED`
automatically.

## 20. Definition of Done

- [x] Implementation matching this spec
- [x] Unit + integration tests, all passing (see completion report for exact counts)
- [x] Fail-closed handling: every one of the eleven safety-gate
      conditions independently blocks submission; `UNKNOWN` is never
      coerced to `MATCHED`/`FAILED`/`FILLED`
- [x] Logging/audit: `kill_switch_events`/`reconciliation_events` plus
      reused `broker_requests`/`broker_responses`/`order_status_events`
      is the durable record of every operation
- [x] Documentation: this spec + ADR-0022 + the operational runbook
- [x] Configuration: `LiveTradingConfig` — `live_trading_enabled`
      defaults `False`, `environment` structurally fixed to `"live"`
- [x] Validation: structural boundary tests confirm no AI-driven
      activation, no secret persistence, no risk-limit mutation, and no
      reachable kill-switch-release path outside its own tests
