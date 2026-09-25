"""Category: Rate Limiter Test -- `AlphaVantageRateLimiter` (2026-09-25:
a real recon run burst through Alpha Vantage's real 1/second free-tier
limit with no pacing at all)."""

from __future__ import annotations

from data_infra.providers.alphavantage_ratelimit import AlphaVantageRateLimiter


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestWaitIfNeeded:
    def test_does_not_sleep_for_the_first_call(self) -> None:
        clock = _FakeClock()
        sleeps: list[float] = []
        limiter = AlphaVantageRateLimiter(limit_per_second=1, clock=clock, sleep_fn=sleeps.append)
        limiter.wait_if_needed()
        limiter.record_request()
        assert sleeps == []

    def test_sleeps_once_the_effective_cap_is_reached(self) -> None:
        clock = _FakeClock()
        sleeps: list[float] = []

        def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            clock.advance(seconds)

        limiter = AlphaVantageRateLimiter(limit_per_second=1, clock=clock, sleep_fn=fake_sleep)
        limiter.wait_if_needed()
        limiter.record_request()
        limiter.wait_if_needed()  # the 2nd call must wait for the 1st to age out
        assert len(sleeps) == 1
        assert sleeps[0] == 1.0  # oldest request was at t=0, window is 1s, current clock still at 0

    def test_no_sleep_needed_once_the_window_has_naturally_elapsed(self) -> None:
        clock = _FakeClock()
        sleeps: list[float] = []
        limiter = AlphaVantageRateLimiter(limit_per_second=1, clock=clock, sleep_fn=sleeps.append)
        limiter.wait_if_needed()
        limiter.record_request()
        clock.advance(1.1)  # the whole window has passed
        limiter.wait_if_needed()
        assert sleeps == []

    def test_higher_limit_per_second_allows_more_calls_before_sleeping(self) -> None:
        clock = _FakeClock()
        sleeps: list[float] = []

        def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            clock.advance(seconds)  # a real sleep_fn must advance real wall-clock time

        limiter = AlphaVantageRateLimiter(limit_per_second=3, clock=clock, sleep_fn=fake_sleep)
        for _ in range(3):
            limiter.wait_if_needed()
            limiter.record_request()
        assert sleeps == []
        limiter.wait_if_needed()
        assert len(sleeps) == 1


class TestRecordRequest:
    def test_shared_instance_is_consumed_across_repeated_calls(self) -> None:
        clock = _FakeClock()
        limiter = AlphaVantageRateLimiter(limit_per_second=1, clock=clock, sleep_fn=lambda _s: None)
        limiter.record_request()
        # a 2nd immediate call must be recognized as needing to wait
        waited = {"n": 0}

        def fake_sleep(seconds: float) -> None:
            waited["n"] += 1
            clock.advance(seconds)

        limiter._sleep_fn = fake_sleep
        limiter.wait_if_needed()
        assert waited["n"] == 1


class TestConstructorValidation:
    def test_non_positive_limit_per_second_is_rejected(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            AlphaVantageRateLimiter(limit_per_second=0)
