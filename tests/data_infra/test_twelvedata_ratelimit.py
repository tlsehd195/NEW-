"""Category: Rate Limiter Test -- `TwelveDataRateLimiter` (ADR-0164
follow-up correction: a real production run burst through Twelve
Data's real 8/minute free-tier limit with no pacing at all)."""

from __future__ import annotations

from data_infra.providers.twelvedata_ratelimit import TwelveDataRateLimiter


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestWaitIfNeeded:
    def test_does_not_sleep_while_under_the_effective_cap(self) -> None:
        clock = _FakeClock()
        sleeps: list[float] = []
        limiter = TwelveDataRateLimiter(limit_per_minute=8, safety_margin=1, clock=clock, sleep_fn=sleeps.append)
        for _ in range(7):  # effective cap = 8 - 1 = 7
            limiter.wait_if_needed()
            limiter.record_request()
        assert sleeps == []

    def test_sleeps_once_the_effective_cap_is_reached(self) -> None:
        clock = _FakeClock()
        sleeps: list[float] = []

        def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            clock.advance(seconds)

        limiter = TwelveDataRateLimiter(limit_per_minute=8, safety_margin=1, clock=clock, sleep_fn=fake_sleep)
        for _ in range(7):
            limiter.wait_if_needed()
            limiter.record_request()
        limiter.wait_if_needed()  # the 8th call must wait for the 1st to age out
        assert len(sleeps) == 1
        assert sleeps[0] == 60.0  # oldest request was at t=0, window is 60s, current clock still at 0

    def test_no_sleep_needed_once_the_window_has_naturally_elapsed(self) -> None:
        clock = _FakeClock()
        sleeps: list[float] = []
        limiter = TwelveDataRateLimiter(limit_per_minute=8, safety_margin=1, clock=clock, sleep_fn=sleeps.append)
        for _ in range(7):
            limiter.wait_if_needed()
            limiter.record_request()
        clock.advance(61.0)  # the whole window has passed
        limiter.wait_if_needed()
        assert sleeps == []


class TestRecordRequest:
    def test_shared_instance_is_consumed_across_repeated_calls(self) -> None:
        clock = _FakeClock()
        limiter_a = TwelveDataRateLimiter(limit_per_minute=2, safety_margin=0, clock=clock, sleep_fn=lambda _s: None)
        limiter_a.record_request()
        limiter_a.record_request()
        # a 3rd immediate call must be recognized as needing to wait
        waited = {"n": 0}

        def fake_sleep(seconds: float) -> None:
            waited["n"] += 1
            clock.advance(seconds)

        limiter_a._sleep_fn = fake_sleep
        limiter_a.wait_if_needed()
        assert waited["n"] == 1
