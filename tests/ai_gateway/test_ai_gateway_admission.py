"""Category: RpmAdmissionGate correctness (Batch K, ai_gateway.admission).
No fixtures needed -- the gate is a pure, clock-injected component with
no dependency on any other ai_gateway piece."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ai_gateway.admission import RpmAdmissionGate


def _t(seconds: float = 0.0) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)


class TestConstruction:
    def test_zero_rpm_limit_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            RpmAdmissionGate(0)

    def test_negative_rpm_limit_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            RpmAdmissionGate(-5)

    def test_none_rpm_limit_is_accepted_as_unlimited(self) -> None:
        RpmAdmissionGate(None)  # must not raise


class TestNoLimitConfigured:
    def test_every_call_is_admitted_regardless_of_spacing(self) -> None:
        gate = RpmAdmissionGate(None)
        for i in range(5):
            decision = gate.evaluate(at=_t(i * 0.001))
            assert decision.admitted
            assert decision.retry_after is None
            gate.record_admission(at=_t(i * 0.001))


class TestEvenlySpacedAdmission:
    def test_first_call_is_always_admitted(self) -> None:
        gate = RpmAdmissionGate(rpm_limit=60)  # 1 per second
        decision = gate.evaluate(at=_t(0))
        assert decision.admitted
        assert decision.retry_after is None

    def test_second_call_before_min_interval_elapsed_is_denied(self) -> None:
        gate = RpmAdmissionGate(rpm_limit=60)  # min interval = 1.0s
        gate.record_admission(at=_t(0))
        decision = gate.evaluate(at=_t(0.5))
        assert not decision.admitted
        assert decision.retry_after == _t(1.0)

    def test_call_at_exactly_the_min_interval_boundary_is_admitted(self) -> None:
        gate = RpmAdmissionGate(rpm_limit=60)
        gate.record_admission(at=_t(0))
        decision = gate.evaluate(at=_t(1.0))
        assert decision.admitted

    def test_call_after_the_min_interval_is_admitted(self) -> None:
        gate = RpmAdmissionGate(rpm_limit=60)
        gate.record_admission(at=_t(0))
        decision = gate.evaluate(at=_t(1.5))
        assert decision.admitted

    def test_rpm_limit_of_30_means_a_2_second_spacing(self) -> None:
        gate = RpmAdmissionGate(rpm_limit=30)
        gate.record_admission(at=_t(0))
        assert not gate.evaluate(at=_t(1.9)).admitted
        assert gate.evaluate(at=_t(2.0)).admitted


class TestIdleTimeNeverAccumulatesBurstAllowance:
    def test_a_long_idle_period_still_only_admits_one_request_at_a_time(self) -> None:
        # The defining difference from a token bucket: waiting 100x the
        # min interval must not let two requests through back-to-back.
        gate = RpmAdmissionGate(rpm_limit=60)  # min interval = 1.0s
        gate.record_admission(at=_t(0))

        first = gate.evaluate(at=_t(100.0))  # idle for 100 seconds
        assert first.admitted
        gate.record_admission(at=_t(100.0))

        second = gate.evaluate(at=_t(100.0))  # immediately after, same instant
        assert not second.admitted
        assert second.retry_after == _t(101.0)


class TestRecordAdmissionMonotonicity:
    def test_recording_an_earlier_timestamp_than_the_last_one_raises(self) -> None:
        gate = RpmAdmissionGate(rpm_limit=60)
        gate.record_admission(at=_t(10))
        with pytest.raises(ValueError, match="monotonically"):
            gate.record_admission(at=_t(5))

    def test_recording_the_same_timestamp_twice_is_allowed(self) -> None:
        gate = RpmAdmissionGate(rpm_limit=60)
        gate.record_admission(at=_t(10))
        gate.record_admission(at=_t(10))  # must not raise
