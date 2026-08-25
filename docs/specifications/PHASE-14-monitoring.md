# Phase 14 — Monitoring

## 0. Git / Branch Integrity Check (performed before any implementation)

This session started from the state Phase 13 left: on
`claude/phase-13-toss-securities-adapter`, HEAD
`5b4b30cfd50c233ac83181b7dd5db7f36bd2feb9` ("Phase 13: Toss Securities
Adapter"), working tree clean. `git log --oneline --graph --decorate
--all` confirmed a single linear history (`Initial commit → Phase 0 →
… → Phase 13`), zero merge commits (`git log --merges --oneline | wc
-l` → `0`). `git merge-base HEAD origin/main` returned `origin/main`'s
own HEAD (`c3abad0eb9b2ba1ed4dda5ee158b448606a87d59`, "Initial
commit") — `main` is a strict, non-diverged ancestor, nothing on
`main` outside this lineage. A new branch,
`claude/phase-14-monitoring`, was created from this verified HEAD (not
`main`). The full suite was run before any Phase 14 code was written:
**901/901 tests passed** (baseline).

## 1. Scope

Per `PROJECT_MASTER_PLAN.md` §12 (Kill Switch & 장애/복구 규칙,
specifically §12.4's Monitoring metrics list and §12.5's Alerting
severities) and §11.6 (Drift Detection triggers re-validation, never
automatic model replacement), and the handoff's 23-section
instruction, this phase implements a strictly **read-only**
observability layer over Phases 1-13:

- **Monitoring domain models**: `monitoring.models.MonitoringEvent`/
  `ComponentHealth`/`DriftResult`/`Alert`.
- **Metric computation**: `monitoring.metrics` — pure functions over
  already-materialized Phase 1-13 record sequences (data quality,
  prediction, decision, sizing, risk, broker, AI Gateway, learning,
  model evolution).
- **Health evaluation**: `monitoring.health` — deterministic
  `ComponentHealthStatus` verdicts (`HEALTHY`/`DEGRADED`/
  `UNAVAILABLE`/`UNKNOWN`) from those metrics, plus end-to-end
  pipeline aggregation.
- **Drift detection**: `monitoring.drift` — three deterministic,
  statistically simple detectors (mean shift, variance shift,
  bucket-frequency distribution shift).
- **Alerting**: `monitoring.alerts` — pure mapping from an event/
  health/drift observation to an `Alert` (`INFO`/`WARNING`/
  `CRITICAL`/`UNKNOWN`), logging-centric per §12.5's "초기에는
  logging 중심으로 구현."
- **Collection/orchestration**: `monitoring.collectors` (point-in-time
  filtering + metric + health per component) and `monitoring.pipeline`
  (end-to-end aggregation + alert assembly).
- **Persistence + lineage**: four new DuckDB tables
  (`monitoring_events`, `component_health_states`, `drift_results`,
  `alerts`), reusing every id Phase 1-13 already assigned.

### 1.1 Explicitly out of scope

- **Trading execution of any kind.** Monitoring is not "the layer that
  decides to trade" (instruction's own framing: "Monitoring은 '거래를
  결정하는 계층'이 아니다") — nothing here can construct or submit a
  `broker.models.ValidatedOrder`.
- **Automatic model approval/deployment/retraining.** Drift detection
  produces an *observation* only; §11.6 is explicit that drift
  triggers re-validation, never automatic replacement. No code path in
  `monitoring.*` can assign `learning.enums.CandidateModelStatus.
  APPROVED`/`DEPLOYED`, and nothing here invokes a trainer.
  §3's module table itself names this the module's own prohibition:
  "모델 재학습 자체 실행" is listed as what Monitoring/Drift Detection
  must **not** do.
- **Mutating any prior-phase state.** No code in `monitoring.*` calls
  a Risk/Sizing/Decision/Broker mutator; every `ComponentHealth`/
  `MonitoringEvent` is a new, independent observation record.
- **Real external notification channels** (email/Slack/PagerDuty). Per
  §12.5's "초기에는 logging 중심으로 구현," `Alert` is a durable,
  queryable record — the actual notification transport is deferred
  (ADR-0020's Known Limitations).
- **Paper Trading / Live Trading.** Phase 15's own scope.

## 2. Architecture Boundary

```
Data / Regime / Prediction / Decision / Sizing / Risk / Broker / AI Gateway / Learning / Model Evolution (Phases 1-13)
        │  (already-materialized records, read only)
        ▼
  monitoring.collectors  →  monitoring.metrics  →  monitoring.health
        │                                               │
        ▼                                               ▼
  monitoring.drift  ───────────────────────►  monitoring.pipeline
        │                                               │
        ▼                                               ▼
  MonitoringEvent / ComponentHealth / DriftResult  →  monitoring.alerts → Alert
        │
        ▼
  storage.monitoring_repository (DuckDB, additive-only)
```

`monitoring.*` sits strictly downstream of every other phase, never
alongside or upstream of it:

| It is **not** | Why |
|---|---|
| Decision Agent / Position Sizer / Risk Engine | never imports `decision.agent`/`risk.sizing`/`risk.engine`; produces no `DecisionAction`/target weight of its own |
| Broker Adapter | never imports `broker.pipeline`/`broker.validation`/`broker.protocol`; cannot submit/cancel an order |
| AI Gateway | never imports `ai_gateway.gateway`; cannot call a real provider |
| Model Registry approver | reads `learning.enums.CandidateModelStatus` (to *count* observed transitions) but never assigns `.APPROVED`/`.DEPLOYED` — the boundary is "never write," not "never read" |
| Kill Switch executor | produces `Alert`s a human/future system can act on; nothing here halts trading or flips an execution mode |

`tests/monitoring/test_monitoring_boundary.py` verifies every row
structurally (AST scan across the whole package + `dataclasses.fields`
reflection), not just by convention.

## 3. Monitoring Event Model

`MonitoringEvent` (`monitoring/models.py`) is one observation over an
already-computed metric set: `event_id`, `component`
(`MonitoringComponent`), `event_type`, `severity` (`AlertSeverity`),
`observed_at` (when the computation ran), `as_of_time` (the
point-in-time cutoff records were filtered to), `metrics` (a
`dict[str, Optional[float]]` — a metric that could not be honestly
computed is `None`, never a fabricated `0.0`), plus
`configuration_version`/`data_version`/`source_record_ids` for
lineage. `source_record_ids` carries forward whichever upstream ids
(decision_id/risk_id/request_id/candidate_id/etc.) the event
summarizes — Monitoring never mints a parallel identity system.

## 4. Health Evaluation

`monitoring/health.py` provides three evaluator shapes over
`monitoring.config.MonitoringConfig` thresholds, plus one aggregator:

- `evaluate_health_from_failure_rate` — Broker, AI Gateway, Risk,
  Sizing: `UNKNOWN` if `sample_count` is missing/below
  `min_sample_count` or `failure_rate` is non-finite; else
  `HEALTHY`/`DEGRADED`/`UNAVAILABLE` by threshold. Sizing is grouped
  here (not with the existence evaluators below) because its
  `REJECT`/`UNKNOWN` outcomes are a meaningful failure signal, unlike
  Decision's `NO_TRADE`/`HOLD`.
- `evaluate_existence_health` — Prediction, Decision, Learning, Model
  Evolution: `NO_TRADE`/`HOLD` are legitimate Decision outputs
  (`PROJECT_MASTER_PLAN.md` §8.2), so this only checks that the layer
  *produced* output at all, never what it produced. `UNKNOWN` if count
  is `None`; `UNAVAILABLE` if `count <= 0`.
- `evaluate_data_health` — Data: combines observation-count
  sufficiency, `invalid_rate`, and staleness (`stale_seconds` vs.
  `MonitoringConfig.stale_data_max_age_seconds`).
- `evaluate_pipeline_health` — worst-of aggregation across every
  observed `ComponentHealth`
  (`UNAVAILABLE > UNKNOWN > DEGRADED > HEALTHY`); an empty input is
  `UNKNOWN` ("no_components_observed"), never assumed healthy.

## 5. Fail-Closed Behavior

| Situation | Result |
|---|---|
| Metric input empty | every `metrics.py` rate/mean is `None`, count is `0.0` — never a fabricated `0.0` rate |
| Sample count below `min_sample_count` | `ComponentHealthStatus.UNKNOWN` |
| Failure rate / invalid rate non-finite (`NaN`/`inf`) | `ComponentHealthStatus.UNKNOWN` |
| No component healths observed for a pipeline run | `ComponentHealthStatus.UNKNOWN` ("no_components_observed") |
| Drift sample below `min_drift_sample_count` | `DriftStatus.UNKNOWN` ("insufficient_sample") |
| Drift baseline degenerate (zero stdev/variance/range) | `DriftStatus.UNKNOWN` |
| `BrokerCapabilities` entries never confirmed | counted via `compute_capability_unknown_count`, never treated as `ENABLED` |
| `ComponentHealthStatus.UNKNOWN` anywhere in a pipeline | never coerced to `HEALTHY`; outranks `DEGRADED` in `evaluate_pipeline_health` |
| Drift detected | `DriftStatus.DRIFT_DETECTED` — an observation, never a model swap (§11.6) |

## 6. Drift Detection

`monitoring/drift.py` — statistically simple and deterministic by
design (instruction: "초기 구현은 통계적으로 단순하고 deterministic한
방법을 사용하라"):

- `detect_mean_shift` — z-score = `|current_mean - baseline_mean| /
  baseline_stdev`, vs. `MonitoringConfig.mean_shift_z_threshold`.
- `detect_variance_shift` — ratio = `max(var) / min(var)`, vs.
  `variance_shift_ratio_threshold`.
- `detect_distribution_shift` — a simplified, deterministic
  bucket-frequency-difference statistic: equal-width buckets spanning
  the *baseline*'s own `[min, max]` range (never the current window's
  range); values outside that range clamp to the nearest edge bucket
  rather than being dropped. Documented as "PSI-like," not a textbook
  Population Stability Index (ADR-0020 §"Known Limitations").

All three return `DriftStatus.UNKNOWN` when either sample is below
`min_drift_sample_count`, or the baseline is degenerate (zero
stdev/variance/range) — never a guessed verdict from too little or
unusable data. A `DRIFT_DETECTED` verdict is a fact about a statistic
crossing a configured threshold, not a diagnosis of cause; `alerts.py`
raises it as `WARNING`, never `CRITICAL` — a trigger for
re-validation, never an automatic action (§11.6).

## 7. Alerting

`monitoring/alerts.py` — pure, deterministic mapping only, never a
side-effecting notification call:

- `severity_for_health_status`: `HEALTHY→INFO`,
  `DEGRADED→WARNING`, `UNAVAILABLE→CRITICAL`, `UNKNOWN→UNKNOWN`.
- `raise_alert_from_event`/`raise_alert_from_health`: `None` when the
  resulting severity is `INFO` — a routine observation is never
  escalated.
- `raise_alert_from_drift`: `NO_DRIFT→None`;
  `DRIFT_DETECTED→WARNING`; `UNKNOWN→UNKNOWN` severity.

`Alert` is append-only — this phase does not implement
acknowledgement/resolution workflow at all (ADR-0020's Known
Limitations); once raised, an `Alert` is never mutated.

## 8. Collectors

`monitoring/collectors.py` is the only place in `monitoring.*` that
combines point-in-time filtering with `metrics.py` + `health.py`. Nine
collectors, one per component: `collect_data_quality`,
`collect_prediction`, `collect_decision`, `collect_sizing`,
`collect_risk`, `collect_broker`, `collect_ai_gateway`,
`collect_learning`, `collect_model_evolution`. Every collector filters
its input sequence to `<field> <= as_of_time` *before* calling
`metrics.py` (`PriceBar.available_time`, `PredictionOutput.as_of_time`,
`DecisionOutput.as_of_time`, `PositionSizingResult.as_of_time`,
`RiskCheckedPosition.as_of_time`, `BrokerRequestRecord.requested_at`/
`BrokerResponseRecord.responded_at`, `AIResponse.responded_at`,
`TrainingDataset.created_at`/`CandidateModelArtifact.trained_at`/
`EvaluationResult.evaluated_at`, `ModelStatusTransition.evaluated_at`)
— `metrics.py`'s own functions are deliberately pure and unfiltered,
so no metric can ever be influenced by a record that would not yet
have existed as of `as_of_time` (§13's leakage-protection
requirement). `ModelLineageRecord.recorded_at` is set by the
repository at persistence time and may be `None` on a record
constructed before it has ever been persisted; such a record is kept
rather than dropped (it carries no forward-looking information beyond
the `candidate_id` the caller already selected) — only a record with a
*known future* `recorded_at` is excluded.

## 9. Pipeline Orchestration

`monitoring/pipeline.py::assemble_pipeline_observation` takes the
`(MonitoringEvent, ComponentHealth)` pairs already produced by one
run's collectors, computes one aggregated pipeline `ComponentHealth`
via `evaluate_pipeline_health`, and raises every qualifying `Alert`
from the run's events/healths/drifts via `alerts.py`'s pure functions.
It performs no metric or health computation of its own — purely
aggregation. `alert_id_factory` is caller-supplied (not invented by
this function), matching the caller-assigned, globally-unique id
discipline every prior phase already uses.

## 10. Persistence

Four new tables in Phase 4's existing DuckDB catalog file
(`src/storage/schema.py`, purely additive — `git diff src/storage/
schema.py src/storage/serialization.py | grep '^-'` shows zero
deleted/changed lines against the Phase 13 baseline):

- `monitoring_events`/`alerts` — dedupe on the caller-assigned
  `event_id`/`alert_id` directly (the same Phase 5-8/12/13
  `decisions`/`predictions`/`ai_requests`/`broker_requests` pattern) —
  two events/alerts with identical content are still two distinct
  observations, not duplicates of one another.
- `component_health_states`/`drift_results` — append-only
  (seq-ordered), the same `regime_observations`/`provider_quota_states`/
  `model_status_transitions` pattern (Phase 5/12/11) — idempotent only
  on the record's own `health_id`/`drift_id`.

Only one `monitoring_metrics` table was considered and deliberately
**not** built: per-event metrics are folded into
`MonitoringEvent.metrics` (a JSON payload column) instead, keeping to
"필요한 최소 테이블만" (ADR-0020 §"Decision: No Separate Metrics
Table"). The one non-primitive value ever stored in `metrics`
(`compute_data_quality_metrics`'s `latest_available_time`, a real
`datetime`, needed for `collectors.py`'s staleness arithmetic) is
round-tripped explicitly by `storage/serialization.py`'s
`_deserialize_metrics` helper so a reloaded `MonitoringEvent` is
identical to the one that was persisted.

## 11. Lineage Traceability

```
Risk (Phase 8) / Broker (Phase 13) / any Phase 1-13 output
   → monitoring.collectors → MonitoringEvent (source_record_ids) → ComponentHealth / DriftResult → Alert
```

`tests/integration/test_monitoring_lineage.py` proves this is
SQL-joinable — `risk_assessments` ⋈ `monitoring_events` via
`list_contains(CAST(json_extract(monitoring_events.payload_json,
'$.source_record_ids') AS VARCHAR[]), risk_assessments.risk_id)` — and
survives a process restart. `monitoring.*` never regenerates a
`RiskCheckStatus`/`DecisionAction`/order of its own — every id in
`source_record_ids` is carried forward from what an earlier phase
already produced.

## 12. Point-in-Time

Every collector requires an explicit `as_of_time` parameter with no
default (`inspect.signature` verified,
`tests/monitoring/test_monitoring_leakage.py`); nothing in
`monitoring.*` calls `datetime.now()`/`datetime.utcnow()`
(AST-verified across the whole package). Adding a future observation
to an already-filtered input never changes a past collector's result
— proven directly by constructing the same collector call with and
without an out-of-window future record and asserting identical
`metrics`/`health.status`.

## 13. Reproducibility

No module in `monitoring.*` imports `random`
(`tests/monitoring/test_monitoring_reproducibility.py`, an AST scan).
The same input sequence + `MonitoringConfig` + `as_of_time` always
produces byte-identical `ComponentHealth`/`DriftResult`/
`MonitoringEvent` output.

## 14. Test Strategy

| Category | File |
|---|---|
| Metric computation | `tests/monitoring/test_monitoring_metrics.py` |
| Health evaluation | `tests/monitoring/test_monitoring_health.py` |
| Drift detection | `tests/monitoring/test_monitoring_drift.py` |
| Alerting | `tests/monitoring/test_monitoring_alerts.py` |
| Collectors (per-component) | `tests/monitoring/test_monitoring_collectors.py` |
| Pipeline orchestration | `tests/monitoring/test_monitoring_pipeline.py` |
| Leakage / point-in-time | `tests/monitoring/test_monitoring_leakage.py` |
| Boundary (no order/broker/risk/decision mutation, no model approval, no AI provider call) | `tests/monitoring/test_monitoring_boundary.py` |
| Reproducibility | `tests/monitoring/test_monitoring_reproducibility.py` |
| In-memory repository | `tests/monitoring/test_monitoring_repository_inmemory.py` |
| Persistence / restart / idempotency (DuckDB) | `tests/storage/test_monitoring_repository.py` |
| Integration lineage (SQL join, restart, mixed health) | `tests/integration/test_monitoring_lineage.py` |

## 15. Definition of Done

- [x] Implementation matching this spec
- [x] Unit + integration tests, all passing (see completion report for exact counts)
- [x] Fail-closed handling: `UNKNOWN` is never coerced to `HEALTHY`;
      a metric that cannot be honestly computed is `None`, never a
      fabricated `0.0`
- [x] Logging/audit: `monitoring_events`/`component_health_states`/
      `drift_results`/`alerts` is the durable record of every
      observation
- [x] Documentation: this spec + ADR-0020
- [x] Configuration: `MonitoringConfig` — every threshold explicit and
      validated, no hardcoded magic numbers scattered across the
      package
- [x] Validation: structural boundary tests confirm no order/broker/
      risk/decision mutation, no model approval/deployment path, and
      no direct AI provider call
