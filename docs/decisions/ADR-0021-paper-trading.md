# ADR-0021: Paper Trading

## Context

`PROJECT_MASTER_PLAN.md` §9.4 already specifies the target shape:

```
Trading Engine → Broker Interface → Paper Broker   (개발/검증 기본값)
Trading Engine → Broker Interface → Toss Broker    (Live에서만, 명시적 활성화 후)
```

Phase 13 already built the `Broker Interface` half of this
(`broker.protocol.BrokerAdapter`) and its one real implementation
(`broker.toss.adapter.TossBrokerAdapter`), plus a minimal
`broker.mock.MockBrokerAdapter` used only to prove the Protocol and
exercise backtest integration. The handoff for this session is explicit
that Paper Trading is not a repeat of that minimal mock — it must be a
"production-like execution environment": deterministic, auditable,
restart-safe, point-in-time-safe, fail-closed, idempotent, observable,
reproducible, while never sending a real order.

This session's Git/Branch Integrity Check (see
`docs/specifications/PHASE-15-paper-trading.md` §0) found the
repository in a clean, correctly-lineaged state on the prior session's
`claude/phase-14-monitoring` branch and created
`claude/phase-15-paper-trading` from that verified HEAD.

The central design tension this ADR resolves: build a genuinely richer
simulation (partial fills over time, real cost/slippage math, average-
cost accounting, restart safety) without duplicating logic Phase 2
already built and tested for an almost identical purpose
(`backtest.fills.FillSimulator`/`backtest.costs.*`/`backtest.portfolio.
PortfolioAccounting`), and without violating Phase 13's own
"never call `data_infra.repository`/`backtest.asof` directly" boundary.

## Decision

### 1. Reuse Phase 2's cost models, `Fill` type, and `PortfolioAccounting`
   directly -- never re-derive an equivalent shape

`backtest.costs.TransactionCostModel`/`FixedBpsSlippageModel` and
`backtest.fills.Fill` already express exactly what Paper Trading needs:
a reference price, spread/slippage adjustment, and a commission
function. `backtest.portfolio.PortfolioAccounting.apply_fill` already
implements average-cost-basis bookkeeping and realized-PnL computation
over that same `Fill` type, tested since Phase 2. `broker.paper.
execution.simulate_fill` re-derives `FillSimulator.execute`'s exact
math rather than calling `FillSimulator` itself, only because
`FillSimulator` is coupled to `backtest.orders.Order`/`backtest.
portfolio.PortfolioView` — types this phase does not use (a
`ValidatedOrder` plus a remaining-quantity float is enough context) —
but the *models* and the resulting `Fill` object are the identical
Phase 2 types, unchanged. `PaperBrokerAdapter` holds one
`PortfolioAccounting` instance directly rather than a parallel account
class. This is instruction section 4/28's own explicit ask ("Paper
전용 shortcut으로 core trading logic을 복제하지 않는다") taken as far
as the type system allows.

### 2. Market data is always caller-supplied via a `PaperMarketDataSource`
   Protocol -- the adapter never queries `data_infra`/`backtest.asof`
   itself

Phase 13's own point-in-time boundary test
(`tests/broker/test_broker_point_in_time.py`) already established that
nothing in `broker.*` imports `data_infra.repository`/`backtest.asof`.
Paper Trading genuinely needs market data to simulate a fill, so the
same discipline `broker.validation.build_validated_order` already
applies to `current_quantity` ("must be supplied by the caller") is
generalized here: a caller builds a `PaperMarketDataSource` from
whatever point-in-time-safe accessor it already has and hands the
finished object to `PaperBrokerAdapter`'s constructor. Because
`requested_at`/`as_of` are already required parameters on every
`BrokerAdapter` Protocol method, no *new* parameter is needed on the
Protocol surface itself — only the constructor gains a dependency.
`InMemoryPaperMarketDataSource.get_reference_bar` enforces point-in-time
safety structurally, filtering to `PriceBar.available_time <= as_of`
before ever returning a bar.

### 3. `advance_simulation` is a Paper-only method, not part of the
   `BrokerAdapter` Protocol

A real broker doesn't need to be told "more time has passed, check for
new fills" — it pushes state changes to the caller (or the caller polls
`get_order_status`, which itself is a pure read in this codebase's
established discipline, matching `MockBrokerAdapter`'s side-effect-free
reads). Paper Trading, uniquely, needs an explicit mechanism to let an
open order attempt further fills as simulated market data becomes
available over multiple ticks. Adding this to the shared `BrokerAdapter`
Protocol would force `MockBrokerAdapter`/`TossBrokerAdapter` to
implement a method that means nothing for either of them. Keeping it
Paper-specific (and outside the Protocol) means `broker.pipeline.
submit_validated_order`/any other caller written against `BrokerAdapter`
in the abstract continues to work unchanged, while a caller that knows
it's driving Paper Trading specifically (`PaperTradingSession`) can use
the richer, adapter-specific surface.

