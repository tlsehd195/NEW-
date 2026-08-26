"""Category: persistence, restart, idempotency, immutability, provenance,
version lineage, correction/audit for the persistent Trade Journal
(Phase 4 spec section 16). Mirrors the Phase 3 in-memory test categories
(tests/trade_journal/) against DuckDBTradeJournalRepository."""

from __future__ import annotations

import dataclasses

import pytest
from journal_helpers import make_fill, make_order, utc

from storage.config import StorageConfig
from storage.engine import StorageEngine
from storage.trade_journal_repository import DuckDBTradeJournalRepository
from storage_helpers import new_engine

from trade_journal.enums import CorrectionTargetType, DecisionAction, TradeProvenance


class TestPersistenceAndRestart:
    def test_decision_and_trade_survive_restart(self, tmp_path) -> None:
        config = StorageConfig(tmp_path / "store")
        engine1 = StorageEngine(config)
        journal1 = DuckDBTradeJournalRepository(engine1)

        order = make_order()
        decision = journal1.record_decision(
            decision_time=order.decision_time, security_id="AAA", decision=DecisionAction.BUY,
            order=order, experiment_id="EXP-1", strategy_version="test_v1",
        )
        fill = make_fill()
        trade = journal1.record_trade(
            decision_id=decision.snapshot_id, fill=fill, position_after=10.0, experiment_id="EXP-1",
        )
        engine1.close()

        engine2 = StorageEngine(config)
        journal2 = DuckDBTradeJournalRepository(engine2)
        reloaded_decision = journal2.get_decision(decision.snapshot_id)
        reloaded_trade = journal2.get_trade(trade.trade_id)
        assert reloaded_decision is not None and reloaded_decision.security_id == "AAA"
        assert reloaded_trade is not None and reloaded_trade.execution_price == fill.price
        assert reloaded_trade.fill == fill
        engine2.close()


