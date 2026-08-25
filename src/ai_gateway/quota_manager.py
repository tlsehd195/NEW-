"""QuotaManager: tracks each provider's quota/health/billing state and
decides availability, per PROJECT_MASTER_PLAN.md sections 6.3-6.4.

See docs/specifications/PHASE-12-ai-gateway.md section 8.

Every state change is a new, appended `ProviderQuotaState` observation
(never a mutation of a prior one) -- the audit trail this project's
append-history discipline already established for
`learning`/`counterfactual`/`evolution`, applied here to quota state
instead. `is_available` is the single fail-closed gate every routing
decision goes through: a provider that has never been initialized, is
disabled, has unknown/unavailable health, has unknown/paid billing
status, or has exhausted quota with no elapsed reset window, is never
selected -- PROJECT_MASTER_PLAN.md section 6.4's "무료 한도 상태를
정확히 알 수 없는 provider는 보수적으로(사용 중단 방향으로) 처리한다."
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from ai_gateway.config import ProviderConfig
from ai_gateway.enums import BillingStatus, ProviderHealthStatus
from ai_gateway.models import ProviderQuotaState, UsageInfo
from ai_gateway.repository import QuotaStateRepository


class _IdAllocator:
    def __init__(self) -> None:
        self._next_id = 1

    def allocate(self) -> str:
        sid = f"QSTATE-{self._next_id:06d}"
        self._next_id += 1
        return sid


class QuotaManager:
    def __init__(self, repository: QuotaStateRepository) -> None:
        self._repository = repository
        self._ids = _IdAllocator()

    def initialize(self, provider_config: ProviderConfig, *, at: datetime) -> ProviderQuotaState:
        """Idempotent: a provider already observed keeps its existing
        history rather than being reset back to a fresh state."""
        existing = self._repository.get_latest(provider_config.provider_id)
        if existing is not None:
            return existing
        state = ProviderQuotaState(
            state_id=self._ids.allocate(), provider_id=provider_config.provider_id, observed_at=at,
            remaining_requests=provider_config.rpd_limit, remaining_tokens=provider_config.tpd_limit,
            reset_time=None, health_status=ProviderHealthStatus.HEALTHY, billing_status=BillingStatus.CONFIRMED_FREE,
            enabled=provider_config.enabled, error_count=0, last_success_at=None, last_error_at=None,
            last_error_reason=None, reason="initial",
        )
        return self._repository.record(state)

    def is_available(self, provider_id: str, *, as_of: datetime) -> bool:
        state = self._repository.get_latest(provider_id)
        if state is None:
            return False  # never initialized -- fail closed, never assume available
        if not state.enabled:
            return False
        if state.health_status in (ProviderHealthStatus.UNAVAILABLE, ProviderHealthStatus.UNKNOWN):
            return False
        if state.billing_status in (BillingStatus.PAID_DETECTED, BillingStatus.UNKNOWN):
            return False
        if state.reset_time is not None and as_of >= state.reset_time:
            return True  # the quota window has rolled over -- fresh again
        if state.remaining_requests is not None and state.remaining_requests <= 0:
            return False
        if state.remaining_tokens is not None and state.remaining_tokens <= 0:
            return False
        return True

    def record_success(self, provider_id: str, *, at: datetime, usage: Optional[UsageInfo]) -> ProviderQuotaState:
        prior = self._require_latest(provider_id)
        remaining_requests = None if prior.remaining_requests is None else max(0, prior.remaining_requests - 1)
        remaining_tokens = prior.remaining_tokens
        if remaining_tokens is not None and usage is not None and usage.total_tokens is not None:
            remaining_tokens = max(0, remaining_tokens - usage.total_tokens)
        return self._append(
            prior, at=at, reason="success", health_status=ProviderHealthStatus.HEALTHY,
            remaining_requests=remaining_requests, remaining_tokens=remaining_tokens,
            error_count=0, last_success_at=at, last_error_at=prior.last_error_at,
            last_error_reason=prior.last_error_reason,
        )

    def record_error(self, provider_id: str, *, at: datetime, reason: str) -> ProviderQuotaState:
        prior = self._require_latest(provider_id)
        return self._append(
            prior, at=at, reason=reason, health_status=ProviderHealthStatus.DEGRADED,
            remaining_requests=prior.remaining_requests, remaining_tokens=prior.remaining_tokens,
            error_count=prior.error_count + 1, last_success_at=prior.last_success_at,
            last_error_at=at, last_error_reason=reason,
        )

    def mark_unavailable(self, provider_id: str, *, at: datetime, reason: str) -> ProviderQuotaState:
        prior = self._require_latest(provider_id)
        return self._append(
            prior, at=at, reason=reason, health_status=ProviderHealthStatus.UNAVAILABLE,
            remaining_requests=prior.remaining_requests, remaining_tokens=prior.remaining_tokens,
            error_count=prior.error_count + 1, last_success_at=prior.last_success_at,
            last_error_at=at, last_error_reason=reason,
        )

    def mark_quota_exhausted(
        self, provider_id: str, *, at: datetime, reason: str = "quota_exhausted", reset_time: Optional[datetime] = None
    ) -> ProviderQuotaState:
        prior = self._require_latest(provider_id)
        return self._append(
            prior, at=at, reason=reason, health_status=prior.health_status,
            remaining_requests=0, remaining_tokens=0, reset_time=reset_time,
            error_count=prior.error_count, last_success_at=prior.last_success_at,
            last_error_at=prior.last_error_at, last_error_reason=prior.last_error_reason,
        )

    def mark_billing_detected(self, provider_id: str, *, at: datetime, reason: str = "billing_detected") -> ProviderQuotaState:
        """PROJECT_MASTER_PLAN.md section 1.5: this is a deterministic-
        code decision only -- nothing in `ai_gateway.*` calls this based
        on AI-generated response content (verified structurally in
        `tests/ai_gateway/test_ai_gateway_boundary.py`)."""
        prior = self._require_latest(provider_id)
        return self._append(
            prior, at=at, reason=reason, health_status=prior.health_status,
            remaining_requests=prior.remaining_requests, remaining_tokens=prior.remaining_tokens,
            billing_status=BillingStatus.PAID_DETECTED,
            error_count=prior.error_count, last_success_at=prior.last_success_at,
            last_error_at=prior.last_error_at, last_error_reason=prior.last_error_reason,
        )

    def _require_latest(self, provider_id: str) -> ProviderQuotaState:
        state = self._repository.get_latest(provider_id)
        if state is None:
            raise ValueError(f"provider {provider_id!r} was never initialized -- call initialize() first")
        return state

    def _append(
        self, prior: ProviderQuotaState, *, at: datetime, reason: str,
        health_status: ProviderHealthStatus, remaining_requests: Optional[int], remaining_tokens: Optional[int],
        error_count: int, last_success_at: Optional[datetime], last_error_at: Optional[datetime],
        last_error_reason: Optional[str], billing_status: Optional[BillingStatus] = None,
        reset_time: Optional[datetime] = None,
    ) -> ProviderQuotaState:
        new_state = ProviderQuotaState(
            state_id=self._ids.allocate(), provider_id=prior.provider_id, observed_at=at,
            remaining_requests=remaining_requests, remaining_tokens=remaining_tokens,
            reset_time=reset_time if reset_time is not None else prior.reset_time,
            health_status=health_status, billing_status=billing_status or prior.billing_status,
            enabled=prior.enabled, error_count=error_count, last_success_at=last_success_at,
            last_error_at=last_error_at, last_error_reason=last_error_reason, reason=reason,
        )
        return self._repository.record(new_state)
