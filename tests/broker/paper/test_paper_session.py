"""Category: Unit + Persistence Test -- `PaperTradingSession`'s
orchestration (submit/advance/cancel + persistence) and its
`restore()` rehydration path against `InMemory*` repositories."""

from __future__ import annotations

from paper_helpers import make_bar, make_paper_config, make_validated_order, utc

from broker.enums import BrokerOrderStatus
from broker.paper.market_data import InMemoryPaperMarketDataSource
from broker.paper.repository import (
    InMemoryPaperCorporateActionRepository,
    InMemoryPaperFillRepository,
    InMemoryPaperOrderRepository,
)
from broker.paper.session import PaperTradingSession
from broker.repository import InMemoryOrderStatusEventRepository


def _new_session(config=None, bars=()):
    config = config or make_paper_config(max_participation=0.10)
    mds = InMemoryPaperMarketDataSource(list(bars))
    order_repo = InMemoryPaperOrderRepository()
    fill_repo = InMemoryPaperFillRepository()
    status_repo = InMemoryOrderStatusEventRepository()
    corporate_action_repo = InMemoryPaperCorporateActionRepository()
    session = PaperTradingSession(
        config, mds, order_repository=order_repo, fill_repository=fill_repo, status_repository=status_repo,
        corporate_action_repository=corporate_action_repo,
    )
    return session, mds, order_repo, fill_repo, status_repo, corporate_action_repo


