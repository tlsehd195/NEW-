# PHASE 6 SPECIFICATION — Prediction

**Status:** ACTIVE (design confirmed, reference implementation complete)
**Phase:** Phase 6 — Prediction
**Depends on:** `PROJECT_MASTER_PLAN.md`, `docs/decisions/ADR-0001`
through `ADR-0011`, Phase 1 (`src/data_infra/*`), Phase 2
(`docs/specifications/PHASE-2-backtesting.md`, `src/backtest/*`), Phase 3
(`src/trade_journal/*`), Phase 4 (`docs/specifications/PHASE-4-baseline-models-and-storage.md`,
`src/storage/*`), Phase 5 (`docs/specifications/PHASE-5-market-regime.md`,
`src/regime/*`)
**Produces ADRs:** ADR-0012 (prediction layer architecture)

---

## 0. Git / Branch Integrity Check (prerequisite, performed before any Phase 6 work)

Per this phase's explicit instruction, the repository's Git/branch/phase
lineage was verified **before** any Phase 6 code was written. Full
results are recorded in this session's chat transcript and summarized in
the Phase 6 completion report; the short version:

```
Current Branch: claude/phase-4-baseline-storage-tuavwk
Current HEAD (at verification time): d386420 (Phase 5: Market Regime Detection)

History: c3abad0 (Initial commit) -> e00cfb1 (Phase 0) -> 194efc4 (Phase 1)
  -> 926189a (Phase 2) -> e329716 (Phase 3) -> 4583707 (preserve prompt)
  -> 44eff48 (Phase 4) -> d386420 (Phase 5)

- Single linear chain, no merges, no divergent branches.
- origin/main (c3abad0) is the root of this history -- zero commits on
  main not already in HEAD.
- origin/claude/autonomous-ai-investment-system-wvscwe's HEAD (4583707)
  is a direct ancestor of HEAD -- zero commits on it not already in HEAD.
- All Phase 1-5 files present and populated; 310/310 tests passing at
  verification time; working tree clean.

GIT / BRANCH INTEGRITY: PASS
```

Phase 6 work began only after this PASS result.

---

## 1. Purpose of This Document

`PROJECT_MASTER_PLAN.md` §8.1 defines the Prediction layer: it is
separate from Decision, and its only outputs are `expected_return`,
`probability`, `expected_volatility`, `uncertainty`, `confidence` --
never an order. Phase 6 builds the first version of that layer. Per the
instruction:

> "복잡한 AI를 만드는 것"이 아니라 "Prediction이 실제로 baseline 대비
> 가치가 있는지를 검증할 수 있는 연구 시스템"을 만드는 것.

Every design choice below is evaluated against that standard, the same
way Phase 4's baseline strategies and Phase 5's baseline regime
classifiers were.

---

## 2. Scope

### 2.1 In scope for Phase 6

- A `Predictor` Protocol + two deterministic baseline implementations:
  `RandomWalkPredictor` (the null hypothesis: `expected_return=0`,
  `probability=0.5`, no data dependency) and `DriftPredictor` (trailing-
  mean-return extrapolation + realized-volatility persistence, both
  textbook naive forecasting baselines) — §4, §6.
- `PredictionOutput`, structurally incapable of representing an order
  (no `side`/`quantity`/`target_weight`/risk-shaped field anywhere on the
  type), with full version lineage (§5, §7).
- Point-in-time-safe prediction computation, sourcing data exclusively
  through `backtest.asof.AsOfDataView` — zero new leakage-guard code (§3).
- `PredictionMethodType.DETERMINISTIC_BASELINE` vs. `MODEL_BASED` as a
  typed, queryable field — the interface point a future trained model
  will use, with no model built now (§6).
