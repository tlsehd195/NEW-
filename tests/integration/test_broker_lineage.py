"""Category: Integration Test -- Decision -> Risk -> Validated Order ->
Broker Submission -> Broker Order Status, persisted through the same
DuckDB catalog Phase 4-12 already use, SQL-joinable end to end, and
surviving a process restart (docs/specifications/
PHASE-13-toss-securities-adapter.md section 16).
"""

from __future__ import annotations

from datetime import datetime, timezone

from storage_helpers import new_engine

from broker.config import BrokerConfig
from broker.enums import BrokerOrderStatus
from broker.mock import MockBrokerAdapter
from broker.pipeline import submit_validated_order
from broker.validation import build_validated_order

from decision.models import DecisionOutput

from risk.enums import RiskCheckStatus
from risk.models import RiskCheckedPosition

from storage.broker_repository import DuckDBBrokerRequestRepository, DuckDBBrokerResponseRepository, DuckDBOrderStatusEventRepository
from storage.decision_repository import DuckDBDecisionRepository
from storage.risk_repository import DuckDBRiskRepository

from trade_journal.enums import DecisionAction, TradeProvenance


def utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


class TestDecisionToBrokerLineageEndToEnd:
    def test_full_chain_is_joinable_and_survives_restart(self, tmp_path) -> None:
        as_of = utc(2024, 3, 1)

        decision = DecisionOutput(
            decision_id="DEC-OUT-100001", security_id="AAA", as_of_time=as_of, action=DecisionAction.BUY,
            decision_reason="positive_expected_return_above_threshold", confidence=0.8, time_horizon_days=5,
            target_weight_hint=0.10, regime=None, prediction_id="PRED-100001", prediction_version="drift_v1",
            regime_version=None, feature_version="phase7_decision_features_v1", model_version=None,
            decision_version="baseline_rule_decision_agent_v1", data_version=(), provenance=TradeProvenance.HISTORICAL_SIMULATION,
        )
        risk = RiskCheckedPosition(
            risk_id="RISK-100001", security_id="AAA", as_of_time=as_of, status=RiskCheckStatus.PASS,
            reason="normal_sizing", breached_limits=(), final_target_weight=0.10, final_target_quantity=40.0,
            sizing_id="SIZE-100001", decision_id=decision.decision_id, prediction_id=decision.prediction_id,
            risk_state=None, risk_version="deterministic_portfolio_risk_engine_v1", feature_version="test_feature_v1",
            provenance=TradeProvenance.HISTORICAL_SIMULATION,
        )

        engine = new_engine(tmp_path)
        decision_repo = DuckDBDecisionRepository(engine)
        risk_repo = DuckDBRiskRepository(engine)
        request_repo = DuckDBBrokerRequestRepository(engine)
        response_repo = DuckDBBrokerResponseRepository(engine)
        status_repo = DuckDBOrderStatusEventRepository(engine)

        stored_decision = decision_repo.record(decision)
        stored_risk = risk_repo.record(risk)

        validation = build_validated_order(stored_risk, current_quantity=0.0, configuration_version="cfg-v1")
        assert validation.validated_order is not None
        order = validation.validated_order

        broker_config = BrokerConfig()
        broker_adapter = MockBrokerAdapter(broker_config)
        order_response = submit_validated_order(
            broker_adapter, order, execution_mode=broker_config.execution_mode.value, requested_at=utc(2024, 3, 1, 13),
            configuration_version="cfg-v1", request_repository=request_repo, response_repository=response_repo,
        )
        assert order_response.status == BrokerOrderStatus.FILLED

        status_observation = broker_adapter.get_order_status(order.client_order_id, as_of=utc(2024, 3, 1, 14))
        status_repo.record(status_observation)

        # -- SQL joinability: decision_outputs <-> risk_assessments <-> broker_requests <-> broker_responses <-> order_status_events --
        rows = engine.connection.execute(
            "SELECT d.decision_id, r.risk_id, req.request_id, resp.response_id, ev.status "
            "FROM decision_outputs d "
            "JOIN risk_assessments r ON r.decision_id = d.decision_id "
            "JOIN broker_requests req ON req.decision_id = d.decision_id AND req.risk_assessment_id = r.risk_id "
            "JOIN broker_responses resp ON resp.request_id = req.request_id "
            "JOIN order_status_events ev ON ev.client_order_id = req.client_order_id "
            "WHERE d.decision_id = ?",
            [stored_decision.decision_id],
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][4] == BrokerOrderStatus.FILLED.value

        engine.close()

        # -- restart: reopen the same catalog file, everything is still there --
        engine2 = new_engine(tmp_path)
        reloaded_response = DuckDBBrokerResponseRepository(engine2).get_by_request(
            DuckDBBrokerRequestRepository(engine2).list_all()[0].request_id
        )
        assert reloaded_response is not None
        assert reloaded_response.status == BrokerOrderStatus.FILLED.value
        reloaded_status = DuckDBOrderStatusEventRepository(engine2).get_latest(order.client_order_id)
        assert reloaded_status.status == BrokerOrderStatus.FILLED
        engine2.close()

    def test_broker_never_regenerates_decision_or_risk_from_scratch(self, tmp_path) -> None:
        """The broker layer only ever carries lineage ids forward -- it
        never recomputes `final_target_weight`/`final_target_quantity`
        or a `DecisionAction` of its own."""
        as_of = utc(2024, 3, 1)
        risk = RiskCheckedPosition(
            risk_id="RISK-200001", security_id="BBB", as_of_time=as_of, status=RiskCheckStatus.PASS,
            reason="normal_sizing", breached_limits=(), final_target_weight=0.05, final_target_quantity=15.0,
            sizing_id="SIZE-200001", decision_id="DEC-OUT-200001", prediction_id="PRED-200001",
            risk_state=None, risk_version="v1", feature_version="v1", provenance=TradeProvenance.HISTORICAL_SIMULATION,
        )
        validation = build_validated_order(risk, current_quantity=0.0, configuration_version="cfg-v1")
        order = validation.validated_order
        assert order.quantity == risk.final_target_quantity  # carried forward exactly, not recomputed
        assert order.decision_id == risk.decision_id
        assert order.risk_assessment_id == risk.risk_id
