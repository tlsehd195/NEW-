"""Category: Gateway / Fail-Closed Test -- PROJECT_MASTER_PLAN.md section
6.5's required scenarios (Provider A success; A exhausted -> B; A/B/C all
fail -> NO AI CALL safe failure; A quota reset -> priority reverts;
billing detected -> disabled) plus timeout/malformed/missing-config
handling from section 5.3."""

from __future__ import annotations

from ai_gateway_helpers import make_gateway_config, make_provider_config, make_request, utc

from ai_gateway.enums import RequestStatus, TaskTier
from ai_gateway.gateway import AIGateway
from ai_gateway.provider import MockProviderAdapter
from ai_gateway.quota_manager import QuotaManager
from ai_gateway.repository import InMemoryAIRequestRepository, InMemoryAIResponseRepository, InMemoryQuotaStateRepository


def _build(*provider_configs, adapters_by_id=None):
    config = make_gateway_config(*provider_configs) if provider_configs else make_gateway_config()
    provider_configs = provider_configs or config.providers
    qrepo = InMemoryQuotaStateRepository()
    qm = QuotaManager(qrepo)
    for p in provider_configs:
        qm.initialize(p, at=utc(2024, 1, 1))
    adapters = adapters_by_id or {p.provider_id: MockProviderAdapter(p) for p in provider_configs}
    request_repo = InMemoryAIRequestRepository()
    response_repo = InMemoryAIResponseRepository()
    gateway = AIGateway(config, adapters, qm, request_repository=request_repo, response_repository=response_repo)
    return gateway, qm, request_repo, response_repo


class TestHappyPath:
    def test_single_healthy_provider_succeeds(self) -> None:
        a = make_provider_config("a")
        gateway, *_ = _build(a)
        response = gateway.generate(make_request(), as_of=utc(2024, 1, 2))
        assert response.status == RequestStatus.SUCCESS
        assert response.provider_id == "a"
        assert response.content is not None
        assert response.error_reason is None

    def test_request_and_response_are_logged(self) -> None:
        a = make_provider_config("a")
        gateway, _qm, request_repo, response_repo = _build(a)
        request = make_request()
        response = gateway.generate(request, as_of=utc(2024, 1, 2))
        assert request_repo.get(request.request_id) == request
        assert response_repo.get(response.response_id) == response
        assert response_repo.get_by_request(request.request_id) == response


class TestFailoverRotation:
    def test_provider_a_quota_exhausted_switches_to_b(self) -> None:
        a = make_provider_config("a", priority=0)
        b = make_provider_config("b", priority=1)
        gateway, qm, *_ = _build(a, b)
        qm.mark_quota_exhausted("a", at=utc(2024, 1, 1, 13))
        response = gateway.generate(make_request(), as_of=utc(2024, 1, 1, 14))
        assert response.status == RequestStatus.SUCCESS
        assert response.provider_id == "b"

    def test_a_and_b_both_fail_moves_to_c(self) -> None:
        a = make_provider_config("a", priority=0, max_retries=0)
        b = make_provider_config("b", priority=1, max_retries=0)
        c = make_provider_config("c", priority=2, max_retries=0)
        adapters = {
            "a": MockProviderAdapter(a, failure_mode="rate_limit"),
            "b": MockProviderAdapter(b, failure_mode="timeout"),
            "c": MockProviderAdapter(c),
        }
        gateway, *_ = _build(a, b, c, adapters_by_id=adapters)
        response = gateway.generate(make_request(), as_of=utc(2024, 1, 2))
        assert response.status == RequestStatus.SUCCESS
        assert response.provider_id == "c"

    def test_a_b_c_all_fail_is_a_safe_failure_not_a_fabricated_response(self) -> None:
        a = make_provider_config("a", priority=0, max_retries=0)
        b = make_provider_config("b", priority=1, max_retries=0)
        c = make_provider_config("c", priority=2, max_retries=0)
        adapters = {
            "a": MockProviderAdapter(a, failure_mode="rate_limit"),
            "b": MockProviderAdapter(b, failure_mode="timeout"),
            "c": MockProviderAdapter(c, failure_mode="auth"),
        }
        gateway, *_ = _build(a, b, c, adapters_by_id=adapters)
        response = gateway.generate(make_request(), as_of=utc(2024, 1, 2))
        assert response.status != RequestStatus.SUCCESS
        assert response.content is None
        assert response.error_reason is not None

    def test_a_quota_reset_reverts_priority_back_to_a(self) -> None:
        a = make_provider_config("a", priority=0)
        b = make_provider_config("b", priority=1)
        gateway, qm, *_ = _build(a, b)
        qm.mark_quota_exhausted("a", at=utc(2024, 1, 1, 13), reset_time=utc(2024, 1, 2))
        r1 = gateway.generate(make_request("AIREQ-1"), as_of=utc(2024, 1, 1, 14))
        assert r1.provider_id == "b"
        r2 = gateway.generate(make_request("AIREQ-2"), as_of=utc(2024, 1, 3))
        assert r2.provider_id == "a"  # back to top priority once the window rolled over

    def test_billing_detected_disables_provider_for_all_future_calls(self) -> None:
        a = make_provider_config("a", priority=0)
        b = make_provider_config("b", priority=1)
        gateway, qm, *_ = _build(a, b)
        qm.mark_billing_detected("a", at=utc(2024, 1, 1, 13))
        response = gateway.generate(make_request(), as_of=utc(2024, 6, 1))
        assert response.provider_id == "b"


