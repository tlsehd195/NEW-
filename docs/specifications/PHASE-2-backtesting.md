# PHASE 2 SPECIFICATION — Backtesting

**Status:** ACTIVE (design confirmed, reference implementation in progress)
**Phase:** Phase 2 — Backtesting
**Depends on:** `PROJECT_MASTER_PLAN.md`, `docs/decisions/ADR-0001-master-architecture.md`,
Phase 1 (`docs/specifications/PHASE-1-data-infrastructure.md`,
ADR-0002..0005, `src/data_infra/*`)
**Produces ADRs:** ADR-0006 (backtest broker & execution timing),
ADR-0007 (transaction cost & slippage model), ADR-0008 (validation
protocol)
**Open decision:** §9.3 below — benchmark return-type — is raised as
`DECISION REQUIRED`, not resolved unilaterally in this document.

---

## 0. Purpose of This Document

Phase 1 guaranteed that the system can answer, for any past moment,
exactly what data was available then, and can trace any result back to
the data version that produced it. Phase 2 is where those guarantees are
first put to use: it builds the mechanism that replays history bar by
bar, feeds a strategy only what it could have known at each step,
simulates realistic order execution and cost, and produces a performance
report that can be honestly compared against a benchmark.

The goal of Phase 2 is **not** to produce an impressive backtest return.
Per the initialization instruction for this phase:

> "높은 백테스트 수익률을 만드는 것"이 목표가 아니다. "실전에서 믿을 수
> 있는 검증 방법을 만드는 것"이 Phase 2의 목표다.

Every design choice below is evaluated against that standard: does it
make the backtest more trustworthy, or does it just make results look
better? Where a convenient choice would make results look better while
making them less trustworthy (e.g., filling orders at a price that
could not actually have been traded), the trustworthy choice is taken,
even at the cost of a strategy looking worse than a naively-implemented
version of it would.

---

## 1. Scope

### 1.1 In scope for Phase 2

- A `BacktestEngine` that replays a historical period day-by-day, using
  only Phase 1's `DataRepository` (as-of-bound) for all data access.
- A `BacktestClock` and an `AsOfDataView` that make it **structurally
  impossible** for strategy code to request data beyond the current
  simulated time (not just a documented convention — see §3.2).
- A minimal `Strategy` interface, generic enough that a future ML-based
  strategy (Phase 6+) can implement it without changes, plus two
  concrete baseline strategies: S&P 500 Buy & Hold and a long-only Simple
  Momentum strategy (§10).
- Order/fill simulation: market orders, a structurally-reserved (not yet
  implemented) limit order type, partial fills under a liquidity cap,
  rejection on insufficient cash or insufficient position, explicit
  order/execution timestamps (§6).
- A Transaction Cost Model (commission + spread) and a Slippage Model
  (fixed bps, plus a volume-scaled variant demonstrating the extension
  point for a future market-impact model) (§7).
- Portfolio accounting: cash, positions (average-cost basis), market
  value, realized/unrealized PnL, turnover, transaction costs — all
  computed deterministically and reproducibly (§8).
- Corporate action application during a backtest: stock splits adjust
  held quantity and cost basis; dividends credit cash. Applied only when
  `available_time <= as_of_time`, using the exact same look-ahead guard
  Phase 1 already enforces at the data layer (§8.4).
- A `BenchmarkEngine` computing S&P 500 Buy & Hold performance over the
  identical period/capital/data version for a fair comparison (§9).
- Performance metrics: cumulative return, CAGR, annualized volatility,
  Sharpe, Sortino, max drawdown, Calmar ratio, turnover, transaction
  cost, win rate, average trade return, and benchmark-relative figures
  (excess return, annualized excess return, drawdown/risk comparison)
  (§11).
- A `BacktestIntegrityChecker` that runs during/after every backtest and
  can mark a result `FAILED`/`CRITICAL_FAILURE`, in which case the
  result is not to be treated as a legitimate performance outcome (§12).
- `ExperimentRecord`/`ExperimentTracker` giving every backtest run a
  unique id and a full reproducibility record (§13).
- A minimal validation-split utility: chronological train/test split and
  a `WalkForwardSplitter`, plus a `ValidationSplitter` extension point
  reserved (not implemented) for Purged K-Fold/Embargo (§14, ADR-0008).
- Leakage tests for every category named in the Phase 2 initialization
  instruction (§4, §16).

### 1.2 Out of scope for Phase 2

- Real trading, Toss Securities integration, AI/LLM API calls, Live
  Trading — none of this is touched in this phase, per explicit
  instruction.
