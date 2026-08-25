"""Category: Broker Domain Model Test -- structural invariants on the
account/position read types and the open/closed status classification
(instruction section 14: an unavailable read is never coerced into
"0원"/"포지션 없음")."""

from __future__ import annotations

import pytest
from broker_helpers import utc

from broker.enums import BrokerOrderStatus, is_closed_status, is_open_status
from broker.models import BrokerAccountSnapshot, BrokerPosition


class TestOpenClosedStatusClassification:
    @pytest.mark.parametrize("status", [
        BrokerOrderStatus.PENDING, BrokerOrderStatus.PARTIAL_FILLED,
        BrokerOrderStatus.PENDING_CANCEL, BrokerOrderStatus.PENDING_REPLACE,
    ])
    def test_open_statuses(self, status) -> None:
        assert is_open_status(status) is True
        assert is_closed_status(status) is False

    @pytest.mark.parametrize("status", [
        BrokerOrderStatus.FILLED, BrokerOrderStatus.CANCELED,
        BrokerOrderStatus.REJECTED, BrokerOrderStatus.REPLACED,
    ])
    def test_closed_statuses(self, status) -> None:
        assert is_closed_status(status) is True
        assert is_open_status(status) is False

    def test_unknown_is_neither_open_nor_closed(self) -> None:
        assert is_open_status(BrokerOrderStatus.UNKNOWN) is False
        assert is_closed_status(BrokerOrderStatus.UNKNOWN) is False


class TestBrokerAccountSnapshotInvariants:
    def test_available_true_with_unavailable_reason_rejected(self) -> None:
        with pytest.raises(ValueError):
            BrokerAccountSnapshot(
                broker_id="b", as_of_time=utc(2024, 1, 2), available=True,
                unavailable_reason="should not be set", cash=100.0,
            )

    def test_available_false_without_reason_rejected(self) -> None:
        with pytest.raises(ValueError):
            BrokerAccountSnapshot(broker_id="b", as_of_time=utc(2024, 1, 2), available=False, unavailable_reason=None)

    def test_available_false_with_cash_value_rejected(self) -> None:
        with pytest.raises(ValueError):
            BrokerAccountSnapshot(
                broker_id="b", as_of_time=utc(2024, 1, 2), available=False,
                unavailable_reason="down", cash=0.0,
            )

    def test_available_false_is_a_valid_honest_state(self) -> None:
        snapshot = BrokerAccountSnapshot(
            broker_id="b", as_of_time=utc(2024, 1, 2), available=False, unavailable_reason="timeout",
        )
        assert snapshot.cash is None


class TestBrokerPositionInvariants:
    def test_available_false_with_quantity_rejected(self) -> None:
        with pytest.raises(ValueError):
            BrokerPosition(
                security_id="AAA", as_of_time=utc(2024, 1, 2), available=False,
                unavailable_reason="down", quantity=0.0,
            )

    def test_available_false_is_never_zero_quantity(self) -> None:
        position = BrokerPosition(
            security_id="AAA", as_of_time=utc(2024, 1, 2), available=False, unavailable_reason="down",
        )
        assert position.quantity is None

    def test_empty_security_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            BrokerPosition(security_id="", as_of_time=utc(2024, 1, 2), available=True, unavailable_reason=None)
