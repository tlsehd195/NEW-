"""Category: Fail-Closed / Quota Rotation Test -- PROJECT_MASTER_PLAN.md
sections 6.3-6.5's required scenarios: provider disabled, unknown health/
billing treated conservatively, quota exhaustion, reset-time rollover,
billing detection."""

from __future__ import annotations

import pytest
from ai_gateway_helpers import make_provider_config, utc

from ai_gateway.enums import BillingStatus, ProviderHealthStatus
from ai_gateway.quota_manager import QuotaManager
from ai_gateway.repository import InMemoryQuotaStateRepository


def _manager() -> QuotaManager:
    return QuotaManager(InMemoryQuotaStateRepository())


class TestNeverInitialized:
    def test_unknown_provider_is_never_available(self) -> None:
        qm = _manager()
        assert qm.is_available("never-heard-of-it", as_of=utc(2024, 1, 1)) is False

    def test_operating_on_an_uninitialized_provider_raises(self) -> None:
        qm = _manager()
        with pytest.raises(ValueError):
            qm.record_success("never-heard-of-it", at=utc(2024, 1, 1), usage=None)


class TestInitialize:
    def test_initialize_is_idempotent(self) -> None:
        qm = _manager()
        config = make_provider_config("a")
        s1 = qm.initialize(config, at=utc(2024, 1, 1))
        s2 = qm.initialize(config, at=utc(2024, 1, 2))
        assert s1 is s2

    def test_freshly_initialized_provider_is_available(self) -> None:
        qm = _manager()
        qm.initialize(make_provider_config("a"), at=utc(2024, 1, 1))
        assert qm.is_available("a", as_of=utc(2024, 1, 1)) is True

    def test_disabled_provider_is_never_available(self) -> None:
        qm = _manager()
        qm.initialize(make_provider_config("a", enabled=False), at=utc(2024, 1, 1))
        assert qm.is_available("a", as_of=utc(2024, 1, 1)) is False


class TestSuccessAndErrorRecording:
    def test_success_decrements_remaining_requests(self) -> None:
        qm = _manager()
        qm.initialize(make_provider_config("a", rpd_limit=2), at=utc(2024, 1, 1))
        state = qm.record_success("a", at=utc(2024, 1, 1, 13), usage=None)
        assert state.remaining_requests == 1
        assert qm.is_available("a", as_of=utc(2024, 1, 1, 14)) is True
        qm.record_success("a", at=utc(2024, 1, 1, 15), usage=None)
        assert qm.is_available("a", as_of=utc(2024, 1, 1, 16)) is False  # exhausted at 0

    def test_error_increments_error_count_and_degrades_health(self) -> None:
        qm = _manager()
        qm.initialize(make_provider_config("a"), at=utc(2024, 1, 1))
        state = qm.record_error("a", at=utc(2024, 1, 1, 13), reason="timeout:x")
        assert state.error_count == 1
        assert state.health_status == ProviderHealthStatus.DEGRADED
        # still available -- a single transient error is not a hard stop
        assert qm.is_available("a", as_of=utc(2024, 1, 1, 14)) is True

    def test_success_resets_error_count(self) -> None:
        qm = _manager()
        qm.initialize(make_provider_config("a"), at=utc(2024, 1, 1))
        qm.record_error("a", at=utc(2024, 1, 1, 13), reason="timeout:x")
        state = qm.record_success("a", at=utc(2024, 1, 1, 14), usage=None)
        assert state.error_count == 0
        assert state.health_status == ProviderHealthStatus.HEALTHY


class TestMarkUnavailable:
    def test_unavailable_provider_is_never_available(self) -> None:
        qm = _manager()
        qm.initialize(make_provider_config("a"), at=utc(2024, 1, 1))
        qm.mark_unavailable("a", at=utc(2024, 1, 1, 13), reason="auth_failed:x")
        assert qm.is_available("a", as_of=utc(2024, 1, 1, 14)) is False