- Market Regime Detection, Prediction/Signal Engine, the full Decision
  Agent, Position Sizing, and the Portfolio Risk Engine as described in
  `PROJECT_MASTER_PLAN.md` §20-25 — those are Phase 5-8. Phase 2's
  `Strategy` interface is intentionally simpler: baseline strategies
  compute their own signal and emit order intents directly, without a
  separate regime/prediction/risk layer. The interface is shaped so a
  later phase can insert those layers without changing
  `BacktestEngine`.
- Limit order execution logic (the `OrderType.LIMIT` enum value exists
  for interface extensibility; using it raises `NotImplementedError` in
  Phase 2 — see §6.1).
- Full market-impact modeling (Almgren & Chriss's optimal execution
  model informs the *shape* of the extension point — see §7.3 — but a
  calibrated impact model is not built now).
- Purged K-Fold cross-validation and embargo periods (interface reserved,
  not implemented — §14, ADR-0008).
- A persistent `ExperimentRecord` store (Phase 2 ships an in-process
  `ExperimentTracker`; durable storage is future work, consistent with
  Phase 1 also deferring its DuckDB/Parquet backend).
- A Simple-ML baseline strategy (§10.3 — only the interface is kept open
  for one; no model is trained in this phase).
- Full historical S&P 500 constituent/dividend data acquisition (Phase 2
  continues to use Phase 1's mock datasets, extended with a longer date
  range for realistic multi-month simulation).

---

## 2. Phase 1 Data Layer — What Phase 2 Builds On

Re-confirmed by direct inspection of `src/data_infra/` before writing
this spec (no conflicts found — see §17):

- `DataRepository` (`src/data_infra/repository.py`) exposes
  `get_bars(security_id, start, end, as_of_time)`,
  `get_security(security_id, as_of_time)`,
  `get_corporate_actions(security_id, start, end, as_of_time)`,
  `get_trading_calendar(market)`, `get_benchmark(benchmark_id, start,
  end, as_of_time)`, `get_universe(market, universe, as_of_time)`. Every
  time-sensitive method requires `as_of_time`; there is no
  overload that omits it.
- The **look-ahead guard is enforced inside the repository**: any record
  with `available_time > as_of_time` is filtered out before it reaches
  the caller (verified again by re-reading `repository.py` — every
  as-of method applies this filter directly).
- `PriceBar` carries one `available_time` for the **entire bar**
  (open/high/low/close/volume together) — there is no separate,
  earlier availability timestamp for the intraday open. This has a
  direct, material consequence for backtest execution timing, resolved
  in §6.2/ADR-0006.
- `UniverseMembership.is_member_at(at_time)` and
  `DataRepository.get_universe(market, universe, as_of_time)` support
  survivorship-bias-safe universe queries, already tested in Phase 1
  (`tests/data/test_survivorship.py`).
- `CorporateAction` distinguishes `event_time` / `announcement_time` /
  `effective_time` / `available_time`, with a generic `details: dict`
  payload (Phase 1 only populates `SPLIT` and `DIVIDEND` semantics in
  its mock data/tests).
- `Provenance` (`source`, `source_dataset`, `source_record_id`,
  `retrieved_at`, `data_version`, `schema_version`) is composed into
  every time-series record — Phase 2's `ExperimentRecord` records the
  `data_version`(s) actually read during a run for reproducibility
  (§13).
- `DataQualityFramework` (`src/data_infra/quality.py`) is a pre-storage
  concern (Raw→Clean promotion); Phase 2 does not re-run it, but
  `BacktestIntegrityChecker` (§12) plays an analogous role at the
  *simulation* level (are the mechanics of the replay itself sound),
  which is a different concern from data quality.
- Phase 1's test suite (`tests/data/`, 57 tests) is unaffected by Phase
  2; Phase 2 adds `tests/backtest/` alongside it. Both suites must pass
  together (verified in §18).

---

## 3. Architecture

### 3.1 Layer diagram

```
                    DataRepository (Phase 1, as-of aware)
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │ AsOfDataView              │  binds as_of_time to
                    │ (asof.py)                 │  BacktestClock.current_time;
                    └──────────────┬────────────┘  no as_of_time parameter
                                   │                exists on this view at all
                                   ▼
                    ┌─────────────────────────┐
                    │ BacktestClock              │  drives the simulation
                    │ (clock.py)                 │  forward one trading day
                    └──────────────┬────────────┘  at a time
                                   │
                                   ▼
                    ┌─────────────────────────┐
                    │ Strategy                   │  generate_orders(as_of_time,
                    │ (strategy.py)              │  data_view, portfolio_view)
                    └──────────────┬────────────┘  -> list[OrderIntent]
                                   │
                                   ▼
                    ┌─────────────────────────┐
                    │ OrderSimulator              │  validates cash/position
                    │ (orders.py)                 │  constraints -> Order
                    └──────────────┬────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────┐
                    │ FillSimulator               │  T+1-close execution,
                    │ (fills.py)                  │  partial fill, cost+slippage
                    └──────────────┬────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────┐
                    │ BacktestBroker               │  Broker Interface impl
                    │ (broker.py)                  │  (Backtest today; Paper/
                    └──────────────┬────────────┘  Toss later, same interface)
                                   │
                                   ▼
                    ┌─────────────────────────┐
                    │ PortfolioAccounting          │  cash, positions, PnL,
                    │ (portfolio.py)                │  turnover, tx costs
                    └──────────────┬────────────┘
                                   │
                    ┌──────────────┴────────────┐
                    ▼                            ▼
        ┌─────────────────────┐      ┌─────────────────────────┐
        │ CorporateActionApplier│      │ BacktestIntegrityChecker │
        │ (corporate_actions.py)│      │ (integrity.py)           │
        └─────────────────────┘      └─────────────────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────┐
                    │ BenchmarkEngine + Metrics    │  benchmark.py, metrics.py
                    └──────────────┬────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────┐
                    │ ExperimentTracker             │  experiment.py
                    └─────────────────────────┘
```

