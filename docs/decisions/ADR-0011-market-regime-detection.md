# ADR-0011: Market Regime Detection Architecture

**Status:** Accepted
**Date:** 2026-08-24
**Deciders:** Claude Code (Phase 5 session), pending project owner review
**Related documents:** `PROJECT_MASTER_PLAN.md` §3, §7.6, ADR-0004
(point-in-time), ADR-0009 (Trade Journal data model & reuse), ADR-0010
(persistent storage backend), `docs/specifications/PHASE-5-market-regime.md`

---

## Context

`PROJECT_MASTER_PLAN.md` names Market Regime Detection as an independent
module (§3's boundary table: "시장 상태(추세/변동성/유동성 등) 분류" /
"하지 않는 것: 종목 선택, 매매 판단") and lists five example axes (§7.6:
Trend, Volatility, Liquidity, Correlation, Market Stress) without
prescribing an algorithm ("최종 regime 모델은 실험을 통해 결정하며,
초기 구현에서 특정 알고리즘을 전제하지 않는다"). This phase builds the
first, deliberately minimal implementation of that module: deterministic,
interpretable baseline classifiers — no HMM, no Transformer, no deep
learning, per the explicit instruction — plus the persistence and
Backtest-integration scaffolding a Phase 6+ Prediction/Decision/Risk
layer, and eventually a Learning Engine (Phase 9), will build on.

## Decision

### 1. Regime data model reuses `TradeProvenance`; no parallel enum

`RegimeObservation`/`CompositeRegimeObservation.provenance` is
`trade_journal.enums.TradeProvenance` (`HISTORICAL_SIMULATION |
PAPER_TRADING | LIVE_TRADING`) directly, not a new, differently-named
enum with the same three values. This is the identical reasoning ADR-0009
already applied when Phase 3 embedded Phase 2's `Order`/`Fill` rather
than redefining them: a regime observation's provenance is the *same
concept* Trade Journal already tracks, and a second enum for it would
only invite drift between the two (e.g., a future session adding a fourth
provenance value to one but not the other).

### 2. `RegimeDetector` sources data exclusively through `backtest.asof.AsOfDataView`

Rather than building a new point-in-time-safe view, `RegimeDetector`
takes an `AsOfDataView` as its only data-access parameter. This is the
exact object a `Strategy.generate_orders` already receives from
`BacktestEngine` (Phase 2 spec §3.2) — its `get_bars`/`get_benchmark`
methods are already bound to `BacktestClock.current_time` with no
parameter through which a caller could request a later time. A regime
computed through this class therefore automatically inherits the same
"no accidental leakage path" guarantee ADR-0004 established at the data
layer and Phase 2 re-established one layer up, with zero new leakage-
guard code written for Phase 5.

For regime computation *outside* a live backtest loop (standalone
historical analysis, or a future Paper Trading replay),
`regime.detector.make_single_point_view(repository, as_of_time)`
constructs a one-checkpoint `BacktestClock` + `AsOfDataView` pair over an
arbitrary `DataRepository`. A `BacktestClock` with exactly one checkpoint
is already a fully valid instance of that type (its own validation only
requires "at least one checkpoint, strictly increasing," which one
checkpoint trivially satisfies) — this is reuse of an existing Phase 2
type for a use case its original author did not anticipate, not a
modification of it. `tests/regime/test_point_in_time.py::
test_standalone_repository_view_matches_backtest_clock_view` verifies both
paths produce identical results for the same `(repository, as_of_time)`.

### 3. Both a security and a benchmark can be a regime "subject"

`PriceBar` (per-security) and `BenchmarkPoint` (index-level) both reduce
to the same `PricePoint` shape (`regime/points.py`) before any feature
function runs, so the identical trend/volatility/stress math applies to
either a single stock or a market index — "Market Regime" is treated as
a concept that can describe the market as a whole (via a benchmark) or
one security, matching how the phrase is actually used in practice, not
arbitrarily restricted to one or the other. A benchmark subject's
Liquidity axis is honestly `UNKNOWN` (never guessed) because
`BenchmarkPoint` carries no volume field.

### 4. Persistent storage: DuckDB tables, not Parquet

`regime_observations`/`regime_composites` are DuckDB tables in the same
catalog file ADR-0010 already established for Trade Journal/Experiment/
Experience data, not a new Parquet dataset. This applies ADR-0010 §1's
existing criterion (bulk-columnar-scan workloads that scale like
`securities × trading days` go to Parquet; point-lookup/filter-heavy
relational data — even data that also scales with `securities × days` —
goes to DuckDB when it needs natural-key idempotency and cross-table
joins, exactly Benchmark data's situation) rather than inventing a new
rule. Regime data needs both: idempotent re-recording of an identical
observation, and `get_composite_as_of(subject, as_of_time)` point-in-time
lookups joined against `decisions`/`trades` for lineage — both are
DuckDB-table-shaped needs, not Parquet-shaped ones. This is **not** a
change to any existing table's schema (the instruction's "기존 storage
schema 변경" `DECISION REQUIRED` trigger) — it is two new, additive
tables created via the same idempotent `CREATE TABLE IF NOT EXISTS`
pattern every other Phase 4 table already uses.

### 5. Regime ↔ Trade Journal lineage is an opt-in join, not a Phase 3 code change

`ExperienceRecord.market_regime` already exists on Phase 3's model,
reserved verbatim for this phase ("reserved -- needs Phase 5"). Rather
than modifying `trade_journal.experience.build_experience_records` (Phase
3, stable, already tested) to populate it directly,
`regime.experience.attach_regime_context(records, journal, regime_repo,
...)` is a separate, explicit enrichment step: for each
`ExperienceRecord`, it looks up the record's decision via
`journal.get_decision`, then queries `regime_repo.get_composite_as_of`
for the most recent regime at or before that decision's `decision_time`
— itself a point-in-time query, so a decision is never enriched with a
regime observation computed *after* it. This keeps Phase 3 completely
unmodified (per this phase's explicit "Phase 2의 기존 Strategy 동작을
불필요하게 변경하지 않는다" instruction, extended here to Phase 3's
`experience.py` on the same reasoning) while still delivering the "Regime
정보도 Decision Snapshot / Trade Journal과 lineage를 연결할 수 있어야
한다" requirement.

### 6. `RegimeConditionedStrategy` is one illustrative `Strategy`, with an explicit no-alpha-claim policy

To satisfy the instruction's requirement to actually try Regime as a
conditioning variable (Phase 5 spec §9), `regime.strategy.
RegimeConditionedStrategy` wraps any existing `Strategy` and drops its
BUY intents while a configured subject's Trend axis is BEAR. It
implements the unmodified `Strategy` Protocol, so it runs through the
unmodified `BacktestEngine` exactly like `BuyAndHoldStrategy`. Every test
exercising it (`tests/regime/test_regime_conditioning_experiment.py`)
reports the conditioned vs. unconditioned `PerformanceReport` side by
side and asserts only mechanical properties (both runs are valid; fewer
or equal trades, since the wrapper can only remove BUY intents) — **no
test asserts higher return, Sharpe, or any other performance figure for
the conditioned version.** This directly implements
`PROJECT_MASTER_PLAN.md` §1.1's "백테스트 성능이 높다는 이유만으로
모델을 채택하지 않는다," applied specifically to Regime per this phase's
own explicit instruction ("이것을 근거로 Regime이 alpha를 만든다고
주장하지 않는다").

### 7. `reliability`, not a fabricated `confidence`

Every `RegimeObservation` carries `reliability: float` — the fraction of
the required lookback window actually available (`data_completeness()`
in `features.py`), forced to drive the state to `UNKNOWN` below
`RegimeConfig.min_data_completeness` (fail-closed, mirroring
`PROJECT_MASTER_PLAN.md` §1.4's "Model Unknown → 신규 주문 차단" applied
to a classification result rather than a trading decision). This is a
real, honestly-computable number. A probabilistic "confidence" score
would be fabricated for a deterministic threshold classifier that has no
underlying probability model to draw one from — ADR-0009 §4's "unknown
fields are `None`, never estimated" principle, applied here to mean
"the one number reported is real, not merely plausible-looking."

## Alternatives Considered

- **HMM / clustering / any statistical or ML regime model now**: Rejected
  — the instruction is explicit ("처음부터 HMM/Transformer/Deep Learning
  등을 사용하지 않는다"), and no baseline yet exists to know whether a
  more complex model would even be worth its added opacity/overfitting
  risk (`PROJECT_MASTER_PLAN.md` §13.6's "baseline first" principle,
  already applied to strategies in Phase 4, applied here to regime
  models).
- **A full percentile computed over the entire historical sample**
  (rather than a bounded trailing window): Rejected — using the full
  sample for a volatility percentile computed "as of" an early date would
  implicitly use dates after that date once the sample later grows,
  reintroducing exactly the look-ahead bias category Phase 1/2 already
  guard against at the data/execution layers. A trailing, bounded
  `volatility_percentile_window` keeps every percentile computed only
  from data at or before its own `as_of_time`.
- **Generating a composite label for every combination of axis states**
  (3-5 states × 5 axes): Rejected — Phase 5 spec §6 explicitly warns
  against unbounded state-space growth; a small, curated lookup table
  (`regime/detector.py::_COMPOSITE_LABELS`) covers the combinations
  actually useful to name, and every other combination is honestly
  `None` rather than an auto-generated, unvalidated label.
- **Building a full, general-purpose Feature Registry now** (feature_id,
  formula DSL, arbitrary derived-data types): Rejected — Phase 1 spec
  explicitly deferred the Derived/Feature layer to "Phase 5+" without
  specifying its shape, and no design decision in this phase requires
  more than the regime-scoped feature metadata (`feature_version`,
  `method_version`, `configuration_version`) already on
  `RegimeObservation`. A general registry is exactly the kind of
  "정의되지 않은 미래 요구사항을 위해 설계" `PROJECT_MASTER_PLAN.md` §1.2
  warns against; the versioning fields are structured so a future,
  broader registry can absorb them without a schema rewrite.
- **Computing Stress from Volatility + Drawdown + Correlation** (a
  three-input composite): Rejected for now — no concrete need has
  established that Correlation materially changes Stress classification
  over Volatility + Drawdown alone; documented in `features.py` as an
  extension point, not built speculatively.

## Consequences

### Positive

- Zero new point-in-time-guard code: Regime's leakage safety is entirely
  inherited from `AsOfDataView`/`BacktestClock`, already tested by Phase
  2's own no-lookahead suite, and re-verified for the regime code path
  specifically (`tests/regime/test_point_in_time.py`).
- Regime, Trade Journal, and Experiment data all live in one DuckDB
  catalog file, so a decision's regime context is a plain SQL join, not a
  cross-file federation.
- `RegimeConditionedStrategy` proves the "Backtest → Regime → Strategy"
  connection end to end without a single line of `BacktestEngine`
  changing.

### Negative / Trade-offs

- The curated composite-label table (`_COMPOSITE_LABELS`) will need
  extension by hand as new useful combinations are identified — this is
  an accepted, deliberate trade-off (no automatic generation) per Phase 5
  spec §6.
- `RegimeObservation`'s `state` field is a plain `str` (the winning
  per-axis Enum member's `.value`), not itself a typed Enum column, since
  a single dataclass generic across five different per-axis Enum domains
  has no one correct Enum type — `regime.enums.AXIS_STATE_ENUM` is the
  documented way to recover the typed value when needed. This mirrors a
  trade-off Phase 2/3 already accepted in a different place (average-cost
  accounting over FIFO lots) — not new complexity, just this phase's
  instance of "some precision is deliberately not carried in the type
  system, and is documented instead."
- Correlation/Stress computed at the security level depend on an
  optional `reference_id` (typically a benchmark) being supplied by the
  caller; omitting it is honestly `UNKNOWN`, not a silent single-asset
  fallback — callers that want Correlation must actively provide a
  reference series.

## Status of Implementation at Time of This ADR

Implemented in `src/regime/` (`enums.py`, `config.py`, `points.py`,
`features.py`, `models.py`, `detector.py`, `repository.py`,
`experience.py`, `strategy.py`) and `src/storage/regime_repository.py`
(+ `storage/schema.py`, `storage/serialization.py` additions), exercised
by `tests/regime/`, `tests/storage/test_regime_repository.py`, and
`tests/integration/test_regime_experience_lineage.py`.
