"""Monitoring / Observability (Phase 14).

See docs/specifications/PHASE-14-monitoring.md and ADR-0020.

`PROJECT_MASTER_PLAN.md` section 3's module table: "Monitoring/Drift
Detection | 지속적 관찰, 이상 감지, 피드백 트리거 | 모델 재학습 자체
실행" -- this package only ever *observes* what Phase 1-13 already
computed and persisted; it never recomputes a prediction, decision,
sizing, risk assessment, or broker/AI Gateway call, and it never
executes anything (a retrain, an order, a model transition) on its own.

This package is fully additive on top of Phase 0-13 -- no Phase 0-13
source file is modified to build it. Every collector
(`monitoring.collectors`) takes already-materialized records the caller
already read from Phase 1-13's own repositories -- nothing here queries
`data_infra.repository.DataRepository`/calls
`broker.protocol.BrokerAdapter`/calls `ai_gateway.gateway.AIGateway`
itself (`tests/monitoring/test_monitoring_boundary.py`).

`ComponentHealthStatus.UNKNOWN` is never silently treated as `HEALTHY`,
and a metric that cannot be honestly computed (insufficient sample,
NaN/Inf, missing dependency) is `None`, never a fabricated `0.0`
(`tests/monitoring/test_monitoring_health.py`). Drift detection
(`monitoring.drift`) only ever produces `DriftStatus.DRIFT_DETECTED`/
`NO_DRIFT`/`UNKNOWN` -- an observation, never an action; no code path in
this package can assign `learning.enums.CandidateModelStatus.APPROVED`/
`DEPLOYED`, submit/cancel a `broker.models.ValidatedOrder`, or mutate a
Position Sizing/Risk result (`tests/monitoring/test_monitoring_boundary.py`).
"""

from __future__ import annotations
