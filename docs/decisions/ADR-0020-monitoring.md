# ADR-0020: Monitoring

**Status:** Accepted

(Renumbered from the handoff's suggested `ADR-0019` — that number was
already taken by Phase 13's `ADR-0019-toss-securities-adapter.md`; this
is the next free number in sequence.)

## Context

`PROJECT_MASTER_PLAN.md` §12 (Kill Switch & 장애/복구 규칙) specifies a
Monitoring metrics list (§12.4: portfolio_value/cash/positions/
exposure/PnL/drawdown/orders/fills/API status/data status/model
status/feature drift/prediction drift/performance) and Alerting
severities (§12.5: `CRITICAL`/`WARNING`/`INFO`, "초기에는 logging
중심으로 구현"). §11.6 establishes that drift detection triggers a
re-validation process, never an automatic model replacement. §3's
module table names Monitoring/Drift Detection's own explicit
prohibition: "모델 재학습 자체 실행" (executing retraining itself) is
listed as what this module must **not** do. The handoff's own framing
is direct: "Monitoring은 '거래를 결정하는 계층'이 아니다" (Monitoring
is not the layer that decides to trade).

This session's Git/Branch Integrity Check (see
`docs/specifications/PHASE-14-monitoring.md` §0) found the repository
in a clean, correctly-lineaged state on the prior session's
`claude/phase-13-toss-securities-adapter` branch and created
`claude/phase-14-monitoring` from that verified HEAD.

Unlike Phase 12/13, this phase makes no external network call and
resolves no secret at all — every input is an already-materialized
Phase 1-13 record sequence the caller supplies. The central design
question is therefore not "what can we confirm about a third-party
API" but "how do we observe eleven prior phases without ever becoming
able to influence any of them."

## Decision

### 1. Every collector filters explicitly to `as_of_time` before calling
   a metrics function — `metrics.py` itself is never given that
   responsibility

`monitoring.metrics`'s functions are deliberately pure over whatever
sequence they receive, with no `as_of_time` parameter at all. Putting
point-in-time filtering there would mean every future metric function
added to this module has to remember to filter correctly; instead,
`monitoring.collectors` is the single, obvious place that discipline
lives, one filter expression per component keyed to that record type's
already-established point-in-time field (`PriceBar.available_time`,
`PredictionOutput.as_of_time`, `BrokerResponseRecord.responded_at`,
etc.) — the same "point-in-time field already exists, just use it"
principle every prior phase's own point-in-time boundary already
established, applied one layer downstream.

### 2. `UNKNOWN` is a first-class `ComponentHealthStatus`/`DriftStatus`/
   `AlertSeverity` value, never collapsed into `HEALTHY`/`NO_DRIFT`/`INFO`

A monitoring system that silently treats "I don't have enough data to
tell" as "everything is fine" is worse than having no monitoring at
all — it manufactures false confidence exactly when a human most needs
an honest "I don't know." Every evaluator in `health.py`/`drift.py`
checks its inputs' sufficiency *before* computing a verdict, and
returns `UNKNOWN` on any missing/non-finite/degenerate input, never
falling through to a default. `evaluate_pipeline_health`'s worst-of
aggregation ranks `UNAVAILABLE > UNKNOWN > DEGRADED > HEALTHY`
specifically so one `UNKNOWN` component health cannot be outvoted by
several `HEALTHY` ones into an overall `HEALTHY` pipeline verdict.

### 3. Sizing is evaluated by failure rate, like Risk — not by mere
   existence, like Decision

`health.py`'s two generic evaluators were designed around a real
distinction: Decision's `NO_TRADE`/`HOLD` are legitimate business
outcomes (`PROJECT_MASTER_PLAN.md` §8.2), so "did this layer produce
output" is the right question for it. `PositionSizingResult.status`,
however, uses the same `RiskCheckStatus` vocabulary as
`RiskCheckedPosition.status` — a `REJECT` from Sizing is a genuine
operational failure signal (the position could not be sized), not a
legitimate business outcome the way `HOLD` is. `collect_sizing`
therefore computes a `failure_rate` (`reject_rate + unknown_rate`, the
identical formula `compute_risk_metrics` already uses for Risk) and
evaluates it through `evaluate_health_from_failure_rate`, even though
`compute_sizing_metrics` itself does not expose a `failure_rate` key —
that combination is intentionally left to the collector rather than
added to the metrics function, since it is a health-evaluation
decision, not a property of the raw metric.

