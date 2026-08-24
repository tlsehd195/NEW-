# PHASE 3 SPECIFICATION — Trade Journal

**Status:** ACTIVE (design confirmed, reference implementation in progress)
**Phase:** Phase 3 — Trade Journal
**Depends on:** `PROJECT_MASTER_PLAN.md`, `docs/decisions/ADR-0001-master-architecture.md`,
Phase 1 (`docs/specifications/PHASE-1-data-infrastructure.md`, ADR-0002..0005),
Phase 2 (`docs/specifications/PHASE-2-backtesting.md`, ADR-0006..0008,
`src/backtest/*`)
**Produces ADRs:** ADR-0009 (Trade Journal data model & immutability)

---

## 0. Purpose of This Document

`PROJECT_MASTER_PLAN.md` §92 states the principle this phase exists to
implement: **"Trade Journal은 로그가 아니다. 경험 메모리다."** A log
answers "what happened." A memory answers "what did we know, why did we
act, and what actually followed" — years later, without relying on
anyone's recollection or on re-deriving the answer from data that may
since have changed.

Phase 3 does not add any new trading capability. It adds the
**permanent record** of every decision and trade Phase 2 (and, later,
Paper/Live trading) produces, structured so that Phase 9 (Learning),
Phase 10 (Counterfactual/Attribution), and Phase 11 (Model Evolution)
have a real substrate to build on instead of an empty interface.

---

## 1. Scope

### 1.1 In scope for Phase 3

- A Trade Journal data model: `DecisionSnapshot`, `TradeRecord`,
  `PostTradeAnalysis`, `CounterfactualRecord`, `AttributionResult`,
  `ExperienceRecord`, `CorrectionRecord` (§3-§10).
- Direct reuse of Phase 2's existing, already-immutable types
  (`Order`, `Fill`, `PortfolioView`) inside the Journal's own records,
  rather than redefining parallel types (§2, ADR-0009).
- A `TradeJournalRepository` interface plus an
  `InMemoryTradeJournalRepository` reference implementation, following
  the same Repository-interface discipline Phase 1's `DataRepository`
  established (§11).
- Point-in-time-correct, immutable Decision Snapshots — captured once,
  never reconstructed by re-querying current state (§4).
- Idempotent recording keyed by natural identity (`experiment_id` +
  `order_id`), so re-ingesting the same source data never duplicates
  Journal entries (§12).
- An immutability + correction-record pattern: a wrong entry is never
  edited or deleted; a `CorrectionRecord` is appended alongside it (§9).
- A minimal, honestly-scoped Post Trade Analysis, Counterfactual, and
  Performance Attribution structure: fields that Phase 3 can compute
  for real are computed; fields that require modules that do not exist
  yet (Prediction, Regime, Risk, sector/factor data) are left `None`,
  never estimated and stored as if they were fact (§6-§8).
- An Experience Dataset conversion (`ExperienceRecord`), tagged with
  provenance (`HISTORICAL_SIMULATION | PAPER_TRADING | LIVE_TRADING`)
  so historical, paper, and live experience are never silently mixed
  (§10).
- A Phase 2 integration adapter (`ingest_backtest_result`) that walks a
  `BacktestResult` and populates the Journal, without modifying Phase 2
  behavior and without breaking any existing Phase 2 test (§13).
- An `audit_trail()` query that directly answers the seven questions
  `PROJECT_MASTER_PLAN.md` §57 requires the system to be able to answer
  (§14).

### 1.2 Out of scope for Phase 3

- AI/LLM API calls, Toss Securities integration, real or paper order
  submission, Live Trading — none of this is touched, per explicit
  instruction.
- Actually computing `prediction_error`, `timing_error`,
  `risk_estimation_error`, `regime_error`, or `signal_error` — these
  require a Prediction Engine (Phase 6), Regime Detection (Phase 5), and
  Risk Engine (Phase 8) that do not exist yet. The fields exist on
  `PostTradeAnalysis`; they are populated as `None` by everything built
  in this phase (§6).
- Sector/factor/market decomposition for Performance Attribution — no
  sector or factor data source exists yet (Phase 1 §4 lists this as a
  reserved, not-yet-built data category). Only the `execution` component
  of `AttributionResult`, which Phase 3's own data can compute honestly,
  is populated (§8).
- A trained-model-driven counterfactual (e.g., "what would a different
  strategy have decided") — Phase 3 implements exactly one concrete,
  honestly-computable counterfactual: a post-hoc "what if we had not
  traded" replay using already-elapsed, now-available price data (§7.2).
  Anything requiring a hypothetical alternative model's output is
  deferred to Phase 11.
- A persistent storage backend — `InMemoryTradeJournalRepository` is the
  only implementation, mirroring Phase 1's own deferred DuckDB/Parquet
  backend (ADR-0002) and Phase 2's in-process `ExperimentTracker`. No
  new storage technology decision is made in this phase.
- Explicit `NO_TRADE` decision logging for every security the strategy
  considered and declined — Phase 2's `Strategy.generate_orders` only
  returns `OrderIntent`s for securities it acts on; it does not emit an
  explicit "decided not to trade AAA today" signal. Phase 3 therefore
  only journals decisions that produced an `Order` (including rejected
  and not-executed ones). Explicit, first-class `NO_TRADE` decisions
  become journalable once Phase 7's Decision Agent (which evaluates
  `NO_TRADE` as one of its five possible actions,
  `PROJECT_MASTER_PLAN.md` §22-23) exists. This is a scope boundary, not
  data loss — see §5.4.