- `RegimeAwarePredictor`, illustrating Prediction consuming Regime as an
  input (`PROJECT_MASTER_PLAN.md` §4.1's data flow), with the identical
  no-alpha-claim testing discipline Phase 5 established (§9).
- A `PredictionRepository` Protocol + `InMemoryPredictionRepository`
  reference implementation, plus a persistent `DuckDBPredictionRepository`
  extending Phase 4's storage layer (§11).
- A non-invasive lineage link from Prediction to the Trade Journal /
  Experience Dataset (`predict.experience.attach_prediction_context`),
  without modifying any Phase 3 code (§12).
- Backtest integration as pure observation: predictions computed at
  every checkpoint of a live `BacktestEngine.run()` loop, proven not to
  change the strategy's own fills/performance (§8).

### 2.2 Out of scope for Phase 6

- AI/LLM API calls, Toss Securities integration, real or paper order
  submission, Live Trading — none of this is touched, per explicit
  instruction.
- Any trained statistical or ML model — the instruction explicitly
  forbids starting there; `PredictionMethodType.MODEL_BASED` is reserved,
  not implemented.
- A Strategy that converts a `PredictionOutput` into an order, even
  illustratively — unlike Phase 5's `RegimeConditionedStrategy`, this
  phase's instruction states the Prediction/Decision boundary more
  strongly ("Prediction 결과만으로 주문 생성 금지" as an explicit
  numbered principle), and with no Position Sizing/Risk Engine yet
  (Phase 8) to gate such an order, building one now would work against
  the boundary this phase exists to preserve (ADR-0012 §7).
- A Decision Agent, Position Sizing, or Risk Engine (Phases 7-8) — this
  phase produces and persists predictions; nothing yet acts on them.
- Modifying `BacktestEngine`, `Strategy` Protocol, `trade_journal.
  experience.build_experience_records`, or any other Phase 1-5 code
  beyond one additive rename (§2.3 below).
- Real external data provider selection — the reference implementation
  is exercised against the same deterministic mock/fixture data every
  prior phase uses; ADR-0005's provider decision remains deferred.

### 2.3 One additive change to Phase 5 code

`regime.features._annualized_realized_vol` is renamed to
`annualized_realized_vol` (public) so Phase 6's `DriftPredictor` can
reuse it directly rather than reimplementing the same realized-volatility
formula a second time. This is a rename only — no behavior, signature,
or internal caller logic changed; verified by Phase 5's full 48-test
suite passing unmodified after the change (ADR-0012 §5).

---

## 3. Point-in-Time Correctness

`Predictor.predict(data: AsOfDataView, security_id, ...)` takes only an
`AsOfDataView` — the identical reuse Phase 5's `RegimeDetector` already
established (ADR-0011 §2). No new look-ahead guard was written for
Phase 6. `tests/predict/test_predict_point_in_time.py` (the phase's
"Leakage Tests" category) verifies: appending future bars to the
repository never changes an already-computed prediction at an earlier
checkpoint; replaying the same checkpoint twice is deterministic; and
`AsOfDataView.get_bars`'s signature structurally has no `as_of_time`
parameter (defensively re-verified for the prediction code path,
mirroring Phase 5's identical check).

`RegimeAwarePredictor` constructs its internal `RegimeDetector` with the
same `AsOfDataView` it receives — Regime and Prediction share one
point-in-time-safe input surface, never two.

---

## 4. Baseline Predictors

| Predictor | Method | expected_return | probability | expected_volatility | uncertainty |
|---|---|---|---|---|---|
| `RandomWalkPredictor` | Null hypothesis: no forecastable drift | `0.0`, by construction | `0.5`, by construction | `None` (no data used) | `None` (nothing estimated) |
| `DriftPredictor` | Trailing-mean-return extrapolation + realized-vol persistence | `(1 + mean_daily_return)^horizon_days - 1` | fraction of trailing daily returns that were positive | `annualized_realized_vol` over the lookback window (reused from Phase 5) | standard error of the mean daily return |

`RandomWalkPredictor` needs no market data lookup at all — it is the
concrete, trivial-to-beat baseline every future, more sophisticated
predictor (including a real trained model, once one exists) must be
compared against, the same "baseline first" role Phase 4's Buy & Hold
plays for strategies (`PROJECT_MASTER_PLAN.md` §85-86).

Every window/threshold lives in `predict.config.PredictionConfig`, never
hardcoded — `PredictionConfig.configuration_version()` reuses Phase 1's
`compute_data_version` content-hash helper, the same one
`BacktestConfig`/`RegimeConfig` already use.

---

## 5. Prediction Data Model

`PredictionOutput` (frozen dataclass):

```
prediction_id, security_id, as_of_time, horizon_days,
expected_return, probability, expected_volatility, uncertainty, confidence,
method, method_type,
feature_version, data_version, method_version, configuration_version,
model_version, regime_context,
provenance, experiment_id, recorded_at
```

`model_version` is `None` for every Phase 6 predictor (no trained model
exists) — reserved for whenever `MODEL_BASED` is first actually used.
`regime_context` is `None` unless the predictor consumed Regime as an
input (only `RegimeAwarePredictor` populates it).

`confidence` is a real data-completeness ratio (reusing Phase 5's
`data_completeness()` helper) — never a fabricated model confidence
score. `uncertainty` on `DriftPredictor` is the standard error of the
specific sample mean being estimated — a real dispersion measure for that
number, not a generic placeholder (ADR-0012 §4).

**Fail-closed**: whenever the required lookback window is not fully
available (or `confidence` falls below `PredictionConfig.
min_data_completeness`), every numeric estimate (`expected_return`,
`probability`, `expected_volatility`, `uncertainty`) is `None` — never a
plausible-looking guess. `tests/predict/test_fail_closed.py` verifies
this directly, mirroring Regime's `UNKNOWN` state discipline (ADR-0011
§7) one layer up.

---

## 6. Deterministic Baseline vs. Model-Based — the Explicit Distinction

`predict.enums.PredictionMethodType` (`DETERMINISTIC_BASELINE |
MODEL_BASED`) is a typed field on every `PredictionOutput`, satisfying
the instruction's "deterministic baseline과 model-based prediction을
명확하게 구분" requirement structurally rather than through a naming
convention alone. Both `RandomWalkPredictor` and `DriftPredictor` are
`DETERMINISTIC_BASELINE`. `MODEL_BASED` is reserved and used by nothing
in this phase — that absence is itself the point: no complex model was
introduced before a baseline existed to measure it against.

---

## 7. Feature/Model Versioning

Every `PredictionOutput` carries `feature_version`
(`"phase6_prediction_features_v1"`), `method_version` (the predictor's
own version string, e.g. `"drift_v1"`), `configuration_version` (a
content hash of the exact `PredictionConfig` used), `data_version` (the
actual bar `Provenance.data_version`s read), and `model_version`
(reserved, `None` today). These are exactly the fields a future Learning
Engine (Phase 9) or Model Registry (Phase 11) would need to track which
prediction came from which model version — built now, populated
honestly, consumed by nothing yet.

---

## 8. Backtest Integration — Observation, Not Influence

Predictions are computed at every checkpoint of a live
`BacktestEngine.run()` loop purely as an observer:
`tests/predict/test_predict_backtest_integration.py::
test_predictions_computed_at_every_checkpoint_do_not_change_the_backtest_result`
runs the identical strategy/config twice — once with predictions computed
alongside the run, once without — and asserts the resulting fills are
byte-identical. This is deliberately different from Phase 5's
`RegimeConditionedStrategy`, which *did* feed Regime into order
generation: this phase's stronger "Prediction 결과만으로 주문 생성 금지"
constraint (ADR-0012 §7) is honored by never wiring Prediction into a
Strategy's decisions at all, not even illustratively.

---

## 9. Prediction Consuming Regime — What Was Tested, and What Was Not Claimed

`RegimeAwarePredictor` (§1.1, ADR-0012 §6) wraps `DriftPredictor` +
`RegimeDetector`; when the subject's Volatility regime is `EXTREME`, it
dampens the expected-return estimate toward zero and lowers confidence.
What is verified (`tests/predict/test_regime_aware_predictor.py`):

- `regime_context` is always populated with all five axes.
- The damping only ever moves `expected_return` toward zero (never away
  from it) and only ever lowers confidence (never raises it), and only
  when Volatility is specifically `EXTREME` — never under any other
  state.
- It fails closed identically to the wrapped `DriftPredictor` when
  history is insufficient.

**What is explicitly not tested or claimed**: that `RegimeAwarePredictor`
produces a more accurate forecast than plain `DriftPredictor`. No such
assertion exists anywhere in this phase's test suite — the same
no-alpha-claim discipline ADR-0011 §6 established for
`RegimeConditionedStrategy`, applied here to Prediction.

---

## 10. Data Availability

Only deterministic, `MockDataProvider`-shaped fixture data is used
(`tests/backtest/backtest_helpers.py`'s existing builders, via
`tests/predict/predict_helpers.py`). No real external data provider is
selected in this phase — ADR-0005's decision remains deferred; nothing in
this phase requires it.

---

## 11. Persistence

Predictions are a DuckDB table (`predictions`) in the same catalog file
Phase 4's `StorageEngine` manages and Phase 5's Regime tables already
extended — not a new Parquet dataset. ADR-0012 §8 records the reasoning:
the same point-lookup/filter/join-heavy criterion ADR-0010 §1 / ADR-0011
§4 already applied to Benchmark and Regime data. `storage.
prediction_repository.DuckDBPredictionRepository` implements the exact
`predict.repository.PredictionRepository` Protocol the in-memory
reference implementation does — restart safety, natural-key idempotency
(on `(security_id, as_of_time, method, horizon_days,
configuration_version, provenance)`), and a point-in-time `get_as_of`
lookup are all verified in `tests/storage/test_prediction_repository.py`.

---

## 12. Paper Trading Readiness — Prediction ↔ Trade Journal Lineage

`ExperienceRecord.expected_outcome` (already present on Phase 3's model,
populated today only when `DecisionSnapshot.expected_return`/
`expected_risk` are set — never true for a Phase 2-sourced backtest) is
populated by `predict.experience.attach_prediction_context`, an opt-in
enrichment step mirroring `regime.experience.attach_regime_context`
exactly (ADR-0012 §9) — not a change to `build_experience_records`
itself. For each record, it resolves the record's decision via
`journal.get_decision`, then finds the prediction whose `as_of_time` is
the most recent one at or before that decision's `decision_time` — a
point-in-time query (`PredictionRepository.get_as_of`), so a decision is
never enriched with a prediction made after it
(`tests/integration/test_prediction_experience_lineage.py::
test_prediction_context_is_never_from_after_the_decision`). A record
whose `expected_outcome` is already populated (e.g., by a future Phase 7
Decision Agent that sets it directly) is left untouched, never
overwritten.

Prediction, Regime, Trade Journal, and Experiment all live in one DuckDB
catalog file, so this lineage join is a plain SQL query
(`tests/integration/test_prediction_experience_lineage.py::
test_prediction_and_trade_journal_share_the_same_storage_catalog`).

No Paper/Live producer of predictions exists yet (Phase 13/15/16) — this
phase proves the storage, lineage, and point-in-time-correctness are
ready to receive them, not that they are being produced.

---

## 13. Test Strategy

| Requirement | Test file |
|---|---|
| Deterministic calculation / parameter boundary | `tests/predict/test_predictor_baselines.py` |
| Point-in-time leakage / future-data rejection (Leakage Tests) | `tests/predict/test_predict_point_in_time.py` |
| Fail-closed on insufficient data | `tests/predict/test_fail_closed.py` |
| Version lineage / reproducibility | `tests/predict/test_predict_version_lineage.py` |
| Structural boundary with Decision/Risk/Execution | `tests/predict/test_boundary.py` |
| Backtest integration (observation, not influence) | `tests/predict/test_predict_backtest_integration.py` |
| Regime-as-input (no alpha claim) | `tests/predict/test_regime_aware_predictor.py` |
| Persistence / restart / idempotency / provenance | `tests/storage/test_prediction_repository.py` |
| Backtest → Journal → Prediction → Experience lineage | `tests/integration/test_prediction_experience_lineage.py` |

All of Phase 1-5's existing tests (310) continue to pass unmodified
(`python3 -m pytest tests/ -q`); Phase 6 adds 39 new tests, for **349
total**.

---

## 14. Research Grounding

No new paper is added to the research foundation this phase (per
instruction: "새로운 논문을 무작정 추가하지 않는다"). Per the "what
design decision requires evidence?" question the instruction asks to
pose first: the two baseline predictors (random walk / drift
extrapolation) are standard, textbook forecasting-baseline constructions
that require no new academic grounding beyond what
`PROJECT_MASTER_PLAN.md` §71 already registers, and neither decision
turned on a specific paper's result. If a future phase's predictor is
statistical/ML-based, research grounding is raised at that time — this
phase asked the question and answered "none needed, for two deterministic
baselines," the same conclusion Phase 5 reached for its regime
classifiers.

---

## 15. Overfitting Avoidance

No threshold in `PredictionConfig` (lookback window, horizon, the
`RegimeAwarePredictor` damping factors) was fit against backtest
performance — they are round, interpretable defaults, not search results.
`tests/predict/test_predictor_baselines.py::
test_different_lookback_yields_different_configuration_version` and
`test_longer_horizon_compounds_the_same_daily_drift` verify that trying
different configurations produces independently distinguishable
`configuration_version`s, the same "no configuration's identity is
silently discarded in favor of the best-looking one" discipline Phase
5's `test_experiment_count_and_configs_are_individually_recorded_not_
selected` already established.

---

## 16. DECISION REQUIRED Review

Per instruction, this phase evaluated every listed trigger:

- **실제 데이터 provider 선정**: Not needed — Phase 6 uses only
  deterministic mock/fixture data, the same as every prior phase.
- **Regime 정의 자체의 중대한 변경**: N/A to Regime's own definition
  (unchanged); the one Phase 5 code change (§2.3) is an additive rename,
  not a definitional change, verified against Phase 5's full test suite.
- **기존 storage schema 변경**: Not applicable — `predictions` is one
  new, additive table via the same idempotent DDL pattern every existing
  table uses; no existing table's schema changed.
- **Phase 3 미결 benchmark 문제 / data_version 문제 / corporate-action
  portfolio 재구성 문제**: Not resolved — all three remain unrelated to
  Prediction, which reads `DataRepository`/`AsOfDataView` exactly as
  Regime already does and does not touch `BacktestEngine`,
  `ingest_backtest_result`, or portfolio reconstruction at all.

**Conclusion**: no `DECISION REQUIRED` item needed resolution to complete
Phase 6's mandate. All Phase 3-originated open items remain correctly
deferred, consistent with their status at the end of Phase 4 and Phase 5.

---

## 17. Definition of Done for Phase 6

- [x] Git/branch integrity verified PASS before any Phase 6 work began
      (§0)
- [x] Master Plan / prior ADRs / prior specs / current `src/`+`tests/`
      reviewed (§0-2)
- [x] This specification written
- [x] Prediction architecture defined, boundary with Decision/Risk/
      Execution preserved structurally (§2, §8, ADR-0012 §1, §7)
- [x] Point-in-time correctness inherited from `AsOfDataView`, verified
      independently for the prediction code path (§3)
- [x] Two deterministic baseline predictors implemented, no trained
      model (§4, §6)
- [x] Prediction data model with full version lineage and honest
      `confidence`/`uncertainty` (§5, §7)
- [x] Backtest integration as pure observation, proven not to alter
      strategy behavior (§8)
- [x] Prediction-as-Regime-consumer experiment run, with an explicit,
      tested no-alpha-claim policy (§9)
- [x] Persistence: DuckDB table in the existing catalog, restart-safe,
      idempotent (§11, ADR-0012 §8)
- [x] Prediction ↔ Trade Journal / Experience lineage, non-invasive to
      Phase 3 (§12)
- [x] DECISION REQUIRED review completed — none required resolution (§16)
- [x] Full test suite passing: 349/349 (310 prior + 39 new)
- [x] `docs/PROJECT_STATUS.md` updated
- [x] `README.md` updated
- [x] Design + reference implementation committed to git
