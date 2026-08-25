"""Enumerations for the AI Gateway (Phase 12).

See docs/specifications/PHASE-12-ai-gateway.md sections 4, 5.
"""

from __future__ import annotations

from enum import Enum


class TaskTier(str, Enum):
    """PROJECT_MASTER_PLAN.md section 5.2's three task grades -- the
    Task Router selects provider priority per tier, not a single global
    ranking."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ProviderHealthStatus(str, Enum):
    """A provider's most recently observed health. `UNKNOWN` is treated
    exactly like `UNAVAILABLE` by `quota_manager.is_available` --
    PROJECT_MASTER_PLAN.md section 6.4: "무료 한도 상태를 정확히 알 수
    없는 provider는 보수적으로(사용 중단 방향으로) 처리한다.\""""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class BillingStatus(str, Enum):
    """Whether a provider is still known to be strictly free-tier.
    `UNKNOWN` is treated the same as `PAID_DETECTED` by
    `quota_manager.is_available` -- the same conservative "if in doubt,
    stop using it" rule as `ProviderHealthStatus.UNKNOWN` (section 6.4).
    Never changed based on AI-generated response *content* -- only a
    caller's explicit, deterministic-code call to
    `QuotaManager.mark_billing_detected`/`mark_billing_confirmed_free`
    can move this (PROJECT_MASTER_PLAN.md section 1.5: "free API billing
    policy" is not something AI can change itself)."""

    CONFIRMED_FREE = "CONFIRMED_FREE"
    PAID_DETECTED = "PAID_DETECTED"
    UNKNOWN = "UNKNOWN"


class RequestStatus(str, Enum):
    """Every possible outcome of one `AIGateway.generate()` call. There
    is no "success but unsure" state -- a response is either `SUCCESS`
    or one of these named, factual failure reasons; nothing here is ever
    silently coerced into a fabricated success."""

    SUCCESS = "SUCCESS"
    NO_PROVIDER_AVAILABLE = "NO_PROVIDER_AVAILABLE"  # every candidate provider was unavailable -- PROJECT_MASTER_PLAN.md section 6.2 "NO AI CALL / safe failure"
    TIMEOUT = "TIMEOUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_FAILED = "AUTH_FAILED"
    INVALID_RESPONSE = "INVALID_RESPONSE"  # malformed/unparseable/schema-invalid/missing-field content
    MISSING_CONFIGURATION = "MISSING_CONFIGURATION"  # no provider configured for the requested TaskTier at all