`engine.py::BacktestEngine` owns the loop and wires all of the above
together; no component reaches into another's internals.

### 3.2 The look-ahead guard, extended into the simulation layer

Phase 1's guard prevents `DataRepository` from *returning* future data.
Phase 2 adds a second, independent guard: strategy code never even holds
a reference to `DataRepository` or to an `as_of_time` parameter it could
set itself. It only ever receives an `AsOfDataView`, whose methods have
exactly the same names as `DataRepository`'s **minus the `as_of_time`
parameter** — that value is read from the `BacktestClock` internally on
every call. There is no method, override, or parameter on
`AsOfDataView` through which a well-behaved `Strategy` implementation
could request a later `as_of_time`. This mirrors the Phase 1 design
principle (ADR-0004: "no method exists that returns data regardless of
as_of_time") one layer higher, and is why the no-lookahead tests in §18
test the *view*, not just the underlying repository.

(Caveat, stated plainly: Python cannot stop a strategy from importing
`data_infra.repository` directly and calling it with a self-chosen
`as_of_time`. The guard removes the *accidental* path to leakage — the
one every real strategy implementation actually uses — not adversarial
bypass. This is the same class of guarantee Phase 1 already accepted for
its own guard.)

---

## 4. Look-ahead / Leakage Categories and How Each Is Prevented

| Leakage category | Mechanism that prevents it | Verified by |
|---|---|---|
| Future price leakage | `AsOfDataView.get_bars` never exposes `as_of_time`; bound to `BacktestClock.current_time`, which only ever holds the *current* simulated checkpoint | `tests/backtest/test_no_lookahead.py` |
| Future feature leakage | Out of scope in Phase 2 (no Feature Engine yet — Phase 5+); the same `AsOfDataView` mechanism will apply to Feature Repository access once built, and this spec's §3.2 guard pattern is the one Phase 5 must reuse | N/A this phase — flagged as a design carry-forward, not tested here |
| Future corporate action leakage | `AsOfDataView.get_corporate_actions` same binding as above; `CorporateActionApplier` only applies an action once `available_time <= current_time` | `tests/backtest/test_corporate_actions.py` |
| Future universe membership leakage | `AsOfDataView.get_universe` same binding; `BacktestEngine` resolves the tradable universe fresh at every checkpoint, never once at setup time | `tests/backtest/test_survivorship.py` |
| Survivorship bias | Universe membership resolved per-checkpoint via `UniverseMembership.is_member_at`, not a single "current" list applied to all history (reuses Phase 1 §8 mechanism end-to-end through a full backtest run) | `tests/backtest/test_survivorship.py` |
| Execution timing leakage | Orders decided using checkpoint `T`'s data are never filled at a price from checkpoint `T` or earlier — always at `T+1`'s close, the first bar not yet knowable at decision time (§6.2) | `tests/backtest/test_execution_timing.py` |

---

## 5. Strategy Interface

```python
class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

@dataclass(frozen=True)
class OrderIntent:
    security_id: str
    side: OrderSide
    quantity: float           # shares; Phase 2 baseline strategies are long-only
    order_type: OrderType = OrderType.MARKET

class Strategy(Protocol):
    def generate_orders(
        self, as_of_time: datetime, data: AsOfDataView, portfolio: PortfolioView
    ) -> list[OrderIntent]: ...
```

`PortfolioView` is a read-only snapshot (cash, positions, portfolio
value at last mark) — a `Strategy` cannot mutate portfolio state
directly; only `BacktestBroker`/`PortfolioAccounting` can, after going
through order/fill simulation. This mirrors
`PROJECT_MASTER_PLAN.md` §8.3/§8.4: even in this simplified Phase 2
form, a strategy proposes, it does not execute.

A future ML-based strategy (Phase 6+) implements the same `Strategy`
Protocol; `generate_orders` internally calling a trained model instead
of a fixed rule requires no change to `BacktestEngine`, `AsOfDataView`,
or the broker/accounting stack (§1.2, §10.3).

---

## 6. Order & Fill Simulation

### 6.1 Order types and validation

`OrderType.MARKET` is implemented. `OrderType.LIMIT` exists in the enum
(so the type signature and downstream code — cost/fill logic — are
already shaped to accept it) but `FillSimulator` raises
`NotImplementedError` if asked to fill one; this is the "확장 가능한
구조" the instruction asks for without building unused logic now
(`PROJECT_MASTER_PLAN.md` §84).

`OrderSimulator` validates, at order-creation time (using the portfolio
state as of the **decision** checkpoint, before any same-step fills):

- **Insufficient cash**: a BUY whose estimated notional (quantity ×
  last-known close, without yet knowing the real fill price — see below)
  exceeds available cash is `REJECTED`.
- **Insufficient position**: a SELL for more shares than currently held
  is `REJECTED` (Phase 2 baseline strategies are long-only; no
  shorting infrastructure exists yet).

Because the true fill price is not known until the *execution*
checkpoint (§6.2), the cash check at order time uses the **decision
checkpoint's own close price** as a conservative estimate, and
`FillSimulator` re-validates against actual cash immediately before
committing a fill (a second, authoritative check) — a request that
looked affordable at estimate time but would overdraw cash once the real
(possibly worse, post-slippage) price is known is rejected at fill time,
not silently allowed to run cash negative. This two-stage check is a
direct instance of `PROJECT_MASTER_PLAN.md` §90 (fail-closed: an
uncertain/estimated state does not get the benefit of the doubt over an
authoritative one).

### 6.2 Execution timing convention (see ADR-0006 for full reasoning)

**Decision:** a `Strategy` decides using data available as-of checkpoint
`T` (`T`'s bar, whose `available_time` has been reached). The resulting
orders are filled using checkpoint `T+1`'s **close** price as the
reference price (before cost/slippage adjustment), once `T+1`'s
`available_time` is itself reached in the simulation.

This is deliberately **not** "fill at `T+1`'s open." Phase 1's
`PriceBar` model has a single `available_time` for the whole bar; there
is no field that says the opening print became knowable earlier than the
rest of the bar. Filling at `T+1`'s open using `T+1`'s single
`available_time` as the gate would either (a) require the simulation to
access `T+1`'s open before `T+1`'s `available_time` — which the
`DataRepository`'s own look-ahead guard already refuses to do, or (b) if
implemented anyway by bypassing that guard, would silently reintroduce
exactly the execution-timing leakage this spec is supposed to prevent.
Filling at `T+1`'s **close** requires no assumption not already present
in Phase 1's data model, and gives a full trading day of realistic
latency between decision and fill. See ADR-0006 for the alternative
considered (extending `PriceBar` with a distinct open-availability
timestamp) and why it is deferred rather than adopted now.

If there is no `T+1` checkpoint (orders generated on the final decision
day of the backtest window), those orders are **not executed** — there
is no realizable future price to fill them at within the window, and
fabricating one is exactly the kind of "미래정보를 사용" the instruction
prohibits. This is logged as an `INFO`-level integrity note, not
silently dropped (§12).

### 6.3 Partial fills

A fill is capped at a configurable fraction of the execution bar's
`volume` (default 10%) to avoid pretending unlimited liquidity exists.
An order requesting more than the cap is `PARTIALLY_FILLED`; the
unfilled remainder is not carried over to a later day automatically
(Phase 2 does not implement a resting/working order book — an
unfilled remainder is simply not executed, and the `Strategy` sees the
resulting position at its next decision step and may re-request more if
it still wants it). This keeps Phase 2's order model a single-shot
"propose, attempt to fill once" model, deferring a full order-book/
resting-order simulation to a later phase if ever needed.

### 6.4 Timestamps

Every `Order` carries a `decision_time` (the checkpoint it was generated
at) and every `Fill` carries an `execution_time` (the checkpoint it was
filled at, always `> decision_time`, per §6.2). `BacktestIntegrityChecker`
verifies this ordering on every fill (§12).

---

## 7. Transaction Cost & Slippage Model

(See ADR-0007 for full reasoning.)

- **Commission**: a configurable fixed cost per trade plus a
  configurable per-share cost, applied to every fill.
- **Spread**: modeled as a configurable half-spread cost applied against
  the reference execution price (buys pay slightly above, sells receive
  slightly below).
- **Slippage**: `SlippageModel` protocol; Phase 2 ships
  `FixedBpsSlippageModel` (a constant basis-point adjustment against the
  reference price, in the adverse direction for the trader) and
  `VolumeScaledSlippageModel` (adds an impact term proportional to
  `order_quantity / bar_volume`, demonstrating — not fully calibrating —
  the extension point toward an Almgren & Chriss-style market-impact
  model per `PROJECT_MASTER_PLAN.md` §71's research foundation).

None of these models are ever allowed to produce a fill price *more*
favorable than the reference price — cost and slippage only ever move
the effective price against the trader. A configuration with all costs
set to zero is supported (useful for isolating strategy-signal quality
from execution-cost effects during development) but any such run's
`ExperimentRecord` records `transaction_cost_config`/`slippage_config`
explicitly, and `PerformanceMetrics`/reporting must never present a
zero-cost run as representative real-world performance
(`PROJECT_MASTER_PLAN.md` §46: "거래비용을 반드시 고려한다" — the
default config is always non-zero; zero-cost is an opt-in diagnostic
mode, not the default).

---

## 8. Portfolio Accounting

### 8.1 State

```
cash: float
positions: dict[security_id, Position]   # Position: quantity, average_cost
```

Average-cost basis is used (not FIFO tax lots) — sufficient for
strategy-comparison purposes in Phase 2; FIFO/lot-level accounting is a
documented simplification, deferred until a phase that specifically
needs tax-lot-accurate PnL (e.g., a real Trade Journal feeding
regulatory or tax reporting).

### 8.2 Computed at every checkpoint (mark-to-market)

- `market_value` = sum of `quantity * last_known_close` per position,
  using **that checkpoint's own** close (not a future one — marking a
  position on date `T` using date `T`'s own close, after `T` has already
  been simulated, is retrospective reporting, not a forward-looking
  decision, and is not leakage; see §8.3 for why this is safe).
- `portfolio_value` = `cash + market_value`
- `realized_pnl` — accumulated on each SELL fill, `(fill_price -
  average_cost) * quantity_sold`, net of that fill's transaction costs
- `unrealized_pnl` = `market_value - cost_basis_of_open_positions`
- `turnover` — computed at report time as
  `sum(abs(fill_notional)) / average(portfolio_value)` over the backtest
  window
- Cumulative `transaction_costs` (commission + spread + slippage
  components tracked separately)

### 8.3 Why same-day mark-to-market is not leakage

A concern worth stating explicitly: §8.2 uses checkpoint `T`'s own close
to value the portfolio *as of* `T`, while §6.2 refuses to use `T+1`'s
open to *execute* a trade at `T`. These are different operations. Mark-
to-market at `T` is a backward-looking report — "what was this portfolio
worth on `T`, given everything that happened up to and including `T`" —
computed only after the simulation has already reached `T`'s checkpoint
in its forward pass. Execution at `T` would require knowing `T+1`'s
price *before* `T+1` has been simulated, which is the actual definition
of look-ahead bias. `BacktestIntegrityChecker`'s timestamp-ordering
check (§12) verifies this distinction is respected mechanically, not
just by argument.

### 8.4 Corporate action application

`CorporateActionApplier` runs once per checkpoint, before the strategy
is asked for orders, over every currently-held position:

- `SPLIT` / `REVERSE_SPLIT`: `quantity *= ratio`, `average_cost /=
  ratio` (parsed from `CorporateAction.details["ratio"]`, e.g.
  `"2:1"`). This is a portfolio adjustment, not a trade — it must not
  appear in trade count, turnover, or win-rate statistics (§11).
- `DIVIDEND` / `SPECIAL_DIVIDEND`: `cash += quantity_held *
  details["amount"]`, applied once `effective_time`/`available_time`
  conditions are met (identical look-ahead guard as price data).
- `MERGER`, `ACQUISITION`, `SPIN_OFF`, `TICKER_CHANGE`, `DELISTING`: not
  handled in Phase 2 — the mock dataset (Phase 1 data-catalog.md) does
  not populate these event types, and handling them correctly (e.g., a
  merger converting one `security_id`'s position into cash or another
  `security_id`'s shares) needs design work proportionate to when it is
  actually needed. Documented as a known limitation, not silently
  ignored.

Momentum/return-based **signal calculation** (used by
`SimpleMomentumStrategy`, §10.2) uses `PriceBar.adjusted_close` when
present, falling back to raw `close` with an `WARNING`-level integrity
note otherwise — consistent with Phase 1 spec §5.2's stated purpose for
that field (avoiding a split showing up as a fake price crash in a
momentum signal), while cash/execution accounting always uses the real,
unadjusted traded price (§6.2), since that is what actually changes
hands.

---

## 9. Benchmark Engine

### 9.1 What it computes

`BenchmarkEngine.compute(repository, benchmark_id, start, end,
as_of_time, initial_capital)` fetches `BenchmarkPoint`s via
`DataRepository.get_benchmark` (same as-of discipline as everything
else — post-hoc reporting, evaluated at `as_of_time = end` of the
already-completed backtest window, per the same reasoning as §8.3) and
computes a benchmark equity curve starting from the **same
`initial_capital`** and **same start/end dates** as the strategy backtest,
so the two are comparable on equal terms (`PROJECT_MASTER_PLAN.md` §50).

### 9.2 Cost assumption for the benchmark

The benchmark applies the same commission/spread assumptions as the
strategy's own `TransactionCostModel` for its single buy at `start` and
single sell (if liquidated) at `end`, per the instruction's "가능한 비용
가정"으로 비교" requirement — a costless benchmark compared against a
cost-burdened strategy would not be a fair comparison.

### 9.3 DECISION REQUIRED — benchmark return type

Phase 1's `BenchmarkPoint.return_type` field
(`BenchmarkReturnType.PRICE_RETURN | TOTAL_RETURN`) exists specifically
so this could not be decided silently (Phase 1 data-catalog.md flagged
it as an open item). Phase 2's `BenchmarkEngine` is implemented to
correctly handle **either** value — it reads `return_type` off the data
and labels its output accordingly — but the actual mock benchmark
dataset Phase 1 shipped is `PRICE_RETURN` only, and no real S&P 500
total-return data source has been selected (that is itself gated behind
the Phase 1 ADR-0005 provider decision). This is raised formally below
(§20 of this spec / the session's final report) rather than resolved
here, per this Phase 2 instruction's explicit direction not to decide it
unilaterally.

---

## 10. Baseline Strategies

### 10.1 S&P 500 Buy & Hold (`BuyAndHoldStrategy`)

On the first checkpoint, allocates available cash equally (or by a
configurable weighting) across the strategy's configured universe and
buys once; issues no further orders afterward (holds through
corporate actions, which `CorporateActionApplier` continues to apply
throughout — §8.4). This baseline exists both as *the* strategy
benchmark logic can be sanity-checked against and as a trivial
`Strategy` implementation exercising the full engine.

### 10.2 Simple Momentum (`SimpleMomentumStrategy`)

A long-only, cross-sectional momentum strategy: every `rebalance_every`
trading days, ranks the current universe by trailing total return over a
`lookback_days` window (using `adjusted_close`, §8.4), goes equal-weight
long the top `top_n`, and sells anything currently held that has fallen
out of the top `top_n`. This is a deliberately simplified reading of the
time-series/cross-sectional momentum literature
(`PROJECT_MASTER_PLAN.md` §71 — Moskowitz, Ooi & Pedersen) — the paper's
absolute (long/short, single-asset) momentum construction is not
replicated, since Phase 2 has no short-selling infrastructure; only the
core "trailing-return ranking signal, periodic rebalance" idea is used,
and this simplification is stated explicitly rather than implied.

### 10.3 Simple ML — interface only

No ML strategy is built in Phase 2. The `Strategy` Protocol (§5) is the
only thing Phase 6+ needs to satisfy to plug in a trained model; nothing
further is speculatively built now (`PROJECT_MASTER_PLAN.md` §17.3/§84).

---

## 11. Performance Metrics

`PerformanceReport` (computed by `metrics.py` from the portfolio's daily
value series, trade list, and the `BenchmarkEngine` result):

```
cumulative_return
cagr
annualized_volatility
sharpe_ratio           # using a configurable risk-free rate, default 0
sortino_ratio
max_drawdown
calmar_ratio
turnover
total_transaction_cost
win_rate                # fraction of closed round-trip trades with positive realized PnL
avg_trade_return
benchmark_cumulative_return
benchmark_cagr
benchmark_max_drawdown
excess_return            # strategy cumulative_return - benchmark_cumulative_return
annualized_excess_return
```

No single figure (Sharpe, or return alone) is treated as a pass/fail
signal — per the instruction, "단일 Sharpe나 단일 수익률만으로 전략을
평가하지 않는다" — `PerformanceReport` is always reported as a whole
alongside the benchmark comparison and the integrity report (§12); which
figures matter for a given decision is left to whoever reads the report
(a human, in Phase 2 — no automated accept/reject gate on metrics alone
exists yet, consistent with `PROJECT_MASTER_PLAN.md` §1.1 forbidding
"백테스트 성능이 높다는 이유만으로 모델을 채택").

---

## 12. Backtest Integrity Layer

`BacktestIntegrityChecker` accumulates `IntegrityIssue`s (severity
`INFO/WARNING/ERROR/CRITICAL`, mirroring Phase 1's
`DataQualitySeverity` taxonomy for consistency) throughout a run:

| Check | Severity when violated |
|---|---|
| Timestamp ordering (checkpoints strictly increasing; every fill's `execution_time > decision_time`) | CRITICAL |
| Future data access (an `AsOfDataView` call attempted with a time later than the clock — defensive check even though structurally prevented, §3.2) | CRITICAL |
| Universe correctness (an order for a security not in the resolved universe at that checkpoint) | ERROR |
| Corporate action correctness (an action applied with `available_time > as_of_time` — defensive re-check of §8.4) | CRITICAL |
| Execution timing (a fill's reference price bar is not the expected `T+1` checkpoint) | CRITICAL |
| Duplicate trades (two fills sharing the same `order_id`, or a strategy issuing two intents for the same security+side in one step) | ERROR |
| Impossible portfolio state (cash goes negative; a position quantity goes negative) | CRITICAL |
| Missing data (a universe member has no bar at an expected checkpoint) | WARNING |
| Data version consistency (the same security/timestamp pair observed with two different `data_version`s within one run — would indicate the underlying data mutated mid-run, breaking reproducibility) | CRITICAL |

**Gating rule** (directly implements the instruction's §12: "Integrity
failure는 결과를 정상적인 백테스트 성과로 저장하지 않는다"):
`BacktestResult.is_valid_performance` is `False` whenever any `ERROR` or
`CRITICAL` issue was recorded. `PerformanceReport` and
`ExperimentRecord` are still populated (so the failure itself remains
inspectable/debuggable) but every consumer of a `BacktestResult` must
check `is_valid_performance` before treating its metrics as a legitimate
result — the engine does not silently discard the numbers, but it also
never presents an integrity-failed run as if it were a clean one.

---

## 13. Experiment Tracking

```
experiment_id            # "BT-000001" style, monotonic (mirrors Phase 1's "DQ-000001")
strategy_version           # e.g. class name + a version string on the Strategy instance
data_version                # the set of PriceBar/CorporateAction/BenchmarkPoint data_versions
                             # actually read during the run (from Provenance)
feature_version              # N/A in Phase 2 (no Feature Engine yet) — recorded as None, not omitted
configuration_version        # hash of the full BacktestConfig (cost/slippage/dates/capital/universe)
start_date / end_date
initial_capital
transaction_cost_config
slippage_config
benchmark                    # benchmark_id + return_type actually used
metrics                      # the PerformanceReport
code_version                  # git commit hash if available, else "unknown"
seed                          # for any strategy/component that uses randomness
result                        # PASSED | INTEGRITY_FAILED (mirrors is_valid_performance)
timestamp
```

`ExperimentTracker` is an in-process registry (list of
`ExperimentRecord`s), the same scoping decision Phase 1 made for
`DataQualityFramework`'s run counter — a persistent store is future
work, not built speculatively now.

---

## 14. Validation Structure

`validation.py` provides:

- `chronological_train_test_split(start, end, split_date) ->
  (train_range, test_range)` — a plain, non-random, time-ordered split.
  Random train/test splitting is never used for this project's
  time-series data (`PROJECT_MASTER_PLAN.md` §48 — random splits leak
  future information into training through shuffling and are explicitly
  rejected).
- `WalkForwardSplitter(train_period, test_period, step)` — yields a
  sequence of `(train_start, train_end, test_start, test_end)` windows
  advancing forward through the calendar, each test window strictly
  after its train window, consistent with `PROJECT_MASTER_PLAN.md` §48's
  Walk Forward stage.
- `ValidationSplitter` (Protocol) — the extension point a future Purged
  K-Fold / Embargo implementation (`PROJECT_MASTER_PLAN.md` §48,
  López de Prado-style validation) must satisfy. Not implemented in
  Phase 2 (ADR-0008) — Phase 2 has no trained model yet to validate this
  way; building purge/embargo logic now, with nothing to purge around,
  would be speculative.

`BacktestEngine` accepts any `(start, end)` range, so both a single
in-sample/out-of-sample run and a full walk-forward sequence (calling
the engine once per `WalkForwardSplitter` window) are supported without
engine changes.

---

## 15. Research Grounding Applied in Phase 2

Per the instruction (§17: "Phase 2에 직접 필요한 원칙만 반영한다"), only
these principles from the existing research foundation
(`PROJECT_MASTER_PLAN.md` §71) are applied, and only where they
concretely shape a Phase 2 decision:

- **Almgren & Chriss (Optimal Execution)** — motivates *why* Phase 2's
  slippage model has a volume-scaled extension point (§7) rather than a
  flat cost only; their full optimal-execution trajectory framework is
  not implemented.
- **López de Prado-style financial ML validation** — motivates the
  chronological-only split rule (§14) and the reserved (not built)
  Purged K-Fold/Embargo extension point.
- **Time Series Momentum (Moskowitz, Ooi & Pedersen)** — motivates the
  trailing-return ranking construction of the Simple Momentum baseline
  (§10.2), explicitly noted as a simplified reading, not a replication.
- **The Probability of Backtest Overfitting / The Deflated Sharpe
  Ratio (Bailey et al.; Bailey & López de Prado)** — not implemented as
  code in Phase 2 (there is only one strategy family and no parameter
  search yet, so there is nothing to compute PBO/Deflated Sharpe over).
  `ExperimentTracker` (§13) exists specifically so that once Phase 4+
  starts running many strategy variants, the experiment count these
  metrics require as an input is already being recorded from day one —
  this is the concrete, minimal thing Phase 2 does to serve that future
  need, per §17's "필요한 최소한의 연구만 반영한다."
- **Empirical Asset Pricing via Machine Learning (Gu, Kelly & Xiu)** —
  not applied in Phase 2; it is a Phase 5/6 (Feature/Prediction) concern.
  No new research is pulled in for it here.

No new paper is added to the research foundation in this phase.

---

## 16. Test Strategy

The following 15 categories (from the Phase 2 initialization
instruction) are each covered by at least one test in `tests/backtest/`:

1. Deterministic replay — identical inputs replayed twice produce an
   identical order/fill sequence, checkpoint by checkpoint.
2. No-lookahead — `AsOfDataView` cannot surface data beyond
   `BacktestClock.current_time`, exercised through a full engine run.
3. Transaction cost — commission/spread arithmetic verified against
   hand-computed expected values.
4. Slippage — `FixedBpsSlippageModel`/`VolumeScaledSlippageModel` verified
   against hand-computed expected adjustments; always adverse to the
   trader.
5. Cash accounting — cash decreases/increases exactly by fill notional +
   costs, including a dividend cash credit.
6. Position accounting — quantity/average cost track buys, sells, and a
   stock split correctly.
7. PnL — realized PnL on a round-trip trade matches hand computation;
   unrealized PnL matches mark-to-market.
8. Drawdown — a constructed value series with a known peak-to-trough
   produces the expected `max_drawdown`.
9. Benchmark — `BenchmarkEngine` output uses the same period/capital as
   the strategy run and correctly labels/uses `return_type`.
10. Corporate action — a split occurring mid-backtest adjusts quantity/
    cost basis and does not appear as a trade; a dividend credits cash.
11. Survivorship — a security leaving the universe mid-backtest is
    excluded from new purchases from that point forward, using the same
    mechanism Phase 1 already validated at the data layer.
12. Execution timing — every fill's reference bar is verified to be the
    checkpoint immediately after the order's decision checkpoint, never
    the same or an earlier one.
13. Duplicate order — two intents for the same security+side in one step
    are flagged by the integrity checker.
14. Reproducibility — same data + code + config + seed run twice (fresh
    engine instances) yields byte-identical `PerformanceReport` values.
15. Integrity failure — a deliberately corrupted scenario (e.g. a
    synthetic negative-cash situation) is verified to set
    `is_valid_performance = False` and is not reported as a clean
    result.

Both the Phase 1 suite (`tests/data/`) and the new Phase 2 suite
(`tests/backtest/`) must pass together (§20).

---

## 17. Interaction with the Master Plan and Phase 1

No conflicts were found between this specification and
`PROJECT_MASTER_PLAN.md` / ADR-0001 / Phase 1's specification and ADRs.
Phase 2 consumes Phase 1's `DataRepository` exactly as designed, with no
changes requested to Phase 1 code. The one open item (§9.3, benchmark
return type) is a data-sourcing decision explicitly deferred by Phase 1
itself (data-catalog.md), not a conflict between the two phases' designs
— it is raised as `DECISION REQUIRED` per master plan §19.1.

---

## 18. Definition of Done for Phase 2 (design stage)

- [x] Phase 1 data layer re-inspected (§2)
- [x] This specification written
- [x] Backtesting Architecture defined (§3)
- [x] Look-ahead / leakage prevention mapped per category (§4)
- [x] Strategy Interface defined (§5)
- [x] Order/Fill simulation designed, including execution timing
      resolution (§6, ADR-0006)
- [x] Transaction Cost / Slippage Model designed (§7, ADR-0007)
- [x] Portfolio Accounting designed (§8)
- [x] Benchmark Engine designed; return-type ambiguity raised as
      DECISION REQUIRED rather than resolved silently (§9.3)
- [x] Performance Metrics defined (§11)
- [x] Backtest Integrity Layer designed (§12)
- [x] Experiment Tracking designed (§13)
- [x] Validation structure (train/test + walk-forward; purged/embargo
      reserved) designed (§14, ADR-0008)
- [x] Baseline strategies designed (§10)
- [x] Research grounding limited to what Phase 2 concretely needs (§15)
- [x] Test strategy defined for all 15 required categories (§16)
- [ ] Reference implementation completed and passing (tracked in
      `docs/PROJECT_STATUS.md`)
- [ ] `docs/PROJECT_STATUS.md` updated (this session's final step)
- [ ] Design + reference implementation committed to git (this
      session's final step)
