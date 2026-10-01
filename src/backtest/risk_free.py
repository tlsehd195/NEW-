"""Risk-free rate for Sharpe/Sortino: the 3-month Treasury yield (ADR-0227).

FRED `DGS3MO` is a daily annualized yield in percent. A backtest or paper
report covers one window, so it uses the average yield over that window as
its annual risk-free rate. Sharpe's numerator is mean(r - rf), and
mean(r - rf_t) equals mean(r) - mean(rf_t), so the window average is exact
for the numerator; only the denominator's tiny rf variance is ignored.

The rate is only used to score a finished window, never by a strategy's
decisions, so averaging over the window is not look-ahead.
"""

from __future__ import annotations

import bisect
from datetime import date
from typing import Iterable, Optional

from data_infra.macro_models import MacroObservationRecord

RISK_FREE_SERIES_ID = "DGS3MO"


class RiskFreeRates:
    def __init__(self, observations: Iterable[tuple[date, float]], *, source: str) -> None:
        by_date: dict[date, float] = {}
        for day, percent in observations:
            if percent is None:
                continue
            by_date[day] = float(percent)
        self._dates = sorted(by_date)
        self._values = [by_date[d] for d in self._dates]
        self.source = source

    @classmethod
    def from_macro_records(cls, records: Iterable[MacroObservationRecord], *, source: str) -> "RiskFreeRates":
        """Latest vintage per observation date. DGS3MO is never revised,
        so this is simply its value; FRED "." days (value None) are skipped."""
        latest: dict[date, tuple[object, Optional[float]]] = {}
        for r in records:
            day = r.observation_date.date()
            if day not in latest or r.realtime_start > latest[day][0]:
                latest[day] = (r.realtime_start, r.value)
        return cls(((d, v) for d, (_, v) in latest.items()), source=source)

    def __len__(self) -> int:
        return len(self._dates)

    def average_annual_rate(self, start: date, end: date) -> float:
        """Mean yield over observations dated in [start, end], as a decimal
        (4.5% -> 0.045). Raises when the window has no observation, so a
        missing series never silently becomes 0%."""
        lo = bisect.bisect_left(self._dates, start)
        hi = bisect.bisect_right(self._dates, end)
        window = self._values[lo:hi]
        if not window:
            raise ValueError(f"no {RISK_FREE_SERIES_ID} observation between {start} and {end} ({self.source})")
        return sum(window) / len(window) / 100.0

    def latest_annual_rate_before(self, day: date, *, max_stale_days: int = 10) -> Optional[float]:
        """Yield of the latest observation dated strictly before `day`, as
        a decimal; None when there is none within `max_stale_days`. Used to
        accrue interest on cash (ADR-0229): the day before's yield is the
        one already published by the backtest's end-of-day checkpoint, and
        the staleness cap carries it over holidays and FRED "." days without
        stretching one rate across a real gap in the series."""
        i = bisect.bisect_left(self._dates, day) - 1
        if i < 0 or (day - self._dates[i]).days > max_stale_days:
            return None
        return self._values[i] / 100.0

    def describe(self) -> dict:
        return {
            "series_id": RISK_FREE_SERIES_ID,
            "source": self.source,
            "method": "mean daily yield over each evaluated window",
            "observation_count": len(self._dates),
            "first_observation": self._dates[0].isoformat() if self._dates else None,
            "last_observation": self._dates[-1].isoformat() if self._dates else None,
        }
