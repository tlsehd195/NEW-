# ADR-0012: Prediction Layer Architecture

**Status:** Accepted
**Date:** 2026-08-24
**Deciders:** Claude Code (Phase 6 session), pending project owner review
**Related documents:** `PROJECT_MASTER_PLAN.md` §8.1, §4.1, ADR-0004
(point-in-time), ADR-0009 (Trade Journal data model & reuse), ADR-0011
(market regime detection), `docs/specifications/PHASE-6-prediction.md`

---

## Context

`PROJECT_MASTER_PLAN.md` §8.1 defines Prediction as separate from
Decision: it produces `expected_return`, `probability`,
`expected_volatility`, `uncertainty`, `confidence`, and nothing else --
"Prediction 결과만으로 바로 주문하지 않는다." The module boundary table
(§3) is explicit about what Prediction/Signal Engine must **not** do:
"매매 여부 결정, 포지션 크기 결정." This phase builds the first version
of that layer: deterministic, interpretable baseline predictors (no
trained model), the interface a future model-based predictor will
implement, and the persistence/lineage scaffolding a Learning Engine
(Phase 9) will eventually build on.

## Decision

### 1. `PredictionOutput` has no order/portfolio/risk-shaped field, structurally

`PredictionOutput` carries exactly `expected_return`, `probability`,
`expected_volatility`, `uncertainty`, `confidence`, plus lineage fields
-- no `side`, `quantity`, `target_weight`, `risk_state`, or
`portfolio_state`. `Predictor.predict(data: AsOfDataView, security_id,
...)` has no parameter through which a portfolio or risk state could
even be threaded in. This is the same choice ADR-0011 made for
`RegimeObservation` (no order-producing field) applied one layer up, and
is verified structurally by reflection
(`tests/predict/test_boundary.py`), not left as a documented convention
alone.

### 2. Predictors source data exclusively through `AsOfDataView`

Identical reuse to `RegimeDetector` (ADR-0011 §2): `Predictor.predict`
takes only `AsOfDataView`, so it inherits the point-in-time guarantee
Phase 1 (ADR-0004) and Phase 2 (spec §3.2) already built, with zero new
leakage-guard code. `RegimeAwarePredictor` additionally constructs a
`RegimeDetector` internally and calls it with the same `AsOfDataView` --
Regime and Prediction share the identical point-in-time-safe input
surface.

### 3. Two deterministic baselines, explicitly typed apart from a (unbuilt) model-based category

`PredictionMethodType.DETERMINISTIC_BASELINE` vs. `MODEL_BASED` is a
queryable, typed field on every `PredictionOutput` -- the instruction's
"deterministic baseline과 model-based prediction을 명확하게 구분"
requirement made structural, not left to a naming convention.
`RandomWalkPredictor` (`expected_return=0`, `probability=0.5` by
construction -- the null hypothesis, no data lookup at all) and
`DriftPredictor` (trailing-mean-return extrapolation + realized-
volatility persistence, both textbook naive forecasting baselines) are
the only two implementations Phase 6 ships; both are
`DETERMINISTIC_BASELINE`. No `MODEL_BASED` predictor exists yet --
`PredictionMethodType.MODEL_BASED` is reserved, exactly the extension
point the instruction asks for ("향후 더 복잡한 ML 모델을 추가할 수 있는
interface를 설계한다") without building one now.

### 4. `confidence` is a real completeness ratio, `uncertainty` is a real standard error -- neither is fabricated

`confidence` reuses the exact `data_completeness()` reliability
computation `RegimeObservation.reliability` already established (ADR-0011
§7) -- the fraction of the required lookback window actually available,
forced toward 0 (and every numeric estimate to `None`) when insufficient
(fail-closed, `PROJECT_MASTER_PLAN.md` §1.4 applied to Prediction).
`uncertainty` on `DriftPredictor` is the standard error of the sample
mean return (`stdev(returns) / sqrt(n)`) -- a real, computable dispersion
measure for the specific number being estimated, not a generic
placeholder. `RandomWalkPredictor` reports `uncertainty=None` because its
`expected_return=0` is not derived from a sample at all -- there is no
"standard error" of a value fixed by construction, and reporting one
would be exactly the fabricated-precision failure mode ADR-0009 §4
already rejected for the Trade Journal.

### 5. `annualized_realized_vol` promoted from Phase 5's private helper to a shared public one

`DriftPredictor`'s volatility-persistence estimate reuses
`regime.features.annualized_realized_vol` directly, rather than
reimplementing the same realized-volatility formula a second time. That
function was previously private (`_annualized_realized_vol`) inside
`regime/features.py`; this phase renames it (removing the leading
underscore) so it can be imported from `predict/predictor.py`. This is a
minor, additive, backward-compatible rename -- its behavior, signature,
and every internal caller within `regime/features.py` are otherwise
unchanged, verified by Phase 5's full test suite (48 tests) still passing
unmodified. This is the same "don't duplicate math across phases"
precedent Phase 5 itself set by reusing `backtest.metrics.
compute_max_drawdown` directly for its Stress axis (ADR-0011), continued
one phase further; `backtest.metrics.compute_returns` (already public
since Phase 2) is reused the same way for return-series computation.

### 6. `RegimeAwarePredictor` demonstrates the Regime → Prediction connection, with the same no-alpha-claim policy Phase 5 established

`PROJECT_MASTER_PLAN.md` §4.1's data flow places "Market Regime Detection
→ Prediction/Signal Engine" directly in sequence. `RegimeAwarePredictor`
wraps `DriftPredictor` + a `RegimeDetector`, damping the expected-return
estimate toward zero and reducing confidence specifically when the
Volatility regime is `EXTREME`, and always populating `regime_context`
with every axis's state for lineage. Every test exercising it
(`tests/predict/test_regime_aware_predictor.py`) asserts only mechanical
properties of the damping rule itself (it triggers only under
`EXTREME`, and only ever moves the estimate toward zero / lowers
confidence) -- **no test claims this predictor is more accurate than the
plain `DriftPredictor`.** This is the identical discipline ADR-0011 §6
established for `RegimeConditionedStrategy`, carried into Phase 6.

### 7. No Prediction→Order wrapper Strategy is built

Unlike Phase 5's `RegimeConditionedStrategy` (which the Phase 5
instruction explicitly asked for, as a conditioning-variable
experiment), this phase does **not** build a Strategy that converts a
`PredictionOutput` into an order, even illustratively. The instruction
for this phase states the constraint more strongly than Phase 5's did:
"Prediction 결과만으로 주문 생성 금지" is listed as principle #4, and with
no Position Sizing/Risk Engine yet (Phase 8) to gate a
prediction-derived order, any such wrapper would blur precisely the
boundary this phase exists to keep intact. Instead, "backtest
integration" is demonstrated by computing predictions at every checkpoint
of a live `BacktestEngine.run()` loop as a pure observer, and proving the
strategy's own fills/performance are byte-identical whether or not
predictions were computed alongside it
(`tests/predict/test_predict_backtest_integration.py::
test_predictions_computed_at_every_checkpoint_do_not_change_the_backtest_result`).

