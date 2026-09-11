"""Category: Restart-Safety Test -- `broker.pipeline`'s module-level
`_request_ids`/`_log_response_ids` id allocators must not collide with
already-persisted rows from a prior process (ADR-0117), the same class
of bug already fixed elsewhere this session (`ai_gateway.QuotaManager`,
`broker.paper.adapter`'s observation_id watermark,
`storage.data_repository`'s raw batch_id).
"""

from __future__ import annotations

from datetime import datetime, timezone

from storage_helpers import new_engine

from broker.config import BrokerConfig
from broker.mock import MockBrokerAdapter
from broker.models import BrokerRequestRecord, BrokerResponseRecord
from broker.pipeline import _IdAllocator, seed_broker_pipeline_ids, submit_validated_order
from broker.validation import build_validated_order

from risk.enums import RiskCheckStatus
from risk.models import RiskCheckedPosition

from storage.broker_repository import DuckDBBrokerRequestRepository, DuckDBBrokerResponseRepository

from trade_journal.enums import TradeProvenance


def utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _risk_checked(risk_id: str = "RISK-000001") -> RiskCheckedPosition:
    return RiskCheckedPosition(
        risk_id=risk_id, security_id="AAA", as_of_time=utc(2024, 3, 1), status=RiskCheckStatus.PASS,
        reason="normal_sizing", breached_limits=(), final_target_weight=0.10, final_target_quantity=40.0,
        sizing_id="SIZE-000001", decision_id="DEC-OUT-000001", prediction_id=None,
        risk_state=None, risk_version="test-v1", feature_version="test-v1",
        provenance=TradeProvenance.HISTORICAL_SIMULATION,
    )


class TestIdAllocatorAdvancePast:
    def test_advances_past_the_highest_matching_numeric_suffix(self) -> None:
        allocator = _IdAllocator("BROKREQ")
        allocator.advance_past(["BROKREQ-000001", "BROKREQ-000007", "BROKREQ-000003"])
        assert allocator.allocate() == "BROKREQ-000008"

    def test_ignores_ids_with_a_different_prefix(self) -> None:
        allocator = _IdAllocator("BROKREQ")
        allocator.advance_past(["BROKRESLOG-000099", "not-even-an-id"])
        assert allocator.allocate() == "BROKREQ-000001"

    def test_never_moves_backward(self) -> None:
        allocator = _IdAllocator("BROKREQ")
        allocator.advance_past(["BROKREQ-000010"])
        allocator.advance_past(["BROKREQ-000002"])  # a smaller/empty later call must not un-seed
        assert allocator.allocate() == "BROKREQ-000011"


class TestSeedBrokerPipelineIdsRestartSafety:
    def test_seeding_after_a_simulated_restart_avoids_colliding_with_a_stale_persisted_request(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        request_repo = DuckDBBrokerRequestRepository(engine)
        response_repo = DuckDBBrokerResponseRepository(engine)

        # A request/response a PRIOR process already persisted, sitting
        # at exactly "BROKREQ-000001"/"BROKRESLOG-000001" -- the id a
        # freshly-imported, unseeded in-process allocator would mint
        # next after a restart.
        stale_request = BrokerRequestRecord(
            request_id="BROKREQ-000001", broker_id="mock", operation="submit_order",
            execution_mode="PAPER", client_order_id="CID-STALE-FROM-PRIOR-PROCESS", decision_id="DEC-STALE",
            sizing_id="SIZE-STALE", risk_assessment_id="RISK-STALE", configuration_version="cfg-v1",
            requested_at=utc(2024, 1, 1), provenance=TradeProvenance.HISTORICAL_SIMULATION,
            payload={}, experiment_id=None,
        )
        request_repo.record(stale_request)
        response_repo.record(BrokerResponseRecord(
            response_id="BROKRESLOG-000001", request_id="BROKREQ-000001", broker_id="mock",
            operation="submit_order", status="FILLED", broker_order_id="BRK-STALE", error_code=None,
            attempt_count=1, latency_ms=10.0, responded_at=utc(2024, 1, 1),
            provenance=TradeProvenance.HISTORICAL_SIMULATION, metadata={}, experiment_id=None,
        ))

        seed_broker_pipeline_ids(request_repo, response_repo)

        broker_config = BrokerConfig()
        broker_adapter = MockBrokerAdapter(broker_config)
        validation = build_validated_order(_risk_checked(), current_quantity=0.0, configuration_version="cfg-v1")
        assert validation.validated_order is not None
        order = validation.validated_order

        submit_validated_order(
            broker_adapter, order, execution_mode=broker_config.execution_mode.value,
            requested_at=utc(2024, 3, 1, 13), configuration_version="cfg-v1",
            request_repository=request_repo, response_repository=response_repo,
        )

        persisted = request_repo.list_all()
        assert len(persisted) == 2, "the real new order's audit entry must not be silently dropped"
        new_rows = [r for r in persisted if r.request_id != "BROKREQ-000001"]
        assert len(new_rows) == 1
        assert new_rows[0].client_order_id == order.client_order_id
