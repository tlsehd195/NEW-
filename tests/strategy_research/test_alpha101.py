"""Category: strategy_research.alpha101 -- Kakushadze (2015) "101
Formulaic Alphas" reimplementations. SYNTHETIC fixtures with exact,
hand-computed expected values (never real-signal evidence) -- each
alpha's formula is verified against a specific numeric example computed
independently of this module's own implementation."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock

from data_infra.calendar import US_EQUITY
from data_infra.models import PriceBar, Provenance
from data_infra.repository import InMemoryDataRepository

import strategy_research.alpha101 as alpha101_module
from strategy_research.alpha101 import (
    ALPHA101_SPECS,
    alpha101_006,
    alpha101_009,
    alpha101_012,
    alpha101_023,
    alpha101_046,
    alpha101_049,
    alpha101_051,
    alpha101_053,
    alpha101_054,
    alpha101_101,
)

SECURITY = "AAA"


def _utc(d: date, hour: int = 20) -> datetime:
    return datetime(d.year, d.month, d.day, hour, tzinfo=timezone.utc)


def _trading_days(n: int, start: date = date(2020, 1, 2)) -> list[date]:
    days: list[date] = []
    current = start
    while len(days) < n:
        if US_EQUITY.is_trading_day(current):
            days.append(current)
        current += timedelta(days=1)
    return days


def _bar(
    d: date, *, open_: float, high: float, low: float, close: float, volume: float = 1_000.0,
) -> PriceBar:
    return PriceBar(
        security_id=SECURITY,
        timestamp=_utc(d, 0),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        available_time=_utc(d),
        ingestion_time=_utc(d),
        provenance=Provenance(
            source="test", source_dataset="test", source_record_id=f"{SECURITY}-{d.isoformat()}",
            retrieved_at=_utc(d), data_version="v1",
        ),
        adjusted_close=close,
    )


def _view(bars: list[PriceBar], as_of: datetime) -> AsOfDataView:
    return AsOfDataView(InMemoryDataRepository(bars=bars), BacktestClock(checkpoints=(as_of,)))


class TestAlpha006Correlation:
    def test_perfectly_correlated_open_and_volume_scores_minus_one(self) -> None:
        days = _trading_days(10)
        bars = [
            _bar(d, open_=float(i + 1), high=float(i + 1) + 1, low=float(i + 1) - 1, close=float(i + 1), volume=100.0 * (i + 1))
            for i, d in enumerate(days)
        ]
        as_of = _utc(days[-1])
        assert alpha101_006(SECURITY, as_of, _view(bars, as_of)) == pytest.approx(-1.0)

    def test_fewer_than_ten_bars_returns_none(self) -> None:
        days = _trading_days(5)
        bars = [_bar(d, open_=1.0, high=2.0, low=0.5, close=1.0, volume=100.0) for d in days]
        as_of = _utc(days[-1])
        assert alpha101_006(SECURITY, as_of, _view(bars, as_of)) is None


class TestAlpha009MonotonicRun:
    def _run(self, closes: list[float]) -> float:
        days = _trading_days(len(closes))
        bars = [_bar(d, open_=c, high=c + 1, low=c - 1, close=c) for d, c in zip(days, closes)]
        as_of = _utc(days[-1])
        result = alpha101_009(SECURITY, as_of, _view(bars, as_of))
        assert result is not None
        return result

    def test_monotonic_increase_follows_the_last_delta(self) -> None:
        assert self._run([10, 11, 12, 13, 14, 15]) == pytest.approx(1.0)

    def test_monotonic_decrease_follows_the_last_delta(self) -> None:
        assert self._run([15, 14, 13, 12, 11, 10]) == pytest.approx(-1.0)

    def test_mixed_direction_fades_the_last_delta(self) -> None:
        assert self._run([10, 11, 10, 11, 10, 11]) == pytest.approx(-1.0)


class TestAlpha012VolumeSignedReversal:
    def _run(self, closes: list[float], volumes: list[float]) -> float:
        days = _trading_days(2)
        bars = [
            _bar(d, open_=c, high=c + 1, low=c - 1, close=c, volume=v)
            for d, c, v in zip(days, closes, volumes)
        ]
        as_of = _utc(days[-1])
        result = alpha101_012(SECURITY, as_of, _view(bars, as_of))
        assert result is not None
        return result

    def test_rising_volume_gives_negative_of_close_delta(self) -> None:
        assert self._run([10.0, 12.0], [100.0, 150.0]) == pytest.approx(-2.0)

    def test_falling_volume_flips_the_sign(self) -> None:
        assert self._run([10.0, 12.0], [150.0, 100.0]) == pytest.approx(2.0)

    def test_unchanged_volume_scores_zero(self) -> None:
        assert self._run([10.0, 12.0], [100.0, 100.0]) == pytest.approx(0.0)


class TestAlpha023HighBreakout:
    def test_high_above_its_20day_average_scores_negative_2day_delta(self) -> None:
        days = _trading_days(20)
        highs = [10.0] * 19 + [15.0]
        bars = [_bar(d, open_=h, high=h, low=h - 1, close=h) for d, h in zip(days, highs)]
        as_of = _utc(days[-1])
        assert alpha101_023(SECURITY, as_of, _view(bars, as_of)) == pytest.approx(-5.0)

    def test_high_at_its_20day_average_scores_zero(self) -> None:
        days = _trading_days(20)
        bars = [_bar(d, open_=10.0, high=10.0, low=9.0, close=10.0) for d in days]
        as_of = _utc(days[-1])
        assert alpha101_023(SECURITY, as_of, _view(bars, as_of)) == pytest.approx(0.0)


def _trend_of_trend_bars(c20: float, c10: float, c_t1: float, c_t: float) -> tuple[list[date], list[PriceBar]]:
    # 21 bars: index 0 = T-20 (c20), index 10 = T-10 (c10), index 19 =
    # T-1 (c_t1), index 20 = T (c_t) -- the only 4 positions #46/#49/#51
    # actually read; everything in between is filler.
    days = _trading_days(21)
    closes = [c20] * 10 + [c10] * 9 + [c_t1, c_t]
    assert len(closes) == 21
    bars = [_bar(d, open_=c, high=c + 1, low=c - 1, close=c) for d, c in zip(days, closes)]
    return days, bars


class TestAlpha046ThreeWaySplit:
    def test_strongly_positive_x_scores_maximally_bearish(self) -> None:
        days, bars = _trend_of_trend_bars(c20=100.0, c10=90.0, c_t1=100.0, c_t=100.0)
        as_of = _utc(days[-1])
        assert alpha101_046(SECURITY, as_of, _view(bars, as_of)) == pytest.approx(-1.0)

    def test_negative_x_scores_maximally_bullish(self) -> None:
        days, bars = _trend_of_trend_bars(c20=90.0, c10=100.0, c_t1=90.0, c_t=90.0)
        as_of = _utc(days[-1])
        assert alpha101_046(SECURITY, as_of, _view(bars, as_of)) == pytest.approx(1.0)

    def test_mid_range_x_falls_back_to_a_1day_reversal(self) -> None:
        days, bars = _trend_of_trend_bars(c20=100.0, c10=100.0, c_t1=99.0, c_t=100.0)
        as_of = _utc(days[-1])
        assert alpha101_046(SECURITY, as_of, _view(bars, as_of)) == pytest.approx(-1.0)


class TestAlpha049And051ThresholdDifference:
    # x = -0.075: below #051's -0.05 threshold but not below #049's -0.1
    # threshold -- the two alphas must disagree on this exact input.
    def test_049_does_not_trigger_at_minus_0_075_and_falls_back(self) -> None:
        days, bars = _trend_of_trend_bars(c20=99.25, c10=100.0, c_t1=99.0, c_t=100.0)
        as_of = _utc(days[-1])
        assert alpha101_049(SECURITY, as_of, _view(bars, as_of)) == pytest.approx(-1.0)

    def test_051_does_trigger_at_minus_0_075(self) -> None:
        days, bars = _trend_of_trend_bars(c20=99.25, c10=100.0, c_t1=99.0, c_t=100.0)
        as_of = _utc(days[-1])
        assert alpha101_051(SECURITY, as_of, _view(bars, as_of)) == pytest.approx(1.0)

    def test_049_triggers_well_below_minus_0_1(self) -> None:
        days, bars = _trend_of_trend_bars(c20=90.0, c10=100.0, c_t1=90.0, c_t=90.0)
        as_of = _utc(days[-1])
        assert alpha101_049(SECURITY, as_of, _view(bars, as_of)) == pytest.approx(1.0)


class TestAlpha053CloseLocationChange:
    def test_close_location_shift_toward_the_high_is_negative(self) -> None:
        days = _trading_days(10)
        # Day 0 (T-9): close near the low. Day 9 (T): close near the high.
        bars = [_bar(d, open_=10.0, high=10.0, low=9.0, close=9.5) for d in days[:-1]]
        bars.append(_bar(days[-1], open_=10.0, high=11.0, low=9.0, close=10.5))
        as_of = _utc(days[-1])
        # x_t9 (high=10,low=9,close=9.5) = (2*9.5-9-10)/(9.5-9) = 0.0
        # x_t  (high=11,low=9,close=10.5) = (2*10.5-9-11)/(10.5-9) = 2/3
        expected = -1.0 * ((2 / 3) - 0.0)
        result = alpha101_053(SECURITY, as_of, _view(bars, as_of))
        assert result == pytest.approx(expected)

    def test_a_zero_range_bar_returns_none_instead_of_dividing_by_zero(self) -> None:
        days = _trading_days(10)
        bars = [_bar(d, open_=10.0, high=10.0, low=9.0, close=9.5) for d in days[:-1]]
        # close == low on the most recent bar -> denominator is zero.
        bars.append(_bar(days[-1], open_=10.0, high=11.0, low=9.0, close=9.0))
        as_of = _utc(days[-1])
        assert alpha101_053(SECURITY, as_of, _view(bars, as_of)) is None


class TestAlpha054FifthPowerReversal:
    def test_matches_the_formula_computed_by_hand(self) -> None:
        days = _trading_days(1)
        bars = [_bar(days[0], open_=10.0, high=12.0, low=9.0, close=11.0)]
        as_of = _utc(days[0])
        num = (9.0 - 11.0) * (10.0 ** 5)
        denom = (9.0 - 12.0) * (11.0 ** 5)
        expected = -1.0 * (num / denom)
        assert alpha101_054(SECURITY, as_of, _view(bars, as_of)) == pytest.approx(expected)

    def test_a_flat_bar_with_zero_range_returns_none(self) -> None:
        days = _trading_days(1)
        # low == high -> denominator is zero.
        bars = [_bar(days[0], open_=10.0, high=10.0, low=10.0, close=10.0)]
        as_of = _utc(days[0])
        assert alpha101_054(SECURITY, as_of, _view(bars, as_of)) is None


class TestAlpha101IntradayReturn:
    def test_matches_the_formula_computed_by_hand(self) -> None:
        days = _trading_days(1)
        bars = [_bar(days[0], open_=10.0, high=12.0, low=9.0, close=11.0)]
        as_of = _utc(days[0])
        expected = (11.0 - 10.0) / ((12.0 - 9.0) + 0.001)
        assert alpha101_101(SECURITY, as_of, _view(bars, as_of)) == pytest.approx(expected)

    def test_no_bars_returns_none(self) -> None:
        as_of = _utc(date(2020, 1, 2))
        assert alpha101_101(SECURITY, as_of, _view([], as_of)) is None


class TestAlpha101Specs:
    def test_exactly_ten_specs_are_registered(self) -> None:
        assert len(ALPHA101_SPECS) == 10

    def test_every_spec_id_is_unique(self) -> None:
        ids = [spec.alpha_id for spec in ALPHA101_SPECS]
        assert len(ids) == len(set(ids))

    def test_every_spec_has_a_corresponding_module_function(self) -> None:
        for spec in ALPHA101_SPECS:
            assert hasattr(alpha101_module, spec.alpha_id), f"missing function for {spec.alpha_id}"

    def test_every_spec_declares_a_positive_warmup(self) -> None:
        for spec in ALPHA101_SPECS:
            assert spec.min_warmup_bars > 0