### 4. `PaperBrokerAdapter` itself never persists anything -- restart
   safety lives entirely in `PaperTradingSession`

`broker.mock.MockBrokerAdapter` (Phase 13) is purely in-memory with no
repository dependency; the discipline that separates "call the adapter"
from "persist what happened" already lives in `broker.pipeline.
submit_validated_order`. Paper Trading needs richer persisted state
than a generic request/response log (individual fills with a cost
breakdown, enough to reconstruct cash/positions on restart) — rather
than have the adapter itself grow repository dependencies (breaking
parity with `MockBrokerAdapter`'s design and complicating every unit
test that just wants a deterministic adapter with no I/O),
`broker.paper.session.PaperTradingSession` wraps a `PaperBrokerAdapter`
instance and owns all persistence, exposing `submit`/`advance`/`cancel`
(call + persist) and a `restore(...)` classmethod (replay persisted
orders, then persisted fills, into a fresh adapter instance) for
restart safety. `session.capture(client_order_id, as_of=...)` exposes
the persistence half separately, so a caller that drives the adapter
through `broker.pipeline.submit_validated_order` directly (to also get
the generic Phase 13 audit trail) can still sync Paper's own richer
state afterward without double-submitting the order.

### 5. Two new tables (`paper_orders`, `paper_fills`); everything else
   reuses Phase 13's existing schema unchanged

`order_status_events` (Phase 13) already fits `OrderStatusObservation`
exactly, including a `broker_id` column that already differentiates
Paper from Toss — reusing it needs zero schema changes.
`broker_requests`/`broker_responses` (Phase 13) are already generic
over any `broker_id`; when a caller drives Paper Trading through
`broker.pipeline.submit_validated_order`, that audit trail is already
fully captured with zero new schema. The two genuinely new pieces of
information no existing table captures are: (a) a fill's individual
cost breakdown (commission/spread/slippage) over time (`BrokerOrderResponse`
only carries an aggregate `filled_quantity`/`avg_fill_price`), and (b)
the original order's requested quantity, needed on restart to know when
an order transitions `PARTIAL_FILLED → FILLED` (not derivable from fills
alone, since a `REJECTED` order has no fills at all but is still a
terminal outcome worth recording). `paper_orders` wraps `broker.models.
ValidatedOrder` directly (already exactly the right shape); `paper_fills`
wraps `backtest.fills.Fill` directly, plus the `fill_id`/`client_order_id`
identity fields Paper's own audit needs.

### 6. `PaperOrderRecord`/`paper_orders` dedupe on the caller-assigned
   `client_order_id`; `PaperFillRecord`/`paper_fills` are append-only

The same distinction ADR-0018 §4/ADR-0019 §4/ADR-0020 §5 already
established applies unchanged: an order submission is an event-log
entry (the same `ai_requests`/`broker_requests` shape — the caller
already assigns a deterministic, unique `client_order_id`, so trusting
it directly is correct), while a fill is a "one observation per point
in time" history record, the same shape as `ProviderQuotaState`/
`ModelStatusTransition`.

### 7. Trade Journal integration reuses `trade_journal.models.TradeRecord`
   directly -- no new Paper-only journal type