class TestIdempotency:
    def test_recording_same_order_twice_does_not_duplicate(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        journal = DuckDBTradeJournalRepository(engine)
        order = make_order()
        d1 = journal.record_decision(
            decision_time=order.decision_time, security_id="AAA", decision=DecisionAction.BUY,
            order=order, experiment_id="EXP-1",
        )
        d2 = journal.record_decision(
            decision_time=order.decision_time, security_id="AAA", decision=DecisionAction.BUY,
            order=order, experiment_id="EXP-1",
        )
        assert d1.snapshot_id == d2.snapshot_id
        assert len(journal.list_decisions()) == 1
        engine.close()

    def test_recording_same_fill_twice_does_not_duplicate(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        journal = DuckDBTradeJournalRepository(engine)
        order = make_order()
        decision = journal.record_decision(
            decision_time=order.decision_time, security_id="AAA", decision=DecisionAction.BUY,
            order=order, experiment_id="EXP-1",
        )
        fill = make_fill()
        t1 = journal.record_trade(decision_id=decision.snapshot_id, fill=fill, position_after=10.0, experiment_id="EXP-1")
        t2 = journal.record_trade(decision_id=decision.snapshot_id, fill=fill, position_after=10.0, experiment_id="EXP-1")
        assert t1.trade_id == t2.trade_id
        assert len(journal.list_trades()) == 1
        engine.close()

    def test_two_distinct_partial_fills_of_the_same_order_are_both_recorded(self, tmp_path) -> None:
        """Phase 17 Production Safety Review regression test (DuckDB
        backend) -- mirrors tests/trade_journal/test_idempotency.py::
        test_two_distinct_partial_fills_of_the_same_order_are_not_deduplicated_against_each_other."""
        from dataclasses import replace

        engine = new_engine(tmp_path)
        journal = DuckDBTradeJournalRepository(engine)
        order = make_order()
        decision = journal.record_decision(
            decision_time=order.decision_time, security_id="AAA", decision=DecisionAction.BUY,
            order=order, experiment_id="EXP-1",
        )
        first_fill = make_fill(quantity=100.0, execution_time=utc(2024, 1, 2))
        second_fill = replace(first_fill, quantity=50.0, execution_time=utc(2024, 1, 3))
        t1 = journal.record_trade(decision_id=decision.snapshot_id, fill=first_fill, position_after=100.0, experiment_id="EXP-1")
        t2 = journal.record_trade(decision_id=decision.snapshot_id, fill=second_fill, position_after=150.0, experiment_id="EXP-1")
        assert t1.trade_id != t2.trade_id
        assert len(journal.list_trades()) == 2
        engine.close()


class TestImmutability:
    def test_decision_snapshot_is_frozen(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        journal = DuckDBTradeJournalRepository(engine)
        order = make_order()
        decision = journal.record_decision(
            decision_time=order.decision_time, security_id="AAA", decision=DecisionAction.BUY, order=order,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            decision.security_id = "BBB"  # type: ignore[misc]
        engine.close()

    def test_no_update_or_delete_method_exists(self) -> None:
        methods = {name for name in dir(DuckDBTradeJournalRepository) if not name.startswith("_")}
        assert not any(name.startswith("update_") or name.startswith("delete_") for name in methods)

    def test_mutating_source_object_after_recording_does_not_change_stored_snapshot(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        journal = DuckDBTradeJournalRepository(engine)
        order = make_order()
        portfolio_state_dict = {"note": "captured"}
        decision = journal.record_decision(
            decision_time=order.decision_time, security_id="AAA", decision=DecisionAction.BUY,
            order=order, market_state=portfolio_state_dict,
        )
        portfolio_state_dict["note"] = "mutated after recording"
        reloaded = journal.get_decision(decision.snapshot_id)
        assert reloaded.market_state == {"note": "captured"}
        engine.close()


class TestProvenanceSeparation:
    def test_list_trades_filters_by_provenance(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        journal = DuckDBTradeJournalRepository(engine)
        order1 = make_order(order_id="ORD-000001")
        d1 = journal.record_decision(
            decision_time=order1.decision_time, security_id="AAA", decision=DecisionAction.BUY, order=order1,
            experiment_id="EXP-1",
        )
        journal.record_trade(
            decision_id=d1.snapshot_id, fill=make_fill(order_id="ORD-000001"), position_after=10.0,
            experiment_id="EXP-1", provenance=TradeProvenance.HISTORICAL_SIMULATION,
        )
        order2 = make_order(order_id="ORD-000002")
        d2 = journal.record_decision(
            decision_time=order2.decision_time, security_id="AAA", decision=DecisionAction.BUY, order=order2,
            experiment_id="EXP-2",
        )
        journal.record_trade(
            decision_id=d2.snapshot_id, fill=make_fill(order_id="ORD-000002"), position_after=10.0,
            experiment_id="EXP-2", provenance=TradeProvenance.PAPER_TRADING,
        )

        historical = journal.list_trades(provenance=TradeProvenance.HISTORICAL_SIMULATION)
        paper = journal.list_trades(provenance=TradeProvenance.PAPER_TRADING)
        live = journal.list_trades(provenance=TradeProvenance.LIVE_TRADING)
        assert len(historical) == 1 and len(paper) == 1 and len(live) == 0
        assert historical[0].order_id != paper[0].order_id
        engine.close()


class TestVersionLineage:
    def test_strategy_and_execution_version_round_trip(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        journal = DuckDBTradeJournalRepository(engine)
        order = make_order()
        decision = journal.record_decision(
            decision_time=order.decision_time, security_id="AAA", decision=DecisionAction.BUY, order=order,
            strategy_version="simple_momentum_v1", execution_version="phase2_backtest_engine_v1",
            data_version=("dv-1", "dv-2"),
        )
        reloaded = journal.get_decision(decision.snapshot_id)
        assert reloaded.strategy_version == "simple_momentum_v1"
        assert reloaded.execution_version == "phase2_backtest_engine_v1"
        assert reloaded.data_version == ("dv-1", "dv-2")
        engine.close()


class TestCorrectionAndAuditTrail:
    def test_correction_is_additive_and_original_is_unchanged(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        journal = DuckDBTradeJournalRepository(engine)
        order = make_order()
        decision = journal.record_decision(
            decision_time=order.decision_time, security_id="AAA", decision=DecisionAction.BUY, order=order,
            experiment_id="EXP-1",
        )
        trade = journal.record_trade(
            decision_id=decision.snapshot_id, fill=make_fill(), position_after=10.0, experiment_id="EXP-1",
        )
        journal.record_correction(
            CorrectionTargetType.TRADE, trade.trade_id, "manual audit fix",
            {"realized_pnl": 5.0}, utc(2024, 1, 5),
        )
        original = journal.get_trade(trade.trade_id)
        assert original.realized_pnl is None  # untouched
        corrections = journal.get_corrections(trade.trade_id)
        assert len(corrections) == 1
        assert corrections[0].reason == "manual audit fix"
        engine.close()

    def test_correction_requires_a_reason(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        journal = DuckDBTradeJournalRepository(engine)
        with pytest.raises(ValueError):
            journal.record_correction(CorrectionTargetType.TRADE, "TRD-000001", "", {}, utc(2024, 1, 5))
        engine.close()

    def test_audit_trail_composes_decision_trade_and_corrections(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        journal = DuckDBTradeJournalRepository(engine)
        order = make_order()
        decision = journal.record_decision(
            decision_time=order.decision_time, security_id="AAA", decision=DecisionAction.BUY, order=order,
            experiment_id="EXP-1",
        )
        trade = journal.record_trade(
            decision_id=decision.snapshot_id, fill=make_fill(), position_after=10.0, experiment_id="EXP-1",
        )
        journal.record_post_trade_analysis(trade.trade_id, execution_error=0.0012)
        journal.record_correction(
            CorrectionTargetType.TRADE, trade.trade_id, "audit", {"x": 1}, utc(2024, 1, 5)
        )
        trail = journal.audit_trail(trade.trade_id)
        assert trail.decision.snapshot_id == decision.snapshot_id
        assert trail.trade.trade_id == trade.trade_id
        assert trail.post_trade_analysis.execution_error == 0.0012
        assert len(trail.corrections) == 1
        engine.close()
