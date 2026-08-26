"""Category: Reconciliation Test -- account/position/order-status
comparison, UNKNOWN-when-unavailable, never coerced to MATCHED."""

from __future__ import annotations

from live_helpers import utc

from broker.enums import BrokerOrderStatus
from broker.live.enums import ReconciliationStatus
from broker.live.reconciliation import (
    InMemoryReconciliationRepository,
    compare_account,
    compare_order_status,
    compare_positions,
)
from broker.models import BrokerAccountSnapshot, BrokerPosition, OrderStatusObservation


def _snapshot(*, available=True, cash=1000.0) -> BrokerAccountSnapshot:
    return BrokerAccountSnapshot(
        broker_id="toss", as_of_time=utc(2024, 1, 2), available=available,
        unavailable_reason=None if available else "simulated failure",
        cash=cash if available else None, buying_power=cash if available else None, currency="KRW",
    )


def _position(*, available=True, quantity=10.0) -> BrokerPosition:
    return BrokerPosition(
        security_id="AAA", as_of_time=utc(2024, 1, 2), available=available,
        unavailable_reason=None if available else "simulated failure",
        quantity=quantity if available else None, average_cost=100.0 if available else None,
    )


def _observation(status=BrokerOrderStatus.FILLED) -> OrderStatusObservation:
    return OrderStatusObservation(
        observation_id="O1", client_order_id="CID-1", broker_id="toss", broker_order_id="X", status=status,
        filled_quantity=10.0 if status != BrokerOrderStatus.UNKNOWN else None,
        avg_fill_price=100.0 if status != BrokerOrderStatus.UNKNOWN else None,
        observed_at=utc(2024, 1, 2), raw_status_code=status.value,
    )


class TestCompareAccount:
    def test_matched_within_tolerance(self) -> None:
        result = compare_account(1000.005, _snapshot(), tolerance=0.01, reconciliation_id="R1", as_of_time=utc(2024, 1, 2), configuration_version="cfg-1")
        assert result.status == ReconciliationStatus.MATCHED

    def test_mismatch_beyond_tolerance(self) -> None:
        result = compare_account(500.0, _snapshot(), tolerance=0.01, reconciliation_id="R2", as_of_time=utc(2024, 1, 2), configuration_version="cfg-1")
        assert result.status == ReconciliationStatus.MISMATCH

    def test_unknown_when_internal_cash_missing(self) -> None:
        result = compare_account(None, _snapshot(), tolerance=0.01, reconciliation_id="R3", as_of_time=utc(2024, 1, 2), configuration_version="cfg-1")
        assert result.status == ReconciliationStatus.UNKNOWN

    def test_unknown_when_broker_unavailable(self) -> None:
        result = compare_account(1000.0, _snapshot(available=False), tolerance=0.01, reconciliation_id="R4", as_of_time=utc(2024, 1, 2), configuration_version="cfg-1")
        assert result.status == ReconciliationStatus.UNKNOWN
        assert result.status != ReconciliationStatus.MATCHED


class TestComparePositions:
    def test_matched(self) -> None:
        result = compare_positions(10.0, _position(), security_id="AAA", tolerance=0.01, reconciliation_id="R5", as_of_time=utc(2024, 1, 2), configuration_version="cfg-1")
        assert result.status == ReconciliationStatus.MATCHED

    def test_mismatch(self) -> None:
        result = compare_positions(5.0, _position(), security_id="AAA", tolerance=0.01, reconciliation_id="R6", as_of_time=utc(2024, 1, 2), configuration_version="cfg-1")
        assert result.status == ReconciliationStatus.MISMATCH

    def test_unknown_when_position_missing_entirely(self) -> None:
        result = compare_positions(10.0, None, security_id="AAA", tolerance=0.01, reconciliation_id="R7", as_of_time=utc(2024, 1, 2), configuration_version="cfg-1")
        assert result.status == ReconciliationStatus.UNKNOWN

    def test_unknown_when_broker_position_unavailable(self) -> None:
        result = compare_positions(10.0, _position(available=False), security_id="AAA", tolerance=0.01, reconciliation_id="R8", as_of_time=utc(2024, 1, 2), configuration_version="cfg-1")
        assert result.status == ReconciliationStatus.UNKNOWN


class TestCompareOrderStatus:
    def test_matched(self) -> None:
        result = compare_order_status(BrokerOrderStatus.FILLED, _observation(BrokerOrderStatus.FILLED), reconciliation_id="R9", as_of_time=utc(2024, 1, 2), configuration_version="cfg-1")
        assert result.status == ReconciliationStatus.MATCHED

    def test_mismatch(self) -> None:
        result = compare_order_status(BrokerOrderStatus.PENDING, _observation(BrokerOrderStatus.FILLED), reconciliation_id="R10", as_of_time=utc(2024, 1, 2), configuration_version="cfg-1")
        assert result.status == ReconciliationStatus.MISMATCH

    def test_unknown_when_internal_status_missing(self) -> None:
        result = compare_order_status(None, _observation(BrokerOrderStatus.FILLED), reconciliation_id="R11", as_of_time=utc(2024, 1, 2), configuration_version="cfg-1")
        assert result.status == ReconciliationStatus.UNKNOWN

    def test_unknown_when_broker_status_itself_unknown(self) -> None:
        """A broker-side UNKNOWN can never be resolved to MATCHED just
        because the internal side happens to have a real value."""
        result = compare_order_status(BrokerOrderStatus.FILLED, _observation(BrokerOrderStatus.UNKNOWN), reconciliation_id="R12", as_of_time=utc(2024, 1, 2), configuration_version="cfg-1")
        assert result.status == ReconciliationStatus.UNKNOWN


class TestReconciliationRepository:
    def test_append_only_and_idempotent(self) -> None:
        repo = InMemoryReconciliationRepository()
        result = compare_account(1000.0, _snapshot(), tolerance=0.01, reconciliation_id="R13", as_of_time=utc(2024, 1, 2), configuration_version="cfg-1")
        repo.record(result)
        repo.record(result)
        assert len(repo.list_all()) == 1

    def test_get_latest_scoped_by_target_and_subject(self) -> None:
        repo = InMemoryReconciliationRepository()
        r1 = compare_account(1000.0, _snapshot(cash=1000.0), tolerance=0.01, reconciliation_id="R14", as_of_time=utc(2024, 1, 2), configuration_version="cfg-1")
        r2 = compare_account(900.0, _snapshot(cash=850.0), tolerance=0.01, reconciliation_id="R15", as_of_time=utc(2024, 1, 3), configuration_version="cfg-1")
        repo.record(r1)
        repo.record(r2)
        latest = repo.get_latest("account", "toss")
        assert latest.reconciliation_id == "R15"
