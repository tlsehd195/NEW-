"""Reconciliation -- PROJECT_MASTER_PLAN.md section 12.3: "Broker와의
연결이 끊긴 뒤 재연결되었을 때, 먼저 포지션/현금/미체결 주문 상태를
broker 측과 대조한 이후에만 신규 주문을 재개한다." Every comparison
function here is pure: it never queries the broker itself, only compares
two already-fetched snapshots. A mismatch or an unavailable side is
never silently resolved by trusting one side over the other --
`ReconciliationStatus.UNKNOWN`/`MISMATCH` both block new order
submission in `broker.live.session.LiveTradingSession` until an operator
records a resolution (instruction section 16, 17, 30).

See docs/specifications/PHASE-16-live-trading.md section 8.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol

from broker.enums import BrokerOrderStatus
from broker.live.enums import ReconciliationStatus
from broker.models import BrokerAccountSnapshot, BrokerPosition, OrderStatusObservation


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


@dataclass(frozen=True)
class ReconciliationResult:
    reconciliation_id: str  # "RECON-000001"
    target: str  # "account" | "position" | "order_status"
    subject_id: str  # broker_id / security_id / client_order_id, depending on target
    status: ReconciliationStatus
    as_of_time: datetime
    details: dict = field(default_factory=dict)
    configuration_version: str = "unknown"

    def __post_init__(self) -> None:
        if not self.reconciliation_id or not self.target or not self.subject_id:
            raise ValueError("ReconciliationResult requires non-empty reconciliation_id/target/subject_id")
        _require_aware("ReconciliationResult.as_of_time", self.as_of_time)


def compare_account(
    internal_cash: Optional[float], broker_snapshot: BrokerAccountSnapshot, *,
    tolerance: float, reconciliation_id: str, as_of_time: datetime, configuration_version: str,
) -> ReconciliationResult:
    if internal_cash is None or not broker_snapshot.available or broker_snapshot.cash is None:
        return ReconciliationResult(
            reconciliation_id=reconciliation_id, target="account", subject_id=broker_snapshot.broker_id,
            status=ReconciliationStatus.UNKNOWN,
            details={"internal_cash": internal_cash, "broker_available": broker_snapshot.available},
            as_of_time=as_of_time, configuration_version=configuration_version,
        )
    diff = abs(internal_cash - broker_snapshot.cash)
    status = ReconciliationStatus.MATCHED if diff <= tolerance else ReconciliationStatus.MISMATCH
    return ReconciliationResult(
        reconciliation_id=reconciliation_id, target="account", subject_id=broker_snapshot.broker_id, status=status,
        details={"internal_cash": internal_cash, "broker_cash": broker_snapshot.cash, "diff": diff},
        as_of_time=as_of_time, configuration_version=configuration_version,
    )


def compare_positions(
    internal_quantity: Optional[float], broker_position: Optional[BrokerPosition], *, security_id: str,
    tolerance: float, reconciliation_id: str, as_of_time: datetime, configuration_version: str,
) -> ReconciliationResult:
    if internal_quantity is None or broker_position is None or not broker_position.available or broker_position.quantity is None:
        return ReconciliationResult(
            reconciliation_id=reconciliation_id, target="position", subject_id=security_id,
            status=ReconciliationStatus.UNKNOWN,
            details={
                "internal_quantity": internal_quantity,
                "broker_available": broker_position.available if broker_position is not None else None,
            },
            as_of_time=as_of_time, configuration_version=configuration_version,
        )
    diff = abs(internal_quantity - broker_position.quantity)
    status = ReconciliationStatus.MATCHED if diff <= tolerance else ReconciliationStatus.MISMATCH
    return ReconciliationResult(
        reconciliation_id=reconciliation_id, target="position", subject_id=security_id, status=status,
        details={"internal_quantity": internal_quantity, "broker_quantity": broker_position.quantity, "diff": diff},
        as_of_time=as_of_time, configuration_version=configuration_version,
    )


def compare_order_status(
    internal_status: Optional[BrokerOrderStatus], broker_status: OrderStatusObservation, *,
    reconciliation_id: str, as_of_time: datetime, configuration_version: str,
) -> ReconciliationResult:
    if internal_status is None or broker_status.status == BrokerOrderStatus.UNKNOWN:
        return ReconciliationResult(
            reconciliation_id=reconciliation_id, target="order_status", subject_id=broker_status.client_order_id,
            status=ReconciliationStatus.UNKNOWN,
            details={
                "internal_status": internal_status.value if internal_status is not None else None,
                "broker_status": broker_status.status.value,
            },
            as_of_time=as_of_time, configuration_version=configuration_version,
        )
    status = ReconciliationStatus.MATCHED if internal_status == broker_status.status else ReconciliationStatus.MISMATCH
    return ReconciliationResult(
        reconciliation_id=reconciliation_id, target="order_status", subject_id=broker_status.client_order_id,
        status=status,
        details={"internal_status": internal_status.value, "broker_status": broker_status.status.value},
        as_of_time=as_of_time, configuration_version=configuration_version,
    )


class ReconciliationRepository(Protocol):
    def record(self, result: ReconciliationResult) -> ReconciliationResult:
        """Append-only -- idempotent only on `reconciliation_id` itself."""
        ...

    def get_latest(self, target: str, subject_id: str) -> Optional[ReconciliationResult]: ...
    def list_all(self) -> list[ReconciliationResult]: ...


class InMemoryReconciliationRepository:
    def __init__(self) -> None:
        self._results: list[ReconciliationResult] = []
        self._by_id: dict[str, ReconciliationResult] = {}

    def record(self, result: ReconciliationResult) -> ReconciliationResult:
        existing = self._by_id.get(result.reconciliation_id)
        if existing is not None:
            return existing
        self._results.append(result)
        self._by_id[result.reconciliation_id] = result
        return result

    def get_latest(self, target: str, subject_id: str) -> Optional[ReconciliationResult]:
        matching = [r for r in self._results if r.target == target and r.subject_id == subject_id]
        if not matching:
            return None
        return max(matching, key=lambda r: (r.as_of_time, r.reconciliation_id))

    def list_all(self) -> list[ReconciliationResult]:
        return sorted(self._results, key=lambda r: (r.as_of_time, r.reconciliation_id))