`TradeRecord.fill: Fill` (Phase 3) already nests the exact type Paper
Trading's own fills are. `broker.paper.journal.build_trade_record` is a
pure mapping function from a `PaperFillRecord` to a `TradeRecord`, and
the integration test additionally demonstrates `storage.
trade_journal_repository.DuckDBTradeJournalRepository.record_trade`
(Phase 3's own persistence method) accepting a Paper fill without any
modification — `provenance=TradeProvenance.PAPER_TRADING` is the only
thing that distinguishes a Paper trade from any other in that table
(`PROJECT_MASTER_PLAN.md` §10.7).

### 8. Monitoring integration reuses `monitoring.collectors.collect_broker`
   unmodified; richer Paper-specific metrics are deliberately left
   unwired this phase

Phase 14's broker collector is already generic over `broker_id` — Paper
Trading's request/response audit trail (when persisted via `broker.
pipeline.submit_validated_order`) is observed by it with zero code
change on either side. `paper_account_equity`/`paper_cash`/`paper_pnl`/
`paper_drawdown` are real, computable values
(`PaperTradingSession.account_summary()` exposes them as a plain
snapshot), but wiring them into a `MonitoringEvent` honestly requires a
design decision this phase does not make on its own: either add a new
`MonitoringComponent` member (touching Phase 14's closed enum) or fold
account-level metrics into the existing generic broker metrics (a
mismatch — those are per-request/response, not per-account-snapshot).
Rather than force one of those choices without explicit direction, this
phase surfaces the raw data honestly and leaves the wiring decision
open (`docs/specifications/PHASE-15-paper-trading.md` §16, Known
Limitations) — matching this project's own discipline of marking an
unconfirmed/undone piece explicitly rather than half-implementing it
(the same posture Phase 13 took toward Toss's unconfirmed endpoints).

## Alternatives Considered

1. **Give `PaperBrokerAdapter` a `DataRepository`/`AsOfDataView`
   dependency directly, so it can fetch its own market data.** Rejected
   — see decision 2; directly violates Phase 13's own established
   point-in-time boundary (`broker.*` never imports `data_infra.
   repository`/`backtest.asof`), and would make the adapter's behavior
   depend on an external data layer's own correctness rather than being
   a self-contained, easily-unit-tested simulation core.
2. **Reuse `backtest.fills.FillSimulator`/`backtest.broker.
   BrokerInterface` directly instead of `broker.protocol.BrokerAdapter`.**
   Rejected — `backtest.broker.BrokerInterface` is Phase 2's own,
   narrower Protocol (`submit_order(order, execution_bar, portfolio,
   execution_time)`), coupled to the synchronous, single-step backtest
   loop; Phase 13's `BrokerAdapter` is the one Core Trading Logic
   (Decision → Risk → Order Validation) actually depends on today, and
   instruction section 4 explicitly asks for that exact Protocol to be
   reused "가능한 한 그대로."
3. **Model partial fills as a probabilistic/randomized process** (e.g.
   random fill ratios to simulate realistic order-book uncertainty).
   Rejected — instruction section 17 explicitly asks for a deterministic
   simulation with an auditable seed if randomness is ever needed;
   participation-capped, volume-driven partial fills are already
   realistic and fully deterministic without needing one.
4. **A single "Paper Account" persisted snapshot table**, updated after
   every fill, instead of replaying `paper_fills` on restart. Rejected —
   see decision 5; a redundant snapshot can drift from the fills that
   produced it (a real defect class this project has already
   encountered once, ADR-0015 §6/ADR-0017 §7's id-collision fix); ground
   truth (`paper_fills`) plus deterministic replay (`PortfolioAccounting.
   apply_fill`) has no such drift risk by construction.
5. **Wire `paper_account_equity`/`paper_pnl`/`paper_drawdown` into a new
   `MonitoringComponent.PAPER_TRADING` immediately.** Rejected for this
   phase — see decision 8; touching Phase 14's closed enum is a real,
   cross-phase design decision this instruction did not explicitly
   direct, and the project's own discipline (per instruction section 43,
   "DECISION REQUIRED") is to surface such a choice rather than make it
   silently. The raw data remains available and honestly documented as
   not yet wired.

## Consequences

### Positive

- Zero modifications to Phase 1-14 source files; `git diff | grep '^-'`
  on `src/storage/schema.py` and `src/storage/serialization.py` shows no
  deleted/changed lines, only additions.
- No code path anywhere in `broker.paper.*` can reach a real broker, a
  real credential, or a real network call — verified structurally (AST
  scan), not by convention; the one reference to `TossBrokerAdapter`
  (`guard.py`) is `isinstance`-only and itself tested to never construct
  or call it.
- Cash, positions, and order status are provably byte-identical before
  and after a simulated process restart against a real DuckDB catalog
  file, proven by an actual test rather than asserted.
- The full `Risk → ValidatedOrder → PaperBrokerAdapter → Fill → Trade
  Journal → Monitoring` chain is demonstrated end to end in one
  integration test, reusing four different prior phases' own
  persistence/observation code completely unmodified.

### Negative / Trade-offs

- `paper_account_equity`/`paper_pnl`/`paper_drawdown` are not yet
  observable through Phase 14's Monitoring event stream — a future
  session must make the `MonitoringComponent` extension decision this
  one deliberately deferred (§16 of the spec).
- No always-on Trading Engine loop exists yet — `PaperTradingSession`
  provides the primitives (`submit`/`advance`/`cancel`/`restore`), but
  nothing in this repository currently drives them on a schedule against
  live-ish data; that orchestration is left to a future phase.
- Average-cost-basis accounting (inherited from Phase 2 unchanged) means
  Paper Trading cannot distinguish tax lots the way a FIFO-lot broker
  would — an intentional, documented limitation, not an oversight.
