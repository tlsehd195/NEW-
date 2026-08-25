"""AI Gateway data models.

See docs/specifications/PHASE-12-ai-gateway.md sections 4, 7, 8.

**Structural boundary enforcement**: no type in this module has an
`order_id`, `broker_order`, `execution_price`, `quantity`, `side`,
`risk_limit`, or `kill_switch`-shaped field, and nothing here carries a
`trade_journal.enums.DecisionAction` or
`learning.enums.CandidateModelStatus` value (verified by reflection in
`tests/ai_gateway/test_ai_gateway_boundary.py`). `AIRequest.payload` is
a plain, already-prepared `dict`/`str` the caller assembled -- this
module never calls `data_infra.repository.DataRepository`/
`backtest.asof.AsOfDataView` itself (PROJECT_MASTER_PLAN.md's
point-in-time principle, applied here as "the Gateway does not go
looking for its own market data").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ai_gateway.enums import BillingStatus, ProviderHealthStatus, RequestStatus, TaskTier

from trade_journal.enums import TradeProvenance


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


@dataclass(frozen=True)
class AIRequest:
    """One request into the Gateway. `payload` is opaque, already-built
    text/data the caller assembled -- the Gateway never inspects it for
    trading intent and never fetches anything to enrich it."""

    request_id: str  # "AIREQ-000001"
    task_tier: TaskTier
    prompt_template_id: str
    prompt_template_version: str
    payload: str
    max_tokens: Optional[int]
    requested_at: datetime
    provenance: TradeProvenance
    experiment_id: Optional[str] = None
    # when set, the Gateway requires `content` to parse as a JSON object
    # containing every one of these keys -- a response missing any of
    # them, or that fails to parse at all, is INVALID_RESPONSE, never a
    # partially-trusted SUCCESS (ai_gateway.validation).
    response_schema: Optional[tuple[str, ...]] = None

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("AIRequest.request_id must not be empty")
        if not self.prompt_template_id or not self.prompt_template_version:
            raise ValueError("AIRequest requires a non-empty prompt_template_id/prompt_template_version")
        _require_aware("AIRequest.requested_at", self.requested_at)
        if self.response_schema is not None and not self.response_schema:
            raise ValueError("AIRequest.response_schema must be None or a non-empty tuple")


@dataclass(frozen=True)
class UsageInfo:
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


@dataclass(frozen=True)
class ProviderLimits:
    """A snapshot of `ProviderConfig`'s configured limits -- what
    `AIProviderAdapter.get_limits()` returns, kept as its own type
    rather than exposing the config dataclass directly so a real future
    adapter can report limits it discovered (rather than only ones
    hand-configured) without changing this shape."""

    provider_id: str
    rpm_limit: Optional[int]
    rpd_limit: Optional[int]
    tpm_limit: Optional[int]
    tpd_limit: Optional[int]
    monthly_limit: Optional[int]


@dataclass(frozen=True)
class UsageEstimate:
    provider_id: str
    estimated_prompt_tokens: int
    estimated_total_tokens: int
    basis: str  # e.g. "char_count_heuristic_v1" -- an estimate, never presented as an exact measurement


@dataclass(frozen=True)
class AIResponse:
    """One `AIGateway.generate()` outcome -- always exactly one of
    `status == SUCCESS` with `content` set, or `status != SUCCESS` with
    `content=None` and `error_reason` set. There is no third state where
    both are populated or both are empty."""

    response_id: str  # "AIRESP-000001"
    request_id: str
    status: RequestStatus
    provider_id: Optional[str]
    model: Optional[str]
    model_version: Optional[str]
    prompt_template_version: str
    configuration_version: str
    content: Optional[str]
    parsed: Optional[dict]
    usage: Optional[UsageInfo]
    latency_ms: Optional[float]
    error_reason: Optional[str]
    attempt_count: int
    responded_at: datetime
    provenance: TradeProvenance
    experiment_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.response_id or not self.request_id:
            raise ValueError("AIResponse requires non-empty response_id/request_id")
        _require_aware("AIResponse.responded_at", self.responded_at)
        if self.status == RequestStatus.SUCCESS:
            if self.content is None:
                raise ValueError("AIResponse.status == SUCCESS requires content to be set")
            if self.error_reason is not None:
                raise ValueError("AIResponse.status == SUCCESS must not carry an error_reason")
        else:
            if self.content is not None:
                raise ValueError(f"AIResponse.status == {self.status.value} must not carry content")
            if self.error_reason is None:
                raise ValueError(f"AIResponse.status == {self.status.value} requires a factual error_reason")
        if self.attempt_count < 0:
            raise ValueError("AIResponse.attempt_count must not be negative")
        if self.status == RequestStatus.SUCCESS and self.attempt_count < 1:
            raise ValueError("AIResponse.status == SUCCESS requires attempt_count >= 1")


@dataclass(frozen=True)
class ProviderQuotaState:
    """One observed state of a provider's quota/health/billing -- an
    append-only history record (mirrors `regime.models.
    RegimeObservation`'s "one observation per point in time" pattern,
    Phase 5), never mutated in place. A provider's *current* state is
    always the most recent `ProviderQuotaState` for that `provider_id`.
    """

    state_id: str  # "QSTATE-000001"
    provider_id: str
    observed_at: datetime
    remaining_requests: Optional[int]
    remaining_tokens: Optional[int]
    reset_time: Optional[datetime]
    health_status: ProviderHealthStatus
    billing_status: BillingStatus
    enabled: bool
    error_count: int
    last_success_at: Optional[datetime]
    last_error_at: Optional[datetime]
    last_error_reason: Optional[str]
    reason: str  # factual: why this observation was recorded, e.g. "initial", "success", "quota_exhausted", "billing_detected"

    def __post_init__(self) -> None:
        if not self.state_id or not self.provider_id:
            raise ValueError("ProviderQuotaState requires non-empty state_id/provider_id")
        _require_aware("ProviderQuotaState.observed_at", self.observed_at)
        if self.reset_time is not None:
            _require_aware("ProviderQuotaState.reset_time", self.reset_time)
        if self.last_success_at is not None:
            _require_aware("ProviderQuotaState.last_success_at", self.last_success_at)
        if self.last_error_at is not None:
            _require_aware("ProviderQuotaState.last_error_at", self.last_error_at)
        if self.error_count < 0:
            raise ValueError("ProviderQuotaState.error_count must not be negative")
