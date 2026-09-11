"""submit_validated_order: wraps one `BrokerAdapter.submit_order` call
with the uniform audit-log recording every operation gets (instruction
section 15) -- mirrors `ai_gateway.gateway.AIGateway`'s `_finalize`
pattern (Phase 12) applied to the broker boundary instead. Persists
nothing itself unless repositories are supplied (the same "return
objects, caller decides what to keep" separation
`learning.pipeline.run_learning_pipeline`/`evolution.pipeline.
generate_candidate_batch` already use).

See docs/specifications/PHASE-13-toss-securities-adapter.md section 15.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from broker.errors import BrokerError
from broker.models import BrokerOrderResponse, BrokerRequestRecord, BrokerResponseRecord, ValidatedOrder
from broker.protocol import BrokerAdapter
from broker.repository import BrokerRequestRepository, BrokerResponseRepository

from trade_journal.enums import TradeProvenance


class _IdAllocator:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._next_id = 1

    def allocate(self) -> str:
        value = f"{self._prefix}-{self._next_id:06d}"
        self._next_id += 1
        return value

    def advance_past(self, ids: list[str]) -> None:
        """Seeds this allocator past the highest numeric suffix among
        `ids` that starts with this allocator's own prefix -- a no-op
        if none do. Never moves `_next_id` backward (a smaller max seen
        on a later call, e.g. an empty `list_all()`, never un-seeds an
        allocator that has already advanced)."""
        needle = f"{self._prefix}-"
        max_seen = 0
        for value in ids:
            if not value.startswith(needle):
                continue
            try:
                max_seen = max(max_seen, int(value[len(needle):]))
            except ValueError:
                continue
        self._next_id = max(self._next_id, max_seen + 1)


_request_ids = _IdAllocator("BROKREQ")
_log_response_ids = _IdAllocator("BROKRESLOG")


def seed_broker_pipeline_ids(
    request_repository: Optional[BrokerRequestRepository] = None,
    response_repository: Optional[BrokerResponseRepository] = None,
) -> None:
    """Restart-safety seeding (same pattern established elsewhere this
    session -- `ai_gateway.QuotaManager`/`storage.data_repository`'s
    `_compute_next_raw_batch_id`/`broker.paper.adapter.
    restore_observation_id_watermark`): `_request_ids`/`_log_response_ids`
    are process-lifetime module counters that otherwise restart at 1
    every process invocation. `DuckDBBrokerRequestRepository.record`/
    `DuckDBBrokerResponseRepository.record` dedupe on the caller-
    assigned id itself (this log has no other natural key -- see this
    module's own docstring), so a post-restart id colliding with an
    already-persisted, UNRELATED row would return that stale row
    instead of raising, silently discarding the real new order's own
    audit entry. Call this once, right after constructing the real
    repositories, before any real `submit_validated_order` call."""
    if request_repository is not None:
        _request_ids.advance_past([r.request_id for r in request_repository.list_all()])
    if response_repository is not None:
        _log_response_ids.advance_past([r.response_id for r in response_repository.list_all()])


def submit_validated_order(
    adapter: BrokerAdapter,
    order: ValidatedOrder,
    *,
    execution_mode: str,
    requested_at: datetime,
    configuration_version: str,
    request_repository: Optional[BrokerRequestRepository] = None,
    response_repository: Optional[BrokerResponseRepository] = None,
) -> BrokerOrderResponse:
    request_record = BrokerRequestRecord(
        request_id=_request_ids.allocate(), broker_id=adapter.broker_id, operation="submit_order",
        execution_mode=execution_mode, client_order_id=order.client_order_id, decision_id=order.decision_id,
        sizing_id=order.sizing_id, risk_assessment_id=order.risk_assessment_id,
        configuration_version=configuration_version, requested_at=requested_at, provenance=order.provenance,
        payload={"security_id": order.security_id, "side": order.side.value, "quantity": order.quantity},
        experiment_id=order.experiment_id,
    )
    if request_repository is not None:
        request_repository.record(request_record)

    try:
        order_response = adapter.submit_order(order, requested_at=requested_at)
    except BrokerError as exc:
        if response_repository is not None:
            response_repository.record(BrokerResponseRecord(
                response_id=_log_response_ids.allocate(), request_id=request_record.request_id,
                broker_id=adapter.broker_id, operation="submit_order", status="ERROR",
                broker_order_id=None, error_code=type(exc).__name__, attempt_count=1, latency_ms=None,
                responded_at=requested_at, provenance=order.provenance, metadata={"reason": str(exc)},
                experiment_id=order.experiment_id,
            ))
        raise

    if response_repository is not None:
        response_repository.record(BrokerResponseRecord(
            response_id=_log_response_ids.allocate(), request_id=request_record.request_id,
            broker_id=adapter.broker_id, operation="submit_order", status=order_response.status.value,
            broker_order_id=order_response.broker_order_id, error_code=order_response.error_code,
            attempt_count=order_response.attempt_count, latency_ms=order_response.latency_ms,
            responded_at=order_response.responded_at, provenance=order_response.provenance,
            metadata={}, experiment_id=order_response.experiment_id,
        ))

    return order_response
