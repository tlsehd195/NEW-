"""Monitoring data models.

See docs/specifications/PHASE-14-monitoring.md sections 7, 8, 9, 10.

**Structural boundary enforcement**: no type in this module has an
`order_id`, `broker_order`, `execution_price`, `quantity`, `side`,
`target_weight`, `risk_limit`, or `kill_switch`-shaped field, and
nothing here carries a `learning.enums.CandidateModelStatus` value or a
`trade_journal.enums.DecisionAction` -- Monitoring observes those
layers' outputs, it never re-expresses or overrides them
(`tests/monitoring/test_monitoring_boundary.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from monitoring.enums import AlertSeverity, ComponentHealthStatus, DriftStatus, MonitoringComponent

from trade_journal.enums import TradeProvenance


def _require_aware(name: str, value: Optional[datetime]) -> None:
    if value is None:
        return
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


@dataclass(frozen=True)
class MonitoringEvent:
    """One monitoring observation over an already-computed set of Phase
    1-13 records. `metrics` values are `Optional[float]` -- a metric
    this event could not honestly compute is `None`, never a fabricated
    `0.0` (instruction section 12). `source_record_ids` carries forward
    whichever upstream ids (decision_id/risk_id/request_id/candidate_id/
    etc.) this event summarizes -- Monitoring never mints a parallel
    identity system; SQL lineage joins go through these ids directly
    into Phase 1-13's own tables."""

    event_id: str  # "MONEVT-000001"
    component: MonitoringComponent
    event_type: str  # e.g. "data_quality", "broker_health", "prediction_distribution"
    severity: AlertSeverity
    observed_at: datetime  # when this monitoring computation ran
    as_of_time: datetime  # the point-in-time cutoff the underlying records were filtered to
    metrics: dict = field(default_factory=dict)
    threshold_version: str = "unknown"
    component_version: Optional[str] = None
    data_version: tuple[str, ...] = ()
    message: str = ""
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION
    correlation_id: Optional[str] = None
    source_record_ids: tuple[str, ...] = ()
    configuration_version: str = "unknown"
    experiment_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("MonitoringEvent.event_id must not be empty")
        if not self.event_type:
            raise ValueError("MonitoringEvent.event_type must not be empty")
        _require_aware("MonitoringEvent.observed_at", self.observed_at)
        _require_aware("MonitoringEvent.as_of_time", self.as_of_time)


@dataclass(frozen=True)
class ComponentHealth:
    """One health observation for one component at one point in time --
    append-only, mirrors `ai_gateway.models.ProviderQuotaState`/
    `broker.models.OrderStatusObservation`'s "one observation per point
    in time" pattern. A component's *current* health is always its most
    recent observation, never a mutated single record."""

    health_id: str  # "HEALTH-000001"
    component: MonitoringComponent
    status: ComponentHealthStatus
    as_of_time: datetime
    reason: str  # factual: which check(s) determined this status
    checks: dict = field(default_factory=dict)
    configuration_version: str = "unknown"
    event_id: Optional[str] = None  # the MonitoringEvent this health verdict was derived from, if any
    recorded_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.health_id:
            raise ValueError("ComponentHealth.health_id must not be empty")
        if not self.reason:
            raise ValueError("ComponentHealth.reason must not be empty")
        _require_aware("ComponentHealth.as_of_time", self.as_of_time)
        _require_aware("ComponentHealth.recorded_at", self.recorded_at)


@dataclass(frozen=True)
class DriftResult:
    """PROJECT_MASTER_PLAN.md section 11.6: an observation, never an
    action -- nothing constructs a `DriftResult` and then replaces a
    model, changes a risk limit, or halts trading. `status ==
    DRIFT_DETECTED` is a fact about a statistic crossing a configured
    threshold, not a verdict about what caused it or what to do next."""

    drift_id: str  # "DRIFT-000001"
    component: MonitoringComponent
    metric_name: str  # e.g. "prediction_expected_return_mean_shift"
    status: DriftStatus
    statistic: Optional[float]
    threshold: Optional[float]
    as_of_time: datetime
    baseline_summary: dict = field(default_factory=dict)
    current_summary: dict = field(default_factory=dict)
    sample_count_baseline: Optional[int] = None
    sample_count_current: Optional[int] = None
    configuration_version: str = "unknown"
    reason: str = ""
    recorded_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.drift_id:
            raise ValueError("DriftResult.drift_id must not be empty")
        _require_aware("DriftResult.as_of_time", self.as_of_time)
        _require_aware("DriftResult.recorded_at", self.recorded_at)


@dataclass(frozen=True)
class Alert:
    """A raised alert -- append-only (instruction section 11:
    "Alert acknowledgement/resolution이 필요하다면 append-only event
    형태로 설계하라"). This phase does not implement acknowledgement/
    resolution workflow at all (ADR-0020's Known Limitations) -- an
    `Alert` is purely a durable record that a condition was observed,
    never mutated after creation."""

    alert_id: str  # "ALERT-000001"
    severity: AlertSeverity
    component: MonitoringComponent
    message: str
    raised_at: datetime
    event_id: Optional[str] = None
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION
    experiment_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.alert_id:
            raise ValueError("Alert.alert_id must not be empty")
        if not self.message:
            raise ValueError("Alert.message must not be empty")
        _require_aware("Alert.raised_at", self.raised_at)
