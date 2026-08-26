# Phase 15 — Paper Trading

## 0. Git / Branch Integrity Check (performed before any implementation)

This session started from the state Phase 14 left: on
`claude/phase-14-monitoring`, HEAD
`e04faba7cbbf163f21b65cca074bb1ffadd7a1e8` ("Phase 14: Monitoring"),
working tree clean. `git log --oneline --graph --decorate --all`
confirmed a single linear history (`Initial commit → Phase 0 → … →
Phase 14`), zero merge commits (`git log --merges --oneline | wc -l` →
`0`). `git merge-base HEAD origin/main` returned `origin/main`'s own
HEAD (`c3abad0eb9b2ba1ed4dda5ee158b448606a87d59`) — `main` is a
strict, non-diverged ancestor. A new branch,
`claude/phase-15-paper-trading`, was created from this verified HEAD
(not `main`). The full suite was run before any Phase 15 code was
written: **1036/1036 tests passed** (baseline).

## 1. Scope

Per `PROJECT_MASTER_PLAN.md` §9.4 (Paper Trading: "Trading Engine →
Broker Interface → Paper Broker (개발/검증 기본값)") and the handoff's
47-section instruction, this phase implements a fully simulated
`broker.protocol.BrokerAdapter` (Phase 13) that never sends a real
order:

- **`PaperBrokerAdapter`** (`broker/paper/adapter.py`) — deterministic,
  in-memory, `BrokerAdapter`-Protocol-conforming: `submit_order`/
  `cancel_order`/`get_order_status`/`get_account`/`get_positions`/
  `get_capabilities`, plus a Paper-only `advance_simulation` hook.
- **Simulated execution** (`broker/paper/execution.py`) — reuses Phase
  2's `backtest.costs.TransactionCostModel`/`SlippageModel` and
  `backtest.fills.Fill` unchanged, capped by `max_participation` of the
  reference bar's volume, same as `backtest.fills.FillSimulator`.
- **Partial fills over simulated time** — an order can stay
  `PENDING`/`PARTIAL_FILLED` across multiple `advance_simulation` calls
  as more market data becomes available, accumulating fills until fully
  filled.
- **Cash/position accounting** — reuses Phase 2's
  `backtest.portfolio.PortfolioAccounting` unchanged (average-cost
  basis, realized PnL on sells) rather than re-deriving equivalent
  bookkeeping.
- **Idempotency** — reuses Phase 13's `client_order_id` discipline: a
  duplicate `submit_order` call returns the existing response, never a
  second fill.
- **Failure simulation** (`PaperTradingConfig.failure_mode`) —
  `rejected`/`timeout`/`auth`/`rate_limit`/`unavailable`/`malformed`/
  `unknown_status`, each deterministic.
- **Persistence + restart safety** — two new DuckDB tables
  (`paper_orders`, `paper_fills`) plus reuse of Phase 13's
  `order_status_events` unchanged; `PaperTradingSession.restore(...)`
  rebuilds an adapter's full in-memory state (cash, positions, order
  status) from these three tables alone.
- **Trade Journal bridge** (`broker/paper/journal.py`) — builds a
  `trade_journal.models.TradeRecord` (Phase 3) directly from a Paper
  fill, always `provenance=TradeProvenance.PAPER_TRADING`.
- **Monitoring integration** — Phase 14's `monitoring.collectors.
  collect_broker`/`compute_broker_metrics` work unmodified over Paper
  Trading's `BrokerRequestRecord`/`BrokerResponseRecord` rows (Paper is
  "just another `broker_id`" from Monitoring's point of view).
- **Live safety boundary** — `PaperTradingConfig.environment` is
  structurally fixed to `"paper"`; `broker.paper.guard.
  assert_paper_environment_safe` rejects a `TossBrokerAdapter` in a
  paper environment.

### 1.1 Explicitly out of scope

- **Live Trading, `execution_mode=LIVE` activation logic.** Phase 16's
  own scope — nothing in `broker.paper.*` reads or sets
  `BrokerExecutionMode.LIVE`.
- **Automatic model approval/deployment/retraining.** No code path in
  `broker.paper.*` can assign `learning.enums.CandidateModelStatus.
  APPROVED`/`DEPLOYED`, and nothing here invokes a trainer.
- **A real, running Trading Engine loop** (a scheduler that reads live
  market data, calls Decision/Sizing/Risk, and drives
  `PaperTradingSession.submit`/`advance` on a timer). This phase builds
  the simulated broker and its orchestration primitives; wiring them
  into an always-on scheduled process is a later phase's concern.
- **Alert acknowledgement/notification channels for `paper_broker_health`
  events.** Reuses Phase 14's existing, logging-centric Monitoring/
  Alerting exactly as-is — no new channel is built.
- **Short selling by default.** `PaperTradingConfig.allow_short=False`
  is the default; `allow_short=True` is supported but never assumed.
- **`LIMIT` orders.** `ValidatedOrder.order_type` is always
  `OrderType.MARKET` this phase (Phase 13's own §1.1 precedent,
  ADR-0006) — no price-sourcing input exists upstream to build a limit
  order from.

## 2. Architecture Boundary

```
Decision (7) → Position Sizing + Risk (8) → [Order Validation, 13] → BrokerAdapter
                                                                          ├── PaperBrokerAdapter (15, this phase)
                                                                          └── TossBrokerAdapter  (13, LIVE only)
