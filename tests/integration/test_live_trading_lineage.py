"""Category: Integration Test -- Risk -> ValidatedOrder -> Live Safety
Gate -> LiveTradingSession -> simulated Fill -> Trade Journal
(`TradeProvenance.LIVE_TRADING`) -> Monitoring, persisted through the
same DuckDB catalog Phase 4-15 already use, SQL-joinable end to end, and
surviving a process restart (docs/specifications/
PHASE-16-live-trading.md section 15).

Uses `broker.mock.MockBrokerAdapter` throughout -- never the one real,
network-capable transport implementation under `broker.toss.transport`
(instruction section 22, 37): this test proves the Live Trading *safety
infrastructure* end to end, not a real order against a real account,
which no automated test in this repository may ever attempt.
"""

from __future__ import annotations

from broker_helpers import make_risk_checked_position
from live_helpers import make_approval, make_broker_capabilities, make_live_config, utc
from storage_helpers import new_engine

from broker.config import BrokerConfig
from broker.enums import BrokerCapability, BrokerOrderStatus, OrderValidationStatus
from broker.live.journal import build_fill_from_broker_response, build_trade_record
from broker.live.reconciliation import compare_account
from broker.live.safety_gate import SafetyGateContext, evaluate_safety_gate
from broker.live.session import LiveTradingSession
from broker.mock import MockBrokerAdapter
from broker.validation import build_validated_order

from monitoring.collectors import collect_broker
from monitoring.config import MonitoringConfig
from monitoring.enums import ComponentHealthStatus

from storage.broker_repository import DuckDBBrokerRequestRepository, DuckDBBrokerResponseRepository
from storage.live_repository import DuckDBKillSwitchRepository, DuckDBReconciliationRepository
from storage.risk_repository import DuckDBRiskRepository
from storage.trade_journal_repository import DuckDBTradeJournalRepository

from broker.pipeline import submit_validated_order

from trade_journal.enums import TradeProvenance


