"""Category: Integration Test (Phase 18, instruction section 17) --
confirms Paper Trading -> Monitoring Collector -> Metrics still holds
after this phase's additions, using both the pre-existing generic
broker collector (Phase 14, unmodified) and the Phase 17 ACCOUNT
collector together in one place. Also documents, by omission, the
Phase 18 decision not to build a new Monitoring collector for the
Performance Report's own metrics (Sharpe/Sortino/Calmar/turnover/
transaction cost/slippage) -- see
docs/specifications/PHASE-18-paper-performance-and-validation.md
section on Monitoring for why: those are periodic evaluation-report
numbers, not continuously-observed component health signals, and do
not fit `ComponentHealth`'s health-status model without inventing a
new "is this Sharpe ratio healthy" threshold this project's own
discipline forbids inventing unilaterally."""

from __future__ import annotations

from datetime import datetime, timezone

from broker_helpers import make_risk_checked_position
from paper_helpers import make_bar, make_paper_config

from broker.paper.market_data import InMemoryPaperMarketDataSource
from broker.paper.session import PaperTradingSession
from broker.pipeline import submit_validated_order
from broker.validation import build_validated_order

from monitoring.collectors import collect_account, collect_broker
from monitoring.config import MonitoringConfig
from monitoring.enums import ComponentHealthStatus

from storage.broker_repository import DuckDBBrokerRequestRepository, DuckDBBrokerResponseRepository
from storage_helpers import new_engine

from trade_journal.enums import TradeProvenance


def utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


class TestPaperTradingReachesBothMonitoringCollectors:
    def test_broker_and_account_collectors_both_observe_the_same_paper_session(self, tmp_path) -> None:
        as_of = utc(2024, 1, 2)
        engine = new_engine(tmp_path)
        request_repo = DuckDBBrokerRequestRepository(engine)
        response_repo = DuckDBBrokerResponseRepository(engine)

        risk = make_risk_checked_position(risk_id="RISK-MON1", final_target_quantity=10.0, provenance=TradeProvenance.PAPER_TRADING)
        validation = build_validated_order(risk, current_quantity=0.0, configuration_version="cfg-v1")
        order = validation.validated_order

        config = make_paper_config(initial_cash=1_000_000.0, max_participation=1.0)
        mds = InMemoryPaperMarketDataSource([make_bar(security_id=order.security_id, available_time=as_of, volume=1_000_000.0)])
        session = PaperTradingSession(config, mds)

        submit_validated_order(
            session.adapter, order, execution_mode="PAPER", requested_at=as_of, configuration_version="cfg-v1",
            request_repository=request_repo, response_repository=response_repo,
        )
        session.adapter.accounting.mark_to_market({order.security_id: 100.0}, as_of)

        broker_event, broker_health = collect_broker(
            response_repo.list_all(), request_repo.list_all(), as_of_time=as_of, observed_at=as_of,
            config=MonitoringConfig(min_sample_count=1), event_id="MONEVT-MON1", health_id="HEALTH-MON1",
        )
        assert broker_health.status == ComponentHealthStatus.HEALTHY

        equity_history = [(p.as_of_time, p.portfolio_value) for p in session.adapter.accounting.value_series]
        account_event, account_health = collect_account(
            equity_history, initial_cash=1_000_000.0, as_of_time=as_of, observed_at=as_of,
            config=MonitoringConfig(min_sample_count=1), event_id="MONEVT-MON2", health_id="HEALTH-MON2",
        )
        assert account_event.metrics["latest_equity"] is not None
        engine.close()
