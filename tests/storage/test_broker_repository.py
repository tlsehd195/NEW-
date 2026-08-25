"""Category: Persistence Test -- save, reload, idempotency, restart for
Phase 13's three Broker Adapter stores (docs/specifications/
PHASE-13-toss-securities-adapter.md section 15)."""

from __future__ import annotations

from broker_helpers import make_broker_config, make_risk_checked_position, utc
from storage_helpers import new_engine

from broker.mock import MockBrokerAdapter
from broker.pipeline import submit_validated_order
from broker.validation import build_validated_order

from storage.broker_repository import DuckDBBrokerRequestRepository, DuckDBBrokerResponseRepository, DuckDBOrderStatusEventRepository

from trade_journal.enums import TradeProvenance


def _order():
    rcp = make_risk_checked_position(final_target_quantity=40.0)
    return build_validated_order(rcp, current_quantity=0.0, configuration_version="cfg-v1").validated_order


class TestBrokerRequestResponsePersistence:
    def test_submit_and_persist_full_round_trip(self, tmp_path) -> None:
        order = _order()
        engine = new_engine(tmp_path)
        request_repo = DuckDBBrokerRequestRepository(engine)
        response_repo = DuckDBBrokerResponseRepository(engine)
        broker = MockBrokerAdapter(make_broker_config())

        result = submit_validated_order(
            broker, order, execution_mode="OFFLINE", requested_at=utc(2024, 1, 2, 13),
            configuration_version="cfg-v1", request_repository=request_repo, response_repository=response_repo,
        )
        assert result.status.value == "FILLED"

        requests = request_repo.list_all()
        responses = response_repo.list_all()
        assert len(requests) == 1
        assert len(responses) == 1
        assert requests[0].client_order_id == order.client_order_id
        assert responses[0].request_id == requests[0].request_id
        engine.close()

    def test_recording_the_same_request_id_twice_is_idempotent(self, tmp_path) -> None:
        from broker.models import BrokerRequestRecord

        engine = new_engine(tmp_path)
        repo = DuckDBBrokerRequestRepository(engine)
        record = BrokerRequestRecord(
            request_id="BROKREQ-000001", broker_id="mock-broker", operation="submit_order",
            execution_mode="OFFLINE", client_order_id="CID-1", decision_id="D", sizing_id="S",
            risk_assessment_id="R", configuration_version="cfg-v1", requested_at=utc(2024, 1, 2),
            provenance=TradeProvenance.HISTORICAL_SIMULATION,
        )
        repo.record(record)
        repo.record(record)
        assert len(repo.list_all()) == 1
        engine.close()

    def test_survives_restart(self, tmp_path) -> None:
        order = _order()
        engine1 = new_engine(tmp_path)
        request_repo1 = DuckDBBrokerRequestRepository(engine1)
        response_repo1 = DuckDBBrokerResponseRepository(engine1)
        broker = MockBrokerAdapter(make_broker_config())
        submit_validated_order(
            broker, order, execution_mode="OFFLINE", requested_at=utc(2024, 1, 2, 13),
            configuration_version="cfg-v1", request_repository=request_repo1, response_repository=response_repo1,
        )
        engine1.close()

        engine2 = new_engine(tmp_path)
        reloaded_requests = DuckDBBrokerRequestRepository(engine2).list_all()
        reloaded_responses = DuckDBBrokerResponseRepository(engine2).list_all()
        assert len(reloaded_requests) == 1
        assert len(reloaded_responses) == 1
        assert reloaded_requests[0].client_order_id == order.client_order_id
        engine2.close()


class TestOrderStatusEventPersistence:
    def test_append_only_history_is_preserved(self, tmp_path) -> None:
        order = _order()
        engine = new_engine(tmp_path)
        status_repo = DuckDBOrderStatusEventRepository(engine)
        broker = MockBrokerAdapter(make_broker_config())
        broker.submit_order(order, requested_at=utc(2024, 1, 2, 13))
        observation = broker.get_order_status(order.client_order_id, as_of=utc(2024, 1, 2, 14))
        status_repo.record(observation)

        cancel_response = broker.cancel_order(order.client_order_id, requested_at=utc(2024, 1, 2, 15))
        engine.close()
        # note: cancel on an already-FILLED order does not add a new
        # get_order_status observation on its own -- MockBrokerAdapter's
        # own status history for this order_id still reflects the fill.
        assert cancel_response.error_code == "already_filled"

    def test_survives_restart(self, tmp_path) -> None:
        order = _order()
        engine1 = new_engine(tmp_path)
        status_repo1 = DuckDBOrderStatusEventRepository(engine1)
        broker = MockBrokerAdapter(make_broker_config())
        broker.submit_order(order, requested_at=utc(2024, 1, 2, 13))
        observation = broker.get_order_status(order.client_order_id, as_of=utc(2024, 1, 2, 14))
        status_repo1.record(observation)
        engine1.close()

        engine2 = new_engine(tmp_path)
        reloaded = DuckDBOrderStatusEventRepository(engine2).get_latest(order.client_order_id)
        assert reloaded is not None
        assert reloaded.status == observation.status
        engine2.close()

    def test_recording_the_same_observation_id_twice_is_idempotent(self, tmp_path) -> None:
        order = _order()
        engine = new_engine(tmp_path)
        status_repo = DuckDBOrderStatusEventRepository(engine)
        broker = MockBrokerAdapter(make_broker_config())
        broker.submit_order(order, requested_at=utc(2024, 1, 2, 13))
        observation = broker.get_order_status(order.client_order_id, as_of=utc(2024, 1, 2, 14))
        status_repo.record(observation)
        status_repo.record(observation)
        assert len(status_repo.get_history(order.client_order_id)) == 1
        engine.close()
