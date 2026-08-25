"""AIGateway: the single entry point PROJECT_MASTER_PLAN.md section 5
requires -- "전체 애플리케이션에서 AI API를 직접 호출하지 않는다."

See docs/specifications/PHASE-12-ai-gateway.md section 9.

Pipeline: `Application -> AIGateway -> TaskRouter -> QuotaManager (via
ProviderSelector) -> AIProviderAdapter`. On total exhaustion (every
candidate for the tier unavailable or failing) this returns a factual,
non-`SUCCESS` `AIResponse` -- it never fabricates content, never retries
into a "paid" fallback, and never raises an unhandled exception out to
the caller for a provider-side failure (PROJECT_MASTER_PLAN.md section
6.2: "NO AI CALL / safe failure").

Structural note: `generate()` takes an already-built `AIRequest` and an
explicit `as_of` timestamp -- it never calls `datetime.now()`/
`datetime.utcnow()` and never calls `data_infra.repository.
DataRepository`/`backtest.asof.AsOfDataView` itself (nothing to leak:
the caller supplies everything this module reads).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from ai_gateway.config import GatewayConfig, ProviderConfig
from ai_gateway.enums import RequestStatus
from ai_gateway.models import AIRequest, AIResponse, UsageInfo
from ai_gateway.provider import (
    AIProviderAdapter,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from ai_gateway.provider_selector import ProviderSelector
from ai_gateway.quota_manager import QuotaManager
from ai_gateway.repository import AIRequestRepository, AIResponseRepository
from ai_gateway.task_router import TaskRouter
from ai_gateway.validation import validate_response_content


class _IdAllocator:
    def __init__(self) -> None:
        self._next_id = 1

    def allocate(self) -> str:
        rid = f"AIRESP-{self._next_id:06d}"
        self._next_id += 1
        return rid


class AIGateway:
    def __init__(
        self,
        config: GatewayConfig,
        adapters: dict[str, AIProviderAdapter],
        quota_manager: QuotaManager,
        *,
        request_repository: Optional[AIRequestRepository] = None,
        response_repository: Optional[AIResponseRepository] = None,
    ) -> None:
        self._config = config
        self._adapters = adapters
        self._task_router = TaskRouter(config)
        self._quota_manager = quota_manager
        self._selector = ProviderSelector(self._task_router, quota_manager)
        self._request_repository = request_repository
        self._response_repository = response_repository
        self._ids = _IdAllocator()

    def generate(self, request: AIRequest, *, as_of: datetime) -> AIResponse:
        if self._request_repository is not None:
            self._request_repository.record(request)

        configured = self._task_router.candidates_for(request.task_tier)
        if not configured:
            return self._finalize(
                request, at=as_of, status=RequestStatus.MISSING_CONFIGURATION,
                error_reason=f"no provider configured for tier {request.task_tier.value}", attempt_count=0,
            )

        available = self._selector.select(request.task_tier, as_of=as_of)
        if not available:
            return self._finalize(
                request, at=as_of, status=RequestStatus.NO_PROVIDER_AVAILABLE,
                error_reason="every configured provider is currently unavailable (quota/health/billing)",
                attempt_count=0,
            )

        attempt_count = 0
        last_status = RequestStatus.NO_PROVIDER_AVAILABLE
        last_reason = "no provider was attempted"

        for provider_config in available:
            adapter = self._adapters.get(provider_config.provider_id)
            if adapter is None:
                continue  # configured but not wired to a real adapter instance -- skip safely, not a provider failure

            local_attempts = 0
            while local_attempts <= provider_config.max_retries:
                attempt_count += 1
                local_attempts += 1
                try:
                    raw = adapter.generate(request)
                except ProviderAuthError as exc:
                    self._quota_manager.mark_unavailable(provider_config.provider_id, at=as_of, reason=f"auth_failed:{exc}")
                    last_status, last_reason = RequestStatus.AUTH_FAILED, str(exc)
                    break
                except ProviderRateLimitError as exc:
                    self._quota_manager.mark_quota_exhausted(provider_config.provider_id, at=as_of, reason="rate_limited")
                    last_status, last_reason = RequestStatus.RATE_LIMITED, str(exc)
                    break
                except ProviderTimeoutError as exc:
                    self._quota_manager.record_error(provider_config.provider_id, at=as_of, reason=f"timeout:{exc}")
                    last_status, last_reason = RequestStatus.TIMEOUT, str(exc)
                    continue  # retryable -- try the same provider again, up to max_retries
                except ProviderError as exc:
                    self._quota_manager.record_error(provider_config.provider_id, at=as_of, reason=f"provider_error:{exc}")
                    last_status, last_reason = RequestStatus.PROVIDER_ERROR, str(exc)
                    continue
                else:
                    validation = validate_response_content(raw.content, request.response_schema)
                    if not validation.valid:
                        self._quota_manager.record_error(
                            provider_config.provider_id, at=as_of, reason=f"invalid_response:{validation.reason}"
                        )
                        last_status, last_reason = RequestStatus.INVALID_RESPONSE, validation.reason
                        break  # not retried -- a deterministic provider producing malformed output would repeat it
                    self._quota_manager.record_success(provider_config.provider_id, at=as_of, usage=raw.usage)
                    return self._finalize(
                        request, at=as_of, status=RequestStatus.SUCCESS, provider_config=provider_config,
                        content=raw.content, parsed=validation.parsed, usage=raw.usage, attempt_count=attempt_count,
                    )

        return self._finalize(
            request, at=as_of, status=last_status, error_reason=last_reason, attempt_count=attempt_count,
        )

    def _finalize(
        self,
        request: AIRequest,
        *,
        at: datetime,
        status: RequestStatus,
        attempt_count: int,
        provider_config: Optional[ProviderConfig] = None,
        content: Optional[str] = None,
        parsed: Optional[dict] = None,
        usage: Optional[UsageInfo] = None,
        error_reason: Optional[str] = None,
    ) -> AIResponse:
        configuration_version = (
            provider_config.configuration_version() if provider_config is not None else self._config.configuration_version()
        )
        response = AIResponse(
            response_id=self._ids.allocate(), request_id=request.request_id, status=status,
            provider_id=provider_config.provider_id if provider_config is not None else None,
            # `model` is already a version-qualified identifier (e.g. "mock-model-v1");
            # this phase has no separate provider-reported version string to track.
            model=provider_config.model if provider_config is not None else None,
            model_version=None,
            prompt_template_version=request.prompt_template_version,
            configuration_version=configuration_version,
            content=content, parsed=parsed, usage=usage, latency_ms=None,
            error_reason=error_reason, attempt_count=attempt_count, responded_at=at,
            provenance=request.provenance, experiment_id=request.experiment_id,
        )
        if self._response_repository is not None:
            self._response_repository.record(response)
        return response
