# PHASE 5 SPECIFICATION — Market Regime Detection

**Status:** ACTIVE (design confirmed, reference implementation complete)
**Phase:** Phase 5 — Market Regime
**Depends on:** `PROJECT_MASTER_PLAN.md`, `docs/decisions/ADR-0001`
through `ADR-0010`, Phase 1 (`src/data_infra/*`), Phase 2
(`docs/specifications/PHASE-2-backtesting.md`, `src/backtest/*`), Phase 3
(`src/trade_journal/*`), Phase 4 (`docs/specifications/PHASE-4-baseline-models-and-storage.md`,
`src/storage/*`, `src/baseline/*`)
**Produces ADRs:** ADR-0011 (market regime detection architecture)

---

## 0. Purpose of This Document

`PROJECT_MASTER_PLAN.md` §3 lists Market Regime Detection as an
independent module: it classifies market state (trend/volatility/
liquidity/etc.), and explicitly must **not** select securities or make
trading decisions (§3's boundary column: "하지 않는 것: 종목 선택, 매매
판단"). Phase 5 builds the first version of that module. Per this phase's
explicit instruction, the goal is:

> "당시 이용 가능했던 정보만 사용하여 시장 상태를 재현 가능하게 설명하고,
> 향후 Prediction/Decision/Risk/Learning이 사용할 수 있는 신뢰 가능한
> 상태 표현을 만드는 것."

Not: building the classifier that would have made the most money in
hindsight. Every design choice below is evaluated against that standard.

---

## 1. Scope

### 1.1 In scope for Phase 5

- Five regime axes, each a deterministic, interpretable baseline
  classifier: Trend (moving-average relationship), Volatility (realized
  volatility, percentile-ranked against its own trailing history),
  Liquidity (recent-vs-baseline volume ratio), Correlation (rolling
  correlation vs. a reference series), Stress (composite of Volatility +
  trailing drawdown) — §4.
- A point-in-time-safe `RegimeDetector` sourcing all data exclusively
  through `backtest.asof.AsOfDataView`, so it inherits Phase 1-2's
  look-ahead guard rather than reimplementing one (§3, ADR-0011 §2).
- A `RegimeObservation`/`CompositeRegimeObservation` data model with full
  version lineage (`feature_version`, `method_version`,
  `configuration_version`, `data_version`) and an honest
  `reliability` figure — never a fabricated confidence score (§5-7).
- A small, curated composite-label table (e.g. `BULL_HIGH_VOL`), not an
  exhaustive combinatorial generation (§6).
- A `RegimeRepository` Protocol + `InMemoryRegimeRepository` reference
  implementation, following the same Repository-interface discipline
  Phase 1/3/4 already established, plus a persistent
  `DuckDBRegimeRepository` (Phase 4's storage layer, extended) (§11).
- A non-invasive lineage link from Regime to the Trade Journal /
  Experience Dataset (`regime.experience.attach_regime_context`),
  without modifying any Phase 3 code (§12).
- `RegimeConditionedStrategy`, an illustrative `Strategy` (Phase 2
  Protocol) that suppresses BUY intents during a BEAR trend, used only to
  demonstrate the "Regime as a conditioning variable" connection — with
  an explicit, tested policy that no test claims outperformance (§9).
- Regime computability on both a single security and a benchmark/index
  series, via a shared `PricePoint` normalization (§2).

### 1.2 Out of scope for Phase 5

- AI/LLM API calls, Toss Securities integration, real or paper order
  submission, Live Trading — none of this is touched, per explicit
  instruction.
- HMM, clustering, Transformer, or any statistical/ML regime model — the
  instruction explicitly forbids starting there; a baseline must exist
  first (`PROJECT_MASTER_PLAN.md` §85-86, already the precedent from
  Phase 4's baseline strategies).
- A general-purpose Feature Registry (arbitrary feature types, a formula
  DSL, cross-phase feature reuse beyond Regime's own scope) — Phase 1
  spec deferred "Derived Data / Feature Layer" to "Phase 5+" without
  specifying its shape; this phase builds exactly the feature machinery
  Regime itself needs, versioned so a future, broader registry can absorb
  it without a rewrite (ADR-0011, "Alternatives Considered").
- Modifying `BacktestEngine`, `Strategy` Protocol, or any existing Phase
  2 baseline strategy's behavior — Regime connects to Backtest through an
  interface (`AsOfDataView` reuse, `RegimeConditionedStrategy` as an
  ordinary `Strategy`), never through an engine change.
- Modifying `trade_journal.experience.build_experience_records` or any
  other Phase 3 code — the Regime↔Journal lineage is an opt-in,
  post-hoc join (§12, ADR-0011 §5).
- A Prediction Engine, Decision Agent, Risk Engine, or Learning Engine
  that actually *consumes* Regime state (Phases 6-9) — this phase only
  produces and persists Regime state reliably; nothing yet reads it for a
  real trading decision.
- Spread-based liquidity indicators — Phase 1's `PriceBar` has no
  bid/ask spread field at all, so this is not implemented (a known,
  documented data-model limitation, not a silent omission).
- Real external data provider selection — the reference implementation
  is exercised against the same deterministic mock/fixture data every
  prior phase uses; ADR-0005's provider decision remains deferred.

---

## 2. Regime's Role in the Data Flow

Per `PROJECT_MASTER_PLAN.md` §4.1 and this phase's own instruction:

```
Market Data
  → Data Validation (Phase 1's DataQualityFramework, already built)
  → Feature/Regime Inputs (regime.points: PriceBar/BenchmarkPoint -> PricePoint)
  → Regime Detection (regime.detector.RegimeDetector)
  → Regime State (RegimeObservation / CompositeRegimeObservation)
  → Prediction / Decision / Risk (Phase 6-8, not built yet)
```

**Invariant, enforced structurally, not just documented:** `RegimeDetector`
has no method that emits an order, a BUY/SELL decision, or a security
selection. Its only outputs are `RegimeObservation`/
`CompositeRegimeObservation` — descriptive state, never an action. The
one place Regime touches an order path in this phase
(`RegimeConditionedStrategy`) is explicitly a *consumer* of Regime output
sitting at the Strategy layer (Phase 2's own layer, one level above
Regime), not part of the Regime module itself — the boundary
`PROJECT_MASTER_PLAN.md` §3 draws is preserved.

Both a single security (`PriceBar`) and a benchmark/index series
(`BenchmarkPoint`) can be a regime "subject" — both reduce to the same
`PricePoint` shape (`regime/points.py`) before any feature function runs,
so the same math serves either (ADR-0011 §3).

---

## 3. Point-in-Time Correctness

`RegimeDetector` takes only an `AsOfDataView` (Phase 2's existing,
already-tested point-in-time-safe view — see ADR-0011 §2 for the full
reuse argument). No new look-ahead guard was written for Phase 5; the one
Phase 1 (ADR-0004) and Phase 2 (spec §3.2) already built is inherited
structurally, because `AsOfDataView.get_bars`/`get_benchmark` have no
parameter through which a caller could request a later `as_of_time`.

`regime.detector.make_single_point_view(repository, as_of_time)` extends
this to standalone (non-backtest-loop) use by constructing a
one-checkpoint `BacktestClock`/`AsOfDataView` pair — reused Phase 2 types,
not a new implementation. `tests/regime/test_point_in_time.py` verifies:
appending future bars to the repository never changes an already-computed
historical regime; the standalone path and the live-backtest path produce
byte-identical results for the same `(repository, as_of_time)`; and
`AsOfDataView.get_bars`'s signature structurally has no `as_of_time`
parameter at all.

Volatility's percentile classification ranks the current estimate against
its own **trailing, bounded** rolling history (`RegimeConfig.
volatility_percentile_window`), never the full sample — using the full
sample for an early date would implicitly include dates after it once the
sample grows, reintroducing look-ahead bias one layer above the data
layer (ADR-0011, "Alternatives Considered").

---

## 4. Baseline Regime Methods

All six axes are deterministic and hand-verifiable (`regime/features.py`,
tested against hand-constructed series in `tests/regime/test_features.py`):

| Axis | Method | States |
|---|---|---|
| Trend | `(short_ma - long_ma) / long_ma`, thresholded by a configurable neutral band | BULL / BEAR / NEUTRAL / UNKNOWN |
| Volatility | Annualized realized volatility, percentile-ranked against its own trailing rolling history | LOW / NORMAL / HIGH / EXTREME / UNKNOWN |
| Liquidity | Recent-vs-baseline average volume ratio | LOW / NORMAL / HIGH / UNKNOWN |
| Correlation | Rolling Pearson correlation of daily returns vs. a reference series | LOW / NORMAL / HIGH / UNKNOWN |
| Stress | Composite of the Volatility axis's own state + trailing max drawdown (reuses `backtest.metrics.compute_max_drawdown` directly) | NORMAL / ELEVATED / HIGH / UNKNOWN |
| Distribution | Count of IBD-style "distribution days" (decline >= threshold on volume higher than the prior day's) within a trailing window (Session 36, found comparing this project against an external repository, dragon1086/prism-insight) | NORMAL / ELEVATED / HIGH / UNKNOWN |

Distribution's addition (after Phase 5's original five) is deliberate
evidence, not a deviation, of `regime.enums.RegimeAxis`'s own docstring
claim that this is "an example classification scheme," not a closed
set: no other axis's code changed, `RegimeRepository`/
`CompositeRegimeObservation`/`RegimeConditionedStrategy` needed zero
changes (all operate on `RegimeAxis` generically, via the `axes` dict or
`AXIS_STATE_ENUM` lookup, never a hardcoded list of five), and every
pre-existing test asserting `set(RegimeAxis)`/`len(RegimeAxis)` continued
to pass by construction rather than needing a hand count updated (two
tests that *did* hardcode a literal `5` were the only ones that needed
touching -- `tests/regime/test_detector_composite.py`,
`tests/storage/test_regime_repository.py`).

Every threshold/window lives in `regime.config.RegimeConfig`, never
hardcoded in `features.py` — a required, non-default-encouraging design
(`RegimeConfig` has no "recommended" values beyond one documented default
instance, and every test that cares about a specific threshold constructs
its own `RegimeConfig`). `RegimeConfig.configuration_version()` reuses
Phase 1's `compute_data_version` content-hash helper, the same one
`BacktestConfig.configuration_version` already uses (Phase 2 spec §13) —
not a second hashing scheme.

**`UNKNOWN` is a first-class state on every axis**, not an exception or a
`None` collapsing into a different state: whenever a required lookback
window is not fully available, or `reliability` (the fraction of the
window actually present) falls below `RegimeConfig.min_data_completeness`,
the axis is `UNKNOWN` — a fail-closed choice consistent with
`PROJECT_MASTER_PLAN.md` §1.4 applied to classification instead of
trading.

---

## 5. Regime Data Model

`RegimeObservation` (one axis, one subject, one point in time):

```
regime_id, axis, subject_id, subject_kind, timestamp, as_of_time,
state, value, definition, reliability, lookback_days, feature_version,
data_version, method_version, configuration_version, provenance,
experiment_id, recorded_at
```

`timestamp` and `as_of_time` are kept as two distinct fields (per the
instruction's explicit minimum list), mirroring Phase 1's
`event_time`/`available_time` split even though the reference
implementation always sets them equal — Regime is computed *at* decision
time, never backfilled, so there is no current scenario where they
differ; keeping them separate avoids a schema change if a future producer
ever does backfill.

`reliability` is the fraction of the required lookback window actually
available — a real, computable number, never a fabricated ML confidence
(ADR-0011 §7). `state` is stored as a plain `str` (the winning
axis-specific Enum's `.value`); `regime.enums.AXIS_STATE_ENUM` recovers
the typed value when needed (a single dataclass generic across six
different Enum domains has no one correct Enum type to declare — ADR-0011
"Negative/Trade-offs").

`CompositeRegimeObservation` composes every axis's independent
observation for one subject at one `as_of_time`, plus an optional
`composite_label` populated only for a small, curated set of combinations
(§6).

Both types are `@dataclass(frozen=True)` — the same immutability
discipline every prior phase's domain types already use.

---

## 6. Composite Regime

Each axis's observation is preserved independently on
`CompositeRegimeObservation.axes` — no dimension is collapsed into
another (`tests/regime/test_detector_composite.py::TestAxisIndependence`
verifies Trend and Volatility can disagree). A separate,
`_COMPOSITE_LABELS` lookup table (`regime/detector.py`) maps a small,
deliberately curated set of `(trend_state, volatility_state)` pairs (and
a Stress-HIGH override) to human-readable labels like `BULL_HIGH_VOL` /
`BEAR_HIGH_STRESS`. Any combination not in that table gets
`composite_label = None` — never an auto-generated concatenation of all
six states, which would produce an unbounded, unvalidated state space
(the instruction's explicit warning: "가능한 상태 조합을 무한히 늘리지
않는다").

---

## 7. Feature Versioning

Every `RegimeObservation` carries `feature_version` (the feature-math
version, currently `"phase5_regime_features_v1"`), `method_version` (the
detector version, `"phase5_baseline_regime_detector_v1"`),
`configuration_version` (a content hash of the exact `RegimeConfig`
used), and `data_version` (the actual `Provenance.data_version`s of every
bar/benchmark point read for that computation). These four fields are
exactly what a future Feature Registry (whenever Prediction/Decision
needs one, Phase 6+) would need to absorb Regime's features as one
registered feature family among others, without a schema change to
`RegimeObservation` itself.

---

## 8. Backtest Integration

`RegimeDetector.compute_composite(data: AsOfDataView, subject_id, ...)`
is usable from inside a `Strategy.generate_orders(as_of_time, data,
portfolio)` call, since `data` is already the exact `AsOfDataView`
instance a Strategy receives from `BacktestEngine`. No `BacktestEngine`
code was changed. `RegimeConditionedStrategy` demonstrates this:
implements the unmodified `Strategy` Protocol, wraps any inner strategy,
and runs through `BacktestEngine` exactly like `BuyAndHoldStrategy`
(`tests/regime/test_regime_backtest_integration.py`).

`tests/regime/test_regime_backtest_integration.py::
TestStandaloneRegimeAlongsideBacktest` additionally verifies a regime
computed as a byproduct of a live `Strategy.generate_orders` call matches
one computed by directly driving a `BacktestClock` to the same
checkpoint — the "Backtest → Regime" connection is faithful, not an
approximation.

---

## 9. Regime as a Conditioning Variable — What Was Actually Tested, and What Was Not Claimed

`RegimeConditionedStrategy` (§1.1, ADR-0011 §6) was run against Phase
4's existing `SimpleMomentumStrategy` baseline, both conditioned and
unconditioned, over identical data/config
(`tests/regime/test_regime_conditioning_experiment.py`). What is verified:

- Both runs are valid (`is_valid_performance`) and produce comparable
  `PerformanceReport`s side by side (`baseline.report.compare_reports`).
- The conditioned run never has more fills than the unconditioned run — a
  purely mechanical consequence of a wrapper that can only *remove* BUY
  intents.

**What is explicitly not tested or claimed**: that the conditioned
version has higher return, Sharpe ratio, or any other performance figure.
No such assertion exists anywhere in this phase's test suite. This
directly follows the instruction: "이것을 근거로 Regime이 alpha를
만든다고 주장하지 않는다."

Also validated, independent of any performance claim (per §9 of the
instruction, "regime stability / transition frequency / persistence /
classification consistency / sensitivity to parameters"):

- **Stability/persistence**: a one-directional synthetic trend produces
  at most a handful of TREND-axis transitions across the whole window,
  and its longest stable run exceeds 10 days
  (`tests/regime/test_transitions_scenarios.py::TestPersistenceAndTransitionFrequency`).
- **Classification consistency**: replaying the same series twice yields
  an identical state sequence.
- **Sensitivity to parameters**: a wider neutral band never classifies
  strictly more days as BULL/BEAR than a narrower one (direction-only
  assertion — no specific threshold value is claimed "correct").
- **Synthetic scenarios**: constructed bull/bear/high-volatility series
  are each correctly classified in their steady state, and a
  calm-then-volatile series shows an actual LOW/NORMAL → HIGH/EXTREME
  transition.

---

## 10. Data Availability

Only `MockDataProvider`-shaped, deterministic fixture data is used
(`tests/backtest/backtest_helpers.py`'s existing bar/benchmark builders,
extended in `tests/regime/regime_helpers.py` with synthetic
trend/volatility generators for scenario tests). No real external data
provider is selected in this phase — ADR-0005's provider decision remains
explicitly deferred; nothing in this phase requires it.

---

## 11. Persistence

Regime observations and composites are DuckDB tables
(`regime_observations`, `regime_composites`) in the same catalog file
Phase 4's `StorageEngine` already manages — not a new Parquet dataset.
ADR-0011 §4 records the reasoning: this applies ADR-0010 §1's existing
Parquet-vs-DuckDB criterion (bulk columnar scans → Parquet; point-lookup/
filter/join-heavy relational data → DuckDB, the same category Benchmark
data already falls into) rather than inventing a new rule, and is an
additive schema change (two new tables via the same idempotent `CREATE
TABLE IF NOT EXISTS` pattern), not a modification of any existing table.

`storage.regime_repository.DuckDBRegimeRepository` implements the exact
`regime.repository.RegimeRepository` Protocol the in-memory reference
implementation does — restart safety, natural-key idempotency (on
`(subject_id, subject_kind, axis, as_of_time, configuration_version,
provenance)` for observations), and a point-in-time
`get_composite_as_of` lookup are all verified in
`tests/storage/test_regime_repository.py`.

---

## 12. Paper Trading Readiness — Regime ↔ Trade Journal Lineage

`ExperienceRecord.market_regime` (reserved by Phase 3 explicitly "for
Phase 5") is populated by `regime.experience.attach_regime_context`, an
opt-in enrichment step over an existing list of `ExperienceRecord`s — not
a change to `trade_journal.experience.build_experience_records` itself
(ADR-0011 §5). For each record, it resolves the record's decision via
`journal.get_decision`, then finds the regime composite whose
`as_of_time` is the most recent one at or before that decision's
`decision_time` — itself a point-in-time query
(`RegimeRepository.get_composite_as_of`), so a decision is never enriched
with a regime observation computed after it
(`tests/integration/test_regime_experience_lineage.py::
test_regime_context_is_never_from_after_the_decision`).

Regime, Trade Journal, and Experiment all live in one DuckDB catalog file
(Phase 4/ADR-0010's design, extended here), so this lineage join is a
plain SQL query, verified directly in
`tests/integration/test_regime_experience_lineage.py::
test_experiment_and_regime_share_the_same_storage_catalog`.

No Paper/Live producer of Regime observations exists yet (Phase 13/15/16)
— this phase proves the storage, lineage, and point-in-time-correctness
are ready to receive them, not that they are being produced.

---

## 13. Test Strategy

| Requirement | Test file |
|---|---|
| Deterministic regime calculation | `tests/regime/test_features.py` |
| Point-in-time leakage / future-data rejection | `tests/regime/test_point_in_time.py` |
| Missing data / insufficient history | `test_features.py` (per-axis UNKNOWN cases) |
| Timezone | `test_features.py`/`test_point_in_time.py` (all `PricePoint`/`AsOfDataView` timestamps are tz-aware by construction, inherited from Phase 1's `_require_aware`) |
| Parameter boundary | `test_features.py::test_neutral_band_is_a_parameter_boundary` |
| Regime transition / persistence | `tests/regime/test_transitions_scenarios.py` |
| Reproducibility | `test_transitions_scenarios.py::TestClassificationConsistency`, `test_detector_composite.py::TestReproducibility` |
| Version lineage | `test_detector_composite.py::TestVersionLineage` |
| Backtest integration | `tests/regime/test_regime_backtest_integration.py` |
| Synthetic bull/bear/high-volatility scenarios | `test_transitions_scenarios.py::TestSyntheticScenarios` |
| Regime-as-conditioning-variable (no alpha claim) | `tests/regime/test_regime_conditioning_experiment.py` |
| Persistence / restart / idempotency / provenance | `tests/storage/test_regime_repository.py` |
| Backtest → Journal → Regime → Experience lineage | `tests/integration/test_regime_experience_lineage.py` |

All of Phase 1-4's existing tests (253) continue to pass unmodified
(`python3 -m pytest tests/ -q`); Phase 5 adds 57 new tests, for **310
total**.

---

## 14. Research Grounding

No new paper is added to the research foundation this phase (per
instruction §14: "새로운 논문을 무작정 추가하지 않는다"). The design
decisions made — moving-average trend, realized-volatility percentile
classification, volume-ratio liquidity, rolling correlation, drawdown-based
stress — are standard, widely-documented techniques that do not require
new academic grounding beyond what `PROJECT_MASTER_PLAN.md` §71 already
registers; none of Phase 5's decisions turned on a specific paper's
result the way, for example, Phase 2's slippage model shape drew directly
on Almgren & Chriss (ADR-0007). If a future phase's regime model
(a statistical/ML classifier) needs research grounding, that is raised at
that time, following the same "what design decision requires evidence?"
question this phase asked and answered "none, for a deterministic
baseline."

---

## 15. Overfitting Avoidance

No threshold search was run against backtest performance to select
`RegimeConfig`'s default values — they are round, interpretable numbers
(20/100-day MA windows, 0.7/0.3 correlation thresholds, etc.), not fit
values. `tests/regime/test_transitions_scenarios.py::
TestParameterSensitivity::test_experiment_count_and_configs_are_
individually_recorded_not_selected` verifies that trying multiple
configurations (as the sensitivity test above it does) produces
independently retrievable `configuration_version`s for each — nothing
about this phase's testing process discards a configuration's identity in
favor of "the best-looking one." Every `RegimeConfig` used anywhere in
this phase's tests is a plain constructor call, directly visible in the
test source, not a search result.

---

## 16. DECISION REQUIRED Review

Per instruction, this phase evaluated every listed trigger:

- **실제 데이터 provider 선정**: Not needed and not decided — Phase 5
  uses only deterministic mock/fixture data, the same as every prior
  phase.
- **Regime 정의 자체의 중대한 변경**: N/A — this is the first Phase to
  define Regime; there is no prior definition to change.
- **기존 storage schema 변경**: Not applicable — `regime_observations`/
  `regime_composites` are two new, additive tables via the same
  idempotent DDL pattern every existing table uses; no existing table's
  schema changed (ADR-0011 §4).
- **Phase 3 미결 benchmark 문제 (PRICE_RETURN vs TOTAL_RETURN)**: Not
  resolved — unaffected by Regime; `BenchmarkPoint.return_type` is read
  and passed through by `regime.points.benchmark_to_price_points`
  exactly as stored, for either value.
- **Phase 3 data_version 문제 (per-decision)**: Not resolved — unrelated
  to Regime; Regime's own `data_version` field is populated fully and
  precisely (the actual bars/benchmark points read), which if anything
  demonstrates the *pattern* Option B of that open item would need,
  without deciding that open item itself.
- **corporate-action-aware portfolio reconstruction 문제**: Not
  resolved — unrelated to Regime, which does not reconstruct portfolio
  state at all.

**Conclusion**: no `DECISION REQUIRED` item needed resolution to complete
Phase 5's mandate. All Phase 3-originated open items remain correctly
deferred, consistent with their status at the end of Phase 4.

---

## 17. Definition of Done for Phase 5

- [x] Master Plan / prior ADRs / prior specs / current `src/`+`tests/`
      reviewed (§0-2)
- [x] This specification written
- [x] Regime architecture defined, boundary with Prediction/Decision
      preserved structurally (§2)
- [x] Point-in-time correctness inherited from `AsOfDataView`, verified
      independently for the regime code path (§3)
- [x] Five baseline regime axes implemented, deterministic and
      interpretable, no HMM/ML (§4)
- [x] Regime data model with full version lineage and honest
      `reliability` (§5, §7)
- [x] Composite regime with a curated (not combinatorial) label set (§6)
- [x] Backtest integration via `AsOfDataView` reuse and
      `RegimeConditionedStrategy`, no `BacktestEngine` change (§8)
- [x] Regime-as-conditioning-variable experiment run, with an explicit,
      tested no-alpha-claim policy (§9)
- [x] Persistence: DuckDB tables in Phase 4's existing catalog,
      restart-safe, idempotent (§11, ADR-0011 §4)
- [x] Regime ↔ Trade Journal / Experience lineage, non-invasive to
      Phase 3 (§12)
- [x] DECISION REQUIRED review completed — none required resolution (§16)
- [x] Full test suite passing: 310/310 (253 prior + 57 new)
- [x] `docs/PROJECT_STATUS.md` updated
- [x] `README.md` updated
- [x] Design + reference implementation committed to git
