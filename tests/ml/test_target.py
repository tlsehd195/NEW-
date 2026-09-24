"""Category: target computation reuses strategy_research.signal_ic's
forward_return exactly -- no second implementation of realized-return
math. SYNTHETIC fixtures only."""

from __future__ import annotations

from datetime import date

from helpers import utc
from research_helpers import synthetic_multi_year_repository

import ml.target as target_module
from ml.target import HORIZON_DAYS, compute_target
from strategy_research.signal_ic import forward_return


class TestComputeTargetMatchesForwardReturn:
    def test_same_value_as_signal_ic_forward_return(self) -> None:
        universe = ("TRENDUP",)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        as_of_time = utc(2020, 6, 1)

        expected = forward_return(price_repo, "TRENDUP", as_of_time, HORIZON_DAYS)
        actual = compute_target(price_repo, "TRENDUP", as_of_time)

        assert actual == expected
        assert actual is not None

    def test_none_when_fewer_than_two_bars_fall_in_the_horizon_window(self) -> None:
        # as_of_time is the last day of ingested history -- the horizon
        # window [as_of_time, as_of_time+60d) contains at most that one
        # bar, so compute_target must return None (matching
        # forward_return's own "len(bars) < 2 -> None" rule) rather
        # than fabricating a return from a single price point.
        universe = ("TRENDUP",)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2020, 2, 1), symbols=universe)
        as_of_time = utc(2020, 2, 1)

        assert compute_target(price_repo, "TRENDUP", as_of_time) is None


class TestNonFiniteResultIsExcludedNotFabricated:
    def test_a_nan_forward_return_is_treated_as_none(self, monkeypatch) -> None:
        # A price-data anomaly (e.g. a zero/negative adjusted_close
        # slipping past forward_return's own guard some other way)
        # must never reach a sample's target field as NaN -- Batch K's
        # NaN/gap contract excludes it exactly like a None.
        monkeypatch.setattr(target_module, "forward_return", lambda *a, **k: float("nan"))
        universe = ("TRENDUP",)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        as_of_time = utc(2020, 6, 1)

        assert compute_target(price_repo, "TRENDUP", as_of_time) is None

    def test_an_infinite_forward_return_is_treated_as_none(self, monkeypatch) -> None:
        monkeypatch.setattr(target_module, "forward_return", lambda *a, **k: float("inf"))
        universe = ("TRENDUP",)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        as_of_time = utc(2020, 6, 1)

        assert compute_target(price_repo, "TRENDUP", as_of_time) is None
