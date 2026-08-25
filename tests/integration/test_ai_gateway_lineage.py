"""Category: Integration Test -- AI Gateway request/response/quota-state
persist through the same DuckDB catalog Phase 4-11 already use,
SQL-joinable end to end, and survive a process restart
(docs/specifications/PHASE-12-ai-gateway.md section 10, 11).
"""

from __future__ import annotations

from ai_gateway_helpers import make_gateway_config, make_provider_config, make_request, utc
from storage_helpers import new_engine

from ai_gateway.enums import RequestStatus
from ai_gateway.gateway import AIGateway
from ai_gateway.provider import MockProviderAdapter
from ai_gateway.quota_manager import QuotaManager

from storage.ai_gateway_repository import (
    DuckDBAIRequestRepository,
    DuckDBAIResponseRepository,
    DuckDBQuotaStateRepository,
)


class TestAIGatewayLineageEndToEnd:
    def test_request_response_and_quota_history_are_joinable_and_survive_restart(self, tmp_path) -> None:
        a = make_provider_config("a", priority=0)
        b = make_provider_config("b", priority=1)
        config = make_gateway_config(a, b)

        engine = new_engine(tmp_path)
        quota_repo = DuckDBQuotaStateRepository(engine)
        request_repo = DuckDBAIRequestRepository(engine)
        response_repo = DuckDBAIResponseRepository(engine)

        qm = QuotaManager(quota_repo)
        qm.initialize(a, at=utc(2024, 1, 1))
        qm.initialize(b, at=utc(2024, 1, 1))
        # simulate A exhausted before this call -- failover to B, all persisted
        qm.mark_quota_exhausted("a", at=utc(2024, 1, 1, 13))

        adapters = {"a": MockProviderAdapter(a), "b": MockProviderAdapter(b)}
        gateway = AIGateway(
            config, adapters, qm, request_repository=request_repo, response_repository=response_repo,
        )
        request = make_request()
        response = gateway.generate(request, as_of=utc(2024, 1, 1, 14))
        assert response.status == RequestStatus.SUCCESS
        assert response.provider_id == "b"

        # -- SQL joinability: ai_requests <-> ai_responses <-> provider_quota_states --
        rows = engine.connection.execute(
            "SELECT r.request_id, resp.response_id, resp.provider_id, resp.status, "
            "(SELECT COUNT(*) FROM provider_quota_states q WHERE q.provider_id = resp.provider_id) as quota_observations "
            "FROM ai_requests r JOIN ai_responses resp ON resp.request_id = r.request_id "
            "WHERE r.request_id = ?",
            [request.request_id],
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][2] == "b"
        assert rows[0][3] == RequestStatus.SUCCESS.value
        assert rows[0][4] >= 2  # initial + success observation for provider b

        engine.close()

        # -- restart: reopen the same catalog file, everything is still there --
        engine2 = new_engine(tmp_path)
        reloaded_request = DuckDBAIRequestRepository(engine2).get(request.request_id)
        reloaded_response = DuckDBAIResponseRepository(engine2).get_by_request(request.request_id)
        reloaded_quota_a = DuckDBQuotaStateRepository(engine2).get_latest("a")
        assert reloaded_request == request
        assert reloaded_response == response
        assert reloaded_quota_a.reason == "quota_exhausted"
        engine2.close()

    def test_all_providers_exhausted_still_persists_a_safe_failure_response(self, tmp_path) -> None:
        a = make_provider_config("a", max_retries=0)
        config = make_gateway_config(a)

        engine = new_engine(tmp_path)
        quota_repo = DuckDBQuotaStateRepository(engine)
        request_repo = DuckDBAIRequestRepository(engine)
        response_repo = DuckDBAIResponseRepository(engine)

        qm = QuotaManager(quota_repo)
        qm.initialize(a, at=utc(2024, 1, 1))
        adapters = {"a": MockProviderAdapter(a, failure_mode="rate_limit")}
        gateway = AIGateway(
            config, adapters, qm, request_repository=request_repo, response_repository=response_repo,
        )
        request = make_request()
        response = gateway.generate(request, as_of=utc(2024, 1, 2))

        assert response.status != RequestStatus.SUCCESS
        assert response.content is None

        reloaded = DuckDBAIResponseRepository(engine).get(response.response_id)
        assert reloaded.status != RequestStatus.SUCCESS
        assert reloaded.content is None
        engine.close()
