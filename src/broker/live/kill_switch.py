"""Kill switch -- PROJECT_MASTER_PLAN.md section 12.1: "다음 상황에서는
신규 주문을 자동으로 중단할 수 있어야 한다," section 1.5: "Kill switch는
AI가 해제할 수 없도록 설계하는 것을 우선 고려한다. 해제는 사람의 명시적
조치를 요구하는 방향을 기본값으로 한다."

`engage_kill_switch` is deterministic and callable from
`LiveTradingSession` itself (an automatic reaction to a detected
condition is exactly what section 12.1 asks for). `release_kill_switch`
requires a `broker.live.approval.LiveActivationApproval`-shaped
argument and is never called by any deterministic pipeline code path in
this repository -- only by its own test
(`tests/broker/live/test_live_kill_switch.py`), verified by an AST scan
(`tests/broker/live/test_live_boundary.py`).

See docs/specifications/PHASE-16-live-trading.md section 7.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol

from broker.live.approval import LiveActivationApproval
from broker.live.config import LiveTradingConfig

from monitoring.enums import ComponentHealthStatus


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


@dataclass(frozen=True)
class KillSwitchEvent:
    """One engage/release observation -- append-only, mirrors
    `monitoring.models.ComponentHealth`/`ai_gateway.models.
    ProviderQuotaState`'s "one observation per point in time" pattern.
    The kill switch's *current* state is always the latest event, never
    a separately mutated flag."""

    event_id: str  # "KSEVENT-000001"
    engaged: bool
    reason: str
    triggered_by: str  # "SYSTEM" for an automatic engage, an operator identity for a release
    occurred_at: datetime
    configuration_version: str

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("KillSwitchEvent.event_id must not be empty")
        if not self.reason:
            raise ValueError("KillSwitchEvent.reason must not be empty")
        if not self.triggered_by:
            raise ValueError("KillSwitchEvent.triggered_by must not be empty")
        _require_aware("KillSwitchEvent.occurred_at", self.occurred_at)


@dataclass(frozen=True)
class KillSwitchTriggerContext:
    """Every input `evaluate_kill_switch_triggers` needs, all
    caller-supplied (already-computed) -- this module performs no I/O,
    no broker call, no Monitoring query itself."""

    as_of_time: datetime
    broker_health: Optional[ComponentHealthStatus]
    risk_health: Optional[ComponentHealthStatus]
    monitoring_pipeline_health: Optional[ComponentHealthStatus]
    account_state_known: bool
    position_state_known: bool
    daily_loss: Optional[float]  # realized + unrealized loss so far today; None if not computed
    orders_in_last_hour: Optional[int]
    config: LiveTradingConfig
    # Phase 17 Production Safety Review addition: `monitoring.collectors.
    # collect_data_quality` (Phase 14) already evaluates market-data
    # pipeline health, but nothing fed it into this trigger evaluation --
    # a real data outage (stale/invalid bars) could go undetected by the
    # kill switch even though broker/risk/monitoring-pipeline health all
    # looked fine. Optional with a `None` default so every existing
    # caller/test keeps constructing this dataclass unchanged; `None`
    # means "not supplied," not "healthy," and is therefore never
    # treated as safe (see `_CRITICAL_STATUSES` check below, which
    # triggers only on an explicit UNAVAILABLE/UNKNOWN value, mirroring
    # how the three pre-existing health fields already behave when
    # `None`).
    data_health: Optional[ComponentHealthStatus] = None


_CRITICAL_STATUSES = frozenset({ComponentHealthStatus.UNAVAILABLE, ComponentHealthStatus.UNKNOWN})


def evaluate_kill_switch_triggers(context: KillSwitchTriggerContext) -> Optional[str]:
    """Returns the first triggered reason, or `None`. Never returns a
    reason for a limit that is not explicitly configured (`None` in
    `LiveTradingConfig` means "not enforced," instruction section 22).
    A limit that IS configured but whose current measurement is `None`
    (`daily_loss`/`orders_in_last_hour` could not be computed this
    cycle) is a different case and does NOT fall through silently --
    it triggers its own `*_unmeasurable` reason (Session 37, ADR-0115,
    external review N-17), the same fail-closed treatment `account_
    state_known`/`position_state_known` already get below."""
    if context.broker_health in _CRITICAL_STATUSES:
        return f"broker_health_{context.broker_health.value.lower()}"
    if context.risk_health in _CRITICAL_STATUSES:
        return f"risk_health_{context.risk_health.value.lower()}"
    if context.monitoring_pipeline_health in _CRITICAL_STATUSES:
        return f"monitoring_pipeline_health_{context.monitoring_pipeline_health.value.lower()}"
    if context.data_health in _CRITICAL_STATUSES:
        return f"data_health_{context.data_health.value.lower()}"
    if not context.account_state_known:
        return "account_state_unknown"
    if not context.position_state_known:
        return "position_state_unknown"
    # Session 37 (ADR-0115, external review N-17): a configured limit
    # whose measurement is `None` (couldn't be computed this cycle --
    # e.g. a data gap) previously fell straight through both of these
    # checks with no trigger at all -- fail-*open*, unlike every other
    # condition in this function (`account_state_known`/
    # `position_state_known`/the health checks above all trigger on
    # `False`/`UNKNOWN`, never silently pass). A limit the operator
    # explicitly configured is exactly the one this system committed to
    # actively enforcing; being unable to measure it right now is itself
    # a reason to halt, not a reason to skip the check -- "not
    # configured" (measurement is irrelevant) and "configured but
    # unmeasurable" (the limit might already be breached and nobody can
    # tell) are different states and must not collapse into the same
    # silent pass.
    if context.config.max_daily_loss is not None:
        if context.daily_loss is None:
            return "daily_loss_unmeasurable"
        if context.daily_loss >= context.config.max_daily_loss:
            return "daily_loss_limit_breached"
    if context.config.max_order_frequency_per_hour is not None:
        if context.orders_in_last_hour is None:
            return "order_frequency_unmeasurable"
        if context.orders_in_last_hour > context.config.max_order_frequency_per_hour:
            return "abnormal_order_frequency"
    return None


def engage_kill_switch(
    *, event_id: str, reason: str, occurred_at: datetime, configuration_version: str,
) -> KillSwitchEvent:
    return KillSwitchEvent(
        event_id=event_id, engaged=True, reason=reason, triggered_by="SYSTEM",
        occurred_at=occurred_at, configuration_version=configuration_version,
    )


def release_kill_switch(
    *, event_id: str, approval: LiveActivationApproval, occurred_at: datetime, configuration_version: str,
) -> KillSwitchEvent:
    """Requires a valid `LiveActivationApproval` -- there is no
    parameter-free or config-only way to produce a `KillSwitchEvent`
    with `engaged=False`."""
    if not approval.is_valid():
        raise ValueError("release_kill_switch requires a valid LiveActivationApproval")
    return KillSwitchEvent(
        event_id=event_id, engaged=False, reason="released_by_operator", triggered_by=approval.approved_by,
        occurred_at=occurred_at, configuration_version=configuration_version,
    )


class KillSwitchRepository(Protocol):
    def record(self, event: KillSwitchEvent) -> KillSwitchEvent:
        """Append-only -- idempotent only on `event_id` itself."""
        ...

    def get_latest(self) -> Optional[KillSwitchEvent]: ...
    def list_all(self) -> list[KillSwitchEvent]: ...


class InMemoryKillSwitchRepository:
    def __init__(self) -> None:
        self._events: list[KillSwitchEvent] = []
        self._by_id: dict[str, KillSwitchEvent] = {}

    def record(self, event: KillSwitchEvent) -> KillSwitchEvent:
        existing = self._by_id.get(event.event_id)
        if existing is not None:
            return existing
        self._events.append(event)
        self._by_id[event.event_id] = event
        return event

    def get_latest(self) -> Optional[KillSwitchEvent]:
        if not self._events:
            return None
        return max(self._events, key=lambda e: (e.occurred_at, e.event_id))

    def list_all(self) -> list[KillSwitchEvent]:
        return sorted(self._events, key=lambda e: (e.occurred_at, e.event_id))


def is_engaged(repository: KillSwitchRepository) -> bool:
    """`True` only when the *latest* recorded event has `engaged=True` --
    an empty history is `False` (no trigger has ever fired), matching
    the kill switch's own natural default-off state."""
    latest = repository.get_latest()
    return latest is not None and latest.engaged
