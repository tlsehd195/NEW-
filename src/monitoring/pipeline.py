"""End-to-end orchestration: takes the `(MonitoringEvent, ComponentHealth)`
pairs already produced by `collectors.py` for each component observed in
one monitoring run, and ties them together into one overall pipeline
`ComponentHealth` plus whatever `Alert`s the run's events/healths/drifts
are worth raising. Nothing here computes a metric or a health verdict
itself -- it only aggregates what `collectors.py`/`drift.py` already
computed, and maps that to alerts via the pure functions in `alerts.py`.

See docs/specifications/PHASE-14-monitoring.md section 11.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Sequence

from monitoring.alerts import raise_alert_from_drift, raise_alert_from_event, raise_alert_from_health
from monitoring.config import MonitoringConfig
from monitoring.health import evaluate_pipeline_health
from monitoring.models import Alert, ComponentHealth, DriftResult, MonitoringEvent


@dataclass(frozen=True)
class PipelineObservation:
    """The full output of one monitoring run: every component event/
    health this run produced, the aggregated end-to-end health, and
    every alert worth raising from any of it. Purely an in-process
    orchestration result -- not itself a persisted type; callers persist
    `events`/`component_healths`/`drift_results`/`alerts` through their
    own repositories exactly as `collectors.py`/`drift.py` produced
    them."""

    events: tuple[MonitoringEvent, ...] = ()
    component_healths: tuple[ComponentHealth, ...] = ()
    drift_results: tuple[DriftResult, ...] = ()
    pipeline_health: Optional[ComponentHealth] = None
    alerts: tuple[Alert, ...] = ()


def assemble_pipeline_observation(
    collected: Sequence[tuple[MonitoringEvent, ComponentHealth]], *, as_of_time: datetime,
    observed_at: datetime, config: MonitoringConfig, pipeline_health_id: str, alert_id_factory,
    drift_results: Sequence[DriftResult] = (),
) -> PipelineObservation:
    """`alert_id_factory` is a zero-argument callable returning the next
    unique `alert_id` -- kept a caller-supplied factory (rather than
    this function inventing ids) so id allocation stays under the same
    discipline every prior phase already uses (caller-assigned,
    globally unique, deterministic per run)."""
    events = tuple(event for event, _ in collected)
    component_healths = tuple(health for _, health in collected)

    pipeline_health = evaluate_pipeline_health(
        component_healths, as_of_time=as_of_time, health_id=pipeline_health_id, config=config,
    )

    alerts: list[Alert] = []
    for event in events:
        alert = raise_alert_from_event(event, alert_id=alert_id_factory(), raised_at=observed_at)
        if alert is not None:
            alerts.append(alert)
    for health in component_healths + (pipeline_health,):
        alert = raise_alert_from_health(health, alert_id=alert_id_factory(), raised_at=observed_at)
        if alert is not None:
            alerts.append(alert)
    for drift in drift_results:
        alert = raise_alert_from_drift(drift, alert_id=alert_id_factory(), raised_at=observed_at)
        if alert is not None:
            alerts.append(alert)

    return PipelineObservation(
        events=events, component_healths=component_healths, drift_results=tuple(drift_results),
        pipeline_health=pipeline_health, alerts=tuple(alerts),
    )
