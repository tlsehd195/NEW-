"""Category: persistence, idempotency, provenance separation for the
persistent Experience Dataset (Phase 4 spec sections 13-15, Part C --
Paper Trading Data Foundation)."""

from __future__ import annotations

from journal_helpers import make_fill, make_order, utc

from backtest.portfolio import PortfolioView

from storage.config import StorageConfig
from storage.engine import StorageEngine
from storage.experience_repository import DuckDBExperienceRepository
from storage.trade_journal_repository import DuckDBTradeJournalRepository
from storage_helpers import new_engine

from trade_journal.enums import DecisionAction, TradeProvenance
from trade_journal.experience import build_experience_records


def _seed_one_trade(journal, provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION):
    order = make_order()
    decision = journal.record_decision(
        decision_time=order.decision_time, security_id="AAA", decision=DecisionAction.BUY, order=order,
        experiment_id="EXP-1",
        portfolio_state=PortfolioView(as_of_time=order.decision_time, cash=1000.0, positions={}, portfolio_value=1000.0),
    )
    journal.record_trade(
        decision_id=decision.snapshot_id, fill=make_fill(), position_after=10.0, experiment_id="EXP-1",
        provenance=provenance,
    )
    return build_experience_records(journal, provenance=provenance)


class TestExperienceRepository:
    def test_record_many_persists_and_round_trips(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        journal = DuckDBTradeJournalRepository(engine)
        records = _seed_one_trade(journal)
        xp_repo = DuckDBExperienceRepository(engine)

        written = xp_repo.record_many(records)
        assert written == 1

        reloaded = xp_repo.list_all()
        assert len(reloaded) == 1
        assert reloaded[0].experience_id == records[0].experience_id
        assert reloaded[0].provenance == TradeProvenance.HISTORICAL_SIMULATION
        assert reloaded[0].state["portfolio_state"] is not None
        engine.close()

    def test_record_many_is_idempotent(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        journal = DuckDBTradeJournalRepository(engine)
        records = _seed_one_trade(journal)
        xp_repo = DuckDBExperienceRepository(engine)
        xp_repo.record_many(records)
        second_write = xp_repo.record_many(records)
        assert second_write == 0
        assert len(xp_repo.list_all()) == 1
        engine.close()

    def test_survives_restart(self, tmp_path) -> None:
        config = StorageConfig(tmp_path / "store")
        engine1 = StorageEngine(config)
        journal1 = DuckDBTradeJournalRepository(engine1)
        records = _seed_one_trade(journal1)
        DuckDBExperienceRepository(engine1).record_many(records)
        engine1.close()

        engine2 = StorageEngine(config)
        reloaded = DuckDBExperienceRepository(engine2).list_all()
        assert len(reloaded) == 1
        engine2.close()

    def test_provenance_filter_never_mixes_categories(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        journal = DuckDBTradeJournalRepository(engine)
        xp_repo = DuckDBExperienceRepository(engine)

        hist_records = _seed_one_trade(journal, TradeProvenance.HISTORICAL_SIMULATION)
        xp_repo.record_many(hist_records)

        order2 = make_order(order_id="ORD-000002")
        decision2 = journal.record_decision(
            decision_time=order2.decision_time, security_id="BBB", decision=DecisionAction.BUY,
            order=order2, experiment_id="EXP-2",
        )
        journal.record_trade(
            decision_id=decision2.snapshot_id, fill=make_fill(order_id="ORD-000002", security_id="BBB"),
            position_after=10.0, experiment_id="EXP-2", provenance=TradeProvenance.PAPER_TRADING,
        )
        paper_records = build_experience_records(journal, provenance=TradeProvenance.PAPER_TRADING)
        xp_repo.record_many(paper_records)

        assert len(xp_repo.list_all(provenance=TradeProvenance.HISTORICAL_SIMULATION)) == 1
        assert len(xp_repo.list_all(provenance=TradeProvenance.PAPER_TRADING)) == 1
        assert len(xp_repo.list_all(provenance=TradeProvenance.LIVE_TRADING)) == 0
        assert len(xp_repo.list_all()) == 2
        engine.close()