### 8. Persistence: a DuckDB table, not Parquet

`predictions` is a new DuckDB table in Phase 4's existing catalog file --
the identical criterion ADR-0010 §1 / ADR-0011 §4 already applied to
Benchmark and Regime data (point-lookup/filter/join-heavy relational
data, not a bulk-columnar-scan workload). No existing table's schema
changed.

### 9. Regime↔Journal lineage pattern reused for Prediction↔Journal lineage

`predict.experience.attach_prediction_context` is structurally identical
to `regime.experience.attach_regime_context` (ADR-0011 §5): an opt-in,
post-hoc enrichment over an existing `ExperienceRecord` list, using a
point-in-time `PredictionRepository.get_as_of` lookup, never modifying
`trade_journal.experience.build_experience_records` itself. It populates
`ExperienceRecord.expected_outcome` -- already present on Phase 3's model
-- rather than requiring a new field.

## Alternatives Considered

- **A trained statistical/ML model in Phase 6** (linear regression,
  gradient boosting, etc.): Rejected -- the instruction is explicit ("처음
  부터 복잡한 딥러닝 모델을 도입하지 마라"), and no baseline yet exists to
  know whether a trained model would be worth its added complexity/
  overfitting risk (the same "baseline first" principle Phase 4 already
  applied to strategies and Phase 5 to regime models).
- **Reimplementing realized volatility inside `predict/predictor.py`**
  instead of promoting Phase 5's helper to public: Rejected -- would
  create two copies of the same formula that could silently drift apart;
  the rename is a smaller, safer change (verified against the full prior
  suite) than accepting that duplication.
- **A `PredictionInformedStrategy` wrapper, mirroring
  `RegimeConditionedStrategy`**: Rejected -- see point 7 above; this
  phase's instruction is stricter about the Prediction/Decision boundary
  than Phase 5's was about Regime/Strategy, and building one now would
  work against that constraint rather than demonstrate it.
- **Storing predictions per-security in Parquet** (reasoning: predictions
  could scale like `securities × checkpoints`, similar order to OHLCV):
  Rejected for the same reason Regime observations were kept in DuckDB
  despite a similar scaling shape (ADR-0011 §4) -- the actual access
  pattern (natural-key idempotency, `get_as_of` point-in-time lookups,
  joins against `decisions`) is relational/point-lookup-shaped, not
  bulk-columnar-scan-shaped.

## Consequences

### Positive

- Zero new point-in-time-guard code, for the same reason Phase 5 needed
  none: `AsOfDataView` reuse.
- `RandomWalkPredictor` gives every future, more sophisticated predictor
  (including a real model, once `MODEL_BASED` is actually used) a
  concrete, trivial-to-beat null baseline recorded in the same repository
  and comparable the same way.
- Prediction, Regime, Trade Journal, and Experiment all live in one
  DuckDB catalog file, so a decision's prediction context is a plain SQL
  join.

### Negative / Trade-offs

- `DriftPredictor`'s `probability` is a coarse empirical frequency
  (fraction of individual daily returns in the lookback window that were
  positive), not a rigorously compounded multi-day-horizon probability --
  documented as a deliberate simplification (Phase 6 spec section 6),
  not presented as more precise than it is.
- `RegimeAwarePredictor`'s damping rule (halve the return estimate and
  confidence under EXTREME volatility) uses round, undocumented-by-
  research parameter values (`PredictionConfig.
  regime_extreme_vol_damping = 0.5`), the same category of "illustrative,
  not fitted" choice ADR-0011 already accepted for Regime's own
  thresholds -- not claimed optimal, and not searched for over historical
  data (no overfitting risk from this phase's own testing process).

## Status of Implementation at Time of This ADR

Implemented in `src/predict/` (`enums.py`, `config.py`, `models.py`,
`predictor.py`, `repository.py`, `experience.py`) and
`src/storage/prediction_repository.py` (+ `storage/schema.py`,
`storage/serialization.py` additions), plus one additive rename in
`src/regime/features.py` (`_annualized_realized_vol` →
`annualized_realized_vol`). Exercised by `tests/predict/`,
`tests/storage/test_prediction_repository.py`, and
`tests/integration/test_prediction_experience_lineage.py`.