```

`broker.paper.*` sits *behind* the same `BrokerAdapter` Protocol Phase
13 already defined — Core Trading Logic (Decision/Sizing/Risk/Order
Validation) does not change when the concrete adapter changes
(`PROJECT_MASTER_PLAN.md` §9.3/§9.4's own precedent, extended to a
second adapter). It is not, and structurally cannot become, any of:

| It is **not** | Why |
|---|---|
| A real broker connection | never imports `broker.toss.*` except one `isinstance`-only reference in `guard.py`; never opens a socket (`tests/broker/paper/test_paper_boundary.py`) |
| Decision Agent / Position Sizer / Risk Engine | never imports `decision.agent`/`risk.sizing`/`risk.engine`; a `ValidatedOrder`'s quantity/side is always carried forward from Phase 8's own output, never recomputed here |
| A parallel accounting/journal system | reuses `backtest.portfolio.PortfolioAccounting`/`backtest.fills.Fill`/`trade_journal.models.TradeRecord` unchanged (§4, §28) |
| A parallel Monitoring system | Phase 14's existing `monitoring.collectors.collect_broker` observes it unmodified |
| Live Trading | `PaperTradingConfig.environment` is structurally `"paper"`; `assert_paper_environment_safe` rejects a `TossBrokerAdapter` |

`tests/broker/paper/test_paper_boundary.py` verifies every row
structurally (AST scan across the whole package), not just by
convention.

## 3. Order State Machine

`PaperBrokerAdapter` reuses `broker.enums.BrokerOrderStatus` (Phase 13)
unchanged rather than inventing a parallel vocabulary —
`PENDING`/`PARTIAL_FILLED`/`FILLED`/`CANCELED`/`REJECTED`/`UNKNOWN`
already cover every transition `PROJECT_MASTER_PLAN.md` §9.1's abstract
state machine describes for this phase's purposes: `PENDING` doubles as
both `PROPOSED`/`SUBMITTED` (an accepted-but-not-yet-fully-filled order
has no separate "submitted" state to track, since acceptance and the
first fill attempt happen in the same `submit_order` call), and a
broker-level failure is always an *exception*
(`BrokerTimeoutError`/`BrokerAuthError`/`BrokerRateLimitError`/
`BrokerTransportError`) rather than a `FAILED` status value, matching
Phase 13's own established convention. `_current_status` derives the
status purely from `(initial_status, fills-so-far, cancelled-flag)` —
never stored redundantly, so it cannot drift from the underlying fill
history. Legal transitions:

```
PENDING → PARTIAL_FILLED → FILLED
PENDING → FILLED
PENDING → CANCELED   (cancel_order, before any/full fill)
PENDING → REJECTED   (insufficient cash discovered on first fill attempt)
(submission time) → REJECTED  (max qty/notional/insufficient position/rejected failure_mode)
```

`FILLED`/`REJECTED`/`CANCELED` are terminal — `_attempt_fill` refuses
to run against a `REJECTED` or cancelled order, and `advance_simulation`
skips any order already `FILLED`
(`tests/broker/paper/test_paper_accounting_invariants.py::
TestTerminalStatesRejectFurtherFills`).

## 4. Execution Model

`broker/paper/execution.py::simulate_fill` re-derives
`backtest.fills.FillSimulator.execute`'s exact math (spread applied to
the reference bar's close via `TransactionCostModel.apply_spread`, then
slippage via `SlippageModel.adjust`, `spread_cost`/`slippage_cost`
computed the identical way) rather than calling `FillSimulator` itself
— `FillSimulator` is coupled to `backtest.orders.Order`/
`backtest.portfolio.PortfolioView`, types Paper Trading does not use.
The *models* and the resulting `backtest.fills.Fill` type are reused
unchanged (ADR-0021 §1). A fill is capped at
`floor(bar.volume * PaperTradingConfig.max_participation)` — Phase 2's
own default (`0.10`). `partial_fill_enabled=False` makes an order
all-or-nothing per attempt: it fills nothing at all until a single
bar's liquidity can satisfy the full remaining quantity.

`PaperMarketDataSource` (`broker/paper/market_data.py`) is always
caller-supplied — `broker.paper.*` never imports `data_infra.
repository`/`backtest.asof` (matching Phase 13's own point-in-time
boundary, `tests/broker/paper/test_paper_boundary.py`). `advance_simulation(as_of)`
is the explicit, Paper-only hook that lets an open order attempt a
further fill as more market data becomes available — never part of the
`BrokerAdapter` Protocol itself, since neither `MockBrokerAdapter` nor
`TossBrokerAdapter` has an equivalent notion of "advance simulated
time."

## 5. Slippage & Transaction Cost

`PaperTradingConfig` exposes `commission_fixed_per_trade`/
`commission_per_share`/`spread_bps`/`slippage_bps` — the exact same
fields `backtest.costs.TransactionCostModel`/`FixedBpsSlippageModel`
already accept (Phase 2), constructed fresh from config rather than
storing model instances directly on the frozen config dataclass. Every
field can be set to `0.0` for a zero-cost diagnostic run, but the
non-zero Phase 2 defaults (`fixed_per_trade=1.0`, `per_share=0.005`,
`spread_bps=2.0`, `slippage_bps=5.0`) are what a fresh
`PaperTradingConfig()` uses — a zero-cost run is always an explicit
override (ADR-0007's Phase 2 precedent, reused unchanged).

## 6. Account & Position Model

`PaperBrokerAdapter` holds one `backtest.portfolio.PortfolioAccounting`
instance (Phase 2) — average-cost-basis accounting, realized PnL
computed on every `SELL` fill exactly as Phase 2's own backtests
already compute it. This directly reuses Phase 2's documented Known
Limitation (`docs/specifications/PHASE-2-backtesting.md` §8.1:
average-cost, not FIFO tax lots) rather than silently fixing or
re-deriving a different convention — Phase 8's own average-cost-proxy
Known Issue is about *portfolio-level risk-limit* accounting
(sector/factor data absence), a different layer entirely, and is
unaffected by this reuse (§17 below).

`get_account`/`get_positions` read `PortfolioAccounting.snapshot_view`
directly — `BrokerAccountSnapshot.cash`/`BrokerPosition.average_cost`
are never independently tracked fields that could drift from the
accounting object's own state.

## 7. Fail-Closed Behavior

| Situation | Result |
|---|---|
| No market data available yet for a security | order stays `PENDING` — never a guessed price |
| Insufficient cash discovered on the very first fill attempt | order `REJECTED`, reason `insufficient_cash` |
| Insufficient cash discovered on a *later* fill attempt (already partially filled) | no further fill this attempt; already-filled quantity is not reversed |
| `SELL` exceeds current holding and `allow_short=False` | order `REJECTED` at submission, reason `insufficient_position` — never fills a portion and shorts the rest |
| `maximum_order_quantity`/`maximum_notional` exceeded | order `REJECTED` at submission, before any market-data lookup |
| `failure_mode="malformed"` | `BrokerOrderStatus.UNKNOWN`, `error_code="malformed_response"` — never a fabricated success, no fill applied |
| `failure_mode="unknown_status"` | `get_order_status` always returns `UNKNOWN`, even after a real fill happened — `UNKNOWN ≠ FILLED` (`tests/broker/paper/test_paper_accounting_invariants.py::TestUnknownNeverTreatedAsFilled`) |
| `failure_mode` in `{unavailable, timeout, auth, rate_limit}` | the matching typed exception (`BrokerTransportError`/`BrokerTimeoutError`/`BrokerAuthError`/`BrokerRateLimitError`) raised on every call |
| Cancel a `FILLED` order | `error_code="already_filled"` — cancellation itself is refused, no state change |
| Cancel an unknown `client_order_id` | `BrokerOrderStatus.UNKNOWN` |
| Duplicate `client_order_id` submission | the existing response is returned, no second fill (`tests/broker/paper/test_paper_adapter.py::TestIdempotency`) |

## 8. Paper vs. Live Safety Boundary

`PaperTradingConfig.environment` accepts only the literal `"paper"` —
`__post_init__` raises on any other value, so a `PaperTradingConfig`
can never represent a live configuration by construction. `broker.
paper.guard.assert_paper_environment_safe(environment, broker)` is a
defense-in-depth check for a future higher-level trading-engine
dispatcher: it `isinstance`-checks the given `broker` against
`broker.toss.adapter.TossBrokerAdapter` and raises if `environment ==
"paper"` and the check matches — the *only* place `broker.paper.*`
references that class, and only for this negative check (never
constructed or called, `tests/broker/paper/test_paper_boundary.py::
TestNoTossImportExceptGuard::test_guard_py_never_constructs_or_calls_toss_adapter`).

## 9. Idempotency & Restart Safety

`PaperBrokerAdapter` itself is a purely in-memory, deterministic
simulation core with no repository dependency (mirrors `broker.mock.
MockBrokerAdapter`'s design, Phase 13) — restart safety lives entirely
in the orchestration layer, `broker.paper.session.PaperTradingSession`:

- `session.submit`/`session.advance`/`session.cancel` each call the
  adapter, then persist whatever new `PaperOrderRecord`/
  `OrderStatusObservation`/`PaperFillRecord`s resulted.
- `session.capture(client_order_id, as_of=...)` is the same persistence
  step exposed separately, so a caller driving the adapter through
  `broker.pipeline.submit_validated_order` directly (to also get the
  generic `broker_requests`/`broker_responses` audit trail) can still
  sync Paper's own richer state afterward.
- `PaperTradingSession.restore(...)` rebuilds a fresh adapter's entire
  state by replaying every persisted `PaperOrderRecord` (registers
  order intent, no re-validation) and then every persisted
  `PaperFillRecord` (applies to a fresh `PortfolioAccounting`, in the
  order they were originally recorded) — never re-running
  `failure_mode`/cash-check logic, only reproducing what already
  happened. `order_status_events` supplies the one piece of state not
  derivable from fills alone: which orders were explicitly cancelled.

`tests/storage/test_paper_repository.py::TestFullSessionRestartAgainstDuckDB`
proves cash and positions are byte-identical before and after a
simulated process restart against a real DuckDB catalog file.

## 10. Trade Journal Integration

`broker/paper/journal.py::build_trade_record` bridges a
`PaperFillRecord` into `trade_journal.models.TradeRecord` (Phase 3)
directly — `TradeRecord.fill: Fill` already nests the exact type Paper
Trading's own fills are (`backtest.fills.Fill`), so no conversion is
needed beyond field mapping. `provenance` is always
`TradeProvenance.PAPER_TRADING`
(`PROJECT_MASTER_PLAN.md` §10.7's "Historical vs Live 구분은 필수다").
The integration test additionally demonstrates
`storage.trade_journal_repository.DuckDBTradeJournalRepository.
record_trade` (Phase 3's own persistence method, unmodified) accepting
a Paper fill directly — no separate Paper-only journal table exists.

## 11. Monitoring Integration

Phase 14's `monitoring.collectors.collect_broker`/`monitoring.metrics.
compute_broker_metrics` are generic over `BrokerRequestRecord`/
`BrokerResponseRecord` regardless of `broker_id` — Paper Trading's own
audit trail (persisted via `broker.pipeline.submit_validated_order`,
exactly as Phase 13 already does) is observed by that same collector
completely unmodified
(`tests/integration/test_paper_trading_lineage.py`). No change was made
to `src/monitoring/*.py`. `paper_account_equity`/`paper_cash`/
`paper_pnl`/`paper_drawdown` are available from
`PaperTradingSession.account_summary()` as a plain, caller-readable
snapshot, but are **not** yet wired into a `MonitoringEvent` — doing so
honestly requires either extending `monitoring.enums.
MonitoringComponent` or folding Paper-specific fields into the existing
generic broker metrics, a design decision deliberately left to a future
session rather than half-implemented here (§17, Known Limitations).

## 12. Persistence

Two new tables in Phase 4's existing DuckDB catalog file
(`src/storage/schema.py`, purely additive — `git diff src/storage/
schema.py src/storage/serialization.py | grep '^-'` shows zero
deleted/changed lines against the Phase 14 baseline):

- `paper_orders` — dedupe on the caller-assigned `client_order_id`
  directly (the same `ai_requests`/`broker_requests` pattern) — wraps
  `broker.models.ValidatedOrder` (Phase 13) rather than a new order
  representation.
- `paper_fills` — append-only (seq-ordered), the same
  `provider_quota_states`/`model_status_transitions` pattern — wraps
  `backtest.fills.Fill` (Phase 2) rather than a new fill representation.

Order status history reuses Phase 13's `order_status_events` table
unchanged. Request/response audit reuses Phase 13's `broker_requests`/
`broker_responses` tables unchanged, when a caller drives Paper
Trading through `broker.pipeline.submit_validated_order`.

## 13. Test Strategy

| Category | File |
|---|---|
| Order lifecycle / fills / idempotency / cancellation / failure modes | `tests/broker/paper/test_paper_adapter.py` |
| Execution math (spread/slippage/participation cap) | `tests/broker/paper/test_paper_execution.py` |
| Configuration validation | `tests/broker/paper/test_paper_config.py` |
| Accounting invariants (cash/position/UNKNOWN≠FILLED/cost signs) | `tests/broker/paper/test_paper_accounting_invariants.py` |
| Boundary (no Toss/network/secret access, live-broker guard) | `tests/broker/paper/test_paper_boundary.py` |
| Leakage / point-in-time | `tests/broker/paper/test_paper_leakage.py` |
| Reproducibility | `tests/broker/paper/test_paper_reproducibility.py` |
| Session orchestration + in-memory restart | `tests/broker/paper/test_paper_session.py` |
| Trade Journal bridge | `tests/broker/paper/test_paper_journal.py` |
| In-memory repository | `tests/broker/paper/test_paper_repository_inmemory.py` |
| Persistence / restart (DuckDB) | `tests/storage/test_paper_repository.py` |
| Integration lineage (SQL join, Monitoring reuse, Trade Journal, restart) | `tests/integration/test_paper_trading_lineage.py` |

## 14. Point-in-Time

`InMemoryPaperMarketDataSource.get_reference_bar` only ever considers
bars whose `PriceBar.available_time <= as_of` — a bar registered "in
the future" relative to a given `as_of` is structurally invisible
regardless of when it was added to the source object
(`tests/broker/paper/test_paper_leakage.py`). Every adapter method that
touches market data or order state requires an explicit timestamp
(`requested_at`/`as_of`) with no default (`inspect.signature`
verified); nothing in `broker.paper.*` calls
`datetime.now()`/`datetime.utcnow()` (AST-verified).

## 15. Reproducibility

No module in `broker.paper.*` imports `random`
(`tests/broker/paper/test_paper_reproducibility.py`, an AST scan). The
fill model is entirely deterministic (participation-capped, no
probabilistic component) — `PaperTradingConfig.seed` is reserved for a
future probabilistic extension, unused by the current logic. The same
input sequence (config + market data + order sequence) always produces
byte-identical orders/fills/cash/positions.

## 16. Known Limitations

- **No always-on Trading Engine loop.** This phase builds
  `PaperTradingSession`'s primitives (`submit`/`advance`/`cancel`); a
  scheduled process that calls `advance` on a timer against live-ish
  market data is not built here (§1.1).
- **`paper_account_equity`/`paper_pnl`/`paper_drawdown` are not yet a
  `MonitoringEvent`.** `PaperTradingSession.account_summary()` exposes
  them as a plain snapshot; wiring that into Phase 14's Monitoring
  requires a design decision (new `MonitoringComponent` member vs.
  folding into existing broker metrics) intentionally left open (§11).
- **Average-cost-basis accounting, not FIFO tax lots** — inherited
  unchanged from Phase 2's own documented Known Limitation (§6);
  unaffected by, and unrelated to, Phase 8's separate
  average_cost-proxy Known Issue (portfolio-level risk-limit
  accounting, §17 of `docs/PROJECT_STATUS.md`).
- **No `LIMIT` order support**, matching Phase 13's own precedent (§1.1)
  — no upstream layer supplies a limit price yet.

## 17. Definition of Done

- [x] Implementation matching this spec
- [x] Unit + integration tests, all passing (see completion report for exact counts)
- [x] Fail-closed handling: `UNKNOWN` is never coerced to `FILLED`; a
      metric/status that cannot be honestly computed is never fabricated
- [x] Logging/audit: `paper_orders`/`paper_fills` plus reused
      `order_status_events`/`broker_requests`/`broker_responses` is the
      durable record of every operation
- [x] Documentation: this spec + ADR-0021
- [x] Configuration: `PaperTradingConfig` — every threshold explicit and
      validated, `environment` structurally fixed to `"paper"`
- [x] Validation: structural boundary tests confirm no live-broker call,
      no secret/network access, and no Decision/Risk mutation
