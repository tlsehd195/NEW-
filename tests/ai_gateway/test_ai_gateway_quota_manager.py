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