class TestQuotaExhaustionAndReset:
    def test_exhausted_provider_is_unavailable_before_reset_time(self) -> None:
        qm = _manager()
        qm.initialize(make_provider_config("a"), at=utc(2024, 1, 1))
        qm.mark_quota_exhausted("a", at=utc(2024, 1, 1, 13), reset_time=utc(2024, 1, 2))
        assert qm.is_available("a", as_of=utc(2024, 1, 1, 23)) is False

    def test_exhausted_provider_becomes_available_again_after_reset_time(self) -> None:
        qm = _manager()
        qm.initialize(make_provider_config("a"), at=utc(2024, 1, 1))
        qm.mark_quota_exhausted("a", at=utc(2024, 1, 1, 13), reset_time=utc(2024, 1, 2))
        assert qm.is_available("a", as_of=utc(2024, 1, 3)) is True

    def test_exhaustion_with_unknown_reset_time_stays_exhausted(self) -> None:
        qm = _manager()
        qm.initialize(make_provider_config("a"), at=utc(2024, 1, 1))
        qm.mark_quota_exhausted("a", at=utc(2024, 1, 1, 13), reset_time=None)
        assert qm.is_available("a", as_of=utc(2024, 6, 1)) is False

    def test_rollover_actually_refills_remaining_requests_not_just_the_availability_check(self) -> None:
        """External review finding (Session 36 continued): before this
        fix, `is_available` returned True after `reset_time` passed, but
        `remaining_requests` in the persisted state was never actually
        refilled anywhere -- a `record_success` call right after
        rollover decremented from the stale (already-0) count, so
        `is_available` fell straight back to False on the very next
        check. This proves the refill is real and persists: a full
        rpd_limit's worth of successes are usable again after rollover,
        not just one illusory "available" reading."""
        qm = _manager()
        qm.initialize(make_provider_config("a", rpd_limit=2), at=utc(2024, 1, 1))
        qm.record_success("a", at=utc(2024, 1, 1, 13), usage=None)
        qm.record_success("a", at=utc(2024, 1, 1, 14), usage=None)
        assert qm.is_available("a", as_of=utc(2024, 1, 1, 15)) is False  # exhausted

        qm.mark_quota_exhausted("a", at=utc(2024, 1, 1, 16), reset_time=utc(2024, 1, 1, 23))
        assert qm.is_available("a", as_of=utc(2024, 1, 2, 1)) is True  # rolled over

        # The real, persisted regression check: two full successes are
        # usable again post-rollover, exactly the original rpd_limit --
        # not "decrement from a stale 0" (which would strand it at -1
        # clamped to 0 and make the very next check False again).
        state = qm.record_success("a", at=utc(2024, 1, 2, 2), usage=None)
        assert state.remaining_requests == 1
        assert qm.is_available("a", as_of=utc(2024, 1, 2, 3)) is True
        state = qm.record_success("a", at=utc(2024, 1, 2, 3), usage=None)
        assert state.remaining_requests == 0
        assert qm.is_available("a", as_of=utc(2024, 1, 2, 4)) is False

    def test_rollover_refill_also_applies_inside_record_error(self) -> None:
        qm = _manager()
        qm.initialize(make_provider_config("a", rpd_limit=1), at=utc(2024, 1, 1))
        qm.mark_quota_exhausted("a", at=utc(2024, 1, 1, 16), reset_time=utc(2024, 1, 2))
        state = qm.record_error("a", at=utc(2024, 1, 3), reason="timeout:x")
        assert state.remaining_requests == 1  # refilled, not still 0
        assert state.reset_time is None  # the rollover was consumed


class TestBillingConfirmedFreeRecovery:
    """External review finding (Session 36 continued): `BillingStatus`'s
    own docstring referenced `mark_billing_confirmed_free` by name as
    the undo for `mark_billing_detected`, but the method did not exist
    -- a provider marked PAID_DETECTED had no way back."""

    def test_confirmed_free_reverses_a_prior_paid_detection(self) -> None:
        qm = _manager()
        qm.initialize(make_provider_config("a"), at=utc(2024, 1, 1))
        qm.mark_billing_detected("a", at=utc(2024, 1, 2))
        assert qm.is_available("a", as_of=utc(2024, 1, 3)) is False

        state = qm.mark_billing_confirmed_free("a", at=utc(2024, 1, 4))
        assert state.billing_status == BillingStatus.CONFIRMED_FREE
        assert qm.is_available("a", as_of=utc(2024, 1, 5)) is True


class TestMarkAvailableAgainRecovery:
    """External review finding (Session 36 continued): `mark_unavailable`
    had no recovery path at all -- `is_available` excludes UNAVAILABLE
    providers from `ProviderSelector.select`'s candidate list, so
    `record_success` (the only OTHER thing that reset health_status to
    HEALTHY) could structurally never be reached again. One auth failure
    permanently retired a provider for the life of the process."""

    def test_mark_available_again_reverses_mark_unavailable(self) -> None:
        qm = _manager()
        qm.initialize(make_provider_config("a"), at=utc(2024, 1, 1))
        qm.mark_unavailable("a", at=utc(2024, 1, 1, 13), reason="auth_failed:x")
        assert qm.is_available("a", as_of=utc(2024, 1, 1, 14)) is False

        state = qm.mark_available_again("a", at=utc(2024, 1, 2))
        assert state.health_status == ProviderHealthStatus.HEALTHY
        assert state.error_count == 0
        assert qm.is_available("a", as_of=utc(2024, 1, 3)) is True


class TestBillingDetection:
    def test_billing_detected_makes_provider_unavailable_regardless_of_quota(self) -> None:
        qm = _manager()
        qm.initialize(make_provider_config("a"), at=utc(2024, 1, 1))
        state = qm.mark_billing_detected("a", at=utc(2024, 1, 2))
        assert state.billing_status == BillingStatus.PAID_DETECTED
        assert qm.is_available("a", as_of=utc(2024, 1, 3)) is False

    def test_billing_detected_persists_even_after_a_quota_reset_window(self) -> None:
        qm = _manager()
        qm.initialize(make_provider_config("a"), at=utc(2024, 1, 1))
        qm.mark_quota_exhausted("a", at=utc(2024, 1, 1, 13), reset_time=utc(2024, 1, 2))
        qm.mark_billing_detected("a", at=utc(2024, 1, 1, 14))
        assert qm.is_available("a", as_of=utc(2024, 6, 1)) is False


class TestAppendOnlyHistory:
    def test_every_state_change_is_a_new_observation_not_a_mutation(self) -> None:
        qm = _manager()
        repo = InMemoryQuotaStateRepository()
        qm = QuotaManager(repo)
        qm.initialize(make_provider_config("a"), at=utc(2024, 1, 1))
        qm.record_success("a", at=utc(2024, 1, 1, 13), usage=None)
        qm.record_error("a", at=utc(2024, 1, 1, 14), reason="timeout:x")
        history = repo.get_history("a")
        assert len(history) == 3
        assert [s.reason for s in history] == ["initial", "success", "timeout:x"]
