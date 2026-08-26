"""LiveTradingSession: orchestrates a `broker.protocol.BrokerAdapter`
call the same way `broker.paper.session.PaperTradingSession` does for
Paper (Phase 15) -- gate check, then call, then persist -- but with two
Live-specific differences instruction section 9/14/15/27 both demand:

1. A submission exception (`BrokerError`) is never retried. The order's
   internal status becomes `UNKNOWN` and the session transitions to
   `OperationalState.RECONCILIATION_REQUIRED`, blocking *every* further
   submission until `reconcile_order` resolves it -- "API 응답을 받지
   못했다"는 "주문이 실행되지 않았다"는 뜻이 아니다.
2. `engage_kill_switch` is callable by this session itself (a
   deterministic, automatic reaction); `release_kill_switch` is not --
   see `broker.live.kill_switch`'s own module docstring.

See docs/specifications/PHASE-16-live-trading.md section 9, 14.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from broker.enums import BrokerOrderStatus
from broker.errors import BrokerError
from broker.live.config import LiveTradingConfig
from broker.live.enums import OperationalState, ReconciliationStatus
from broker.live.kill_switch import (
    InMemoryKillSwitchRepository,
    KillSwitchEvent,
    KillSwitchRepository,
    engage_kill_switch as _engage_kill_switch,
    is_engaged,
    release_kill_switch as _release_kill_switch,
)
from broker.live.approval import LiveActivationApproval
from broker.live.reconciliation import (
    InMemoryReconciliationRepository,
    ReconciliationRepository,
    ReconciliationResult,
    compare_order_status,
)
from broker.live.safety_gate import SafetyGateContext, SafetyGateResult, evaluate_safety_gate
from broker.models import BrokerOrderResponse, ValidatedOrder
from broker.protocol import BrokerAdapter


class _IdAllocator:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._next_id = 1

    def allocate(self) -> str:
        value = f"{self._prefix}-{self._next_id:06d}"
        self._next_id += 1
        return value


@dataclass(frozen=True)
class LiveSubmissionOutcome:
    submitted: bool
    status: str  # "BLOCKED" | "UNKNOWN" | a BrokerOrderStatus value
    gate_result: Optional[SafetyGateResult]
    response: Optional[BrokerOrderResponse]
    error: Optional[str] = None


@dataclass(frozen=True)
class StartupCheckResult:
    ready: bool
    blocking_reasons: tuple[str, ...]
    evaluated_at: datetime


@dataclass(frozen=True)
class ShutdownCheckResult:
    open_client_order_ids: tuple[str, ...]
    shutdown_at: datetime
    operational_state: OperationalState


def run_startup_checks(
    gate_context: SafetyGateContext, *, reconciliation_results: tuple[ReconciliationResult, ...] = (),
) -> StartupCheckResult:
    """Pure -- performs no I/O itself (instruction section 28: startup
    must verify configuration/credential/broker/account/position/risk/
    monitoring/kill-switch/model/reconciliation state before allowing
    any new order; every one of those is caller-supplied here, already
    computed, exactly as `evaluate_safety_gate` already requires)."""
    gate_result = evaluate_safety_gate(gate_context)
    reasons = list(gate_result.failed_conditions)
    for result in reconciliation_results:
        if result.status != ReconciliationStatus.MATCHED:
            reasons.append(f"reconciliation_{result.target}_{result.status.value.lower()}")
    return StartupCheckResult(ready=not reasons, blocking_reasons=tuple(reasons), evaluated_at=gate_context.as_of_time)


def run_shutdown_checks(*, open_client_order_ids: tuple[str, ...], shutdown_at: datetime) -> ShutdownCheckResult:
    """Never force-cancels an open order -- cancellation-on-shutdown is
    a distinct financial policy decision this phase does not make
    unilaterally (instruction section 29)."""
    return ShutdownCheckResult(
        open_client_order_ids=open_client_order_ids, shutdown_at=shutdown_at,
        operational_state=OperationalState.SHUTTING_DOWN,
    )


class LiveTradingSession:
    def __init__(
        self,
        config: LiveTradingConfig,
        adapter: BrokerAdapter,
        *,
        kill_switch_repository: Optional[KillSwitchRepository] = None,
        reconciliation_repository: Optional[ReconciliationRepository] = None,
    ) -> None:
        self.config = config
        self.adapter = adapter
        self._kill_switch_repository = kill_switch_repository or InMemoryKillSwitchRepository()
        self._reconciliation_repository = reconciliation_repository or InMemoryReconciliationRepository()
        self._internal_status: dict[str, BrokerOrderStatus] = {}
        self._operational_state = OperationalState.OFF
        self._kill_switch_ids = _IdAllocator("KSEVENT")
        self._reconciliation_ids = _IdAllocator("RECON")

    @property
    def operational_state(self) -> OperationalState:
        return self._operational_state

    def is_kill_switch_engaged(self) -> bool:
        return is_engaged(self._kill_switch_repository)

    def submit(
        self, order: ValidatedOrder, *, requested_at: datetime, gate_context: SafetyGateContext,
    ) -> LiveSubmissionOutcome:
        if self._operational_state == OperationalState.RECONCILIATION_REQUIRED:
            return LiveSubmissionOutcome(
                submitted=False, status="BLOCKED", gate_result=None, response=None,
                error="reconciliation_required",
            )

        gate_result = evaluate_safety_gate(gate_context)
        if not gate_result.passed:
            return LiveSubmissionOutcome(submitted=False, status="BLOCKED", gate_result=gate_result, response=None)

        try:
            response = self.adapter.submit_order(order, requested_at=requested_at)
        except BrokerError as exc:
            self._internal_status[order.client_order_id] = BrokerOrderStatus.UNKNOWN
            self._operational_state = OperationalState.RECONCILIATION_REQUIRED
            return LiveSubmissionOutcome(
                submitted=False, status="UNKNOWN", gate_result=gate_result, response=None,
                error=f"{type(exc).__name__}: {exc}",
            )

        self._internal_status[order.client_order_id] = response.status
        self._operational_state = OperationalState.ACTIVE
        return LiveSubmissionOutcome(submitted=True, status=response.status.value, gate_result=gate_result, response=response)

    def reconcile_order(self, client_order_id: str, *, as_of: datetime) -> ReconciliationResult:
        internal_status = self._internal_status.get(client_order_id)
        broker_status = self.adapter.get_order_status(client_order_id, as_of=as_of)
        result = compare_order_status(
            internal_status, broker_status, reconciliation_id=self._reconciliation_ids.allocate(),
            as_of_time=as_of, configuration_version=self.config.configuration_version(),
        )
        self._reconciliation_repository.record(result)
        if result.status == ReconciliationStatus.MATCHED:
            self._internal_status[client_order_id] = broker_status.status
            if self._operational_state == OperationalState.RECONCILIATION_REQUIRED:
                self._operational_state = OperationalState.ACTIVE
        return result

    def engage_kill_switch(self, reason: str, *, occurred_at: datetime) -> KillSwitchEvent:
        event = _engage_kill_switch(
            event_id=self._kill_switch_ids.allocate(), reason=reason, occurred_at=occurred_at,
            configuration_version=self.config.configuration_version(),
        )
        self._kill_switch_repository.record(event)
        self._operational_state = OperationalState.KILL_SWITCHED
        return event

    def release_kill_switch(self, approval: LiveActivationApproval, *, occurred_at: datetime) -> KillSwitchEvent:
        event = _release_kill_switch(
            event_id=self._kill_switch_ids.allocate(), approval=approval, occurred_at=occurred_at,
            configuration_version=self.config.configuration_version(),
        )
        self._kill_switch_repository.record(event)
        self._operational_state = OperationalState.READY
        return event