- Live/Paper broker integration for the `PAPER_TRADING`/`LIVE_TRADING`
  provenance values — the enum and the separation logic exist and are
  tested (§10.2), but no producer of paper/live trades exists yet
  (Phase 15-16).

---

## 2. Phase 1/2 Structures Reused (Investigation Summary)

Re-confirmed by direct inspection of `src/backtest/` before writing this
spec:

| Existing type | Where | Reused as |
|---|---|---|
| `backtest.orders.Order` (frozen) | Phase 2 | Embedded directly in `DecisionSnapshot.order` — not redefined |
| `backtest.fills.Fill` (frozen) | Phase 2 | Embedded directly in `TradeRecord.fill` — not redefined |
| `backtest.portfolio.PortfolioView` (frozen) | Phase 2 | Embedded directly in `DecisionSnapshot.portfolio_state` |
| `backtest.enums.OrderStatus` | Phase 2 | Reused as-is; extended with one additive member, `CANCELLED` (see §5.3) |
| `backtest.experiment.ExperimentRecord.experiment_id` | Phase 2 | Foreign key on every Journal record (`experiment_id: Optional[str]`) |
| `backtest.integrity.IntegrityReport` | Phase 2 | Not embedded, but a `BacktestResult` with `is_valid_performance is False` is still ingested — the Journal records what actually happened even when the run is flagged invalid; it never silently drops data because an upstream integrity check failed (§13.3) |
| `data_infra.models.Provenance` | Phase 1 | Reused conceptually — `Fill.data_version` and `ExperimentRecord.data_version` are copied into Journal records rather than re-derived (§4) |
| `data_infra.versioning.compute_data_version` | Phase 1 | Reused for `CorrectionRecord`/audit hashing where a content fingerprint is useful |
| Phase 1 `DataRepository` Protocol pattern | Phase 1 | Directly mirrored by `TradeJournalRepository` (Protocol + InMemory reference impl, §11) |
| Phase 1/2 monotonic id pattern (`DQ-000001`, `BT-000001`) | Phase 1/2 | Directly mirrored: `DEC-000001`, `TRD-000001`, `PTA-000001`, `CF-000001`, `COR-000001` |

No Phase 1 or Phase 2 source file required modification to build this
phase, **except** one additive enum member
(`backtest.enums.OrderStatus.CANCELLED`) — see §5.3 for why, and
confirmation that no existing Phase 2 code or test assumed the prior,
smaller set of `OrderStatus` values was exhaustive.

There is currently **no Prediction, Regime, or Risk interface** in the
codebase (Phase 5-8 do not exist yet), and **no `Decision` type**
carrying `confidence`/`expected_return`/`target_weight`/`decision_reason`
— Phase 2's `Strategy.generate_orders` returns `OrderIntent`s directly.
`DecisionSnapshot` therefore has `Optional` fields for all of these
(§5.1), populated `None` when built from a Phase 2 backtest, and ready
to receive real values once those phases exist without any schema
change.

---

## 3. Architecture

```
BacktestResult (Phase 2: orders, fills, experiment, integrity)
        │
        ▼
┌─────────────────────────┐
│ ingest_backtest_result    │  backtest_adapter.py — the only Phase 2-aware
│ (Phase 2 integration)     │  module in this package
└─────────────┬────────────┘
              │  record_decision() / record_trade()  (idempotent, natural-key)
              ▼
┌─────────────────────────┐
│ TradeJournalRepository     │  Protocol
│ InMemoryTradeJournalRepo    │  reference implementation
└─────────────┬────────────┘
              │
   ┌──────────┼───────────────────────────────┐
   ▼          ▼                                ▼
DecisionSnapshot   TradeRecord         CorrectionRecord (append-only,
(immutable)        (immutable)          never mutates the original)
   │                  │
   │                  ├──► PostTradeAnalysis   (analysis.py — execution_error
   │                  │                          computed now; rest reserved)
   │                  ├──► CounterfactualRecord  (analysis.py — one concrete
   │                  │                            hold-replay counterfactual)
   │                  └──► AttributionResult      (analysis.py — execution
   │                                                component computed now)
   ▼
audit_trail(trade_id)   — composes all of the above into one answer to
                           PROJECT_MASTER_PLAN.md section 57's questions

TradeRecord + DecisionSnapshot + (PostTradeAnalysis, CounterfactualRecord)
        │
        ▼
build_experience_records()  (experience.py)
        │
        ▼
ExperienceRecord  — tagged HISTORICAL_SIMULATION | PAPER_TRADING | LIVE_TRADING
```

### 3.1 Module layout

```
src/trade_journal/
├── enums.py            TradeProvenance, DecisionAction, CorrectionTargetType
├── models.py            DecisionSnapshot, TradeRecord, PostTradeAnalysis,
│                        CounterfactualRecord, AlternativeOutcome,
│                        AttributionResult, ExperienceRecord,
│                        CorrectionRecord, AuditTrail
├── repository.py         TradeJournalRepository (Protocol),
│                          InMemoryTradeJournalRepository
├── analysis.py             compute_execution_error, compute_hold_counterfactual,
│                            compute_execution_attribution
├── experience.py            build_experience_records
└── backtest_adapter.py       ingest_backtest_result (the only module that
                               imports from backtest.*)
```

