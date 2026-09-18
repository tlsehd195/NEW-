"""Category: Persistence Test -- save, reload, idempotency, restart for
Phase 15's two Paper Trading DuckDB stores (docs/specifications/
PHASE-15-paper-trading.md section 13)."""

from __future__ import annotations

from paper_helpers import make_bar, make_corporate_action, make_paper_config, make_validated_order, utc
from storage_helpers import new_engine

from broker.enums import BrokerOrderStatus
from broker.paper.market_data import InMemoryPaperMarketDataSource
from broker.paper.session import PaperTradingSession

from broker.paper.models import PaperAppliedCorporateActionRecord
from broker.paper.repository import InMemoryPaperCorporateActionRepository

import pytest

from backtest.enums import OrderSide

from data_infra.enums import CorporateActionType

from storage.broker_repository import DuckDBOrderStatusEventRepository
from storage.paper_repository import DuckDBPaperCorporateActionRepository, DuckDBPaperFillRepository, DuckDBPaperOrderRepository


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
            corporate_action_repository=InMemoryPaperCorporateActionRepository(), as_of=utc(2024, 1, 3),
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
        session.submit(order, requested_at=utc(2024, 1, 2))
        session.advance(utc(2024, 1, 2))  # ADR-0154: first (deferred) fill attempt -- fills up to 100
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
            corporate_action_repository=InMemoryPaperCorporateActionRepository(), as_of=utc(2024, 1, 3),
        )

        # A genuinely new event, only possible after restart: the final
        # 50 shares fill, taking the order from PARTIAL_FILLED to FILLED.
        mds2.register(make_bar(timestamp=utc(2024, 1, 4), available_time=utc(2024, 1, 4), volume=1_000.0))
        restored.advance(utc(2024, 1, 4))

        latest = status_repo2.get_latest(order.client_order_id)
        assert latest.status == BrokerOrderStatus.FILLED
        assert latest.filled_quantity == 250.0
        engine2.close()


