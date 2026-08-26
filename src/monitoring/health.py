"""Deterministic ComponentHealth evaluation. Every function here reads
only already-computed metrics (never a live call) and a `MonitoringConfig`
threshold set -- `ComponentHealthStatus.UNKNOWN` is the result whenever
a required input is missing or non-finite, never coerced to `HEALTHY`
(instruction section 12).

See docs/specifications/PHASE-14-monitoring.md section 6.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from monitoring.config import MonitoringConfig
from monitoring.enums import ComponentHealthStatus, MonitoringComponent
from monitoring.models import ComponentHealth


def _finite(value: Optional[float]) -> bool:
    if value is None:
        return False
    return value == value and value not in (float("inf"), float("-inf"))


def evaluate_health_from_failure_rate(
    component: MonitoringComponent, *, failure_rate: Optional[float], sample_count: Optional[float],
    config: MonitoringConfig, as_of_time: datetime, health_id: str, event_id: Optional[str] = None,
) -> ComponentHealth:
    """Used for components whose health is naturally expressed as an
    error/rejection rate (Broker, AI Gateway, Risk)."""
    checks = {
        "sample_count_present": sample_count is not None,
        "sample_count_sufficient": sample_count is not None and sample_count >= config.min_sample_count,
        "failure_rate_present": _finite(failure_rate),
    }
    if not all(checks.values()):
        return ComponentHealth(
            health_id=health_id, component=component, status=ComponentHealthStatus.UNKNOWN,
            as_of_time=as_of_time, reason="insufficient_data", checks=checks,
            configuration_version=config.configuration_version(), event_id=event_id,
        )

    if failure_rate >= config.unavailable_failure_rate_threshold:
        status = ComponentHealthStatus.UNAVAILABLE
    elif failure_rate >= config.degraded_failure_rate_threshold:
        status = ComponentHealthStatus.DEGRADED
    else:
        status = ComponentHealthStatus.HEALTHY

    return ComponentHealth(
        health_id=health_id, component=component, status=status, as_of_time=as_of_time,
        reason=f"failure_rate={failure_rate:.4f}", checks=checks,
        configuration_version=config.configuration_version(), event_id=event_id,
    )


def evaluate_existence_health(
    component: MonitoringComponent, *, count: Optional[float], config: MonitoringConfig,
    as_of_time: datetime, health_id: str, event_id: Optional[str] = None,
) -> ComponentHealth:
    """Used for components whose health is "is this layer still
    producing output at all" (Prediction, Decision, Regime, Learning) --
    NO_TRADE/HOLD are legitimate outputs (PROJECT_MASTER_PLAN.md section
    8.2: "NO_TRADE는 실패가 아니다"), so this only checks *production*,
    never judges the *content* of what was produced."""
    checks = {"count_present": count is not None}
    if count is None:
        return ComponentHealth(
            health_id=health_id, component=component, status=ComponentHealthStatus.UNKNOWN,
            as_of_time=as_of_time, reason="no_count_available", checks=checks,
            configuration_version=config.configuration_version(), event_id=event_id,
        )

    if count <= 0:
        status = ComponentHealthStatus.UNAVAILABLE
    elif count < config.degraded_min_expected_count:
        status = ComponentHealthStatus.DEGRADED
    else:
        status = ComponentHealthStatus.HEALTHY

    return ComponentHealth(
        health_id=health_id, component=component, status=status, as_of_time=as_of_time,
        reason=f"count={count:.0f}", checks=checks,
        configuration_version=config.configuration_version(), event_id=event_id,
    )


def evaluate_data_health(
    *, invalid_rate: Optional[float], stale_seconds: Optional[float], observation_count: Optional[float],
    config: MonitoringConfig, as_of_time: datetime, health_id: str, event_id: Optional[str] = None,
) -> ComponentHealth:
    checks = {
        "observation_count_present": observation_count is not None,
        "observation_count_sufficient": observation_count is not None and observation_count >= config.min_sample_count,
        "invalid_rate_present": _finite(invalid_rate),
        "staleness_present": _finite(stale_seconds),
    }
    if not (checks["observation_count_present"] and checks["observation_count_sufficient"] and checks["invalid_rate_present"]):
        return ComponentHealth(
            health_id=health_id, component=MonitoringComponent.DATA, status=ComponentHealthStatus.UNKNOWN,
            as_of_time=as_of_time, reason="insufficient_data", checks=checks,
            configuration_version=config.configuration_version(), event_id=event_id,
        )

    if invalid_rate >= config.unavailable_invalid_rate_threshold:
        status = ComponentHealthStatus.UNAVAILABLE
        reason = f"invalid_rate={invalid_rate:.4f}"
    elif checks["staleness_present"] and stale_seconds > config.stale_data_max_age_seconds:
        status = ComponentHealthStatus.DEGRADED
        reason = f"stale_seconds={stale_seconds:.0f}"
    elif invalid_rate >= config.degraded_invalid_rate_threshold:
        status = ComponentHealthStatus.DEGRADED
        reason = f"invalid_rate={invalid_rate:.4f}"
    else:
        status = ComponentHealthStatus.HEALTHY
        reason = "within_thresholds"

    return ComponentHealth(
        health_id=health_id, component=MonitoringComponent.DATA, status=status, as_of_time=as_of_time,
        reason=reason, checks=checks, configuration_version=config.configuration_version(), event_id=event_id,
    )


def evaluate_account_health(
    *, sample_count: Optional[float], equity: Optional[float], drawdown: Optional[float],
    max_drawdown: Optional[float], config: MonitoringConfig, as_of_time: datetime,
    health_id: str, event_id: Optional[str] = None,
) -> ComponentHealth:
    """Phase 17 Production Safety Review addition. `max_drawdown` is
    caller-supplied and `None` by default ("not enforced") -- the same
    convention `broker.live.config.LiveTradingConfig`'s own threshold
    fields already use -- so this function never invents a drawdown
    number of its own; a caller who wants alerting sets one explicitly
    (e.g. from the same `risk.config.RiskConfig.max_drawdown` already
    enforced pre-trade, or a value chosen specifically for alerting)."""
    checks = {
        "sample_count_present": sample_count is not None,
        "sample_count_sufficient": sample_count is not None and sample_count >= config.min_sample_count,
        "equity_present": _finite(equity),
    }
    if not all(checks.values()):
        return ComponentHealth(
            health_id=health_id, component=MonitoringComponent.ACCOUNT, status=ComponentHealthStatus.UNKNOWN,
            as_of_time=as_of_time, reason="insufficient_data", checks=checks,
            configuration_version=config.configuration_version(), event_id=event_id,
        )

    if max_drawdown is not None and _finite(drawdown) and drawdown >= max_drawdown:
        status = ComponentHealthStatus.UNAVAILABLE
        reason = f"drawdown={drawdown:.4f}_exceeds_max_drawdown={max_drawdown:.4f}"
    else:
        status = ComponentHealthStatus.HEALTHY
        reason = "within_max_drawdown" if max_drawdown is not None else "max_drawdown_not_configured"

    return ComponentHealth(
        health_id=health_id, component=MonitoringComponent.ACCOUNT, status=status, as_of_time=as_of_time,
        reason=reason, checks=checks, configuration_version=config.configuration_version(), event_id=event_id,
    )


def evaluate_pipeline_health(
    component_healths: Sequence[ComponentHealth], *, as_of_time: datetime, health_id: str,
    config: MonitoringConfig,
) -> ComponentHealth:
    """End-to-end health: the worst status among every observed
    component, deterministic, fail-closed. An empty input is `UNKNOWN`
    (no components observed -- never assumed healthy)."""
    checks = {f"{h.component.value}_status": h.status.value for h in component_healths}
    if not component_healths:
        return ComponentHealth(
            health_id=health_id, component=MonitoringComponent.PIPELINE, status=ComponentHealthStatus.UNKNOWN,
            as_of_time=as_of_time, reason="no_components_observed", checks=checks,
            configuration_version=config.configuration_version(),
        )

    statuses = {h.status for h in component_healths}
    if ComponentHealthStatus.UNAVAILABLE in statuses:
        status = ComponentHealthStatus.UNAVAILABLE
    elif ComponentHealthStatus.UNKNOWN in statuses:
        status = ComponentHealthStatus.UNKNOWN
    elif ComponentHealthStatus.DEGRADED in statuses:
        status = ComponentHealthStatus.DEGRADED
    else:
        status = ComponentHealthStatus.HEALTHY

    worst_components = sorted(h.component.value for h in component_healths if h.status == status)
    return ComponentHealth(
        health_id=health_id, component=MonitoringComponent.PIPELINE, status=status, as_of_time=as_of_time,
        reason=f"worst_status={status.value}_from={','.join(worst_components)}", checks=checks,
        configuration_version=config.configuration_version(),
    )