### 4. No separate `monitoring_metrics` table — metrics live inside
   `MonitoringEvent.metrics`, a JSON payload column

The instruction suggested `monitoring_metrics` as one possible table.
A separate table would need its own schema per metric shape (data
quality's metrics look nothing like AI Gateway's), which either means
one enormous sparse table or one table per component — both add
storage-layer complexity for data that is only ever read back
alongside the `MonitoringEvent` that produced it, never queried across
events by individual metric name in this phase's scope. Folding
metrics into `MonitoringEvent.metrics` (already how the in-memory
domain model represents them) keeps the persisted schema to exactly
four tables — "필요한 최소 테이블만." The one non-JSON-primitive value
ever stored there (`compute_data_quality_metrics`'s
`latest_available_time`, a real `datetime`, needed for
`collectors.py`'s own staleness arithmetic) is round-tripped by a
small, explicit `_deserialize_metrics` helper in
`storage/serialization.py` rather than left to decay into a string on
reload.

### 5. `monitoring_events`/`alerts` dedupe on the caller-assigned id
   directly; `component_health_states`/`drift_results` are append-only

The same distinction ADR-0018 §4/ADR-0019 §4 already established for
`ai_requests`/`broker_requests` applies unchanged: `MonitoringEvent`/
`Alert` are event-log entries (two observations with identical content
raised at different times are two distinct events, not duplicates),
while `ComponentHealth`/`DriftResult` are "one observation per point
in time" history records, the same shape as `ProviderQuotaState`/
`ModelStatusTransition` (Phase 11/12). Both `InMemory*` and `DuckDB*`
repositories in this phase are idempotent only on the record's own id
either way — the difference is purely in what "the record's identity"
means for each type, not in the idempotency discipline itself.

### 6. `monitoring.metrics` imports `learning.enums.CandidateModelStatus`
   — the boundary is "never assign `.APPROVED`/`.DEPLOYED`," not "never
   import the enum"

`broker.*` (Phase 13) has no legitimate reason to reference Model
Evolution's status vocabulary at all, so its boundary test forbids
importing `learning.enums` outright. Monitoring's job is different: it
must *count* how many observed `ModelStatusTransition`s reached
`BACKTESTED`/`VALIDATED`/`OOS_TESTED`
(`compute_model_evolution_metrics`), which requires referencing those
enum members to build the `Counter` lookup. The structural guarantee
this phase actually needs is narrower and is what
`tests/monitoring/test_monitoring_boundary.py` enforces: no `.attr`
access to `APPROVED`/`DEPLOYED` anywhere in the package (AST-scanned),
and no assignment path to either state at all — reading the vocabulary
to report on it is not the same violation as writing to it.

### 7. Distribution shift uses a simplified, deterministic
   bucket-frequency-difference statistic — documented as "PSI-like,"
   not a textbook Population Stability Index

The project has no numerical/statistics dependency (only
`duckdb`/`pyarrow`), and the instruction explicitly asked for an
initial implementation that is "통계적으로 단순하고 deterministic."
Equal-width bucketing over the baseline sample's own `[min, max]`
range, with the current sample's values clamped into the nearest edge
bucket rather than dropped when they fall outside that range, gives a
fully deterministic, dependency-free statistic that behaves the way a
practitioner would expect (larger difference in bucket occupancy →
larger statistic) without claiming the precision of a textbook PSI
(which typically uses log-ratio terms and handles zero-frequency
buckets specially). Both `detect_mean_shift`/`detect_variance_shift`
are exact, well-defined statistics (z-score, variance ratio) — only
the distribution-shift detector needed this disclaimer.

## Alternatives Considered

1. **Give `metrics.py` functions an `as_of_time` parameter and do the
   filtering internally.** Rejected — see decision 1; would spread the
   point-in-time discipline across nine near-identical filtering
   blocks instead of concentrating it in one collector module, and
   would make every future metrics function's correctness depend on
   remembering to filter, rather than being handed already-filtered
   input.
2. **Treat `ComponentHealthStatus.UNKNOWN` as equivalent to `HEALTHY`
   for pipeline aggregation** (i.e. only escalate on `DEGRADED`/
   `UNAVAILABLE`). Rejected — see decision 2; directly contradicts the
   fail-closed discipline every prior phase in this codebase already
   established (e.g. `BrokerOrderStatus.UNKNOWN ≠ FILLED`, Phase 13),
   and would hide exactly the "we don't actually know" case a
   monitoring layer exists to surface.
3. **Automatically trigger re-training or candidate promotion when
   `DriftStatus.DRIFT_DETECTED`.** Rejected outright — this is
   `PROJECT_MASTER_PLAN.md` §11.6 and §3's explicit prohibition; no
   code path in `monitoring.*` invokes `learning.trainer`/
   `evolution.criteria` at all.
4. **A separate `monitoring_metrics` table, one row per metric name per
   event.** Rejected — see decision 4; adds schema and join complexity
   for data this phase never needs to query independently of its
   parent `MonitoringEvent`.
5. **Real notification channels (email/Slack) for `CRITICAL` alerts.**
   Rejected for this phase — `PROJECT_MASTER_PLAN.md` §12.5 itself
   scopes the initial implementation to logging-centric; `Alert` is a
   durable, queryable record a future phase can wire a transport onto,
   not a notification system in itself.
6. **A textbook Population Stability Index implementation** (log-ratio
   terms, explicit zero-frequency handling). Rejected for this phase —
   see decision 7; would need either a numerical dependency this
   project does not have or a meaningfully more complex hand-rolled
   implementation, for a phase whose instruction explicitly asked for
   simplicity first.

## Consequences

### Positive

- Zero modifications to Phase 1-13 source files; `git diff | grep
  '^-'` on `src/storage/schema.py` and `src/storage/serialization.py`
  shows no deleted/changed lines, only additions.
- No code path anywhere in `monitoring.*` can submit/cancel an order,
  mutate a Risk/Sizing/Decision result, or assign
  `CandidateModelStatus.APPROVED`/`DEPLOYED` — all verified
  structurally (AST scan + dataclass field reflection), not by
  convention.
- `UNKNOWN` is honest and pervasive: every evaluator fails closed on
  insufficient/non-finite/degenerate input, and pipeline aggregation
  cannot be outvoted into a falsely healthy verdict.
- The full `Risk → MonitoringEvent → ComponentHealth/Alert` chain is
  SQL-joinable (via `json_extract` over `source_record_ids`) and
  survives a restart, proven by an actual integration test.

### Negative / Trade-offs

- The distribution-shift statistic is not a textbook PSI — a future
  phase that needs exact PSI semantics (e.g. for a formal model-risk
  report) will need a dedicated implementation, not just a threshold
  tweak to this one.
- No real alert notification transport exists yet — a `CRITICAL`
  `Alert` is durably recorded and queryable, but nothing currently
  pages anyone; wiring an actual channel is deliberately deferred to a
  future phase.
- No acknowledgement/resolution workflow for `Alert` — every alert is
  permanent and append-only this phase; a human/future system reading
  the `alerts` table has no way to mark one as handled without adding
  that workflow later.
- Sizing's failure-rate grouping (decision 3) is a judgment call not
  explicitly dictated by `health.py`'s original two-evaluator design —
  a future session revisiting Sizing's semantics should re-examine
  whether `REJECT` should instead be treated as a legitimate business
  outcome (similar to Decision's `NO_TRADE`) once Position Sizing's own
  spec is revisited.
