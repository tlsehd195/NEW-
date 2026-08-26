"""Category: Persistence Test (in-memory) -- idempotency and ordering
for `InMemoryPaperOrderRepository`/`InMemoryPaperFillRepository`."""

from __future__ import annotations

from paper_helpers import make_validated_order, utc

from broker.enums import BrokerOrderStatus
from broker.paper.models import PaperFillRecord, PaperOrderRecord
from broker.paper.repository import InMemoryPaperFillRepository, InMemoryPaperOrderRepository

from backtest.enums import OrderSide
from backtest.fills import Fill


def _order_record(client_order_id="CID-1") -> PaperOrderRecord:
    return PaperOrderRecord(
        validated_order=make_validated_order(client_order_id=client_order_id), requested_at=utc(2024, 1, 2),
        initial_status=BrokerOrderStatus.PENDING, rejection_reason=None, configuration_version="cfg-1",
    )


def _fill_record(fill_id="PAPERFILL-000001", client_order_id="CID-1") -> PaperFillRecord:
    fill = Fill(
        order_id=client_order_id, security_id="AAA", side=OrderSide.BUY, quantity=10.0, reference_price=100.0,
        price=100.1, commission=1.0, spread_cost=0.1, slippage_cost=0.05,
        decision_time=utc(2024, 1, 2), execution_time=utc(2024, 1, 2), data_version="dv1",
    )
    return PaperFillRecord(fill_id=fill_id, client_order_id=client_order_id, fill=fill, configuration_version="cfg-1", recorded_at=utc(2024, 1, 2))


class TestPaperOrderRepository:
    def test_record_is_idempotent_on_client_order_id(self) -> None:
        repo = InMemoryPaperOrderRepository()
        record = _order_record()
        repo.record(record)
        repo.record(record)
        assert len(repo.list_all()) == 1

    def test_get_returns_none_when_absent(self) -> None:
        repo = InMemoryPaperOrderRepository()
        assert repo.get("CID-NEVER") is None


class TestPaperFillRepository:
    def test_append_only_and_idempotent_on_fill_id(self) -> None:
        repo = InMemoryPaperFillRepository()
        f1 = _fill_record(fill_id="F1")
        f2 = _fill_record(fill_id="F2")
        repo.record(f1)
        repo.record(f1)  # duplicate
        repo.record(f2)
        assert len(repo.list_all()) == 2

    def test_get_history_scoped_by_client_order_id(self) -> None:
        repo = InMemoryPaperFillRepository()
        repo.record(_fill_record(fill_id="F1", client_order_id="CID-1"))
        repo.record(_fill_record(fill_id="F2", client_order_id="CID-2"))
        assert len(repo.get_history("CID-1")) == 1
