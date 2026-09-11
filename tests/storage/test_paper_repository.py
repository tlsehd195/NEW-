"""Category: Persistence Test -- save, reload, idempotency, restart for
Phase 15's two Paper Trading DuckDB stores (docs/specifications/
PHASE-15-paper-trading.md section 13)."""

from __future__ import annotations

from paper_helpers import make_bar, make_paper_config, make_validated_order, utc
from storage_helpers import new_engine

from broker.enums import BrokerOrderStatus
from broker.paper.market_data import InMemoryPaperMarketDataSource
from broker.paper.session import PaperTradingSession

from storage.broker_repository import DuckDBOrderStatusEventRepository
from storage.paper_repository import DuckDBPaperFillRepository, DuckDBPaperOrderRepository


class TestPaperOrderPersistence:
    def test_record_and_get_round_trips(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        order_repo = DuckDBPaperOrderRepository(engine)
        fill_repo = DuckDBPaperFillRepository(engine)
        status_repo = DuckDBOrderStatusEventRepository(engine)

        config = make_paper_config(max_participation=1.0)
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2), volume=1_000_000.0)])
        session = PaperTradingSession(config, mds, order_repository=order_repo, fill_repository=fill_repo, status_repository=status_repo)

        order = make_validated_order(quantity=10.0)
        session.submit(order, requested_at=utc(2024, 1, 2))

        fetched = order_repo.get(order.client_order_id)
        assert fetched is not None
        assert fetched.validated_order == order
        assert fetched.initial_status == BrokerOrderStatus.PENDING  # accepted -- initial_status is PENDING, fills come after
        engine.close()

    def test_recording_the_same_order_twice_is_idempotent(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        order_repo = DuckDBPaperOrderRepository(engine)
        from broker.paper.models import PaperOrderRecord

        record = PaperOrderRecord(
            validated_order=make_validated_order(), requested_at=utc(2024, 1, 2),
            initial_status=BrokerOrderStatus.PENDING, rejection_reason=None, configuration_version="cfg-1",
        )
        order_repo.record(record)
        order_repo.record(record)
        assert len(order_repo.list_all()) == 1
        engine.close()

    def test_survives_restart(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        order_repo = DuckDBPaperOrderRepository(engine)
        from broker.paper.models import PaperOrderRecord

        record = PaperOrderRecord(
            validated_order=make_validated_order(), requested_at=utc(2024, 1, 2),
            initial_status=BrokerOrderStatus.PENDING, rejection_reason=None, configuration_version="cfg-1",
        )
        order_repo.record(record)
        engine.close()

        engine2 = new_engine(tmp_path)
        order_repo2 = DuckDBPaperOrderRepository(engine2)
        assert order_repo2.get(record.validated_order.client_order_id) == record
        engine2.close()


class TestPaperFillPersistence:
    def test_append_only_and_idempotent(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fill_repo = DuckDBPaperFillRepository(engine)
        from broker.paper.models import PaperFillRecord

        from backtest.enums import OrderSide
        from backtest.fills import Fill

        fill = Fill(
            order_id="CID-1", security_id="AAA", side=OrderSide.BUY, quantity=10.0, reference_price=100.0,
            price=100.1, commission=1.0, spread_cost=0.1, slippage_cost=0.05,
            decision_time=utc(2024, 1, 2), execution_time=utc(2024, 1, 2), data_version="dv1",
        )
        record = PaperFillRecord(fill_id="PAPERFILL-000001", client_order_id="CID-1", fill=fill, configuration_version="cfg-1", recorded_at=utc(2024, 1, 2))
        fill_repo.record(record)
        fill_repo.record(record)
        assert len(fill_repo.list_all()) == 1
        assert fill_repo.get_history("CID-1")[0] == record
        engine.close()


class TestFullSessionRestartAgainstDuckDB:
    def test_submit_advance_restart_reproduces_identical_state(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        order_repo = DuckDBPaperOrderRepository(engine)
        fill_repo = DuckDBPaperFillRepository(engine)
        status_repo = DuckDBOrderStatusEventRepository(engine)

        config = make_paper_config(max_participation=0.10)
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2), volume=1_000.0)])
        session = PaperTradingSession(config, mds, order_repository=order_repo, fill_repository=fill_repo, status_repository=status_repo)

        order = make_validated_order(quantity=250.0)
        session.submit(order, requested_at=utc(2024, 1, 2))
        mds.register(make_bar(timestamp=utc(2024, 1, 3), available_time=utc(2024, 1, 3), volume=1_000.0))
        session.advance(utc(2024, 1, 3))

        before = session.account_summary(as_of=utc(2024, 1, 3))
        engine.close()

        engine2 = new_engine(tmp_path)
        order_repo2 = DuckDBPaperOrderRepository(engine2)
        fill_repo2 = DuckDBPaperFillRepository(engine2)
        status_repo2 = DuckDBOrderStatusEventRepository(engine2)
        mds2 = InMemoryPaperMarketDataSource([
            make_bar(available_time=utc(2024, 1, 2), volume=1_000.0),
            make_bar(timestamp=utc(2024, 1, 3), available_time=utc(2024, 1, 3), volume=1_000.0),
        ])
        restored = PaperTradingSession.restore(
            config, mds2, order_repository=order_repo2, fill_repository=fill_repo2, status_repository=status_repo2,
            as_of=utc(2024, 1, 3),
        )
        after = restored.account_summary(as_of=utc(2024, 1, 3))

        assert before.cash == after.cash
        assert before.positions["AAA"].quantity == after.positions["AAA"].quantity
        engine2.close()

    def test_a_status_observation_recorded_after_restart_is_not_silently_dropped(self, tmp_path) -> None:
        """Session 37 (ADR-0115, external review N-6): before this fix,
        `PaperTradingSession.restore()` never seeded the restored
        adapter's `_observation_ids` allocator past what a prior process
        already persisted -- its first freshly generated id after
        restart always started back at "PAPEROSTAT-000001" again. Once
        that collided with a row `status_repo` already had from before
        the restart, `DuckDBOrderStatusEventRepository.record()`'s
        natural-key dedup on `observation_id` silently returned the
        STALE pre-restart row instead of persisting the genuinely new
        one -- so a status change that happened *after* restart (here,
        an order finally reaching FILLED) never actually reached the
        database at all."""
        engine = new_engine(tmp_path)
        order_repo = DuckDBPaperOrderRepository(engine)
        fill_repo = DuckDBPaperFillRepository(engine)
        status_repo = DuckDBOrderStatusEventRepository(engine)

        config = make_paper_config(max_participation=0.10)
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2), volume=1_000.0)])
        session = PaperTradingSession(config, mds, order_repository=order_repo, fill_repository=fill_repo, status_repository=status_repo)

        order = make_validated_order(quantity=250.0)
        session.submit(order, requested_at=utc(2024, 1, 2))  # fills up to 100 -- PARTIAL_FILLED
        mds.register(make_bar(timestamp=utc(2024, 1, 3), available_time=utc(2024, 1, 3), volume=1_000.0))
        session.advance(utc(2024, 1, 3))  # fills up to another 100 (200 total) -- still PARTIAL_FILLED
        assert status_repo.get_latest(order.client_order_id).status == BrokerOrderStatus.PARTIAL_FILLED
        engine.close()

        engine2 = new_engine(tmp_path)
        order_repo2 = DuckDBPaperOrderRepository(engine2)
        fill_repo2 = DuckDBPaperFillRepository(engine2)
        status_repo2 = DuckDBOrderStatusEventRepository(engine2)
        mds2 = InMemoryPaperMarketDataSource([
            make_bar(available_time=utc(2024, 1, 2), volume=1_000.0),
            make_bar(timestamp=utc(2024, 1, 3), available_time=utc(2024, 1, 3), volume=1_000.0),
        ])
        restored = PaperTradingSession.restore(
            config, mds2, order_repository=order_repo2, fill_repository=fill_repo2, status_repository=status_repo2,
            as_of=utc(2024, 1, 3),
        )

        # A genuinely new event, only possible after restart: the final
        # 50 shares fill, taking the order from PARTIAL_FILLED to FILLED.
        mds2.register(make_bar(timestamp=utc(2024, 1, 4), available_time=utc(2024, 1, 4), volume=1_000.0))
        restored.advance(utc(2024, 1, 4))

        latest = status_repo2.get_latest(order.client_order_id)
        assert latest.status == BrokerOrderStatus.FILLED
        assert latest.filled_quantity == 250.0
        engine2.close()
