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

from datetime import datetime, timedelta
from typing import Optional

from ai_gateway.config import ProviderConfig
from ai_gateway.enums import BillingStatus, ProviderHealthStatus
from ai_gateway.models import ProviderQuotaState, UsageInfo
from ai_gateway.repository import QuotaStateRepository


class _IdAllocator:
    # Session 37 (ADR-0115, external review N-5): `starting_id`,
    # mirroring the restart-safe pattern `predict.predictor._IdAllocator`/
    # `risk.engine._IdAllocator`/`decision.agent._IdAllocator` (ADR-0073)
    # already established. Without it, a fresh process always starts
    # counting from "QSTATE-000001" again; `DuckDBQuotaStateRepository.
    # record()` dedupes on `state_id` and silently returns the *old*
    # stored row on a collision instead of inserting the new one (same
    # natural-key-idempotency pattern every other DuckDB repository in
    # this codebase uses) -- so every observation recorded after a
    # restart whose generated id collides with one from a prior run is
    # silently dropped until the counter runs past the old run's range.
    # A caller that knows the real persisted max id (the same
    # `_next_starting_id(repo.list_all())` pattern `scripts.
    # run_paper_trading_cycle`/`run_multi_strategy_paper_trading_cycle`
    # already use for prediction/decision/sizing/risk ids) can now avoid
    # this by constructing `QuotaManager(repo, starting_id=...)`.
    def __init__(self, starting_id: int = 1) -> None:
        self._next_id = starting_id

    def allocate(self) -> str:
        sid = f"QSTATE-{self._next_id:06d}"
        self._next_id += 1
        return sid


