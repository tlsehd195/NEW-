from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from macro_filter.overlays import (
    IndexOverlayStrategy,
    month_end_closes,
    sma_exposure,
    vol_target_exposure,
)


def _bar(ts: datetime, price: float):
    return SimpleNamespace(timestamp=ts, close=price, adjusted_close=None)


def _monthly(prices: list[float]):
    return [_bar(datetime(2001 + i // 12, i % 12 + 1, 20, tzinfo=timezone.utc), p) for i, p in enumerate(prices)]


def test_month_end_closes_excludes_current_month():
    bars = _monthly([10.0, 11.0, 12.0])
    closes = month_end_closes(bars, datetime(2001, 3, 25, tzinfo=timezone.utc))
    assert closes == [10.0, 11.0]


def test_sma_exposure_above_and_below_average():
    rising = _monthly([float(p) for p in range(100, 112)])
    falling = _monthly([float(p) for p in range(112, 100, -1)])
    as_of = datetime(2002, 1, 3, tzinfo=timezone.utc)
    assert sma_exposure(rising, as_of) == 1.0
    assert sma_exposure(falling, as_of) == 0.0


def test_sma_exposure_none_when_history_short():
    assert sma_exposure(_monthly([100.0] * 5), datetime(2001, 6, 3, tzinfo=timezone.utc)) is None


def test_vol_target_scales_down_when_volatile():
    start = datetime(2001, 1, 1, tzinfo=timezone.utc)
    calm = [_bar(start + timedelta(days=i), 100.0 * (1 + 0.0001 * i)) for i in range(30)]
    wild = [_bar(start + timedelta(days=i), 100.0 * (1.03 if i % 2 else 0.97)) for i in range(30)]
    assert vol_target_exposure(calm) == 1.0
    assert 0.0 < vol_target_exposure(wild) < 0.5


def test_unknown_rule_rejected():
    with pytest.raises(ValueError):
        IndexOverlayStrategy("SPY", "nope")