class TestPaperCorporateActionPersistence:
    """ADR-0155: mirrors `TestPaperOrderPersistence`/`TestPaperFillPersistence`
    above for the new `DuckDBPaperCorporateActionRepository`."""

    def test_record_and_get_round_trips(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBPaperCorporateActionRepository(engine)
        action = make_corporate_action(action_type=CorporateActionType.SPLIT, available_time=utc(2024, 1, 2))
        record = PaperAppliedCorporateActionRecord(action=action, applied_at=utc(2024, 1, 2))

        repo.record(record)
        fetched = repo.get(action.provenance.source_record_id)
        assert fetched is not None
        assert fetched.action == action
        assert fetched.applied_at == record.applied_at
        engine.close()

    def test_recording_the_same_action_twice_is_idempotent(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBPaperCorporateActionRepository(engine)
        action = make_corporate_action(action_type=CorporateActionType.DIVIDEND, available_time=utc(2024, 1, 2))
        record = PaperAppliedCorporateActionRecord(action=action, applied_at=utc(2024, 1, 2))

        repo.record(record)
        repo.record(record)
        assert len(repo.list_all()) == 1
        engine.close()

    def test_survives_restart(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBPaperCorporateActionRepository(engine)
        action = make_corporate_action(action_type=CorporateActionType.SPLIT, available_time=utc(2024, 1, 2))
        record = PaperAppliedCorporateActionRecord(action=action, applied_at=utc(2024, 1, 2))
        repo.record(record)
        engine.close()

        engine2 = new_engine(tmp_path)
        repo2 = DuckDBPaperCorporateActionRepository(engine2)
        assert repo2.get(action.provenance.source_record_id) == record
        engine2.close()

    def test_list_all_is_sorted_by_applied_at(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBPaperCorporateActionRepository(engine)
        later = make_corporate_action(
            action_type=CorporateActionType.SPLIT, available_time=utc(2024, 1, 5), source_record_id="CA-LATER",
        )
        earlier = make_corporate_action(
            action_type=CorporateActionType.SPLIT, available_time=utc(2024, 1, 2), source_record_id="CA-EARLIER",
        )
        repo.record(PaperAppliedCorporateActionRecord(action=later, applied_at=utc(2024, 1, 5)))
        repo.record(PaperAppliedCorporateActionRecord(action=earlier, applied_at=utc(2024, 1, 2)))

        records = repo.list_all()
        assert [r.applied_at for r in records] == [utc(2024, 1, 2), utc(2024, 1, 5)]
        engine.close()


class TestCorporateActionReplayOrdering:
    """ADR-0155: the core ordering hazard this task centers on --
    `backtest.portfolio.PortfolioAccounting.apply_split`/`apply_dividend`
    silently no-ops against a position that does not exist yet (or is
    currently flat), so `PaperTradingSession.restore()` must replay
    fills and corporate actions in ONE true chronological sequence, never
    as two separate batches -- and the persisted ledger must make an
    action's application survive a restart exactly once, never zero and
    never twice."""

    def test_buy_then_split_then_sell_replays_correctly_via_restore(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        order_repo = DuckDBPaperOrderRepository(engine)
        fill_repo = DuckDBPaperFillRepository(engine)
        status_repo = DuckDBOrderStatusEventRepository(engine)
        corp_repo = DuckDBPaperCorporateActionRepository(engine)

        config = make_paper_config(max_participation=1.0)
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2), volume=1_000_000.0)])
        session = PaperTradingSession(
            config, mds, order_repository=order_repo, fill_repository=fill_repo,
            status_repository=status_repo, corporate_action_repository=corp_repo,
        )

        buy = make_validated_order(client_order_id="CID-BUY", quantity=10.0, as_of_time=utc(2024, 1, 2))
        session.submit(buy, requested_at=utc(2024, 1, 2))
        session.advance(utc(2024, 1, 2))  # ADR-0154: deferred fill attempt lands here
        assert session.account_summary(as_of=utc(2024, 1, 2)).positions["AAA"].quantity == 10.0

        # A 2:1 split, replayed BETWEEN the BUY and the SELL below --
        # applying it at the wrong moment (e.g. before the BUY's own
        # fill is replayed) would silently no-op against a flat/absent
        # position and never retroactively apply.
        split = make_corporate_action(action_type=CorporateActionType.SPLIT, available_time=utc(2024, 1, 3))
        session.apply_corporate_actions([split], utc(2024, 1, 3))
        assert session.account_summary(as_of=utc(2024, 1, 3)).positions["AAA"].quantity == 20.0

        mds.register(make_bar(timestamp=utc(2024, 1, 4), available_time=utc(2024, 1, 4), volume=1_000_000.0))
        sell = make_validated_order(
            client_order_id="CID-SELL", side=OrderSide.SELL, quantity=20.0, as_of_time=utc(2024, 1, 4),
        )
        session.submit(sell, requested_at=utc(2024, 1, 4))
        session.advance(utc(2024, 1, 4))  # deferred fill attempt for the SELL

        before = session.account_summary(as_of=utc(2024, 1, 4))
        assert "AAA" not in before.positions  # fully sold out at the real, split-adjusted quantity
        engine.close()

        engine2 = new_engine(tmp_path)
        order_repo2 = DuckDBPaperOrderRepository(engine2)
        fill_repo2 = DuckDBPaperFillRepository(engine2)
        status_repo2 = DuckDBOrderStatusEventRepository(engine2)
        corp_repo2 = DuckDBPaperCorporateActionRepository(engine2)
        mds2 = InMemoryPaperMarketDataSource([
            make_bar(available_time=utc(2024, 1, 2), volume=1_000_000.0),
            make_bar(timestamp=utc(2024, 1, 4), available_time=utc(2024, 1, 4), volume=1_000_000.0),
        ])
        restored = PaperTradingSession.restore(
            config, mds2, order_repository=order_repo2, fill_repository=fill_repo2,
            status_repository=status_repo2, corporate_action_repository=corp_repo2,
            as_of=utc(2024, 1, 4),
        )
        after = restored.account_summary(as_of=utc(2024, 1, 4))

        assert after.cash == pytest.approx(before.cash)
        # The bug this replay ordering guards against: if the split had
        # been replayed as a separate first batch (before the BUY's own
        # fill), the SELL's real 20-share fill would be applied against
        # an un-split-adjusted 10-share position, driving quantity
        # negative instead of exactly zero.
        assert "AAA" not in after.positions
        engine2.close()

    def test_split_with_no_fill_ever_does_not_crash_or_create_a_spurious_position(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        order_repo = DuckDBPaperOrderRepository(engine)
        fill_repo = DuckDBPaperFillRepository(engine)
        status_repo = DuckDBOrderStatusEventRepository(engine)
        corp_repo = DuckDBPaperCorporateActionRepository(engine)

        config = make_paper_config(max_participation=1.0)
        mds = InMemoryPaperMarketDataSource([])
        session = PaperTradingSession(
            config, mds, order_repository=order_repo, fill_repository=fill_repo,
            status_repository=status_repo, corporate_action_repository=corp_repo,
        )

        # A split for a security this account never holds and never
        # trades at all -- available_time earlier than any fill this
        # store will ever have for it (there are none).
        split = make_corporate_action(
            security_id="BBB", action_type=CorporateActionType.SPLIT, available_time=utc(2024, 1, 2),
        )
        warnings = session.apply_corporate_actions([split], utc(2024, 1, 2))
        assert warnings == []  # SPLIT against an absent position is a silent, correct no-op, not a warning
        engine.close()

        engine2 = new_engine(tmp_path)
        order_repo2 = DuckDBPaperOrderRepository(engine2)
        fill_repo2 = DuckDBPaperFillRepository(engine2)
        status_repo2 = DuckDBOrderStatusEventRepository(engine2)
        corp_repo2 = DuckDBPaperCorporateActionRepository(engine2)
        mds2 = InMemoryPaperMarketDataSource([])
        restored = PaperTradingSession.restore(
            config, mds2, order_repository=order_repo2, fill_repository=fill_repo2,
            status_repository=status_repo2, corporate_action_repository=corp_repo2,
            as_of=utc(2024, 1, 2),
        )
        after = restored.account_summary(as_of=utc(2024, 1, 2))
        assert "BBB" not in after.positions  # never spuriously created by the replay
        assert after.cash == config.initial_cash  # untouched
        engine2.close()

    def test_the_same_action_is_never_applied_twice_across_two_separate_processes(self, tmp_path) -> None:
        """The core bug this task exists to prevent: two different daily
        cycle processes (each its own fresh `PaperBrokerAdapter`/
        `PaperTradingSession`) both see the SAME corporate action in
        their own lookback window -- it must be applied exactly once,
        ever, across both, never zero and never twice."""
        engine = new_engine(tmp_path)
        order_repo = DuckDBPaperOrderRepository(engine)
        fill_repo = DuckDBPaperFillRepository(engine)
        status_repo = DuckDBOrderStatusEventRepository(engine)
        corp_repo = DuckDBPaperCorporateActionRepository(engine)

        config = make_paper_config(max_participation=1.0)
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2), volume=1_000_000.0)])
        session1 = PaperTradingSession(
            config, mds, order_repository=order_repo, fill_repository=fill_repo,
            status_repository=status_repo, corporate_action_repository=corp_repo,
        )
        buy = make_validated_order(client_order_id="CID-BUY", quantity=10.0)
        session1.submit(buy, requested_at=utc(2024, 1, 2))
        session1.advance(utc(2024, 1, 2))

        split = make_corporate_action(action_type=CorporateActionType.SPLIT, available_time=utc(2024, 1, 3))
        session1.apply_corporate_actions([split], utc(2024, 1, 3))
        assert session1.account_summary(as_of=utc(2024, 1, 3)).positions["AAA"].quantity == 20.0
        engine.close()

        # "Process 2": a completely fresh engine/adapter/session, backed
        # by the SAME persisted store -- restore() replays the split
        # exactly once (correctly), then this process's own per-cycle
        # corporate-action step re-fetches the SAME action in its own
        # lookback window and calls apply_corporate_actions again, as a
        # real daily cycle's repeated 400-day lookback would.
        engine2 = new_engine(tmp_path)
        order_repo2 = DuckDBPaperOrderRepository(engine2)
        fill_repo2 = DuckDBPaperFillRepository(engine2)
        status_repo2 = DuckDBOrderStatusEventRepository(engine2)
        corp_repo2 = DuckDBPaperCorporateActionRepository(engine2)
        mds2 = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2), volume=1_000_000.0)])
        session2 = PaperTradingSession.restore(
            config, mds2, order_repository=order_repo2, fill_repository=fill_repo2,
            status_repository=status_repo2, corporate_action_repository=corp_repo2,
            as_of=utc(2024, 1, 3),
        )
        assert session2.account_summary(as_of=utc(2024, 1, 3)).positions["AAA"].quantity == 20.0

        warnings = session2.apply_corporate_actions([split], utc(2024, 1, 4))
        assert warnings == []
        quantity_after_second_apply = session2.account_summary(as_of=utc(2024, 1, 4)).positions["AAA"].quantity
        assert quantity_after_second_apply == 20.0  # NOT doubled to 40.0
        engine2.close()
