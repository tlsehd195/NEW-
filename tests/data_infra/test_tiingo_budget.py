"""Category: Unit Test -- `TiingoRequestBudget` tracks Tiingo's real
50-requests/hour cap in a rolling window (ADR-0160). Every test uses an
injected fake clock -- never real `time.sleep`/wall-clock waits."""

from __future__ import annotations

import pytest

from data_infra.providers.tiingo_budget import TiingoRequestBudget


class _FakeClock:
    """Injectable clock: starts at 0.0, advanced explicitly by tests --
    never reads real wall-clock time."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class TestConstruction:
    def test_rejects_non_positive_limit(self) -> None:
        with pytest.raises(ValueError):
            TiingoRequestBudget(limit_per_hour=0)

    def test_rejects_negative_limit(self) -> None:
        with pytest.raises(ValueError):
            TiingoRequestBudget(limit_per_hour=-5)

    def test_rejects_safety_margin_at_the_limit(self) -> None:
        with pytest.raises(ValueError):
            TiingoRequestBudget(limit_per_hour=50, safety_margin=50)

    def test_rejects_safety_margin_above_the_limit(self) -> None:
        with pytest.raises(ValueError):
            TiingoRequestBudget(limit_per_hour=50, safety_margin=51)

    def test_rejects_negative_safety_margin(self) -> None:
        with pytest.raises(ValueError):
            TiingoRequestBudget(limit_per_hour=50, safety_margin=-1)

    def test_zero_safety_margin_is_allowed(self) -> None:
        budget = TiingoRequestBudget(limit_per_hour=50, safety_margin=0, clock=_FakeClock())
        assert budget.remaining() == 50


class TestRemainingAndExhaustion:
    def test_remaining_starts_at_limit_minus_safety_margin(self) -> None:
        budget = TiingoRequestBudget(limit_per_hour=50, safety_margin=2, clock=_FakeClock())
        assert budget.remaining() == 48

    def test_remaining_decreases_with_each_recorded_request(self) -> None:
        budget = TiingoRequestBudget(limit_per_hour=50, safety_margin=2, clock=_FakeClock())
        budget.record_request()
        assert budget.remaining() == 47
        budget.record_request()
        assert budget.remaining() == 46

    def test_would_not_exceed_below_the_margined_cap(self) -> None:
        budget = TiingoRequestBudget(limit_per_hour=50, safety_margin=2, clock=_FakeClock())
        for _ in range(47):
            budget.record_request()
        assert budget.would_exceed() is False
        assert budget.remaining() == 1

    def test_exhausted_exactly_at_the_margined_boundary(self) -> None:
        """50/hour real cap, safety_margin=2 -- ADR-0160's chosen
        headroom -- means the 48th in-window request must already be
        refused, not the 50th."""
        budget = TiingoRequestBudget(limit_per_hour=50, safety_margin=2, clock=_FakeClock())
        for _ in range(48):
            budget.record_request()
        assert budget.would_exceed() is True
        assert budget.remaining() == 0

    def test_the_47th_request_is_still_allowed(self) -> None:
        budget = TiingoRequestBudget(limit_per_hour=50, safety_margin=2, clock=_FakeClock())
        for _ in range(47):
            budget.record_request()
        assert budget.would_exceed() is False

    def test_remaining_never_goes_negative_past_exhaustion(self) -> None:
        budget = TiingoRequestBudget(limit_per_hour=50, safety_margin=2, clock=_FakeClock())
        for _ in range(60):
            budget.record_request()
        assert budget.remaining() == 0
        assert budget.would_exceed() is True


class TestRollingWindow:
    def test_a_request_older_than_one_hour_drops_out_of_the_window(self) -> None:
        clock = _FakeClock()
        budget = TiingoRequestBudget(limit_per_hour=2, safety_margin=0, clock=clock)
        budget.record_request()
        clock.advance(3601)
        assert budget.remaining() == 2  # the old request has rolled off

    def test_a_request_exactly_at_the_one_hour_boundary_has_already_dropped_out(self) -> None:
        """Documents the exact boundary choice: an entry whose age has
        reached the full window is treated as expired, not retained."""
        clock = _FakeClock()
        budget = TiingoRequestBudget(limit_per_hour=1, safety_margin=0, clock=clock)
        budget.record_request()
        clock.advance(3600.0)
        assert budget.would_exceed() is False

    def test_a_request_just_under_the_one_hour_boundary_still_counts(self) -> None:
        clock = _FakeClock()
        budget = TiingoRequestBudget(limit_per_hour=1, safety_margin=0, clock=clock)
        budget.record_request()
        clock.advance(3599.999)
        assert budget.would_exceed() is True

    def test_partial_rollover_only_drops_the_expired_entries(self) -> None:
        clock = _FakeClock()
        budget = TiingoRequestBudget(limit_per_hour=5, safety_margin=0, clock=clock)
        budget.record_request()  # t=0
        clock.advance(3000)
        budget.record_request()  # t=3000
        clock.advance(700)  # t=3700 -- the t=0 request (age 3700) has rolled off, t=3000 one (age 700) has not
        assert budget.remaining() == 4  # 5 - 1 still-in-window request

    def test_window_rollover_lets_new_requests_through_again_after_exhaustion(self) -> None:
        """The real-world case this class exists for: exhausted this
        hour must not mean exhausted forever -- it recovers once the
        old requests age out."""
        clock = _FakeClock()
        budget = TiingoRequestBudget(limit_per_hour=2, safety_margin=0, clock=clock)
        budget.record_request()
        budget.record_request()
        assert budget.would_exceed() is True
        clock.advance(3600.0)
        assert budget.would_exceed() is False
        assert budget.remaining() == 2


class TestSharedAcrossCallers:
    """Regression for the real production gap this class exists to
    close (ADR-0160, finding #2): both real Tiingo call paths --
    `TiingoDataProvider.fetch()` and the direct
    `fetch_corporate_actions` loop -- must decrement the SAME counter.
    Modeled here as two independent callers of one shared instance."""

    def test_two_independent_callers_of_the_same_instance_share_one_counter(self) -> None:
        clock = _FakeClock()
        budget = TiingoRequestBudget(limit_per_hour=4, safety_margin=0, clock=clock)

        def price_fetch_call_path() -> None:
            budget.record_request()

        def corporate_actions_call_path() -> None:
            budget.record_request()

        price_fetch_call_path()
        corporate_actions_call_path()
        price_fetch_call_path()
        corporate_actions_call_path()

        assert budget.remaining() == 0
        assert budget.would_exceed() is True

    def test_exhaustion_reached_by_one_caller_is_visible_to_the_other(self) -> None:
        clock = _FakeClock()
        budget = TiingoRequestBudget(limit_per_hour=1, safety_margin=0, clock=clock)
        budget.record_request()  # "price fetch" call path consumes the only slot
        assert budget.would_exceed() is True  # "corporate actions" call path must see it exhausted too
