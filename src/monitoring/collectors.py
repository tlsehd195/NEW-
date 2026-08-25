"""Read-only collectors: the only place in `monitoring.*` that combines
point-in-time filtering + `metrics.py` + `health.py` into a
`MonitoringEvent`/`ComponentHealth` pair. `metrics.py`'s functions are
deliberately pure over whatever sequence they are given -- every
collector here is responsible for restricting its input to
`<field> <= as_of_time` *before* calling them, so no metric or health
verdict can ever be influenced by a record that would not have existed
yet as of `as_of_time` (instruction section 13: "과거 monitoring 결과를
계산할 때 미래 observation을 참조하면 안 된다").

Each collector takes already-materialized Phase 1-13 record sequences
(fetched by the caller from the appropriate repository) -- nothing here
performs data access, a live API call, or a database query itself.

See docs/specifications/PHASE-14-monitoring.md section 8.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from ai_gateway.models import AIResponse

from broker.models import BrokerRequestRecord, BrokerResponseRecord

from data_infra.models import PriceBar

from decision.models import DecisionOutput

from evolution.models import ModelLineageRecord, ModelStatusTransition

from learning.models import CandidateModelArtifact, EvaluationResult, TrainingDataset

from monitoring.alerts import severity_for_health_status
from monitoring.config import MonitoringConfig
from monitoring.enums import MonitoringComponent
from monitoring.health import (
    evaluate_data_health,
    evaluate_existence_health,
    evaluate_health_from_failure_rate,
)
from monitoring.metrics import (
    compute_ai_gateway_metrics,
    compute_broker_metrics,
    compute_data_quality_metrics,
    compute_decision_metrics,
    compute_learning_metrics,
    compute_model_evolution_metrics,
    compute_prediction_metrics,
    compute_risk_metrics,
    compute_sizing_metrics,
)
from monitoring.models import ComponentHealth, MonitoringEvent

from predict.models import PredictionOutput

from risk.models import PositionSizingResult, RiskCheckedPosition

from trade_journal.enums import TradeProvenance


def _finite(value: Optional[float]) -> bool:
    if value is None:
        return False
    return value == value and value not in (float("inf"), float("-inf"))


def _filter_by_time(records: Sequence, as_of_time: datetime, *, key) -> list:
    return [r for r in records if key(r) <= as_of_time]


def _staleness_seconds(latest_available_time: Optional[datetime], as_of_time: datetime) -> Optional[float]:
    if latest_available_time is None:
        return None
    return (as_of_time - latest_available_time).total_seconds()


def _make_event(
    *, event_id: str, component: MonitoringComponent, event_type: str, health: ComponentHealth,
    observed_at: datetime, as_of_time: datetime, metrics: dict, config: MonitoringConfig,
    source_record_ids: tuple = (), data_version: tuple = (),
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
) -> MonitoringEvent:
    return MonitoringEvent(
        event_id=event_id, component=component, event_type=event_type,
        severity=severity_for_health_status(health.status), observed_at=observed_at, as_of_time=as_of_time,
        metrics=metrics, threshold_version=config.configuration_version(),
        configuration_version=config.configuration_version(), data_version=data_version,
        message=health.reason, provenance=provenance, source_record_ids=source_record_ids,
    )


def collect_data_quality(
    bars: Sequence[PriceBar], *, as_of_time: datetime, observed_at: datetime, config: MonitoringConfig,
    event_id: str, health_id: str,
) -> tuple[MonitoringEvent, ComponentHealth]:
    filtered = _filter_by_time(bars, as_of_time, key=lambda b: b.available_time)
    metrics = compute_data_quality_metrics(filtered)
    health = evaluate_data_health(
        invalid_rate=metrics["invalid_rate"],
        stale_seconds=_staleness_seconds(metrics["latest_available_time"], as_of_time),
        observation_count=metrics["observation_count"], config=config, as_of_time=as_of_time,
        health_id=health_id, event_id=event_id,
    )
    event = _make_event(
        event_id=event_id, component=MonitoringComponent.DATA, event_type="data_quality_observation",
        health=health, observed_at=observed_at, as_of_time=as_of_time, metrics=metrics, config=config,
        source_record_ids=tuple(f"{b.security_id}@{b.timestamp.isoformat()}" for b in filtered),
    )
    return event, health


def collect_prediction(
    predictions: Sequence[PredictionOutput], *, as_of_time: datetime, observed_at: datetime,
    config: MonitoringConfig, event_id: str, health_id: str,
) -> tuple[MonitoringEvent, ComponentHealth]:
    filtered = _filter_by_time(predictions, as_of_time, key=lambda p: p.as_of_time)
    metrics = compute_prediction_metrics(filtered)
    health = evaluate_existence_health(
        MonitoringComponent.PREDICTION, count=metrics["count"], config=config, as_of_time=as_of_time,
        health_id=health_id, event_id=event_id,
    )
    event = _make_event(
        event_id=event_id, component=MonitoringComponent.PREDICTION, event_type="prediction_observation",
        health=health, observed_at=observed_at, as_of_time=as_of_time, metrics=metrics, config=config,
        source_record_ids=tuple(p.prediction_id for p in filtered),
    )
    return event, health


def collect_decision(
    decisions: Sequence[DecisionOutput], *, as_of_time: datetime, observed_at: datetime,
    config: MonitoringConfig, event_id: str, health_id: str,
) -> tuple[MonitoringEvent, ComponentHealth]:
    filtered = _filter_by_time(decisions, as_of_time, key=lambda d: d.as_of_time)
    metrics = compute_decision_metrics(filtered)
    health = evaluate_existence_health(
        MonitoringComponent.DECISION, count=metrics["count"], config=config, as_of_time=as_of_time,
        health_id=health_id, event_id=event_id,
    )
    event = _make_event(
        event_id=event_id, component=MonitoringComponent.DECISION, event_type="decision_observation",
        health=health, observed_at=observed_at, as_of_time=as_of_time, metrics=metrics, config=config,
        source_record_ids=tuple(d.decision_id for d in filtered),
    )
    return event, health


def collect_sizing(
    sizing_results: Sequence[PositionSizingResult], *, as_of_time: datetime, observed_at: datetime,
    config: MonitoringConfig, event_id: str, health_id: str,
) -> tuple[MonitoringEvent, ComponentHealth]:
    """Sizing's `reject_rate`/`unknown_rate` are a meaningful failure
    signal (unlike Decision, where `NO_TRADE`/`HOLD` are legitimate
    outputs), so this is evaluated by failure rate -- like Risk -- not
    mere existence, even though it is not in `health.py`'s originally
    documented failure-rate component list."""
    filtered = _filter_by_time(sizing_results, as_of_time, key=lambda s: s.as_of_time)
    metrics = compute_sizing_metrics(filtered)
    reject_rate, unknown_rate = metrics["reject_rate"], metrics["unknown_rate"]
    failure_rate = (reject_rate + unknown_rate) if _finite(reject_rate) and _finite(unknown_rate) else None
    health = evaluate_health_from_failure_rate(
        MonitoringComponent.SIZING, failure_rate=failure_rate, sample_count=metrics["count"], config=config,
        as_of_time=as_of_time, health_id=health_id, event_id=event_id,
    )
    event = _make_event(
        event_id=event_id, component=MonitoringComponent.SIZING, event_type="sizing_observation",
        health=health, observed_at=observed_at, as_of_time=as_of_time,
        metrics={**metrics, "failure_rate": failure_rate}, config=config,
        source_record_ids=tuple(s.sizing_id for s in filtered),
    )
    return event, health


def collect_risk(
    risk_results: Sequence[RiskCheckedPosition], *, as_of_time: datetime, observed_at: datetime,
    config: MonitoringConfig, event_id: str, health_id: str,
) -> tuple[MonitoringEvent, ComponentHealth]:
    filtered = _filter_by_time(risk_results, as_of_time, key=lambda r: r.as_of_time)
    metrics = compute_risk_metrics(filtered)
    health = evaluate_health_from_failure_rate(
        MonitoringComponent.RISK, failure_rate=metrics["failure_rate"], sample_count=metrics["count"],
        config=config, as_of_time=as_of_time, health_id=health_id, event_id=event_id,
    )
    event = _make_event(
        event_id=event_id, component=MonitoringComponent.RISK, event_type="risk_observation",
        health=health, observed_at=observed_at, as_of_time=as_of_time, metrics=metrics, config=config,
        source_record_ids=tuple(r.risk_id for r in filtered),
    )
    return event, health


def collect_broker(
    responses: Sequence[BrokerResponseRecord], requests: Sequence[BrokerRequestRecord] = (), *,
    as_of_time: datetime, observed_at: datetime, config: MonitoringConfig, event_id: str, health_id: str,
) -> tuple[MonitoringEvent, ComponentHealth]:
    filtered_responses = _filter_by_time(responses, as_of_time, key=lambda r: r.responded_at)
    filtered_requests = _filter_by_time(requests, as_of_time, key=lambda r: r.requested_at)
    metrics = compute_broker_metrics(filtered_responses, filtered_requests)
    health = evaluate_health_from_failure_rate(
        MonitoringComponent.BROKER, failure_rate=metrics["failure_rate"], sample_count=metrics["count"],
        config=config, as_of_time=as_of_time, health_id=health_id, event_id=event_id,
    )
    event = _make_event(
        event_id=event_id, component=MonitoringComponent.BROKER, event_type="broker_observation",
        health=health, observed_at=observed_at, as_of_time=as_of_time, metrics=metrics, config=config,
        source_record_ids=tuple(r.response_id for r in filtered_responses),
    )
    return event, health


def collect_ai_gateway(
    responses: Sequence[AIResponse], *, as_of_time: datetime, observed_at: datetime, config: MonitoringConfig,
    event_id: str, health_id: str,
) -> tuple[MonitoringEvent, ComponentHealth]:
    filtered = _filter_by_time(responses, as_of_time, key=lambda r: r.responded_at)
    metrics = compute_ai_gateway_metrics(filtered)
    health = evaluate_health_from_failure_rate(
        MonitoringComponent.AI_GATEWAY, failure_rate=metrics["failure_rate"], sample_count=metrics["count"],
        config=config, as_of_time=as_of_time, health_id=health_id, event_id=event_id,
    )
    event = _make_event(
        event_id=event_id, component=MonitoringComponent.AI_GATEWAY, event_type="ai_gateway_observation",
        health=health, observed_at=observed_at, as_of_time=as_of_time, metrics=metrics, config=config,
        source_record_ids=tuple(r.response_id for r in filtered),
    )
    return event, health


def collect_learning(
    datasets: Sequence[TrainingDataset], candidates: Sequence[CandidateModelArtifact],
    evaluations: Sequence[EvaluationResult], *, as_of_time: datetime, observed_at: datetime,
    config: MonitoringConfig, event_id: str, health_id: str,
) -> tuple[MonitoringEvent, ComponentHealth]:
    filtered_datasets = _filter_by_time(datasets, as_of_time, key=lambda d: d.created_at)
    filtered_candidates = _filter_by_time(candidates, as_of_time, key=lambda c: c.trained_at)
    filtered_evaluations = _filter_by_time(evaluations, as_of_time, key=lambda e: e.evaluated_at)
    metrics = compute_learning_metrics(filtered_datasets, filtered_candidates, filtered_evaluations)
    health = evaluate_existence_health(
        MonitoringComponent.LEARNING, count=metrics["dataset_count"], config=config, as_of_time=as_of_time,
        health_id=health_id, event_id=event_id,
    )
    event = _make_event(
        event_id=event_id, component=MonitoringComponent.LEARNING, event_type="learning_observation",
        health=health, observed_at=observed_at, as_of_time=as_of_time, metrics=metrics, config=config,
        source_record_ids=(
            tuple(d.dataset_id for d in filtered_datasets)
            + tuple(c.candidate_id for c in filtered_candidates)
            + tuple(e.evaluation_id for e in filtered_evaluations)
        ),
    )
    return event, health


def collect_model_evolution(
    transitions: Sequence[ModelStatusTransition], lineages: Sequence[ModelLineageRecord], *,
    as_of_time: datetime, observed_at: datetime, config: MonitoringConfig, event_id: str, health_id: str,
) -> tuple[MonitoringEvent, ComponentHealth]:
    """`ModelLineageRecord.recorded_at` is set by the repository at
    persistence time and may be `None` on a record constructed directly
    (e.g. before it has ever been persisted); such a record carries no
    forward-looking information of its own beyond the candidate_id the
    caller already selected, so it is kept rather than dropped -- only
    a record with a *known* `recorded_at` in the future is excluded."""
    filtered_transitions = _filter_by_time(transitions, as_of_time, key=lambda t: t.evaluated_at)
    filtered_lineages = [
        lin for lin in lineages if lin.recorded_at is None or lin.recorded_at <= as_of_time
    ]
    metrics = compute_model_evolution_metrics(filtered_transitions, filtered_lineages)
    health = evaluate_existence_health(
        MonitoringComponent.MODEL_EVOLUTION, count=metrics["transition_count"], config=config,
        as_of_time=as_of_time, health_id=health_id, event_id=event_id,
    )
    event = _make_event(
        event_id=event_id, component=MonitoringComponent.MODEL_EVOLUTION, event_type="model_evolution_observation",
        health=health, observed_at=observed_at, as_of_time=as_of_time, metrics=metrics, config=config,
        source_record_ids=(
            tuple(t.transition_id for t in filtered_transitions)
            + tuple(lin.candidate_id for lin in filtered_lineages)
        ),
    )
    return event, health