Only `backtest_adapter.py` depends on `src/backtest/`. Every other
module depends only on Phase 1's `data_infra` (for `DataRepository`,
used by the counterfactual helper) and the standard library — so the
Journal's core data model is not structurally coupled to backtesting
specifically, and a future Paper/Live adapter can populate it the same
way without touching `models.py` or `repository.py`.

---

## 4. Point-in-Time Principle Applied to the Journal

`PROJECT_MASTER_PLAN.md`'s Point-in-Time principle (§16) governs *data*:
a decision at time T must not see data from after T. Phase 3 applies the
same discipline to the **Journal's own records**: a `DecisionSnapshot`
must not be reconstructable by re-querying current repository state,
because "current state" changes and a naive re-query years later would
silently answer a different, wrong question ("what does the system know
now about that day" instead of "what did the system know then").

Concretely:

- `DecisionSnapshot.portfolio_state` embeds an actual `PortfolioView`
  value object (already immutable) captured at decision time — not a
  reference to a live, mutable `PortfolioAccounting` instance.
- `DecisionSnapshot.order` embeds the actual `Order` (immutable) that
  resulted from that decision.
- `TradeRecord.fill` embeds the actual `Fill` (immutable).
- `DecisionSnapshot.data_version` / `TradeRecord`'s data version (via
  `fill.data_version`) copy the specific `Provenance.data_version`
  values that priced the decision/trade, not a pointer that could later
  resolve to a different (corrected/restated) value.
- Every record's `recorded_at` timestamp (when the Journal ingested it)
  is kept distinct from the record's own decision/execution timestamp —
  mirroring Phase 1's `event_time` vs. `ingestion_time` split
  (Phase 1 spec §10, ADR-0004) — so a Journal entry created well after
  the fact (e.g., a late backfill) is honestly distinguishable from one
  recorded contemporaneously.

Because Python dataclasses with `frozen=True` raise
`dataclasses.FrozenInstanceError` on attribute assignment, every Journal
record type is declared `@dataclass(frozen=True)` — immutability is
enforced by the language, not by convention or documentation alone
(the same choice Phase 1 and Phase 2 already made for their own domain
types).

---

## 5. Data Model

### 5.1 `DecisionSnapshot`

```python
@dataclass(frozen=True)
class DecisionSnapshot:
    snapshot_id: str                      # "DEC-000001"
    decision_time: datetime               # == order.decision_time
    security_id: str
    decision: DecisionAction              # BUY | SELL | HOLD | EXIT | NO_TRADE
    order: Optional[Order]                # Phase 2 Order — embedded, not copied field-by-field
    portfolio_state: Optional[PortfolioView]  # captured at decision time (see section 4, 13.2 on reconstruction)
    market_state: dict                    # minimal now — reference price, as_of_time (no Feature Engine yet)
    features: Optional[dict] = None       # reserved for Phase 5
    prediction: Optional[dict] = None     # reserved for Phase 6
    confidence: Optional[float] = None    # reserved for Phase 6/7
    decision_reason: Optional[str] = None # factual note only — never a fabricated "why" (section 5.2)
    expected_return: Optional[float] = None   # reserved for Phase 6/7
    expected_risk: Optional[float] = None     # reserved for Phase 8
    risk_state: Optional[dict] = None         # reserved for Phase 8
    target_weight: Optional[float] = None     # reserved for Phase 7/8
    model_version: Optional[str] = None       # reserved for Phase 6+
    strategy_version: str = "unknown"
    feature_version: Optional[str] = None     # reserved for Phase 5
    data_version: Optional[tuple[str, ...]] = None  # see section 13.2 — honestly None at
                                                        # per-decision granularity for Phase 2
                                                        # backtests (known limitation)
    risk_version: Optional[str] = None        # reserved for Phase 8
    execution_version: str = "unknown"        # e.g. "phase2_backtest_engine_v1"
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION
    experiment_id: Optional[str] = None       # Phase 2 ExperimentRecord.experiment_id
    recorded_at: datetime = ...               # journal ingestion time (section 4)
```

### 5.2 `decision_reason` — what it is and is not