class TestSubmitPersistsOrderFillsAndStatus:
    def test_submit_persists_order_status_and_fills(self) -> None:
        session, _, order_repo, fill_repo, status_repo, _ = _new_session(
            bars=[make_bar(available_time=utc(2024, 1, 2), volume=1_000_000.0)],
            config=make_paper_config(max_participation=1.0),
        )
        order = make_validated_order(quantity=10.0)
        response, fills = session.submit(order, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.PENDING  # ADR-0154: fill is deferred
        assert len(fills) == 0

        _, fills2 = session.advance(utc(2024, 1, 2))  # first (deferred) fill attempt
        assert len(fills2) == 1
        assert order_repo.get(order.client_order_id) is not None
        assert len(fill_repo.list_all()) == 1
        assert status_repo.get_latest(order.client_order_id).status == BrokerOrderStatus.FILLED


class TestAdvancePersistsIncrementalFills:
    def test_advance_persists_new_status_and_fills_only(self) -> None:
        session, mds, order_repo, fill_repo, status_repo, _ = _new_session(
            bars=[make_bar(available_time=utc(2024, 1, 2), volume=1_000.0)],
            config=make_paper_config(max_participation=0.10),
        )
        order = make_validated_order(quantity=250.0)
        session.submit(order, requested_at=utc(2024, 1, 2))
        assert len(fill_repo.list_all()) == 0  # ADR-0154: fill is deferred

        updates0, fills0 = session.advance(utc(2024, 1, 2))  # first (deferred) fill attempt
        assert len(updates0) == 1
        assert len(fills0) == 1
        assert len(fill_repo.list_all()) == 1

        mds.register(make_bar(timestamp=utc(2024, 1, 3), available_time=utc(2024, 1, 3), volume=1_000.0))
        updates, fills2 = session.advance(utc(2024, 1, 3))
        assert len(updates) == 1
        assert len(fills2) == 1
        assert len(fill_repo.list_all()) == 2  # cumulative -- old fill still there, one new


class TestCancelPersistsStatus:
    def test_cancel_persists_cancelled_status(self) -> None:
        session, _, _, _, status_repo, _ = _new_session(bars=[])
        order = make_validated_order(quantity=10.0)
        session.submit(order, requested_at=utc(2024, 1, 2))
        session.cancel(order.client_order_id, requested_at=utc(2024, 1, 2))
        assert status_repo.get_latest(order.client_order_id).status == BrokerOrderStatus.CANCELED


class TestAccountSummary:
    def test_account_summary_reflects_fills(self) -> None:
        session, _, _, _, _, _ = _new_session(
            bars=[make_bar(available_time=utc(2024, 1, 2), volume=1_000_000.0)],
            config=make_paper_config(max_participation=1.0),
        )
        order = make_validated_order(quantity=10.0)
        session.submit(order, requested_at=utc(2024, 1, 2))
        session.advance(utc(2024, 1, 2))  # ADR-0154: fill is deferred -- attempt it now
        summary = session.account_summary(as_of=utc(2024, 1, 2))
        assert summary.cash < session.config.initial_cash
        assert summary.positions["AAA"].quantity == 10.0


class TestRestoreRehydratesFullState:
    def test_restore_reproduces_identical_cash_and_positions(self) -> None:
        session, mds, order_repo, fill_repo, status_repo, _ = _new_session(
            bars=[make_bar(available_time=utc(2024, 1, 2), volume=1_000.0)],
            config=make_paper_config(max_participation=0.10),
        )
        order = make_validated_order(quantity=250.0)
        session.submit(order, requested_at=utc(2024, 1, 2))
        session.advance(utc(2024, 1, 2))  # ADR-0154: first (deferred) fill attempt -- consumes day 2's cap
        mds.register(make_bar(timestamp=utc(2024, 1, 3), available_time=utc(2024, 1, 3), volume=1_000.0))
        session.advance(utc(2024, 1, 3))  # a fresh cap -- 100 more, total 200

        before = session.account_summary(as_of=utc(2024, 1, 3))

        mds2 = InMemoryPaperMarketDataSource([
            make_bar(available_time=utc(2024, 1, 2), volume=1_000.0),
            make_bar(timestamp=utc(2024, 1, 3), available_time=utc(2024, 1, 3), volume=1_000.0),
        ])
        restored = PaperTradingSession.restore(
            session.config, mds2, order_repository=order_repo, fill_repository=fill_repo,
            status_repository=status_repo, corporate_action_repository=InMemoryPaperCorporateActionRepository(),
            as_of=utc(2024, 1, 3),
        )
        after = restored.account_summary(as_of=utc(2024, 1, 3))

        assert before.cash == after.cash
        assert before.positions["AAA"].quantity == after.positions["AAA"].quantity
        status_after = restored.adapter.get_order_status(order.client_order_id, as_of=utc(2024, 1, 3))
        assert status_after.status == BrokerOrderStatus.PARTIAL_FILLED
        assert status_after.filled_quantity == 200.0

    def test_restore_does_not_resurrect_a_fill_time_rejection_as_pending(self) -> None:
        """Independent audit finding (Step 8, P3, "R2" -- "restart
        amnesia"): an order rejected at FILL time (never at submit
        time) used to have its ORIGINAL, stale PENDING PaperOrderRecord
        replayed by `restore()` -- reviving it as PENDING in the fresh
        process and letting `advance()` retry it forever, since nothing
        had ever persisted the fill-time REJECTED mutation back to
        `order_repository` itself (only to `status_repository`, as an
        observation)."""
        session, _, order_repo, fill_repo, status_repo, _ = _new_session(
            bars=[make_bar(available_time=utc(2024, 1, 2), close=100.0)],
            config=make_paper_config(initial_cash=100.0),  # far below a 10-share, $100/share order's notional
        )
        order = make_validated_order(quantity=10.0)
        session.submit(order, requested_at=utc(2024, 1, 2))
        session.advance(utc(2024, 1, 2))  # ADR-0154: first (deferred) fill attempt -> insufficient_cash REJECTED
        assert status_repo.get_latest(order.client_order_id).status == BrokerOrderStatus.REJECTED
        assert len(fill_repo.list_all()) == 0

        mds2 = InMemoryPaperMarketDataSource([
            make_bar(available_time=utc(2024, 1, 2), close=100.0),
            make_bar(timestamp=utc(2024, 1, 3), available_time=utc(2024, 1, 3), close=100.0),
        ])
        restored = PaperTradingSession.restore(
            session.config, mds2, order_repository=order_repo, fill_repository=fill_repo,
            status_repository=status_repo, corporate_action_repository=InMemoryPaperCorporateActionRepository(),
            as_of=utc(2024, 1, 2),
        )
        status_after_restore = restored.adapter.get_order_status(order.client_order_id, as_of=utc(2024, 1, 2))
        assert status_after_restore.status == BrokerOrderStatus.REJECTED  # not resurrected as PENDING

        # A later advance() must never retry a genuinely-rejected order.
        restored.advance(utc(2024, 1, 3))
        assert len(fill_repo.list_all()) == 0
        final_status = restored.adapter.get_order_status(order.client_order_id, as_of=utc(2024, 1, 3))
        assert final_status.status == BrokerOrderStatus.REJECTED

    def test_restore_does_not_duplicate_fills(self) -> None:
        session, _, order_repo, fill_repo, status_repo, _ = _new_session(
            bars=[make_bar(available_time=utc(2024, 1, 2), volume=1_000_000.0)],
            config=make_paper_config(max_participation=1.0),
        )
        order = make_validated_order(quantity=10.0)
        session.submit(order, requested_at=utc(2024, 1, 2))
        session.advance(utc(2024, 1, 2))  # ADR-0154: fill is deferred -- attempt it now
        assert len(fill_repo.list_all()) == 1

        mds2 = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2), volume=1_000_000.0)])
        restored = PaperTradingSession.restore(
            session.config, mds2, order_repository=order_repo, fill_repository=fill_repo,
            status_repository=status_repo, corporate_action_repository=InMemoryPaperCorporateActionRepository(),
            as_of=utc(2024, 1, 2),
        )
        # resubmitting the identical order after restore must not double-fill
        response, fills = restored.submit(order, requested_at=utc(2024, 1, 2))
        assert response.filled_quantity == 10.0
        assert len(fill_repo.list_all()) == 1  # still exactly one fill total

    def test_restore_reproduces_the_bar_participation_cap_already_consumed(self) -> None:
        """Independent audit finding F2 (2026-09-24, same "restart
        amnesia" family as R2 above): `_bar_participation_consumed`
        (max_participation's own running tally of how much of a single
        bar's real volume has already been claimed) was never rebuilt by
        `restore()` -- a restart mid-bar silently reset the tally to
        empty, letting a SECOND order against the SAME bar in the
        restored process claim up to the FULL cap all over again on top
        of what the pre-restart process already consumed."""
        session, _, order_repo, fill_repo, status_repo, _ = _new_session(
            bars=[make_bar(available_time=utc(2024, 1, 2), volume=1_000.0)],
            config=make_paper_config(max_participation=0.10),  # cap = 100 shares of this bar
        )
        first = make_validated_order(client_order_id="CID-1", quantity=60.0)
        session.submit(first, requested_at=utc(2024, 1, 2))
        session.advance(utc(2024, 1, 2))  # ADR-0154: first (deferred) fill attempt -- consumes 60 of the 100-share cap
        status1 = session.adapter.get_order_status("CID-1", as_of=utc(2024, 1, 2))
        assert status1.status == BrokerOrderStatus.FILLED
        assert status1.filled_quantity == 60.0

        mds2 = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2), volume=1_000.0)])
        restored = PaperTradingSession.restore(
            session.config, mds2, order_repository=order_repo, fill_repository=fill_repo,
            status_repository=status_repo, corporate_action_repository=InMemoryPaperCorporateActionRepository(),
            as_of=utc(2024, 1, 2),
        )

        second = make_validated_order(client_order_id="CID-2", quantity=100.0)
        restored.submit(second, requested_at=utc(2024, 1, 2))
        restored.advance(utc(2024, 1, 2))
        status2 = restored.adapter.get_order_status("CID-2", as_of=utc(2024, 1, 2))
        # Only 100 - 60 = 40 of the 100-share cap remains for this bar --
        # NOT the full 100 a reset-to-empty tally would have wrongly allowed.
        assert status2.status == BrokerOrderStatus.PARTIAL_FILLED
        assert status2.filled_quantity == 40.0
