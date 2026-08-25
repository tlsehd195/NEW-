"""Category: Provider Abstraction Test -- `MockProviderAdapter`
implements PROJECT_MASTER_PLAN.md section 5.1's full interface
deterministically, offline, with each documented failure mode."""

from __future__ import annotations

import pytest
from ai_gateway_helpers import make_provider_config, make_request

from ai_gateway.enums import ProviderHealthStatus
from ai_gateway.provider import (
    MockProviderAdapter,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)


class TestSuccessPath:
    def test_generate_returns_deterministic_content(self) -> None:
        config = make_provider_config()
        adapter = MockProviderAdapter(config)
        request = make_request()
        out1 = adapter.generate(request)
        out2 = MockProviderAdapter(config).generate(request)
        assert out1.content == out2.content
        assert out1.usage.total_tokens == out2.usage.total_tokens

    def test_generate_with_response_schema_produces_valid_json(self) -> None:
        import json

        config = make_provider_config()
        adapter = MockProviderAdapter(config)
        request = make_request(response_schema=("action", "confidence"))
        out = adapter.generate(request)
        parsed = json.loads(out.content)
        assert set(parsed.keys()) == {"action", "confidence"}

    def test_stream_yields_the_same_content_as_generate(self) -> None:
        config = make_provider_config()
        adapter = MockProviderAdapter(config)
        request = make_request()
        expected = adapter.generate(request).content
        streamed = "".join(MockProviderAdapter(config).stream(request))
        assert streamed == expected

    def test_get_usage_accumulates_across_calls(self) -> None:
        config = make_provider_config()
        adapter = MockProviderAdapter(config)
        assert adapter.get_usage().total_tokens == 0
        adapter.generate(make_request("AIREQ-1"))
        first = adapter.get_usage().total_tokens
        assert first > 0
        adapter.generate(make_request("AIREQ-2"))
        assert adapter.get_usage().total_tokens > first

    def test_get_limits_reflects_config(self) -> None:
        config = make_provider_config(rpm_limit=42, rpd_limit=100)
        adapter = MockProviderAdapter(config)
        limits = adapter.get_limits()
        assert limits.rpm_limit == 42
        assert limits.rpd_limit == 100
        assert limits.provider_id == config.provider_id

    def test_estimate_usage_is_deterministic_and_never_negative(self) -> None:
        config = make_provider_config()
        adapter = MockProviderAdapter(config)
        request = make_request(payload="a" * 400)
        est1 = adapter.estimate_usage(request)
        est2 = adapter.estimate_usage(request)
        assert est1.estimated_prompt_tokens == est2.estimated_prompt_tokens > 0
        assert est1.estimated_total_tokens == est2.estimated_total_tokens > 0

    def test_health_check_healthy_by_default(self) -> None:
        adapter = MockProviderAdapter(make_provider_config())
        assert adapter.health_check() == ProviderHealthStatus.HEALTHY


class TestFailureModes:
    def test_timeout_raises_provider_timeout_error(self) -> None:
        adapter = MockProviderAdapter(make_provider_config(), failure_mode="timeout")
        with pytest.raises(ProviderTimeoutError):
            adapter.generate(make_request())

    def test_auth_raises_provider_auth_error(self) -> None:
        adapter = MockProviderAdapter(make_provider_config(), failure_mode="auth")
        with pytest.raises(ProviderAuthError):
            adapter.generate(make_request())

    def test_rate_limit_raises_provider_rate_limit_error(self) -> None:
        adapter = MockProviderAdapter(make_provider_config(), failure_mode="rate_limit")
        with pytest.raises(ProviderRateLimitError):
            adapter.generate(make_request())

    def test_provider_error_raises_base_provider_error(self) -> None:
        adapter = MockProviderAdapter(make_provider_config(), failure_mode="provider_error")
        with pytest.raises(ProviderError):
            adapter.generate(make_request())

    def test_unavailable_only_affects_health_check_not_generate(self) -> None:
        adapter = MockProviderAdapter(make_provider_config(), failure_mode="unavailable")
        assert adapter.health_check() == ProviderHealthStatus.UNAVAILABLE
        out = adapter.generate(make_request())  # generate itself still succeeds -- a separate failure axis
        assert out.content

    def test_malformed_returns_content_that_is_not_valid_json(self) -> None:
        import json

        adapter = MockProviderAdapter(make_provider_config(), failure_mode="malformed")
        out = adapter.generate(make_request(response_schema=("action",)))
        with pytest.raises(json.JSONDecodeError):
            json.loads(out.content)

    def test_missing_field_omits_the_first_schema_field(self) -> None:
        import json

        adapter = MockProviderAdapter(make_provider_config(), failure_mode="missing_field")
        out = adapter.generate(make_request(response_schema=("action", "confidence")))
        parsed = json.loads(out.content)
        assert "action" not in parsed
        assert "confidence" in parsed


class TestSpecificErrorTypesAreProviderErrors:
    def test_all_specific_exceptions_are_provider_errors(self) -> None:
        assert issubclass(ProviderTimeoutError, ProviderError)
        assert issubclass(ProviderAuthError, ProviderError)
        assert issubclass(ProviderRateLimitError, ProviderError)