class QuotaManager:
    def __init__(self, repository: QuotaStateRepository, *, starting_id: int = 1) -> None:
        self._repository = repository
        self._ids = _IdAllocator(starting_id)

    def initialize(
        self, provider_config: ProviderConfig, *, at: datetime,
        billing_status: BillingStatus = BillingStatus.CONFIRMED_FREE,
    ) -> ProviderQuotaState:
        """Idempotent: a provider already observed keeps its existing
        history rather than being reset back to a fresh state.

        `billing_status` defaults to `CONFIRMED_FREE` (unchanged
        behavior for every existing caller) on the premise that a
        human operator only ever adds a `ProviderConfig` to
        `GatewayConfig.providers` for a provider they have already
        vetted as free-tier -- the config's presence in that list *is*
        the human confirmation, mirroring `mark_billing_detected`/
        `mark_billing_confirmed_free`'s own "deterministic-code/human
        decision only" discipline. Session 37 (ADR-0115, external
        review, previously-remaining MEDIUM): before this parameter
        existed there was no way to initialize a provider whose billing
        status is genuinely *not* yet known any other way -- callers
        were forced into `CONFIRMED_FREE` even when that was false,
        which is the opposite of `BillingStatus.UNKNOWN`'s own
        documented "if in doubt, stop using it" contract (`ai_gateway.
        enums.BillingStatus`). A caller that does not yet know can now
        pass `billing_status=BillingStatus.UNKNOWN` explicitly."""
        existing = self._repository.get_latest(provider_config.provider_id)
        if existing is not None:
            return existing
        state = ProviderQuotaState(
            state_id=self._ids.allocate(), provider_id=provider_config.provider_id, observed_at=at,
            remaining_requests=provider_config.rpd_limit, remaining_tokens=provider_config.tpd_limit,
            reset_time=None, health_status=ProviderHealthStatus.HEALTHY, billing_status=billing_status,
            enabled=provider_config.enabled, error_count=0, last_success_at=None, last_error_at=None,
            last_error_reason=None, reason="initial",
            rpd_limit=provider_config.rpd_limit, tpd_limit=provider_config.tpd_limit,
        )
        return self._repository.record(state)

    def _effective_state(self, state: ProviderQuotaState, *, as_of: datetime) -> ProviderQuotaState:
        """Session 36 continued (external review remediation): the real
        fix for "a quota window rolled over but `remaining_requests`/
        `remaining_tokens` were never refilled anywhere." Pure/read-only
        -- never persists anything itself, just computes what `state`
        effectively means as of `as_of`, refilling to this provider's
        own `rpd_limit`/`tpd_limit` (carried on every observation since
        `initialize()`, never re-guessed) and clearing `reset_time` when
        `as_of >= state.reset_time`. Every caller that then WRITES a new
        observation (`record_success`/`record_error`) passes the result
        of this as `prior` to `_append`, so the persisted state actually
        reflects the refill from that point forward -- not just this one
        read. A `state.reset_time is None` (nothing pending) or
        `as_of < state.reset_time` (window hasn't rolled over yet)
        returns `state` unchanged."""
        if state.reset_time is None or as_of < state.reset_time:
            return state
        return ProviderQuotaState(
            state_id=state.state_id, provider_id=state.provider_id, observed_at=state.observed_at,
            remaining_requests=state.rpd_limit, remaining_tokens=state.tpd_limit, reset_time=None,
            health_status=state.health_status, billing_status=state.billing_status, enabled=state.enabled,
            error_count=state.error_count, last_success_at=state.last_success_at,
            last_error_at=state.last_error_at, last_error_reason=state.last_error_reason, reason=state.reason,
            rpd_limit=state.rpd_limit, tpd_limit=state.tpd_limit,
        )

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
        effective = self._effective_state(state, as_of=as_of)
        if effective.remaining_requests is not None and effective.remaining_requests <= 0:
            return False
        if effective.remaining_tokens is not None and effective.remaining_tokens <= 0:
            return False
        return True

    def record_success(self, provider_id: str, *, at: datetime, usage: Optional[UsageInfo]) -> ProviderQuotaState:
        prior = self._effective_state(self._require_latest(provider_id), as_of=at)
        remaining_requests = None if prior.remaining_requests is None else max(0, prior.remaining_requests - 1)
        remaining_tokens = prior.remaining_tokens
        if remaining_tokens is not None and usage is not None and usage.total_tokens is not None:
            remaining_tokens = max(0, remaining_tokens - usage.total_tokens)
        # Session 37 (ADR-0115, external review N-2): a provider that
        # reaches 0 through ordinary usage (as opposed to
        # `mark_quota_exhausted`, which always sets its own
        # `reset_time`) previously never got a `reset_time` at all --
        # and `_effective_state`'s refill only fires when `reset_time`
        # is set AND elapsed, so a naturally-exhausted provider could
        # never self-heal and stayed permanently unavailable for the
        # life of the process. `rpd_limit`/`tpd_limit` are both
        # literally "per day" limits (`ProviderConfig`'s own field
        # names), so a 24h rolling window from `at` is used -- this
        # project has no reliable, provider-specific knowledge of the
        # real reset clock (midnight UTC vs. a rolling window vs.
        # provider-local time), so it does not fabricate one; only
        # opened when nothing is pending yet (`prior.reset_time is
        # None`), never overwriting an already-open window.
        reset_time = prior.reset_time
        if reset_time is None and (
            (remaining_requests is not None and remaining_requests <= 0)
            or (remaining_tokens is not None and remaining_tokens <= 0)
        ):
            reset_time = at + timedelta(days=1)
        return self._append(
            prior, at=at, reason="success", health_status=ProviderHealthStatus.HEALTHY,
            remaining_requests=remaining_requests, remaining_tokens=remaining_tokens,
            error_count=0, last_success_at=at, last_error_at=prior.last_error_at,
            last_error_reason=prior.last_error_reason, reset_time=reset_time,
        )

    def record_error(self, provider_id: str, *, at: datetime, reason: str) -> ProviderQuotaState:
        prior = self._effective_state(self._require_latest(provider_id), as_of=at)
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

    def mark_billing_confirmed_free(
        self, provider_id: str, *, at: datetime, reason: str = "billing_confirmed_free",
    ) -> ProviderQuotaState:
        """Session 36 continued (external review remediation): the
        undo for `mark_billing_detected` this module's own `BillingStatus`
        docstring already referenced by name (`ai_gateway.enums.
        BillingStatus`) but that did not actually exist until now -- a
        provider marked `PAID_DETECTED` had no way back to
        `CONFIRMED_FREE` at all. Same deterministic-code-only discipline
        as `mark_billing_detected`: never called based on AI-generated
        response content."""
        prior = self._require_latest(provider_id)
        return self._append(
            prior, at=at, reason=reason, health_status=prior.health_status,
            remaining_requests=prior.remaining_requests, remaining_tokens=prior.remaining_tokens,
            billing_status=BillingStatus.CONFIRMED_FREE,
            error_count=prior.error_count, last_success_at=prior.last_success_at,
            last_error_at=prior.last_error_at, last_error_reason=prior.last_error_reason,
        )

    def mark_available_again(
        self, provider_id: str, *, at: datetime, reason: str = "manually_confirmed_available",
    ) -> ProviderQuotaState:
        """Session 36 continued (external review remediation): the
        recovery path `mark_unavailable` never had. `is_available`
        excludes any `UNAVAILABLE` provider from `ProviderSelector.
        select`'s own candidate list (`ai_gateway.provider_selector`),
        so `record_success` can structurally never be reached again for
        such a provider -- there was no way back at all, meaning one
        `ProviderAuthError` permanently retired a provider for the
        life of the process. Deliberately NOT automatic/time-based
        (unlike the quota-rollover refill this session also fixed): an
        auth failure is not naturally time-boxed the way a rate-limit
        window is, so resuming requires an explicit call -- a human (or
        deterministic startup code) confirming the underlying problem
        (e.g. an expired credential) was actually fixed, not a timer
        guessing that it probably was."""
        prior = self._require_latest(provider_id)
        return self._append(
            prior, at=at, reason=reason, health_status=ProviderHealthStatus.HEALTHY,
            remaining_requests=prior.remaining_requests, remaining_tokens=prior.remaining_tokens,
            error_count=0, last_success_at=prior.last_success_at,
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
            rpd_limit=prior.rpd_limit, tpd_limit=prior.tpd_limit,
        )
        return self._repository.record(new_state)
