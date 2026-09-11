"""AIProviderAdapter Protocol + MockProviderAdapter.

See docs/specifications/PHASE-12-ai-gateway.md sections 5, 6, 9.

PROJECT_MASTER_PLAN.md section 5.1 defines the provider interface as
`generate()/stream()/estimate_usage()/get_usage()/health_check()/
get_limits()`. `MockProviderAdapter` is the only implementation this
phase ships -- fully deterministic and offline, no network call, no
`os.environ` read anywhere (it never needs to resolve
`ProviderConfig.api_key_reference` to an actual secret). It exists to
prove the Gateway/Router/QuotaManager pipeline end to end, the same
"baseline/mock first" precedent every prior phase's own reference
implementation already established.
"""

from __future__ import annotations

import hashlib
import json
from typing import Iterator, Optional, Protocol

from ai_gateway.config import ProviderConfig
from ai_gateway.enums import ProviderHealthStatus
from ai_gateway.models import AIRequest, ProviderLimits, UsageEstimate, UsageInfo


class ProviderError(Exception):
    """Base class for every AI provider failure the Gateway explicitly
    handles and maps to a `RequestStatus`. Never used for a Gateway/
    routing bug -- those raise a plain `ValueError`/`RuntimeError`
    instead, so they are not silently swallowed as "just another
    provider failure.\""""


class ProviderTimeoutError(ProviderError):
    pass


class ProviderAuthError(ProviderError):
    pass


