"""Category: Persistence Test -- save, reload, idempotency, restart for
Phase 12's three AI Gateway stores (docs/specifications/
PHASE-12-ai-gateway.md section 10)."""

from __future__ import annotations

from ai_gateway_helpers import make_gateway_config, make_provider_config, make_request, utc
from storage_helpers import new_engine

from ai_gateway.gateway import AIGateway
from ai_gateway.provider import MockProviderAdapter
from ai_gateway.quota_manager import QuotaManager
from ai_gateway.repository import InMemoryQuotaStateRepository

from storage.ai_gateway_repository import DuckDBAIRequestRepository, DuckDBAIResponseRepository, DuckDBQuotaStateRepository


class TestAIRequestPersistence:
    def test_record_and_get(self, tmp_path) -> None:
        request = make_request()
        engine = new_engine(tmp_path)
        repo = DuckDBAIRequestRepository(engine)
        repo.record(request)
        assert repo.get(request.request_id) == request
        engine.close()

    def test_recording_the_same_request_id_twice_is_idempotent(self, tmp_path) -> None:
        request = make_request()
        engine = new_engine(tmp_path)
        repo = DuckDBAIRequestRepository(engine)
        repo.record(request)
        repo.record(request)
        assert len(repo.list_all()) == 1
        engine.close()

    def test_survives_restart(self, tmp_path) -> None:
        request = make_request(response_schema=("action", "confidence"))
        engine1 = new_engine(tmp_path)
        DuckDBAIRequestRepository(engine1).record(request)
        engine1.close()

        engine2 = new_engine(tmp_path)
        reloaded = DuckDBAIRequestRepository(engine2).get(request.request_id)
        assert reloaded == request
        engine2.close()


class TestAIResponsePersistence:
    def _make_response(self):
        a = make_provider_config("a")
        config = make_gateway_config(a)
        qm = QuotaManager(InMemoryQuotaStateRepository())
        qm.initialize(a, at=utc(2024, 1, 1))
        gateway = AIGateway(config, {"a": MockProviderAdapter(a)}, qm)
        request = make_request()
        return request, gateway.generate(request, as_of=utc(2024, 1, 2))

    def test_record_and_get(self, tmp_path) -> None:
        _, response = self._make_response()
        engine = new_engine(tmp_path)
        repo = DuckDBAIResponseRepository(engine)
        repo.record(response)
        assert repo.get(response.response_id) == response
        engine.close()

    def test_get_by_request(self, tmp_path) -> None:
        request, response = self._make_response()
        engine = new_engine(tmp_path)
        repo = DuckDBAIResponseRepository(engine)
        repo.record(response)
        assert repo.get_by_request(request.request_id) == response
        engine.close()

    def test_recording_the_same_response_id_twice_is_idempotent(self, tmp_path) -> None:
        _, response = self._make_response()
        engine = new_engine(tmp_path)
        repo = DuckDBAIResponseRepository(engine)
        repo.record(response)
        repo.record(response)
        assert len(repo.list_all()) == 1
        engine.close()

    def test_survives_restart(self, tmp_path) -> None:
        _, response = self._make_response()
        engine1 = new_engine(tmp_path)
        DuckDBAIResponseRepository(engine1).record(response)
        engine1.close()

        engine2 = new_engine(tmp_path)
        reloaded = DuckDBAIResponseRepository(engine2).get(response.response_id)
        assert reloaded == response
        engine2.close()


class TestQuotaStatePersistence:
    def test_record_and_get_latest(self, tmp_path) -> None:
        a = make_provider_config("a")
        engine = new_engine(tmp_path)
        repo = DuckDBQuotaStateRepository(engine)
        qm = QuotaManager(repo)
        state = qm.initialize(a, at=utc(2024, 1, 1))
        assert repo.get_latest("a") == state
        engine.close()

    def test_append_only_history_is_preserved(self, tmp_path) -> None:
        a = make_provider_config("a")
        engine = new_engine(tmp_path)
        repo = DuckDBQuotaStateRepository(engine)
        qm = QuotaManager(repo)
        qm.initialize(a, at=utc(2024, 1, 1))
        qm.record_success("a", at=utc(2024, 1, 1, 13), usage=None)
        qm.mark_quota_exhausted("a", at=utc(2024, 1, 1, 14))
        history = repo.get_history("a")
        assert [s.reason for s in history] == ["initial", "success", "quota_exhausted"]
        engine.close()

    def test_survives_restart(self, tmp_path) -> None:
        a = make_provider_config("a")
        engine1 = new_engine(tmp_path)
        repo1 = DuckDBQuotaStateRepository(engine1)
        qm1 = QuotaManager(repo1)
        qm1.initialize(a, at=utc(2024, 1, 1))
        qm1.record_success("a", at=utc(2024, 1, 1, 13), usage=None)
        engine1.close()

        engine2 = new_engine(tmp_path)
        repo2 = DuckDBQuotaStateRepository(engine2)
        latest = repo2.get_latest("a")
        assert latest is not None
        assert latest.reason == "success"
        assert len(repo2.get_history("a")) == 2
        engine2.close()