`decision_reason` is a **factual provenance note** ("which strategy/rule
produced this order"), never a fabricated causal explanation. For a
Phase 2 backtest, it is set to a string identifying the strategy that
produced the intent (e.g. `"strategy=simple_momentum_v1"`) — something
the system can actually assert with certainty — not a guessed narrative
like "because momentum was strong." A real, LLM-generated causal
explanation is a Phase 6+/AI Gateway concern (`PROJECT_MASTER_PLAN.md`
§14); Phase 3 does not synthesize one.

### 5.3 `TradeRecord`

```python
@dataclass(frozen=True)
class TradeRecord:
    trade_id: str              # "TRD-000001"
    decision_id: str           # links to DecisionSnapshot.snapshot_id
    order_id: str              # == fill.order_id
    security_id: str
    timestamp: datetime        # == fill.execution_time
    side: OrderSide
    quantity: float
    execution_price: float     # == fill.price
    reference_price: float     # == fill.reference_price
    slippage: float            # == fill.slippage_cost
    transaction_cost: float    # == fill.total_cost
    position_after: float      # position in this security immediately after this trade
    realized_pnl: Optional[float] = None      # set only for a SELL that closes/reduces a position
    realized_return: Optional[float] = None   # realized_pnl / cost basis of shares sold
    holding_period: Optional[timedelta] = None  # see section 13.3 — approximate under average-cost accounting
    fill: Fill = ...           # Phase 2 Fill — embedded directly
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION
    experiment_id: Optional[str] = None
    recorded_at: datetime = ...
```

Every Phase 2 `OrderStatus` — including `REJECTED`, `NOT_EXECUTED`, and
the additive `CANCELLED` (reserved for future async brokers; Phase 2's
synchronous engine never produces it, confirmed by inspection of
`src/backtest/orders.py` and `fills.py`) — is representable: a
`DecisionSnapshot` is recorded for every `Order` regardless of its final
status, while a `TradeRecord` exists **only** when a `Fill` actually
occurred. This is a deliberate 1-to-(0-or-1) relationship: it correctly
represents that a rejected or cancelled order is still a real decision
worth remembering, but produced no trade.

### 5.4 `DecisionAction`

```python
class DecisionAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    EXIT = "EXIT"
    NO_TRADE = "NO_TRADE"
```

Mirrors `PROJECT_MASTER_PLAN.md` §22's five possible Decision Agent
outputs in full, even though Phase 2's `Strategy` interface only ever
produces `BUY`/`SELL` today (§1.2). This means Phase 7's Decision Agent
can start emitting `HOLD`/`EXIT`/`NO_TRADE` decisions into the Journal
without a schema change.

### 5.5 `PostTradeAnalysis`

```python
@dataclass(frozen=True)
class PostTradeAnalysis:
    trade_id: str
    prediction_error: Optional[float] = None      # reserved — needs Phase 6 Prediction
    timing_error: Optional[float] = None           # reserved — needs Phase 6/7
    risk_estimation_error: Optional[float] = None    # reserved — needs Phase 8
    execution_error: Optional[float] = None           # COMPUTED NOW — see analysis.py
    regime_error: Optional[float] = None                # reserved — needs Phase 5
    signal_error: Optional[float] = None                  # reserved — needs Phase 6
    notes: Optional[str] = None
    computed_at: Optional[datetime] = None
```

`execution_error` is the one field Phase 3 can honestly compute today:
`(fill.price - fill.reference_price) / fill.reference_price`, i.e., the
realized cost of spread + slippage as a fraction of the bar's reference
price — a real, derivable number, not an estimate (`analysis.py::compute_execution_error`).

### 5.6 `CounterfactualRecord` / `AlternativeOutcome`

```python
@dataclass(frozen=True)
class AlternativeOutcome:
    action: str                          # e.g. "HOLD" (the only alternative Phase 3 computes — section 7.2)
    hypothetical_return: Optional[float] = None
    basis: Optional[str] = None          # e.g. "post_hoc_price_replay" — how it was computed, always stated
    horizon: Optional[timedelta] = None

@dataclass(frozen=True)
class CounterfactualRecord:
    trade_id: str
    selected_action: DecisionAction
    alternatives: tuple[AlternativeOutcome, ...] = ()
    computed_at: Optional[datetime] = None
```

No `AlternativeOutcome.hypothetical_return` is ever populated with a
guessed value — only with the result of an actual, documented
computation (`basis` states which). See §7.

### 5.7 `AttributionResult`

```python
@dataclass(frozen=True)
class AttributionResult:
    experiment_id: str
    market: Optional[float] = None       # reserved — needs a benchmark decomposition model
    sector: Optional[float] = None        # reserved — no sector data source exists (Phase 1 spec section 4)
    factor: Optional[float] = None         # reserved — no factor data source exists
    selection: Optional[float] = None       # reserved — needs Phase 6+ prediction quality analysis
    timing: Optional[float] = None           # reserved — needs Phase 6/7
    execution: Optional[float] = None         # COMPUTED NOW — see analysis.py
    computed_at: Optional[datetime] = None
```

`execution` is computed as `-(total_transaction_costs /
initial_capital)` from a `PortfolioAccounting` — the real, aggregate
cost drag execution introduced, expressed as a fraction of starting
capital (`analysis.py::compute_execution_attribution`). This is
attribution at the **experiment** level (an entire backtest run), not
per-trade — decomposing return by market/sector/factor/selection/timing
is inherently a portfolio-level, not trade-level, analysis
(`PROJECT_MASTER_PLAN.md` §34).

### 5.8 `ExperienceRecord`

```python
@dataclass(frozen=True)
class ExperienceRecord:
    experience_id: str        # "XR-000001"
    trade_id: str
    decision_id: str
    state: dict                  # market_state + portfolio_state snapshot from the DecisionSnapshot
    action: DecisionAction
    expected_outcome: Optional[dict] = None    # from expected_return/expected_risk if present
    actual_outcome: dict = ...                    # realized_pnl, realized_return, holding_period
    reward: Optional[float] = None                  # = realized_return when the trade closed a position;
                                                        # None for an opening trade with no realization yet.
                                                        # A genuine reward *function* (risk-adjusted, multi-step
                                                        # credit assignment, etc.) is a Phase 9 Learning Engine
                                                        # design decision — this identity mapping is a documented
                                                        # placeholder default, not a claim that it is the "right"
                                                        # reward signal to train on.
    market_regime: Optional[str] = None               # reserved — needs Phase 5
    risk_state: Optional[dict] = None                    # reserved — needs Phase 8
    prediction_error: Optional[float] = None               # copied from PostTradeAnalysis if computed
    counterfactual_results: Optional[tuple] = None           # copied from CounterfactualRecord if computed
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION
    data_version: Optional[tuple[str, ...]] = None
    strategy_version: str = "unknown"
    model_version: Optional[str] = None
    created_at: datetime = ...
```

### 5.9 `CorrectionRecord`

```python
class CorrectionTargetType(str, Enum):
    DECISION = "DECISION"
    TRADE = "TRADE"

@dataclass(frozen=True)
class CorrectionRecord:
    correction_id: str            # "COR-000001"
    target_type: CorrectionTargetType
    target_id: str                 # snapshot_id or trade_id being corrected
    reason: str                     # required — a correction with no stated reason is rejected (section 9)
    corrected_fields: dict            # field_name -> corrected value, informational only
    created_at: datetime
    created_by: str = "system"          # who/what authorized the correction
```

### 5.10 `AuditTrail`

```python
@dataclass(frozen=True)
class AuditTrail:
    decision: Optional[DecisionSnapshot]
    trade: Optional[TradeRecord]
    post_trade_analysis: Optional[PostTradeAnalysis]
    counterfactual: Optional[CounterfactualRecord]
    corrections: tuple[CorrectionRecord, ...]
```

A read-only composition, not a stored record — produced on demand by
`InMemoryTradeJournalRepository.audit_trail(trade_id)` (§14).

---

## 6. Version Lineage

`PROJECT_MASTER_PLAN.md` §76 requires:

```
Data Version → Feature Version → Training Dataset → Model Version
   → Strategy Version → Risk Version → Execution Version → Trade
```

Every field in this chain has a home on `DecisionSnapshot`
(`data_version`, `feature_version`, `model_version`, `strategy_version`,
`risk_version`, `execution_version`) and is copied — never re-derived —
from whatever upstream system produced the decision. For a Phase
2-sourced snapshot: `strategy_version` comes from `Strategy.version`
(already present on both baseline strategies, Phase 2 spec §10);
`execution_version` is the constant `"phase2_backtest_engine_v1"`
identifying the execution system; `data_version` is honestly `None` at
per-decision granularity (§13.2); `feature_version`, `model_version`,
and `risk_version` are `None` because Phase 5/6/8 do not exist yet. Once
those phases exist, their outputs slot into these same fields without a
schema change — that is the entire point of defining the full lineage
now.

---

## 7. Post Trade Analysis & Counterfactual — What Is Actually Computed

### 7.1 Post Trade Analysis

Only `execution_error` is computed in Phase 3 (§5.5). It is a genuine
Expected-vs-Actual comparison: the "expected" execution price is the
bar's reference close (`Fill.reference_price`, before cost/slippage);
the "actual" is what was really paid/received (`Fill.price`).
`(price - reference_price) / reference_price` is exactly the execution
slippage realized, expressed as a return — a legitimate instance of
`PROJECT_MASTER_PLAN.md` §32's Post Trade Analysis concept, scoped to
the one error category Phase 3's own data can measure.

### 7.2 Counterfactual — the one method implemented

`analysis.py::compute_hold_counterfactual(repository, security_id,
decision_time, evaluation_time)` answers: "if, instead of trading, the
position had simply been left alone (cash unchanged) from
`decision_time` to `evaluation_time`, what would the security's own
price return have been over that window?" It queries
`DataRepository.get_bars(..., as_of_time=evaluation_time)` — a **post-hoc**
query using an `evaluation_time` at or after `decision_time`, which is
legitimate precisely because this is retrospective analysis run after
the fact, not a forward-looking decision (the same reasoning Phase 2
spec §8.3 already established for benchmark/mark-to-market queries: a
later `as_of_time` used to evaluate an *already-elapsed* window is not
look-ahead bias).

This is the **only** counterfactual Phase 3 computes. A counterfactual
comparing against a different model's or strategy's hypothetical
decision (`PROJECT_MASTER_PLAN.md` §33's `alternative_action_2`, etc.)
requires that alternative to actually exist and be runnable — that is
Phase 11 (Model Evolution) territory. Per this phase's explicit
instruction ("정확한 counterfactual 결과를 계산할 수 없는 경우 추정값을
사실처럼 저장하지 않는다"), Phase 3 does not simulate a second strategy
just to populate this field with a guess.

---

## 8. Idempotency

`InMemoryTradeJournalRepository` keys every write by a **natural key**
derived from source data, not from a freshly-allocated id, so recording
is idempotent under re-ingestion:

- `DecisionSnapshot`: natural key = `(experiment_id, order.order_id)`
  when an order exists, else a caller-supplied explicit key (for a
  future non-order-bearing decision, e.g. an explicit `NO_TRADE` from
  Phase 7).
- `TradeRecord`: natural key = `(experiment_id, fill.order_id)` — an
  order produces at most one fill in Phase 2's synchronous model, so
  this is sufficient; if a future async broker produces multiple partial
  fills per order, the natural key extends to
  `(experiment_id, fill.order_id, fill.execution_time)` (documented as
  a forward-compatible note, not built now since Phase 2 cannot produce
  this case).

`record_decision`/`record_trade` check the natural-key index **before**
allocating a new id; a duplicate call returns the existing record
unchanged rather than allocating a new id and creating a duplicate
entry. This mirrors Phase 1 §25's ingestion idempotency requirement,
applied to the Journal layer.

---

## 9. Immutability & Correction

Once written, a `DecisionSnapshot` or `TradeRecord` is **never** edited
or deleted by `InMemoryTradeJournalRepository` — there is no `update_*`
or `delete_*` method on `TradeJournalRepository` at all; the interface
itself makes mutation impossible to request. A data-entry error is
corrected by calling `record_correction(...)`, which appends a
`CorrectionRecord` referencing the original by id, with a mandatory
`reason`. Readers who need the "corrected" view call
`get_corrections(target_id)` and apply the correction themselves — the
original record is always still there, unchanged, exactly as it was
first recorded (`PROJECT_MASTER_PLAN.md` §11's "original record +
correction/audit record" pattern, applied here for the Journal itself
rather than Raw market data).

---

## 10. Provenance Separation

### 10.1 `TradeProvenance`

```python
class TradeProvenance(str, Enum):
    HISTORICAL_SIMULATION = "HISTORICAL_SIMULATION"
    PAPER_TRADING = "PAPER_TRADING"
    LIVE_TRADING = "LIVE_TRADING"
```

Every `DecisionSnapshot`, `TradeRecord`, and `ExperienceRecord` carries
this field. `ingest_backtest_result` (§13) always tags
`HISTORICAL_SIMULATION` — Phase 3 has no paper or live trade producer
yet, so those values are exercised only by direct unit construction in
tests (§15), proving the separation exists and is respected by every
query/filter path, ready for Phase 15 (Paper Trading) and Phase 16
(Live Trading) to populate for real.

### 10.2 Why this matters now, not later

`PROJECT_MASTER_PLAN.md` §36 requires this separation to exist **in the
Experience Dataset itself**, not bolted on later — mixing simulated and
real experience without a clear boundary would let Phase 9's Learning
Engine train on backtest artifacts as if they were live-validated
behavior. `build_experience_records()` (§8.10, `experience.py`) never
drops or infers `provenance` — it is always copied verbatim from the
source `TradeRecord`/`DecisionSnapshot`, and every query method on
`TradeJournalRepository` accepts an optional `provenance` filter.

---

## 11. Repository Abstraction

```python
class TradeJournalRepository(Protocol):
    def record_decision(self, **fields) -> DecisionSnapshot: ...
    def record_trade(self, **fields) -> TradeRecord: ...
    def record_post_trade_analysis(self, trade_id: str, **fields) -> PostTradeAnalysis: ...
    def record_counterfactual(self, trade_id: str, selected_action: DecisionAction,
                               alternatives: tuple[AlternativeOutcome, ...]) -> CounterfactualRecord: ...
    def record_correction(self, target_type: CorrectionTargetType, target_id: str,
                           reason: str, corrected_fields: dict, created_at: datetime,
                           created_by: str = "system") -> CorrectionRecord: ...

    def get_decision(self, snapshot_id: str) -> Optional[DecisionSnapshot]: ...
    def get_trade(self, trade_id: str) -> Optional[TradeRecord]: ...
    def list_trades(self, *, security_id: Optional[str] = None,
                     provenance: Optional[TradeProvenance] = None,
                     start: Optional[datetime] = None, end: Optional[datetime] = None) -> list[TradeRecord]: ...
    def list_decisions(self, *, security_id: Optional[str] = None,
                        provenance: Optional[TradeProvenance] = None) -> list[DecisionSnapshot]: ...
    def get_post_trade_analysis(self, trade_id: str) -> Optional[PostTradeAnalysis]: ...
    def get_counterfactual(self, trade_id: str) -> Optional[CounterfactualRecord]: ...
    def get_corrections(self, target_id: str) -> tuple[CorrectionRecord, ...]: ...
    def audit_trail(self, trade_id: str) -> AuditTrail: ...
```

Following the id-allocation pattern already established by Phase 1
(`DataQualityFramework`) and Phase 2 (`OrderSimulator`,
`ExperimentTracker`), `record_*` methods accept raw field values and
allocate ids internally — callers never construct a `DecisionSnapshot`
or `TradeRecord` with a pre-chosen id, which is what makes natural-key
idempotency (§8) enforceable in one place.

`InMemoryTradeJournalRepository` is the only implementation, matching
Phase 1's still-deferred DuckDB/Parquet backend (ADR-0002) — no new
storage technology decision is made here. Consumers (the future Learning
Engine, Counterfactual/Attribution modules) depend only on
`TradeJournalRepository`, never on the in-memory implementation
directly.

---

## 12. Trade Lifecycle

```
OrderIntent (Strategy)
   → Order (OrderSimulator) ── REJECTED ──────────────► DecisionSnapshot only (no TradeRecord)
        │
        │ PROPOSED
        ▼
   Fill attempt (FillSimulator)
        │
        ├── NOT_EXECUTED (no execution bar / no liquidity) ─► DecisionSnapshot only
        ├── REJECTED (fails second-stage cash check) ───────► DecisionSnapshot only
        ├── CANCELLED (reserved, Phase 13+ async brokers) ──► DecisionSnapshot only
        └── FILLED / PARTIALLY_FILLED ───────────────────────► DecisionSnapshot + TradeRecord
                                                                     │
                                                          (on a closing/reducing SELL)
                                                                     ▼
                                                          realized_pnl, realized_return,
                                                          holding_period populated
```

Every branch produces a `DecisionSnapshot` — no decision is ever
silently un-recorded because it did not result in a trade. This
directly satisfies instruction §6: partial fill, rejected, cancelled,
failed, and `NOT_EXECUTED` states are all preserved.

---

## 13. Phase 2 Integration — `ingest_backtest_result`

### 13.1 What it does

`ingest_backtest_result(journal_repo, result: BacktestResult, config:
BacktestConfig, *, experiment_id: Optional[str] = None) -> IngestSummary`
walks `result.orders` and `result.fills` **in their original order**
(both are already chronologically ordered by construction — verified
against `src/backtest/engine.py`) and:

1. Calls `record_decision(...)` for every `Order`, regardless of status.
2. Calls `record_trade(...)` for every `Fill`, linked to its `Order`'s
   decision via `order_id`.
3. Tags every record `TradeProvenance.HISTORICAL_SIMULATION` and
   `experiment_id = result.experiment.experiment_id` (or the explicit
   override, if given).

It does **not** modify `BacktestEngine`, `BacktestResult`, or any Phase
2 type. It is read-only with respect to Phase 2's outputs.

### 13.2 Known limitation — per-decision `data_version`

`BacktestEngine` (as inspected in `src/backtest/engine.py`) tracks
`data_versions_used` only in aggregate, across the whole run
(`ExperimentRecord.data_version`); it does not expose which specific
bar's `data_version` informed each individual decision. Rather than
approximate this by re-deriving it from repository queries (which would
violate §4's "capture once, do not reconstruct" principle) or modifying
`BacktestEngine` to track it (out of scope for this phase — a Phase 2
change, not a Phase 3 one), `ingest_backtest_result` leaves
`DecisionSnapshot.data_version` as `None` for Phase 2-sourced snapshots.
The trade-level, execution-time-accurate `Fill.data_version` **is**
available and is preserved on every `TradeRecord`. This is a documented,
honest gap — not a fabricated value — and is the clearest concrete
argument for a small, additive Phase 2 follow-up (per-decision data
version tracking in `BacktestEngine`) if finer-grained lineage is later
required; see the `DECISION REQUIRED` note in this session's final
report.

### 13.3 Known limitation — `portfolio_state` reconstruction

`BacktestResult` does not expose a per-decision `PortfolioView`
snapshot (only the final `PortfolioAccounting` state, via
`compute_performance_report`'s internal use). `ingest_backtest_result`
reconstructs it by **replaying `result.fills` through a fresh
`PortfolioAccounting`** seeded with `config.initial_capital`, in fill
order, taking a snapshot immediately before each fill is applied. This
reconstruction is **exact** with respect to fills (fill application is
a pure, deterministic function of fill order — the same property Phase
2's own reproducibility tests already rely on), but does **not**
account for corporate-action-driven cash/quantity adjustments
(`CorporateActionApplier`) that occurred inside the original
`BacktestEngine.run()` loop between fills, since `BacktestResult` does
not expose those events either. For a backtest window with no corporate
actions (the common case, and true of both Phase 2 baseline strategies
against Phase 1's current mock dataset unless a test deliberately
includes a split/dividend), the reconstruction is exact. This is stated
as a known, documented limitation rather than silently producing a
subtly wrong snapshot — see `DECISION REQUIRED` below.

### 13.4 `holding_period` approximation

Consistent with Phase 2's own accepted average-cost-basis simplification
(Phase 2 spec §8.1), `holding_period` is computed as "time since this
security's position last went from flat (zero) to non-zero," not true
FIFO per-lot holding period. `ingest_backtest_result` tracks
`position_opened_at: dict[security_id, datetime]` while replaying fills;
a SELL's `holding_period = fill.execution_time -
position_opened_at[security_id]`. Documented as an approximation, not
presented as exact lot-level accounting.

---

## 14. Auditability

`InMemoryTradeJournalRepository.audit_trail(trade_id)` composes a
`DecisionSnapshot`, its `TradeRecord`, any `PostTradeAnalysis`,
`CounterfactualRecord`, and all `CorrectionRecord`s into one `AuditTrail`
value, directly answering `PROJECT_MASTER_PLAN.md` §57:

| Question | Answered by |
|---|---|
| 왜 이 거래가 발생했는가? | `decision.decision_reason`, `decision.decision` |
| 당시 AI가 무엇을 알고 있었는가? | `decision.market_state`, `decision.portfolio_state`, `decision.features`/`prediction` (when populated) |
| 어떤 모델이 결정했는가? | `decision.model_version`, `decision.strategy_version` |
| 어떤 risk rule을 통과했는가? | `decision.risk_state`, `decision.risk_version` (reserved until Phase 8; the field exists and is queryable now) |
| 어떤 가격으로 주문했는가? | `trade.execution_price`, `trade.reference_price`, `trade.fill` |
| 왜 모델이 변경되었는가? | Out of scope for Phase 3 — a Model Registry concern (Phase 11); `decision.model_version` provides the "what changed" half now |
| 누가/무엇이 모델 변경을 승인했는가? | Out of scope for Phase 3 — Phase 11/Model Registry |

The last two rows are honestly listed as **not yet answerable** by this
phase, rather than silently omitted — Phase 3 builds the Trade/Decision
half of auditability; the Model Registry half is Phase 11's job.

---

## 15. Research Grounding

No new research is added in this phase (per instruction §17). The
existing foundation already covers what Phase 3 needs conceptually —
`PROJECT_MASTER_PLAN.md` §30-36 (Trade Journal, Decision Snapshot, Post
Trade Analysis, Counterfactual, Attribution, Experience Dataset) *is*
the specification this phase implements; no additional paper-level
justification is required for a data-modeling/persistence phase with no
new algorithmic content. If a future phase (e.g., Phase 9's actual
reward-function design, or Phase 10's real attribution algorithms) needs
research grounding, that is raised at that time, not anticipated here.

---

## 16. Test Strategy

The following categories (from the Phase 3 initialization instruction)
are each covered by at least one test in `tests/trade_journal/`:

1. Trade creation
2. Decision snapshot integrity (all required linkage fields correctly populated)
3. Immutable snapshot (`FrozenInstanceError` on any attempted mutation)
4. Order/fill linkage (`trade.decision_id` resolves to the correct `DecisionSnapshot`; `trade.order_id` matches)
5. Partial fill (a `PARTIALLY_FILLED` order still produces a correctly-sized `TradeRecord`)
6. Rejected order (a `REJECTED` order produces a `DecisionSnapshot` and no `TradeRecord`)
7. Cancelled order (constructed directly, since Phase 2 never produces one — proves the Journal tolerates it without a schema change)
8. Duplicate event / idempotency (re-ingesting the same `Order`/`Fill` — or the same `BacktestResult` twice — does not duplicate Journal entries)
9. Realized PnL (matches Phase 2's own `ClosedTradeRecord` computation for the same fills)
10. Holding period (matches hand computation under the flat-to-flat approximation, §13.4)
11. Provenance (HISTORICAL_SIMULATION/PAPER_TRADING/LIVE_TRADING correctly tagged and filterable)
12. Version lineage (`strategy_version`/`execution_version`/`data_version` correctly threaded from Phase 2 objects to Journal records)
13. Point-in-time snapshot (mutating the *source* `PortfolioAccounting` after a snapshot was taken does not change the already-recorded `DecisionSnapshot`)
14. Audit trail (`audit_trail()` returns a complete, correctly-composed `AuditTrail` answering §14's question table)
15. Historical/paper/live separation (`list_trades(provenance=...)` correctly isolates each category; mixed-provenance data is never silently merged)
16. Experience conversion (`build_experience_records` produces correctly-shaped, correctly-tagged `ExperienceRecord`s, including `reward=None` for a non-closing trade)
17. Correction/audit record (a correction never mutates the original; `get_corrections` surfaces it; a correction without a `reason` is rejected)

Plus an end-to-end Phase 2 integration test: run a `BacktestEngine`
backtest, ingest the result, and verify the Journal's `TradeRecord`
count, realized PnL sum, and provenance tagging are consistent with the
`BacktestResult` it came from — and that Phase 2's own test suite
(`tests/backtest/`) still passes unmodified (§18).

---

## 17. Interaction with the Master Plan and Prior Phases

No conflicts were found between this specification and
`PROJECT_MASTER_PLAN.md` / ADR-0001, or with the Phase 1/Phase 2
specifications and ADRs. One additive, backward-compatible change was
made to Phase 2 code (`backtest.enums.OrderStatus.CANCELLED` — a new
enum member; verified that no existing Phase 2 code or test assumed the
prior set was exhaustive, §2). Two known, honestly-documented
limitations are raised as `DECISION REQUIRED` in this session's final
report (per-decision `data_version` granularity, §13.2; corporate-action
gaps in replayed `portfolio_state`, §13.3) rather than resolved
unilaterally, since both are properly Phase 2 architecture questions,
not Phase 3 ones.

---

## 18. Definition of Done for Phase 3 (design stage)

- [x] Phase 1/2 data structures re-inspected and reused (§2)
- [x] This specification written
- [x] Trade Journal data model defined (§5)
- [x] Point-in-time / immutable snapshot principle applied (§4, §9)
- [x] Provenance and version lineage design (§6, §10)
- [x] Trade lifecycle covering all Phase 2 order/fill statuses (§12)
- [x] Post Trade Analysis structure — one real computation, rest reserved honestly (§7.1)
- [x] Counterfactual structure — one real computation, rest reserved honestly (§7.2)
- [x] Performance Attribution structure — one real computation, rest reserved honestly (§5.7)
- [x] Experience Dataset conversion design (§5.8, §10.2)
- [x] Immutability + correction-record pattern (§9)
- [x] Idempotency design (§8)
- [x] Auditability mapping (§14)
- [x] Repository abstraction, in-memory reference only (§11)
- [x] Phase 2 integration design, including two documented limitations (§13)
- [x] Test strategy for all 17 required categories + Phase 2 integration (§16)
- [ ] Reference implementation completed and passing (tracked in `docs/PROJECT_STATUS.md`)
- [ ] `docs/PROJECT_STATUS.md` updated (this session's final step)
- [ ] Design + reference implementation committed to git (this session's final step)
