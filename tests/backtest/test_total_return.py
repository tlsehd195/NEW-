"""Category: Total-Return Benchmark Construction (Phase 20, instruction
section 13 / ADR-0026). `build_total_return_benchmark_points` reconstructs
a dividend-reinvested index from raw PriceBar + CorporateAction records,
the concrete implementation behind ADR-0026's TOTAL_RETURN decision.
BenchmarkEngine (Phase 2, unmodified) already reads whichever
`return_type` the data reports, so this module is tested standalone
against synthetic price/action fixtures -- no real SPY data exists yet
(ADR-0025/0026 both record that as still BLOCKED).
"""

from __future__ import annotations

import pytest
from helpers import make_provenance, utc

from data_infra.enums import BenchmarkReturnType, CorporateActionType
from data_infra.models import CorporateAction, PriceBar
from backtest.total_return import build_total_return_benchmark_points


def _bar(day: int, close: float, hour: int = 20) -> PriceBar:
    return PriceBar(
        security_id="SPY", timestamp=utc(2024, 1, day), open=close, high=close, low=close,
        close=close, volume=1_000_000.0, available_time=utc(2024, 1, day, hour),
        ingestion_time=utc(2024, 1, day, hour), provenance=make_provenance(source_record_id=f"spy-{day}"),
    )


def _split(day: int, ratio: float, available_hour: int = 20) -> CorporateAction:
    when = utc(2024, 1, day)
    return CorporateAction(
        security_id="SPY",
        action_type=CorporateActionType.SPLIT if ratio > 1.0 else CorporateActionType.REVERSE_SPLIT,
        available_time=utc(2024, 1, day, available_hour), ingestion_time=utc(2024, 1, day, available_hour),
        provenance=make_provenance(source_record_id=f"spy-split-{day}"),
        event_time=when, effective_time=when, details={"ratio": ratio},
    )


def _dividend(day: int, amount: float, available_hour: int = 20, available_day: int | None = None) -> CorporateAction:
    when = utc(2024, 1, day)
    avail_day = available_day if available_day is not None else day
    return CorporateAction(
        security_id="SPY", action_type=CorporateActionType.DIVIDEND,
        available_time=utc(2024, 1, avail_day, available_hour), ingestion_time=utc(2024, 1, avail_day, available_hour),
        provenance=make_provenance(source_record_id=f"spy-div-{day}"),
        event_time=when, effective_time=when, details={"amount": amount, "currency": "USD"},
    )


class TestPlainPriceSeriesNoActions:
    def test_matches_close_to_close_percentage_return(self) -> None:
        bars = [_bar(2, 100.0), _bar(3, 110.0)]
        points = build_total_return_benchmark_points(
            "SPY_TR", bars, [], as_of_time=utc(2024, 1, 4), base_level=100.0
        )
        assert len(points) == 2
        assert points[0].level == 100.0
        assert points[1].level == pytest.approx(110.0)  # +10%, no dividends/splits to adjust for
        assert all(p.return_type == BenchmarkReturnType.TOTAL_RETURN for p in points)


class TestDividendReinvestment:
    def test_dividend_is_added_back_into_the_days_return(self) -> None:
        bars = [_bar(2, 100.0), _bar(3, 99.0)]  # price alone looks like a 1% loss
        dividend = _dividend(3, amount=2.0)  # but a $2 dividend was paid on day 3
        points = build_total_return_benchmark_points(
            "SPY_TR", bars, [dividend], as_of_time=utc(2024, 1, 4), base_level=100.0
        )
        # total return factor = (99 + 2) / 100 = 1.01 -> +1%, not -1%
        assert points[1].level == 101.0

    def test_dividend_not_yet_available_is_excluded(self) -> None:
        bars = [_bar(2, 100.0), _bar(3, 99.0)]
        # the dividend genuinely happened on day 3 but our system only
        # discovered/ingested it on day 6 -- as_of=day 4 must not see it.
        dividend = _dividend(3, amount=2.0, available_day=6)
        points = build_total_return_benchmark_points(
            "SPY_TR", bars, [dividend], as_of_time=utc(2024, 1, 4), base_level=100.0
        )
        assert points[1].level == 99.0  # plain price return, dividend invisible

    def test_the_same_dividend_becomes_visible_once_as_of_passes_its_available_time(self) -> None:
        bars = [_bar(2, 100.0), _bar(3, 99.0)]
        dividend = _dividend(3, amount=2.0, available_day=6)
        points = build_total_return_benchmark_points(
            "SPY_TR", bars, [dividend], as_of_time=utc(2024, 1, 7), base_level=100.0
        )
        assert points[1].level == 101.0


class TestSplitAdjustment:
    def test_forward_split_price_drop_does_not_appear_as_a_loss(self) -> None:
        # a 4:1 split: 400 -> ~100, pure mechanical, no real value change
        bars = [_bar(2, 400.0), _bar(3, 100.0)]
        split = _split(3, ratio=4.0)
        points = build_total_return_benchmark_points(
            "SPY_TR", bars, [split], as_of_time=utc(2024, 1, 4), base_level=100.0
        )
        assert points[1].level == 100.0  # unchanged -- the split is fully absorbed

    def test_reverse_split_price_jump_does_not_appear_as_a_gain(self) -> None:
        # a 1:4 reverse split: 25 -> 100, pure mechanical
        bars = [_bar(2, 25.0), _bar(3, 100.0)]
        split = _split(3, ratio=0.25)
        points = build_total_return_benchmark_points(
            "SPY_TR", bars, [split], as_of_time=utc(2024, 1, 4), base_level=100.0
        )
        assert points[1].level == 100.0


class TestPointInTimeSafetyOfAvailableTime:
    def test_past_points_are_never_rewritten_when_a_later_dividend_is_discovered(self) -> None:
        """The same guarantee as
        tests/integration/test_market_data_point_in_time.py, exercised
        for the derived total-return series: a dividend for day 3
        discovered late must not change day 2's already-published
        level, and day 3's level itself is correctly absent/updated
        depending on when it is queried."""
        bars = [_bar(2, 100.0), _bar(3, 99.0)]
        dividend = _dividend(3, amount=2.0, available_day=6)

        early = build_total_return_benchmark_points(
            "SPY_TR", bars, [dividend], as_of_time=utc(2024, 1, 4), base_level=100.0
        )
        late = build_total_return_benchmark_points(
            "SPY_TR", bars, [dividend], as_of_time=utc(2024, 1, 7), base_level=100.0
        )
        assert early[0].level == late[0].level == 100.0  # day 2, unaffected either way
        assert early[1].level == 99.0  # day 3, dividend not yet knowable
        assert late[1].level == 101.0  # day 3, re-queried after the dividend is known

    def test_available_time_is_the_running_max_not_just_the_days_own_bar(self) -> None:
        bars = [_bar(2, 100.0), _bar(3, 99.0), _bar(4, 100.0)]
        dividend = _dividend(3, amount=2.0, available_day=3, available_hour=23)  # later same day than the bar (hour 20)
        points = build_total_return_benchmark_points(
            "SPY_TR", bars, [dividend], as_of_time=utc(2024, 1, 5), base_level=100.0
        )
        assert points[1].available_time == utc(2024, 1, 3, 23)  # the dividend's later time, not the bar's
        assert points[2].available_time == utc(2024, 1, 4, 20)  # day 4's own bar is later than either
