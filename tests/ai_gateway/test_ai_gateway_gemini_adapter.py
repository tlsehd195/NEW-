"""Category: Provider Abstraction Test -- `GeminiProviderAdapter`
implements the same `AIProviderAdapter` Protocol `MockProviderAdapter`
does (PROJECT_MASTER_PLAN.md section 5.1), so `ai_gateway.gateway.
AIGateway` can use either interchangeably. Exercises the adapter with a
stubbed `GeminiHttpTransport` -- never a real one (see
`test_ai_gateway_gemini_transport.py`'s own docstring)."""

from __future__ import annotations

from typing import Optional

import pytest
from ai_gateway_helpers import make_provider_config, make_request

from ai_gateway.enums import ProviderHealthStatus
from ai_gateway.provider import ProviderAuthError, ProviderRateLimitError
from ai_gateway.providers.gemini import DEFAULT_GEMINI_PROVIDER_CONFIG, GeminiProviderAdapter
from ai_gateway.providers.gemini_transport import GeminiTransportResponse
from ai_gateway.validation import validate_response_content


class _StubTransport:
    def __init__(self, response: Optional[GeminiTransportResponse] = None, *, error: Optional[Exception] = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict] = []

    def generate_content(self, *, model, api_key, request_body, timeout):
        self.calls.append({"model": model, "api_key": api_key, "request_body": request_body, "timeout": timeout})
        if self._error is not None:
            raise self._error
        return self._response


def _config(**overrides):
    fields = dict(
        provider_id="gemini", provider_name="Google Gemini", model="gemini-3.8-flash",
        api_key_reference="GEMINI_API_KEY",
    )
    fields.update(overrides)
    return make_provider_config(**fields)


@pytest.fixture(autouse=True)
def _gemini_api_key_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-for-adapter-tests")


class TestGenerateSuccess:
    def test_generate_returns_text_and_usage(self) -> None:
        body = {
            "candidates": [{"content": {"parts": [{"text": "hello world"}]}}],
            "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2, "totalTokenCount": 10},
        }
        transport = _StubTransport(GeminiTransportResponse(status_code=200, body=body))
        adapter = GeminiProviderAdapter(_config(), transport=transport)
        output = adapter.generate(make_request(payload="hi"))
        assert output.content == "hello world"
        assert output.usage.total_tokens == 10  # from totalTokenCount directly, not prompt+completion

    def test_cumulative_usage_accumulates_across_calls(self) -> None:
        body = {
            "candidates": [{"content": {"parts": [{"text": "x"}]}}],
            "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 3},
        }
        transport = _StubTransport(GeminiTransportResponse(status_code=200, body=body))
        adapter = GeminiProviderAdapter(_config(), transport=transport)
        adapter.generate(make_request(request_id="AIREQ-000001"))
        adapter.generate(make_request(request_id="AIREQ-000002"))
        assert adapter.get_usage().total_tokens == 6

    def test_response_schema_requests_json_mime_type(self) -> None:
        body = {"candidates": [{"content": {"parts": [{"text": "{}"}]}}], "usageMetadata": {}}
        transport = _StubTransport(GeminiTransportResponse(status_code=200, body=body))
        adapter = GeminiProviderAdapter(_config(), transport=transport)
        adapter.generate(make_request(response_schema=("direction", "confidence")))
        assert transport.calls[0]["request_body"]["generationConfig"]["responseMimeType"] == "application/json"

    def test_no_response_schema_omits_json_mime_type(self) -> None:
        body = {"candidates": [{"content": {"parts": [{"text": "free text"}]}}], "usageMetadata": {}}
        transport = _StubTransport(GeminiTransportResponse(status_code=200, body=body))
        adapter = GeminiProviderAdapter(_config(), transport=transport)
        adapter.generate(make_request(response_schema=None))
        assert "responseMimeType" not in transport.calls[0]["request_body"]["generationConfig"]


class TestGenerateEmptyOrBlockedResponse:
    def test_no_candidates_yields_empty_content_not_a_crash(self) -> None:
        body = {"promptFeedback": {"blockReason": "SAFETY"}, "usageMetadata": {}}
        transport = _StubTransport(GeminiTransportResponse(status_code=200, body=body))
        adapter = GeminiProviderAdapter(_config(), transport=transport)
        output = adapter.generate(make_request())
        assert output.content == ""
        # empty content is INVALID_RESPONSE downstream, never a silently-trusted SUCCESS
        assert not validate_response_content(output.content, None).valid


class TestErrorPropagation:
    def test_auth_error_from_transport_propagates(self, monkeypatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "real-key")
        transport = _StubTransport(error=ProviderAuthError("bad key"))
        adapter = GeminiProviderAdapter(_config(), transport=transport)
        with pytest.raises(ProviderAuthError):
            adapter.generate(make_request())

    def test_missing_env_var_raises_before_any_transport_call(self, monkeypatch) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        transport = _StubTransport(GeminiTransportResponse(status_code=200, body={}))
        adapter = GeminiProviderAdapter(_config(api_key_reference="GEMINI_API_KEY"), transport=transport)
        with pytest.raises(ProviderAuthError):
            adapter.generate(make_request())
        assert transport.calls == []

    def test_rate_limit_error_propagates_with_retry_after(self) -> None:
        transport = _StubTransport(error=ProviderRateLimitError("rate limited", retry_after_seconds=18.0))
        adapter = GeminiProviderAdapter(_config(), transport=transport)
        with pytest.raises(ProviderRateLimitError) as excinfo:
            adapter.generate(make_request())
        assert excinfo.value.retry_after_seconds == 18.0


class TestProtocolShape:
    def test_stream_yields_two_chunks_of_the_generate_content(self) -> None:
        body = {"candidates": [{"content": {"parts": [{"text": "abcdef"}]}}], "usageMetadata": {}}
        transport = _StubTransport(GeminiTransportResponse(status_code=200, body=body))
        adapter = GeminiProviderAdapter(_config(), transport=transport)
        chunks = list(adapter.stream(make_request()))
        assert "".join(chunks) == "abcdef"
        assert len(chunks) == 2

    def test_health_check_reports_unknown_never_a_fabricated_healthy(self) -> None:
        adapter = GeminiProviderAdapter(_config(), transport=_StubTransport())
        assert adapter.health_check() == ProviderHealthStatus.UNKNOWN

    def test_get_limits_reflects_configured_values(self) -> None:
        adapter = GeminiProviderAdapter(_config(rpm_limit=5, rpd_limit=None), transport=_StubTransport())
        limits = adapter.get_limits()
        assert limits.provider_id == "gemini"
        assert limits.rpm_limit == 5
        assert limits.rpd_limit is None

    def test_estimate_usage_never_calls_the_transport(self) -> None:
        transport = _StubTransport()
        adapter = GeminiProviderAdapter(_config(), transport=transport)
        adapter.estimate_usage(make_request(payload="a payload of some length"))
        assert transport.calls == []


class TestDefaultProviderConfig:
    def test_default_config_uses_gemini_api_key_reference(self) -> None:
        assert DEFAULT_GEMINI_PROVIDER_CONFIG.api_key_reference == "GEMINI_API_KEY"
        assert DEFAULT_GEMINI_PROVIDER_CONFIG.provider_id == "gemini"