class TestRiskToLiveTradingLineageEndToEnd:
    def test_full_chain_is_joinable_and_survives_restart(self, tmp_path) -> None:
        as_of = utc(2024, 3, 1)
        risk = make_risk_checked_position(
            risk_id="RISK-700001", final_target_quantity=20.0, provenance=TradeProvenance.LIVE_TRADING,
        )

        engine = new_engine(tmp_path)
        risk_repo = DuckDBRiskRepository(engine)
        request_repo = DuckDBBrokerRequestRepository(engine)
        response_repo = DuckDBBrokerResponseRepository(engine)
        kill_switch_repo = DuckDBKillSwitchRepository(engine)
        reconciliation_repo = DuckDBReconciliationRepository(engine)
        journal_repo = DuckDBTradeJournalRepository(engine)

        stored_risk = risk_repo.record(risk)
        validation = build_validated_order(stored_risk, current_quantity=0.0, configuration_version="cfg-v1")
        assert validation.validated_order is not None
        order = validation.validated_order
        assert order.provenance == TradeProvenance.LIVE_TRADING

        adapter = MockBrokerAdapter(BrokerConfig(broker_id="toss"))
        # Phase 22: evaluate_safety_gate now requires max_daily_loss/
        # max_order_frequency_per_hour to be set (Option B, LIVE-RISK-POLICY.md).
        session = LiveTradingSession(
            make_live_config(live_trading_enabled=True, max_daily_loss=2000.0, max_order_frequency_per_hour=6), adapter,
            kill_switch_repository=kill_switch_repo, reconciliation_repository=reconciliation_repo,
        )

        gate_context = SafetyGateContext(
            as_of_time=as_of, config=session.config, approval=make_approval(),
            required_capabilities=(BrokerCapability.MARKET_ORDER,),
            broker_capabilities=adapter.get_capabilities(as_of=as_of),
            risk_health=ComponentHealthStatus.HEALTHY, order_validation_status=validation.status,
            kill_switch_engaged=session.is_kill_switch_engaged(), account_state_known=True,
            position_state_known=True, model_state_valid=True, configuration_integrity_valid=True,
        )
        gate_result = evaluate_safety_gate(gate_context)
        assert gate_result.passed is True

        response = submit_validated_order(
            adapter, order, execution_mode="LIVE", requested_at=as_of, configuration_version="cfg-v1",
            request_repository=request_repo, response_repository=response_repo,
        )
        assert response.status == BrokerOrderStatus.FILLED

        # -- Trade Journal, provenance LIVE_TRADING --
        fill = build_fill_from_broker_response(response, security_id=order.security_id, side=order.side, decision_time=order.as_of_time)
        trade = journal_repo.record_trade(decision_id=order.decision_id, fill=fill, position_after=order.quantity, provenance=TradeProvenance.LIVE_TRADING)
        assert trade.provenance == TradeProvenance.LIVE_TRADING

        # -- Monitoring: Phase 14's generic broker collector, unmodified --
        monitoring_config = MonitoringConfig(min_sample_count=1)
        event, health = collect_broker(
            response_repo.list_all(), request_repo.list_all(), as_of_time=as_of, observed_at=as_of,
            config=monitoring_config, event_id="MONEVT-700001", health_id="HEALTH-700001",
        )
        assert health.status == ComponentHealthStatus.HEALTHY

        # -- Reconciliation: internal cash vs. broker's own account snapshot --
        account_snapshot = adapter.get_account(as_of=as_of)
        internal_cash = 100_000.0 - order.quantity * 100.0  # MockBrokerAdapter's own deterministic fill_price
        reconciliation = compare_account(
            internal_cash, account_snapshot, tolerance=0.01, reconciliation_id="RECON-700001", as_of_time=as_of,
            configuration_version=session.config.configuration_version(),
        )
        reconciliation_repo.record(reconciliation)
        assert reconciliation.status.value == "MATCHED"

        # -- SQL joinability: risk_assessments <-> broker_requests <-> trades --
        rows = engine.connection.execute(
            "SELECT r.risk_id, req.request_id, t.trade_id FROM risk_assessments r "
            "JOIN broker_requests req ON req.risk_assessment_id = r.risk_id "
            "JOIN trades t ON t.order_id = req.client_order_id "
            "WHERE r.risk_id = ?",
            [stored_risk.risk_id],
        ).fetchall()
        assert len(rows) == 1

        engine.close()

        # -- restart: reopen the same catalog file, everything is still there --
        engine2 = new_engine(tmp_path)
        assert DuckDBKillSwitchRepository(engine2).get_latest() is None  # never engaged this test
        reloaded_reconciliation = DuckDBReconciliationRepository(engine2).get_latest("account", "toss")
        assert reloaded_reconciliation.status.value == "MATCHED"
        reloaded_trade = DuckDBTradeJournalRepository(engine2).get_trade(trade.trade_id)
        assert reloaded_trade.provenance == TradeProvenance.LIVE_TRADING
        engine2.close()

    def test_toss_real_capabilities_block_the_gate_end_to_end(self, tmp_path) -> None:
        """Direct integration-level proof of ADR-0022 decision 2 -- even
        with a fully-built ValidatedOrder and every other condition
        satisfied, Toss's own honestly-reported capability gaps (Phase
        13) block Live submission before any broker call is attempted."""
        from broker.capabilities import build_capabilities
        from broker.enums import CapabilityStatus

        as_of = utc(2024, 3, 1)
        risk = make_risk_checked_position(risk_id="RISK-800001", final_target_quantity=20.0, provenance=TradeProvenance.LIVE_TRADING)
        validation = build_validated_order(risk, current_quantity=0.0, configuration_version="cfg-v1")
        order = validation.validated_order

        toss_capabilities = build_capabilities(
            "toss",
            {
                BrokerCapability.MARKET_ORDER: CapabilityStatus.ENABLED,
                BrokerCapability.ACCOUNT_BALANCE: CapabilityStatus.UNKNOWN,
                BrokerCapability.POSITIONS: CapabilityStatus.UNKNOWN,
            },
            recorded_at=as_of,
        )
        gate_context = SafetyGateContext(
            as_of_time=as_of, config=make_live_config(live_trading_enabled=True), approval=make_approval(),
            required_capabilities=(BrokerCapability.MARKET_ORDER, BrokerCapability.ACCOUNT_BALANCE, BrokerCapability.POSITIONS),
            broker_capabilities=toss_capabilities, risk_health=ComponentHealthStatus.HEALTHY,
            order_validation_status=validation.status, kill_switch_engaged=False, account_state_known=True,
            position_state_known=True, model_state_valid=True, configuration_integrity_valid=True,
        )
        result = evaluate_safety_gate(gate_context)
        assert result.passed is False
        assert "broker_capability_not_verified_account_balance" in result.failed_conditions
        assert order is not None  # the order itself was built fine -- the gate, not validation, is what blocks
