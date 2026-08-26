"""Category: Integration Test -- Risk -> ValidatedOrder -> PaperBrokerAdapter
-> simulated Fill -> Trade Journal (`TradeProvenance.PAPER_TRADING`) ->
Monitoring, persisted through the same DuckDB catalog Phase 4-14 already
use, SQL-joinable end to end, and surviving a process restart
(docs/specifications/PHASE-15-paper-trading.md section 16).

Deliberately reuses Phase 8's `RiskCheckedPosition`, Phase 13's
`build_validated_order`/`submit_validated_order`, Phase 3's
`DuckDBTradeJournalRepository.record_trade`, and Phase 14's
`monitoring.collectors.collect_broker` completely unmodified --
Paper Trading is "just another broker_id" from every one of those
layers' point of view (instruction section 4, 23, 24, 28).
"""

from __future__ import annotations

from broker_helpers import make_risk_checked_position
from paper_helpers import make_bar, make_paper_config, utc
from storage_helpers import new_engine

from broker.enums import BrokerOrderStatus
from broker.paper.config import PaperTradingConfig
from broker.paper.market_data import InMemoryPaperMarketDataSource
from broker.paper.session import PaperTradingSession
from broker.pipeline import submit_validated_order
from broker.validation import build_validated_order

from monitoring.collectors import collect_broker
from monitoring.config import MonitoringConfig
from monitoring.enums import ComponentHealthStatus

from storage.broker_repository import DuckDBBrokerRequestRepository, DuckDBBrokerResponseRepository, DuckDBOrderStatusEventRepository
from storage.paper_repository import DuckDBPaperFillRepository, DuckDBPaperOrderRepository
from storage.risk_repository import DuckDBRiskRepository
from storage.trade_journal_repository import DuckDBTradeJournalRepository

from trade_journal.enums import TradeProvenance


class TestRiskToPaperTradingLineageEndToEnd:
    def test_full_chain_is_joinable_and_survives_restart(self, tmp_path) -> None:
        as_of = utc(2024, 3, 1)
        risk = make_risk_checked_position(
            risk_id="RISK-500001", final_target_quantity=40.0, provenance=TradeProvenance.PAPER_TRADING,
        )

        engine = new_engine(tmp_path)
        risk_repo = DuckDBRiskRepository(engine)
        request_repo = DuckDBBrokerRequestRepository(engine)
        response_repo = DuckDBBrokerResponseRepository(engine)
        status_repo = DuckDBOrderStatusEventRepository(engine)
        order_repo = DuckDBPaperOrderRepository(engine)
        fill_repo = DuckDBPaperFillRepository(engine)
        journal_repo = DuckDBTradeJournalRepository(engine)

        stored_risk = risk_repo.record(risk)

        validation = build_validated_order(stored_risk, current_quantity=0.0, configuration_version="cfg-v1")
        assert validation.validated_order is not None
        order = validation.validated_order
        assert order.provenance == TradeProvenance.PAPER_TRADING

        config = PaperTradingConfig(initial_cash=1_000_000.0, max_participation=1.0)
        mds = InMemoryPaperMarketDataSource([make_bar(security_id=order.security_id, available_time=as_of, volume=1_000_000.0)])
        session = PaperTradingSession(
            config, mds, order_repository=order_repo, fill_repository=fill_repo, status_repository=status_repo,
        )

        order_response = submit_validated_order(
            session.adapter, order, execution_mode="PAPER", requested_at=as_of, configuration_version="cfg-v1",
            request_repository=request_repo, response_repository=response_repo,
        )
        assert order_response.status == BrokerOrderStatus.FILLED

        fills = session.capture(order.client_order_id, as_of=as_of)
        assert len(fills) == 1

        trade = journal_repo.record_trade(
            decision_id=order.decision_id, fill=fills[0].fill, position_after=order.quantity,
            provenance=TradeProvenance.PAPER_TRADING,
        )
        assert trade.provenance == TradeProvenance.PAPER_TRADING

        # -- Monitoring: the generic Phase 14 broker collector, unmodified,
        # already understands Paper Trading's broker_requests/broker_responses --
        monitoring_config = MonitoringConfig(min_sample_count=1)
        event, health = collect_broker(
            response_repo.list_all(), request_repo.list_all(), as_of_time=as_of, observed_at=as_of,
            config=monitoring_config, event_id="MONEVT-500001", health_id="HEALTH-500001",
        )
        assert health.status == ComponentHealthStatus.HEALTHY
        assert event.metrics["count"] == 1.0

        # -- SQL joinability: risk_assessments <-> broker_requests <-> paper_fills --
        rows = engine.connection.execute(
            "SELECT r.risk_id, req.request_id, pf.fill_id FROM risk_assessments r "
            "JOIN broker_requests req ON req.risk_assessment_id = r.risk_id "
            "JOIN paper_fills pf ON pf.client_order_id = req.client_order_id "
            "WHERE r.risk_id = ?",
            [stored_risk.risk_id],
        ).fetchall()
        assert len(rows) == 1

        engine.close()

        # -- restart: reopen the same catalog file, everything is still there --
        engine2 = new_engine(tmp_path)
        reloaded_order = DuckDBPaperOrderRepository(engine2).get(order.client_order_id)
        assert reloaded_order is not None
        assert reloaded_order.initial_status == BrokerOrderStatus.PENDING
        reloaded_fills = DuckDBPaperFillRepository(engine2).get_history(order.client_order_id)
        assert len(reloaded_fills) == 1
        reloaded_status = DuckDBOrderStatusEventRepository(engine2).get_latest(order.client_order_id)
        assert reloaded_status.status == BrokerOrderStatus.FILLED
        reloaded_trade = DuckDBTradeJournalRepository(engine2).get_trade(trade.trade_id)
        assert reloaded_trade.provenance == TradeProvenance.PAPER_TRADING
        engine2.close()

    def test_paper_never_regenerates_risk_or_decision_of_its_own(self, tmp_path) -> None:
        """`broker.paper.*` only ever carries lineage ids forward -- it
        never recomputes `final_target_weight`/`final_target_quantity`
        or a `DecisionAction` of its own (mirrors
        `test_broker_lineage.py::test_broker_never_regenerates_decision_or_risk_from_scratch`,
        Phase 13)."""
        risk = make_risk_checked_position(risk_id="RISK-600001", final_target_quantity=15.0, provenance=TradeProvenance.PAPER_TRADING)
        validation = build_validated_order(risk, current_quantity=0.0, configuration_version="cfg-v1")
        order = validation.validated_order
        assert order.quantity == risk.final_target_quantity  # carried forward exactly, not recomputed
        assert order.decision_id == risk.decision_id
        assert order.risk_assessment_id == risk.risk_id
