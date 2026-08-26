"""Category: Unit + Persistence Test -- `PaperTradingSession`'s
orchestration (submit/advance/cancel + persistence) and its
`restore()` rehydration path against `InMemory*` repositories."""

from __future__ import annotations

from paper_helpers import make_bar, make_paper_config, make_validated_order, utc

from broker.enums import BrokerOrderStatus
from broker.paper.market_data import InMemoryPaperMarketDataSource
from broker.paper.repository import InMemoryPaperFillRepository, InMemoryPaperOrderRepository
from broker.paper.session import PaperTradingSession
from broker.repository import InMemoryOrderStatusEventRepository


def _new_session(config=None, bars=()):
    config = config or make_paper_config(max_participation=0.10)
    mds = InMemoryPaperMarketDataSource(list(bars))
    order_repo = InMemoryPaperOrderRepository()
    fill_repo = InMemoryPaperFillRepository()
    status_repo = InMemoryOrderStatusEventRepository()
    session = PaperTradingSession(
        config, mds, order_repository=order_repo, fill_repository=fill_repo, status_repository=status_repo,
    )
    return session, mds, order_repo, fill_repo, status_repo


class TestSubmitPersistsOrderFillsAndStatus:
    def test_submit_persists_order_status_and_fills(self) -> None:
        session, _, order_repo, fill_repo, status_repo = _new_session(
            bars=[make_bar(available_time=utc(2024, 1, 2), volume=1_000_000.0)],
            config=make_paper_config(max_participation=1.0),
        )
        order = make_validated_order(quantity=10.0)
        response, fills = session.submit(order, requested_at=utc(2024, 1, 2))

        assert response.status == BrokerOrderStatus.FILLED
        assert order_repo.get(order.client_order_id) is not None
        assert len(fill_repo.list_all()) == 1
        assert len(fills) == 1
        assert status_repo.get_latest(order.client_order_id).status == BrokerOrderStatus.FILLED


class TestAdvancePersistsIncrementalFills:
    def test_advance_persists_new_status_and_fills_only(self) -> None:
        session, mds, order_repo, fill_repo, status_repo = _new_session(
            bars=[make_bar(available_time=utc(2024, 1, 2), volume=1_000.0)],
            config=make_paper_config(max_participation=0.10),
        )
        order = make_validated_order(quantity=250.0)
        session.submit(order, requested_at=utc(2024, 1, 2))
        assert len(fill_repo.list_all()) == 1

        mds.register(make_bar(timestamp=utc(2024, 1, 3), available_time=utc(2024, 1, 3), volume=1_000.0))
        updates, fills2 = session.advance(utc(2024, 1, 3))
        assert len(updates) == 1
        assert len(fills2) == 1
        assert len(fill_repo.list_all()) == 2  # cumulative -- old fill still there, one new


class TestCancelPersistsStatus:
    def test_cancel_persists_cancelled_status(self) -> None:
        session, _, _, _, status_repo = _new_session(bars=[])
        order = make_validated_order(quantity=10.0)
        session.submit(order, requested_at=utc(2024, 1, 2))
        session.cancel(order.client_order_id, requested_at=utc(2024, 1, 2))
        assert status_repo.get_latest(order.client_order_id).status == BrokerOrderStatus.CANCELED


class TestAccountSummary:
    def test_account_summary_reflects_fills(self) -> None:
        session, _, _, _, _ = _new_session(
            bars=[make_bar(available_time=utc(2024, 1, 2), volume=1_000_000.0)],
            config=make_paper_config(max_participation=1.0),
        )
        order = make_validated_order(quantity=10.0)
        session.submit(order, requested_at=utc(2024, 1, 2))
        summary = session.account_summary(as_of=utc(2024, 1, 2))
        assert summary.cash < session.config.initial_cash
        assert summary.positions["AAA"].quantity == 10.0


class TestRestoreRehydratesFullState:
    def test_restore_reproduces_identical_cash_and_positions(self) -> None:
        session, mds, order_repo, fill_repo, status_repo = _new_session(
            bars=[make_bar(available_time=utc(2024, 1, 2), volume=1_000.0)],
            config=make_paper_config(max_participation=0.10),
        )
        order = make_validated_order(quantity=250.0)
        session.submit(order, requested_at=utc(2024, 1, 2))
        mds.register(make_bar(timestamp=utc(2024, 1, 3), available_time=utc(2024, 1, 3), volume=1_000.0))
        session.advance(utc(2024, 1, 3))

        before = session.account_summary(as_of=utc(2024, 1, 3))

        mds2 = InMemoryPaperMarketDataSource([
            make_bar(available_time=utc(2024, 1, 2), volume=1_000.0),
            make_bar(timestamp=utc(2024, 1, 3), available_time=utc(2024, 1, 3), volume=1_000.0),
        ])
        restored = PaperTradingSession.restore(
            session.config, mds2, order_repository=order_repo, fill_repository=fill_repo,
            status_repository=status_repo, as_of=utc(2024, 1, 3),
        )
        after = restored.account_summary(as_of=utc(2024, 1, 3))

        assert before.cash == after.cash
        assert before.positions["AAA"].quantity == after.positions["AAA"].quantity
        status_after = restored.adapter.get_order_status(order.client_order_id, as_of=utc(2024, 1, 3))
        assert status_after.status == BrokerOrderStatus.PARTIAL_FILLED
        assert status_after.filled_quantity == 200.0

    def test_restore_does_not_duplicate_fills(self) -> None:
        session, _, order_repo, fill_repo, status_repo = _new_session(
            bars=[make_bar(available_time=utc(2024, 1, 2), volume=1_000_000.0)],
            config=make_paper_config(max_participation=1.0),
        )
        order = make_validated_order(quantity=10.0)
        session.submit(order, requested_at=utc(2024, 1, 2))
        assert len(fill_repo.list_all()) == 1

        mds2 = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2), volume=1_000_000.0)])
        restored = PaperTradingSession.restore(
            session.config, mds2, order_repository=order_repo, fill_repository=fill_repo,
            status_repository=status_repo, as_of=utc(2024, 1, 2),
        )
        # resubmitting the identical order after restore must not double-fill
        response, fills = restored.submit(order, requested_at=utc(2024, 1, 2))
        assert response.filled_quantity == 10.0
        assert len(fill_repo.list_all()) == 1  # still exactly one fill total