class TestRetryOnTransientFailure:
    def test_timeout_then_success_on_same_provider_within_retry_budget(self) -> None:
        a = make_provider_config("a", max_retries=2)

        class _FlakyOnceAdapter(MockProviderAdapter):
            def __init__(self, config):
                super().__init__(config)
                self._calls = 0

            def generate(self, request):
                self._calls += 1
                if self._calls == 1:
                    from ai_gateway.provider import ProviderTimeoutError

                    raise ProviderTimeoutError("flaky once")
                return super().generate(request)

        gateway, *_ = _build(a, adapters_by_id={"a": _FlakyOnceAdapter(a)})
        response = gateway.generate(make_request(), as_of=utc(2024, 1, 2))
        assert response.status == RequestStatus.SUCCESS
        assert response.attempt_count == 2

    def test_retries_do_not_exceed_max_retries(self) -> None:
        a = make_provider_config("a", priority=0, max_retries=1)
        adapters = {"a": MockProviderAdapter(a, failure_mode="timeout")}
        gateway, *_ = _build(a, adapters_by_id=adapters)
        response = gateway.generate(make_request(), as_of=utc(2024, 1, 2))
        assert response.status == RequestStatus.TIMEOUT
        assert response.attempt_count == 2  # 1 initial + 1 retry


class TestMissingConfiguration:
    def test_no_provider_configured_for_tier_is_missing_configuration(self) -> None:
        a = make_provider_config("a", supported_tiers=(TaskTier.HIGH,))
        gateway, *_ = _build(a)
        response = gateway.generate(make_request(task_tier=TaskTier.LOW), as_of=utc(2024, 1, 2))
        assert response.status == RequestStatus.MISSING_CONFIGURATION
        assert response.content is None


class TestInvalidResponse:
    def test_malformed_json_response_is_invalid_response_not_success(self) -> None:
        a = make_provider_config("a", max_retries=0)
        adapters = {"a": MockProviderAdapter(a, failure_mode="malformed")}
        gateway, *_ = _build(a, adapters_by_id=adapters)
        response = gateway.generate(make_request(response_schema=("action",)), as_of=utc(2024, 1, 2))
        assert response.status == RequestStatus.INVALID_RESPONSE
        assert response.content is None

    def test_missing_field_response_is_invalid_response(self) -> None:
        a = make_provider_config("a", max_retries=0)
        adapters = {"a": MockProviderAdapter(a, failure_mode="missing_field")}
        gateway, *_ = _build(a, adapters_by_id=adapters)
        response = gateway.generate(make_request(response_schema=("action", "confidence")), as_of=utc(2024, 1, 2))
        assert response.status == RequestStatus.INVALID_RESPONSE


class TestNoProvidersAtAllConfigured:
    def test_empty_gateway_config_is_missing_configuration(self) -> None:
        from ai_gateway.config import GatewayConfig

        empty_config = GatewayConfig(providers=())
        qm = QuotaManager(InMemoryQuotaStateRepository())
        gateway = AIGateway(empty_config, {}, qm)
        response = gateway.generate(make_request(), as_of=utc(2024, 1, 2))
        assert response.status == RequestStatus.MISSING_CONFIGURATION