class ProviderRateLimitError(ProviderError):
    """`retry_after_seconds` (Session 36 continued, external review
    remediation): optional, real signal a provider's own rate-limit
    response supplied (e.g. an HTTP `Retry-After` header) -- `None`
    (the default) when the provider gave no such signal, or when this
    error was raised by something that never had one to give (`Mock
    ProviderAdapter` never sets it, matching its own "no network call"
    design). Never fabricated by this codebase itself: only a real
    adapter parsing a real response may populate it. `ai_gateway.
    gateway.AIGateway` passes it through to `QuotaManager.
    mark_quota_exhausted`'s own `reset_time` when present -- absent, the
    conservative pre-existing behavior (no automatic recovery window,
    requires an operator to intervene) is unchanged."""

    def __init__(self, message: str = "", *, retry_after_seconds: Optional[float] = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class RawProviderOutput:
    """The provider's raw output, before the Gateway wraps it into an
    `AIResponse`. Deliberately not a dataclass with `__post_init__`
    validation -- a real provider adapter's raw output may be malformed
    by construction (that is exactly what `MockProviderAdapter`'s
    `failure_mode="malformed"` simulates), and validating it is the
    Gateway's job (`ai_gateway.validation`), not the adapter's."""

    __slots__ = ("content", "usage")

    def __init__(self, content: str, usage: UsageInfo) -> None:
        self.content = content
        self.usage = usage


class AIProviderAdapter(Protocol):
    """A real implementation's `generate()` (and any other method that
    can hit a provider rate limit) MUST populate `ProviderRateLimitError.
    retry_after_seconds` from the provider's own response (e.g. an HTTP
    `Retry-After` header or an equivalent field the provider's API
    documents) whenever the provider actually supplies one. `ai_gateway.
    gateway.AIGateway` can only open an automatic quota-recovery window
    from a REAL signal -- it never fabricates one (`ProviderRateLimitError`'s
    own docstring) -- so an adapter that raises the error with
    `retry_after_seconds=None` when the provider's response genuinely
    included a usable value leaves that provider locked out for the
    life of the process, indistinguishable from a provider that
    supplied nothing at all (ADR-0117)."""

    provider_id: str

    def generate(self, request: AIRequest) -> RawProviderOutput: ...
    def stream(self, request: AIRequest) -> Iterator[str]: ...
    def estimate_usage(self, request: AIRequest) -> UsageEstimate: ...
    def get_usage(self) -> UsageInfo: ...
    def health_check(self) -> ProviderHealthStatus: ...
    def get_limits(self) -> ProviderLimits: ...


class MockProviderAdapter:
    """`failure_mode` deterministically simulates one failure class per
    PROJECT_MASTER_PLAN.md section 6.5's required test scenarios --
    never a real timer/network wait (this system has no wall-clock
    dependency here): `None` (default, success), `"timeout"`,
    `"auth"`, `"rate_limit"`, `"provider_error"`, `"unavailable"`
    (health_check only), `"malformed"` (returns syntactically invalid
    JSON when the caller expects it), `"missing_field"` (returns valid
    JSON missing a required field)."""

    def __init__(self, config: ProviderConfig, *, failure_mode: Optional[str] = None) -> None:
        self.provider_id = config.provider_id
        self._config = config
        self._failure_mode = failure_mode
        self._cumulative_usage = UsageInfo(prompt_tokens=0, completion_tokens=0, total_tokens=0)

    def generate(self, request: AIRequest) -> RawProviderOutput:
        if self._failure_mode == "timeout":
            raise ProviderTimeoutError(f"simulated timeout for provider {self.provider_id!r}")
        if self._failure_mode == "auth":
            raise ProviderAuthError(f"simulated auth failure for provider {self.provider_id!r}")
        if self._failure_mode == "rate_limit":
            raise ProviderRateLimitError(f"simulated rate limit for provider {self.provider_id!r}")
        if self._failure_mode == "provider_error":
            raise ProviderError(f"simulated provider error for provider {self.provider_id!r}")

        payload_hash = hashlib.sha256(request.payload.encode("utf-8")).hexdigest()[:16]

        if self._failure_mode == "malformed":
            content = "{not valid json!!"
        elif self._failure_mode == "missing_field" and request.response_schema:
            fields = {name: f"mock_value_{name}" for name in request.response_schema[1:]}
            content = json.dumps(fields, sort_keys=True)
        elif request.response_schema:
            fields = {name: f"mock_value_{name}" for name in request.response_schema}
            content = json.dumps(fields, sort_keys=True)
        else:
            content = f"[mock:{self.provider_id}] template={request.prompt_template_id} payload_hash={payload_hash}"

        prompt_tokens = max(1, len(request.payload) // 4)
        completion_tokens = max(1, len(content) // 4)
        usage = UsageInfo(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )
        self._cumulative_usage = UsageInfo(
            prompt_tokens=(self._cumulative_usage.prompt_tokens or 0) + prompt_tokens,
            completion_tokens=(self._cumulative_usage.completion_tokens or 0) + completion_tokens,
            total_tokens=(self._cumulative_usage.total_tokens or 0) + prompt_tokens + completion_tokens,
        )
        return RawProviderOutput(content=content, usage=usage)

    def stream(self, request: AIRequest) -> Iterator[str]:
        output = self.generate(request)
        midpoint = max(1, len(output.content) // 2)
        yield output.content[:midpoint]
        yield output.content[midpoint:]

    def estimate_usage(self, request: AIRequest) -> UsageEstimate:
        estimated_prompt_tokens = max(1, len(request.payload) // 4)
        estimated_completion_tokens = request.max_tokens or estimated_prompt_tokens
        return UsageEstimate(
            provider_id=self.provider_id,
            estimated_prompt_tokens=estimated_prompt_tokens,
            estimated_total_tokens=estimated_prompt_tokens + estimated_completion_tokens,
            basis="char_count_heuristic_v1",
        )

    def get_usage(self) -> UsageInfo:
        return self._cumulative_usage

    def health_check(self) -> ProviderHealthStatus:
        if self._failure_mode == "unavailable":
            return ProviderHealthStatus.UNAVAILABLE
        return ProviderHealthStatus.HEALTHY

    def get_limits(self) -> ProviderLimits:
        return ProviderLimits(
            provider_id=self.provider_id,
            rpm_limit=self._config.rpm_limit, rpd_limit=self._config.rpd_limit,
            tpm_limit=self._config.tpm_limit, tpd_limit=self._config.tpd_limit,
            monthly_limit=self._config.monthly_limit,
        )
